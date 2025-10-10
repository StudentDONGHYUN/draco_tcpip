#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ROS2 PointCloud2 -> PLY 저장 노드 (Open3D 우선 + plyfile 폴백)
- QoS: Reliable/Best Effort
- --every N, --max-frames, --idle-timeout-sec 지원
- PointCloud2 → (N,3) float32 변환 경로를 견고하게 수정(read_points_numpy 우선)
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

import rclpy
from rclpy.node import Node
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import PointCloud2

from draco_roundtrip.io.ply_codec import (
    points_from_pointcloud2,
    save_xyz,
    voxel_downsample,
)
from draco_roundtrip.shared_memory import SharedMemoryPublisher

PAD = 10  # 파일명 인덱스 0패딩


class PcdSaver(Node):
    def __init__(
        self,
        topic: str,
        out_dir: Path,
        prefix: str,
        every: int,
        qos_reliable: bool,
        max_frames: int,
        idle_timeout_sec: float,
        log_csv: Path | None,
        voxel_size: float,
        shared_publisher: SharedMemoryPublisher | None = None,
        shared_memory_only: bool = False,
    ) -> None:
        super().__init__('ply_saver')

        self.topic = topic
        self.out_dir = out_dir
        self.prefix = prefix
        self.every = max(1, every)
        self.max_frames = max_frames  # 0이면 무제한
        self.idle_timeout_sec = float(idle_timeout_sec)
        self.voxel_size = float(max(0.0, voxel_size))
        self._shared_publisher = shared_publisher
        self._shared_only = bool(shared_memory_only)
        if self._shared_only and self._shared_publisher is None:
            raise ValueError('shared_memory_only requires an active SharedMemoryPublisher')

        self.out_dir.mkdir(parents=True, exist_ok=True)

        qos = QoSProfile(depth=10)
        qos.history = HistoryPolicy.KEEP_LAST
        qos.reliability = ReliabilityPolicy.RELIABLE if qos_reliable else ReliabilityPolicy.BEST_EFFORT

        self.sub = self.create_subscription(PointCloud2, self.topic, self.cb, qos)

        self.frame = 0
        self.saved = 0
        self.idx = 0
        self.last_msg_time = time.monotonic()

        self.get_logger().info(
            f"Subscribing topic={self.topic}  out={self.out_dir}  every={self.every}  "
            f"QoS={'RELIABLE' if qos_reliable else 'BEST_EFFORT'}"
        )

        self.timer = self.create_timer(0.5, self._on_timer)

        self._log_path = log_csv
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

    def close_resources(self) -> None:
        if self._log_fp:
            try:
                self._log_fp.close()
            except Exception:
                pass
            self._log_fp = None
        if self._shared_publisher is not None:
            try:
                self._shared_publisher.close()
            except Exception:
                pass

    def cb(self, msg: PointCloud2):
        self.last_msg_time = time.monotonic()
        self.frame += 1
        if (self.frame - 1) % self.every != 0:
            return

        t0 = time.perf_counter()
        xyz = points_from_pointcloud2(msg)
        if xyz.size == 0:
            return

        if self.voxel_size > 0.0:
            xyz = voxel_downsample(xyz, self.voxel_size)
            if xyz.size == 0:
                return

        stem = f"{self.prefix}_{self.idx:0{PAD}d}"
        published = False
        if self._shared_publisher is not None:
            try:
                self._shared_publisher.publish(stem, xyz)
                published = True
            except Exception as exc:
                self.get_logger().error(f"Shared memory publish failed for {stem}: {exc}")
                if self._shared_only:
                    return

        name = f"{stem}.ply"
        path = self.out_dir / name
        if not self._shared_only:
            save_xyz(path, xyz)

        dt_ms = (time.perf_counter() - t0) * 1000.0
        self.saved += 1
        self.idx += 1
        if self._shared_only:
            self.get_logger().info(
                f"Published {stem} via shared memory ({xyz.shape[0]} pts) in {dt_ms:.1f} ms"
            )
        elif published:
            self.get_logger().info(
                f"Saved {path} and published shared memory copy ({xyz.shape[0]} pts) in {dt_ms:.1f} ms"
            )
        else:
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
    ap = argparse.ArgumentParser(description="PointCloud2 -> PLY saver (Open3D 우선+plyfile 폴백)")
    ap.add_argument("--topic", required=True, help="구독할 PointCloud2 토픽")
    ap.add_argument("--out", required=True, help="PLY 저장 디렉토리")
    ap.add_argument("--prefix", default="sample", help="파일 접두어")
    ap.add_argument("--every", type=int, default=1, help="N프레임마다 1회 저장")
    qos_group = ap.add_mutually_exclusive_group()
    qos_group.add_argument("--reliable", action="store_true", help="QoS RELIABLE")
    qos_group.add_argument("--best-effort", action="store_true", help="QoS BEST_EFFORT(기본)")
    ap.add_argument("--max-frames", type=int, default=0, help="저장할 프레임 수(0=무제한)")
    ap.add_argument("--idle-timeout-sec", type=float, default=10.0,
                    help="수신 없을 때 자동 종료까지 대기 초(0=비활성)")
    ap.add_argument("--voxel-size", type=float, default=0.0,
                    help=">0이면 저장 전 voxel downsample 적용 (m)")
    ap.add_argument("--log-csv", default=None, help="프레임 저장 시간 로그 CSV")
    ap.add_argument(
        "--shared-memory-host",
        default=None,
        help="Shared memory 메타데이터 수신 호스트 (지정 시 공유 메모리 게시 활성화)",
    )
    ap.add_argument(
        "--shared-memory-port",
        type=int,
        default=0,
        help="Shared memory 메타데이터 포트",
    )
    ap.add_argument(
        "--shared-memory-only",
        action="store_true",
        help="디스크 저장 없이 공유 메모리 게시만 수행",
    )
    args = ap.parse_args()

    out_dir = Path(args.out).expanduser().resolve()
    log_csv = Path(args.log_csv).expanduser().resolve() if args.log_csv else None

    publisher: SharedMemoryPublisher | None = None
    if args.shared_memory_host and args.shared_memory_port > 0:
        try:
            publisher = SharedMemoryPublisher(args.shared_memory_host, int(args.shared_memory_port))
        except Exception as exc:
            print(f"[bag_recorder] WARN: Shared memory publisher unavailable: {exc}", file=sys.stderr)
            publisher = None
    elif args.shared_memory_only:
        raise SystemExit("--shared-memory-only requires --shared-memory-host/--shared-memory-port")

    rclpy.init(args=None)
    node = PcdSaver(
        topic=args.topic,
        out_dir=out_dir,
        prefix=args.prefix,
        every=args.every,
        qos_reliable=bool(args.reliable and not args.best_effort),
        max_frames=args.max_frames,
        idle_timeout_sec=args.idle_timeout_sec,
        log_csv=log_csv,
        voxel_size=float(args.voxel_size),
        shared_publisher=publisher,
        shared_memory_only=bool(args.shared_memory_only),
    )
    try:
        rclpy.spin(node)
    finally:
        try:
            node.close_resources()
        except Exception:
            pass
        try:
            rclpy.try_shutdown()
        except Exception:
            pass


if __name__ == "__main__":
    main()

# 변경 요약:
# - PointCloud2 프레임을 공유 메모리로 게시할 수 있는 옵션을 추가했습니다.
# - 공유 메모리 전용 모드와 디스크+공유 메모리 병행 모드에서 모두 동작하도록 CLI와 로깅을 조정했습니다.
# - 종료 시 로그 파일과 공유 메모리 소켓이 안전하게 닫히도록 자원 정리 경로를 통합했습니다.
