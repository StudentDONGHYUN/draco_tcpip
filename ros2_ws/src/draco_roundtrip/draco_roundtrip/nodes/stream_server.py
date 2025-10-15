#!/usr/bin/env python3
"""Server-centric Draco streaming bridge with control-plane downlink."""

from __future__ import annotations

import io
import socket
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path as FSPath
from typing import Optional

import rclpy
from geometry_msgs.msg import PoseStamped, Twist
from nav_msgs.msg import Path as NavPath
from rclpy.node import Node
from rclpy.utilities import remove_ros_args
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import PointCloud2
from sensor_msgs_py import point_cloud2 as pc2
from plyfile import PlyData, PlyElement  # type: ignore
from std_msgs.msg import Header

import numpy as np

from draco_roundtrip.draco._draco_adapter import decode_points_np
from draco_roundtrip.net.control_plane import (
    PATH_POSE_LIMIT,
    PathPayload,
    PathPose,
    PosePayload,
    TwistPayload,
    build_path_message,
    build_pose_message,
    build_twist_message,
    message_to_json,
)
from draco_roundtrip.net.protocol import (
    ConnectionClosed,
    Message,
    MSG_ACK,
    MSG_DATA,
    MSG_ERROR,
    MSG_HEARTBEAT,
    recv_message,
    send_message,
)
from draco_roundtrip.utils import ensure_directory


@dataclass(slots=True)
class DownlinkBundle:
    pose: Optional[PosePayload] = None
    twist: Optional[TwistPayload] = None
    path: Optional[PathPayload] = None


def decode_drc_to_points(drc_bytes: bytes) -> np.ndarray:
    """Decode Draco bytes entirely in memory."""

    return decode_points_np(drc_bytes)


def points_to_ply_bytes(points: np.ndarray) -> bytes:
    """Serialise XYZ points to binary PLY bytes."""

    arr = np.asarray(points, dtype=np.float32)
    if arr.ndim != 2 or arr.shape[1] < 3:
        raise ValueError(
            f"Expected points shaped (N, 3+) but received {arr.shape!r}"
        )
    if arr.shape[1] > 3:
        arr = arr[:, :3]
    verts = np.zeros(arr.shape[0], dtype=[("x", "<f4"), ("y", "<f4"), ("z", "<f4")])
    verts["x"] = arr[:, 0]
    verts["y"] = arr[:, 1]
    verts["z"] = arr[:, 2]
    element = PlyElement.describe(verts, "vertex")
    ply = PlyData([element], text=False)
    buffer = io.BytesIO()
    ply.write(buffer)
    return buffer.getvalue()


class StreamServerNode(Node):
    """Accept Draco uplink, publish ROS topics, and stream control-plane telemetry."""

    def __init__(self) -> None:
        super().__init__("draco_stream_server")
        self.declare_parameter("host", "0.0.0.0")
        self.declare_parameter("port", 5000)
        self.declare_parameter("decoder", "")
        self.declare_parameter("work_dir", "data/server_tmp")
        self.declare_parameter("points_topic", "/server/points")
        self.declare_parameter("points_frame_id", "")
        self.declare_parameter("pose_topic", "/server_pose")
        self.declare_parameter("path_topic", "/planned_path")
        self.declare_parameter("twist_topic", "/cmd_vel")
        self.declare_parameter("downlink_port", 0)
        self.declare_parameter("downlink_protocol", "binary")
        self.declare_parameter("downlink_json", False)
        self.declare_parameter("downlink_rate", 10.0)
        self.declare_parameter("legacy_downlink", False)
        self.declare_parameter("heartbeat_interval", 1.0)
        self.declare_parameter("path_length", 20)
        self.declare_parameter("stub_path_stride", 0.25)

        self.host = str(self.get_parameter("host").value)
        self.port = int(self.get_parameter("port").value)
        decoder_param = str(self.get_parameter("decoder").value or "")
        if decoder_param:
            self.get_logger().warn(
                "Parameter 'decoder' is deprecated; DracoPy handles decoding in-memory."
            )
        work_dir_param = str(self.get_parameter("work_dir").value)
        self.work_dir = ensure_directory(FSPath(work_dir_param).resolve())
        qos = QoSProfile(depth=10)
        qos.history = HistoryPolicy.KEEP_LAST
        qos.reliability = ReliabilityPolicy.RELIABLE
        self.pub_points = self.create_publisher(
            PointCloud2, str(self.get_parameter("points_topic").value), qos
        )
        self.pub_pose = self.create_publisher(
            PoseStamped, str(self.get_parameter("pose_topic").value), qos
        )
        self.pub_path = self.create_publisher(
            NavPath, str(self.get_parameter("path_topic").value), qos
        )
        self.pub_twist = self.create_publisher(
            Twist, str(self.get_parameter("twist_topic").value), qos
        )
        downlink_json = bool(self.get_parameter("downlink_json").value)
        self.downlink_protocol = (
            "json" if downlink_json else str(self.get_parameter("downlink_protocol").value)
        )
        self.downlink_rate = max(float(self.get_parameter("downlink_rate").value), 0.1)
        self.heartbeat_interval = max(
            float(self.get_parameter("heartbeat_interval").value), 0.1
        )
        self.path_length = max(
            1, min(int(self.get_parameter("path_length").value), PATH_POSE_LIMIT)
        )
        self.stub_stride = float(self.get_parameter("stub_path_stride").value)
        self.legacy_downlink = bool(self.get_parameter("legacy_downlink").value)
        downlink_port_param = int(self.get_parameter("downlink_port").value)
        self.downlink_port = downlink_port_param if downlink_port_param else self.port + 1
        if self.legacy_downlink:
            self.get_logger().warn(
                "Legacy downlink enabled — decoded PLY responses are deprecated"
            )

        self._uplink_socket: Optional[socket.socket] = None
        self._downlink_socket: Optional[socket.socket] = None
        self._downlink_conn: Optional[socket.socket] = None
        self._downlink_lock = threading.Lock()
        self._downlink_bundle = DownlinkBundle()
        self._last_heartbeat = time.monotonic()
        self._last_downlink_bytes = 0
        self._downlink_bytes_total = 0
        self._downlink_messages = 0
        self._points_frame_id = str(self.get_parameter("points_frame_id").value)

        self._uplink_thread = threading.Thread(target=self._run_uplink, daemon=True)
        self._downlink_thread = threading.Thread(target=self._run_downlink, daemon=True)
        self._running = True

        self._downlink_timer = self.create_timer(1.0 / self.downlink_rate, self._downlink_tick)
        self._uplink_thread.start()
        self._downlink_thread.start()

    # ------------------------------------------------------------------
    # Networking

    def _run_uplink(self) -> None:
        host = self.host
        port = int(self.port)
        try:
            with socket.create_server((host, port), reuse_port=True) as server:
                self.get_logger().info(f"Listening for uplink on {host}:{port}")
                self._uplink_socket = server
                while self._running and rclpy.ok():
                    conn, addr = server.accept()
                    self.get_logger().info(f"Uplink client connected from {addr}")
                    with conn:
                        try:
                            self._serve_client(conn)
                        except ConnectionClosed:
                            self.get_logger().info("Uplink connection closed by peer")
                        except Exception as exc:
                            self.get_logger().error(f"Uplink session error: {exc}")
                        finally:
                            self.get_logger().info("Uplink session finished")
        except Exception as exc:  # pragma: no cover - defensive logging
            self.get_logger().error(f"Failed to start uplink server: {exc}")

    def _run_downlink(self) -> None:
        port = int(self.downlink_port)
        host = self.host
        try:
            with socket.create_server((host, port), reuse_port=True) as server:
                self.get_logger().info(f"Listening for downlink on {host}:{port}")
                self._downlink_socket = server
                while self._running and rclpy.ok():
                    conn, addr = server.accept()
                    self.get_logger().info(f"Downlink client connected from {addr}")
                    with self._downlink_lock:
                        self._downlink_conn = conn
                    try:
                        while self._running and rclpy.ok():
                            data = conn.recv(1)
                            if not data:
                                break
                            # Downlink is currently write-only, but clients may send heartbeats later.
                    finally:
                        with self._downlink_lock:
                            self._downlink_conn = None
                        self.get_logger().info("Downlink connection closed")
        except Exception as exc:  # pragma: no cover
            self.get_logger().error(f"Downlink server error: {exc}")

    def _serve_client(self, conn: socket.socket) -> None:
        bytes_in = 0
        bytes_out = 0
        while self._running and rclpy.ok():
            msg = recv_message(conn)
            if msg is None:
                raise ConnectionClosed("uplink closed")
            if msg.kind == MSG_HEARTBEAT:
                self._last_heartbeat = time.monotonic()
                ack = Message(kind=MSG_ACK, name=msg.name or "hb", payload=b"")
                send_message(conn, ack)
                continue
            if msg.kind != MSG_DATA:
                self.get_logger().warning(f"Ignoring unexpected message kind: {msg.kind}")
                continue
            self._last_heartbeat = time.monotonic()
            stem = msg.name or "frame"
            bytes_in += len(msg.payload)
            self.get_logger().debug(f"Received {stem} ({len(msg.payload)} bytes)")
            try:
                points = decode_drc_to_points(msg.payload)
            except Exception as exc:
                error_msg = Message(kind=MSG_ERROR, name=stem, payload=str(exc).encode())
                send_message(conn, error_msg)
                self.get_logger().error(f"Failed to decode {stem}: {exc}")
                continue

            self._publish_point_cloud(points, frame_id=msg.frame_id)
            self._update_autonomy_outputs()

            if self.legacy_downlink:
                ply_bytes = points_to_ply_bytes(points)
                reply = Message(kind=MSG_DATA, name=f"{stem}.decoded", payload=ply_bytes)
                send_message(conn, reply)
                bytes_out += len(reply.payload)
            else:
                ack = Message(kind=MSG_ACK, name=stem, payload=b"")
                send_message(conn, ack)

        self.get_logger().info(
            f"Uplink session summary: in={bytes_in} bytes, out={bytes_out} bytes"
        )

    # ------------------------------------------------------------------
    # ROS publishing helpers

    def _publish_point_cloud(self, xyz: np.ndarray, frame_id: str) -> None:
        header = Header()
        header.stamp = self.get_clock().now().to_msg()
        header.frame_id = self._points_frame_id or frame_id
        msg = pc2.create_cloud_xyz32(header, xyz)
        self.pub_points.publish(msg)

    def _update_autonomy_outputs(self) -> None:
        now = self.get_clock().now()
        stamp_msg = now.to_msg()
        stamp_ns = int(now.nanoseconds)

        pose_msg = PoseStamped()
        pose_msg.header = Header()
        pose_msg.header.stamp = stamp_msg
        pose_msg.header.frame_id = "map"
        pose_msg.pose.orientation.w = 1.0
        self.pub_pose.publish(pose_msg)

        twist_msg = Twist()
        self.pub_twist.publish(twist_msg)

        path_msg = NavPath()
        path_msg.header = Header()
        path_msg.header.stamp = stamp_msg
        path_msg.header.frame_id = "map"
        path_msg.poses = []
        for i in range(self.path_length):
            pose = PoseStamped()
            pose.header = path_msg.header
            pose.pose.position.x = i * self.stub_stride
            pose.pose.orientation.w = 1.0
            path_msg.poses.append(pose)
        self.pub_path.publish(path_msg)

        pose_payload = PosePayload(
            stamp_ns=stamp_ns,
            frame_id=pose_msg.header.frame_id,
            x=pose_msg.pose.position.x,
            y=pose_msg.pose.position.y,
            z=pose_msg.pose.position.z,
            qx=pose_msg.pose.orientation.x,
            qy=pose_msg.pose.orientation.y,
            qz=pose_msg.pose.orientation.z,
            qw=pose_msg.pose.orientation.w,
        )
        twist_payload = TwistPayload(
            stamp_ns=stamp_ns,
            vx=twist_msg.linear.x,
            vy=twist_msg.linear.y,
            vz=twist_msg.linear.z,
            wx=twist_msg.angular.x,
            wy=twist_msg.angular.y,
            wz=twist_msg.angular.z,
        )
        path_payload = PathPayload(
            stamp_ns=stamp_ns,
            frame_id=path_msg.header.frame_id,
            poses=[
                PathPose(
                    x=pose.pose.position.x,
                    y=pose.pose.position.y,
                    z=pose.pose.position.z,
                    qx=pose.pose.orientation.x,
                    qy=pose.pose.orientation.y,
                    qz=pose.pose.orientation.z,
                    qw=pose.pose.orientation.w,
                )
                for pose in path_msg.poses
            ],
        )
        with self._downlink_lock:
            self._downlink_bundle = DownlinkBundle(
                pose=pose_payload,
                twist=twist_payload,
                path=path_payload,
            )

    # ------------------------------------------------------------------
    # Downlink timer

    def _downlink_tick(self) -> None:
        with self._downlink_lock:
            conn = self._downlink_conn
            bundle = self._downlink_bundle
        if conn is None or bundle.pose is None or bundle.twist is None or bundle.path is None:
            return
        if time.monotonic() - self._last_heartbeat > self.heartbeat_interval * 2.0:
            return

        try:
            self._send_downlink(conn, bundle)
        except Exception as exc:  # pragma: no cover - network errors
            self.get_logger().warning(f"Downlink send failed: {exc}")
            with self._downlink_lock:
                self._downlink_conn = None

    def _send_downlink(self, conn: socket.socket, bundle: DownlinkBundle) -> None:
        messages = [
            build_pose_message(bundle.pose),
            build_path_message(bundle.path),
            build_twist_message(bundle.twist),
        ]
        bytes_written = 0
        for msg in messages:
            if self.downlink_protocol == "json":
                payload = message_to_json(msg)
                out = Message(kind=msg.kind, name=msg.name, payload=payload)
            else:
                # Already encoded in binary by build_* helper.
                payload = msg.payload
                out = Message(kind=msg.kind, name=msg.name, payload=payload)
            send_message(conn, out)
            bytes_written += len(payload)
        self._downlink_messages += len(messages)
        self._downlink_bytes_total += bytes_written
        self._last_downlink_bytes = bytes_written

    # ------------------------------------------------------------------
    def destroy_node(self) -> None:  # pragma: no cover - shutdown path
        self._running = False
        super().destroy_node()
        for sock in (self._uplink_socket, self._downlink_socket, self._downlink_conn):
            if sock:
                try:
                    sock.close()
                except Exception:
                    pass


def _partition_ros_args(argv: list[str]) -> tuple[list[str], list[str]]:
    """Return ROS-compatible args and any extras to ignore."""

    argv = list(argv)
    filtered = remove_ros_args(["stream_server", *argv])[1:]
    extras: list[str] = []
    ros_args: list[str] = []
    idx = 0
    for arg in argv:
        if idx < len(filtered) and arg == filtered[idx]:
            extras.append(arg)
            idx += 1
        else:
            ros_args.append(arg)
    return ros_args, extras


def main(argv: list[str] | None = None) -> None:
    raw_args = list(argv) if argv is not None else sys.argv[1:]
    ros_args, extras = _partition_ros_args(raw_args)
    if extras:
        print(
            f"[stream_server] Ignoring legacy CLI arguments: {' '.join(extras)}",
            file=sys.stderr,
        )
    rclpy.init(args=ros_args)
    node = StreamServerNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
