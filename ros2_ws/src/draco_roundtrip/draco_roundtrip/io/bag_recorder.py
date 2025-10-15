#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ROS2 PointCloud2 -> PLY 저장 노드 (Open3D 우선 + plyfile 폴백)
- QoS: Reliable/Best Effort
- --every N, --max-frames, --idle-timeout-sec 지원
- PointCloud2 → (N,3) float32 변환 경로를 견고하게 수정(read_points_numpy 우선)
"""

import csv
import re
import sys
import time
from pathlib import Path

import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from sensor_msgs.msg import PointCloud2
from sensor_msgs_py import point_cloud2 as pc2

# Open3D는 선택적. 없으면 plyfile로 저장
from plyfile import PlyData, PlyElement

try:
    import open3d as o3d  # type: ignore
    _HAVE_O3D = True
except Exception:
    _HAVE_O3D = False

PAD = 10  # 파일명 인덱스 0패딩


def eprint(*a, **k):
    print(*a, file=sys.stderr, **k)
    sys.stderr.flush()


def to_xyz_array_from_pc2(msg: PointCloud2) -> np.ndarray:
    """
    PointCloud2 -> (N,3) float32
    1) read_points_numpy 우선 사용 (ROS2에서 제공)
    2) 실패 시 read_points로 받아 tuple 또는 구조화 void에서 x,y,z만 추출
    """
    # 1) numpy 경로
    try:
        arr = pc2.read_points_numpy(msg, field_names=['x', 'y', 'z'], skip_nans=True)
        # 일부 환경에서 (3,) 이나 (N,4) 등으로 나올 수 있어 가드
        arr = np.asarray(arr, dtype=np.float32)
        if arr.ndim == 1:
            if arr.size == 0:
                return np.empty((0, 3), dtype=np.float32)
            arr = arr.reshape((-1, 3))
        elif arr.shape[1] > 3:
            arr = arr[:, :3]
        return arr
    except Exception:
        pass

    # 2) generator 경로 (명시적으로 x,y,z를 추출)
    xyz_list = []
    for p in pc2.read_points(msg, field_names=('x', 'y', 'z'), skip_nans=True):
        # p가 tuple/리스트/np.void(구조화) 무엇이든 안전하게 뽑기
        try:
            x, y, z = float(p[0]), float(p[1]), float(p[2])
        except Exception:
            # 구조화일 가능성
            x = float(p['x'])
            y = float(p['y'])
            z = float(p['z'])
        xyz_list.append((x, y, z))
    if not xyz_list:
        return np.empty((0, 3), dtype=np.float32)
    return np.asarray(xyz_list, dtype=np.float32)


def voxel_downsample(xyz: np.ndarray, voxel_size: float) -> np.ndarray:
    if voxel_size <= 0.0 or xyz.size == 0:
        return xyz
    if _HAVE_O3D:
        pcd = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(xyz.astype(np.float64)))
        ds = pcd.voxel_down_sample(voxel_size)
        return np.asarray(ds.points, dtype=np.float32)
    scaled = np.floor(xyz / voxel_size)
    structured = np.core.records.fromarrays(scaled.T, names='x,y,z', formats='i8,i8,i8')
    _, idx = np.unique(structured, return_index=True)
    return xyz[idx]


def save_ply_plyfile(path: Path, xyz_f32: np.ndarray) -> None:
    """plyfile로 float32 보장 저장"""
    verts = np.zeros(xyz_f32.shape[0], dtype=[('x', '<f4'), ('y', '<f4'), ('z', '<f4')])
    verts['x'] = xyz_f32[:, 0]
    verts['y'] = xyz_f32[:, 1]
    verts['z'] = xyz_f32[:, 2]
    el = PlyElement.describe(verts, 'vertex')
    PlyData([el], text=False).write(str(path))


def save_ply_o3d_then_verify(path: Path, xyz_f32: np.ndarray) -> None:
    """
    Open3D(Tensor)로 저장 시도 → 헤더 float 확인 → 실패 시 plyfile 폴백
    """
    if not _HAVE_O3D:
        save_ply_plyfile(path, xyz_f32)
        return

    ok = False
    try:
        pcd = o3d.t.geometry.PointCloud()
        pcd.point["positions"] = o3d.core.Tensor(xyz_f32.astype(np.float32),
                                                 dtype=o3d.core.Dtype.Float32)
        o3d.t.io.write_point_cloud(str(path), pcd, write_ascii=False)
        # 헤더 검증
        with open(path, "rb") as f:
            head = f.read(512).decode("utf-8", "ignore")
        if re.search(r"property\s+float\s+x", head) and \
           re.search(r"property\s+float\s+y", head) and \
           re.search(r"property\s+float\s+z", head):
            ok = True
    except Exception:
        ok = False

    if not ok:
        save_ply_plyfile(path, xyz_f32)


class PcdSaver(Node):
    def __init__(self):
        super().__init__('ply_saver')

        # Declare parameters
        self.declare_parameter('topic', '')
        self.declare_parameter('out', '')
        self.declare_parameter('prefix', 'sample')
        self.declare_parameter('every', 1)
        self.declare_parameter('best_effort', True)
        self.declare_parameter('max_frames', 0)
        self.declare_parameter('idle_timeout_sec', 10.0)
        self.declare_parameter('voxel_size', 0.0)
        self.declare_parameter('log_csv', '')

        # Get parameters
        self.topic = self.get_parameter('topic').value
        out_str = self.get_parameter('out').value
        self.prefix = self.get_parameter('prefix').value
        self.every = max(1, self.get_parameter('every').value)
        qos_best_effort = self.get_parameter('best_effort').value
        self.max_frames = self.get_parameter('max_frames').value
        self.idle_timeout_sec = self.get_parameter('idle_timeout_sec').value
        self.voxel_size = max(0.0, self.get_parameter('voxel_size').value)
        log_csv_str = self.get_parameter('log_csv').value

        if not self.topic or not out_str:
            self.get_logger().error("'topic' and 'out' parameters must be set.")
            # Prevent further execution by returning early or raising an exception
            # For a node, it's better to just log and not crash, but let's make it exit
            # to make the problem obvious.
            sys.exit("Missing required parameters 'topic' or 'out'.")

        self.out_dir = Path(out_str).expanduser().resolve()
        self.out_dir.mkdir(parents=True, exist_ok=True)

        qos = QoSProfile(depth=10)
        qos.history = HistoryPolicy.KEEP_LAST
        qos.reliability = ReliabilityPolicy.BEST_EFFORT if qos_best_effort else ReliabilityPolicy.RELIABLE

        self.sub = self.create_subscription(PointCloud2, self.topic, self.cb, qos)

        self.frame = 0
        self.saved = 0
        self.idx = 0
        self.last_msg_time = time.monotonic()

        self.get_logger().info(
            f"Subscribing topic={self.topic}  out={self.out_dir}  every={self.every}  "
            f"QoS={'BEST_EFFORT' if qos_best_effort else 'RELIABLE'}"
        )

        self.timer = self.create_timer(0.5, self._on_timer)

        self._log_path = Path(log_csv_str).expanduser().resolve() if log_csv_str else None
        self._log_fp = None
        self._log_writer: csv.writer | None = None
        if self._log_path is not None:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            self._log_fp = self._log_path.open('w', newline='', encoding='utf-8')
            self._log_writer = csv.writer(self._log_fp)
            self._log_writer.writerow(['name', 'save_s'])

    def _on_timer(self):
        if self.idle_timeout_sec > 0.0:
            if (time.monotonic() - self.last_msg_time) >= self.idle_timeout_sec:
                self.get_logger().info("No messages for idle-timeout. Shutting down (bag finished?).")
                rclpy.shutdown()

    def close_log(self) -> None:
        if self._log_fp:
            try:
                self._log_fp.close()
            except Exception:
                pass
            self._log_fp = None

    def cb(self, msg: PointCloud2):
        self.last_msg_time = time.monotonic()
        self.frame += 1
        if (self.frame - 1) % self.every != 0:
            return

        t0 = time.perf_counter()
        xyz = to_xyz_array_from_pc2(msg)
        if xyz.size == 0:
            return

        if self.voxel_size > 0.0:
            xyz = voxel_downsample(xyz, self.voxel_size)
            if xyz.size == 0:
                return

        name = f"{self.prefix}_{self.idx:0{PAD}d}.ply"
        path = self.out_dir / name

        save_ply_o3d_then_verify(path, xyz)

        dt_ms = (time.perf_counter() - t0) * 1000.0
        self.saved += 1
        self.idx += 1
        self.get_logger().info(f"Saved {path} ({xyz.shape[0]} pts) in {dt_ms:.1f} ms")

        if self._log_writer and self._log_fp:
            try:
                self._log_writer.writerow([Path(name).stem, dt_ms / 1000.0])
                self._log_fp.flush()
            except Exception:
                pass

        if self.max_frames > 0 and self.saved >= self.max_frames:
            self.get_logger().info("Reached max_frames, shutting down.")
            rclpy.shutdown()


def main():
    rclpy.init(args=None)
    node = PcdSaver()
    try:
        rclpy.spin(node)
    finally:
        try:
            node.close_log()
        except Exception:
            pass
        # Use try_shutdown() to avoid errors if already shutdown
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()