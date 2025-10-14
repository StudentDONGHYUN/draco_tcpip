#!/usr/bin/env python3
"""Server-centric Draco streaming bridge with control-plane downlink."""

from __future__ import annotations

import argparse
import socket
import subprocess
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
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import PointCloud2
from sensor_msgs_py import point_cloud2 as pc2
from std_msgs.msg import Header

import numpy as np

from draco_roundtrip.io.ply_codec import load_xyz_from_bytes
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
from draco_roundtrip.utils import ensure_directory, resolve_executable


@dataclass(slots=True)
class DownlinkBundle:
    pose: Optional[PosePayload] = None
    twist: Optional[TwistPayload] = None
    path: Optional[PathPayload] = None


def decode_drc(decoder: FSPath, drc_bytes: bytes, out_dir: FSPath, stem: str) -> bytes:
    """Decode a Draco .drc byte stream to binary PLY bytes."""
    ensure_directory(out_dir)
    drc_path = out_dir / f"{stem}.drc"
    ply_path = out_dir / f"{stem}.decoded.ply"
    drc_path.write_bytes(drc_bytes)
    cmd = [str(decoder), "-i", str(drc_path), "-o", str(ply_path)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"draco_decoder failed (rc={proc.returncode}):\n"
            f"STDOUT: {proc.stdout.strip()}\nSTDERR: {proc.stderr.strip()}"
        )
    return ply_path.read_bytes()


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Server-centric Draco streaming bridge")
    ap.add_argument("--host", default="0.0.0.0", help="Uplink listen address")
    ap.add_argument("--port", type=int, default=5000, help="Uplink listen port")
    ap.add_argument("--decoder", default=None, help="Path to draco_decoder executable")
    ap.add_argument("--work-dir", default="data/server_tmp", help="Temporary working directory")
    ap.add_argument("--points-topic", default="/server/points", help="PointCloud2 publish topic")
    ap.add_argument("--points-frame-id", default="server_lidar", help="Frame ID for published PointCloud2")
    ap.add_argument("--pose-topic", default="/server_pose", help="Downlink pose ROS topic")
    ap.add_argument("--path-topic", default="/planned_path", help="Downlink path ROS topic")
    ap.add_argument("--twist-topic", default="/cmd_vel", help="Downlink twist ROS topic")
    ap.add_argument("--downlink-port", type=int, default=None, help="Control-plane downlink port (default: uplink port+1)")
    ap.add_argument(
        "--downlink-protocol",
        choices=("binary", "json"),
        default="binary",
        help="Downlink payload encoding",
    )
    ap.add_argument(
        "--downlink-json",
        action="store_true",
        help="Shortcut to force JSON downlink encoding",
    )
    ap.add_argument("--downlink-rate", type=float, default=10.0, help="Downlink publish rate in Hz (max)")
    ap.add_argument(
        "--legacy-downlink",
        action="store_true",
        help="Re-enable legacy decoded PLY downlink responses",
    )
    ap.add_argument(
        "--heartbeat-interval",
        type=float,
        default=1.0,
        help="Expected heartbeat interval from clients in seconds",
    )
    ap.add_argument(
        "--path-length",
        type=int,
        default=20,
        help="Number of poses to emit in stub path outputs (<=200)",
    )
    ap.add_argument(
        "--stub-path-stride",
        type=float,
        default=0.25,
        help="Spacing (m) between poses in stub path output",
    )
    return ap


class StreamServerNode(Node):
    """Accept Draco uplink, publish ROS topics, and stream control-plane telemetry."""

    def __init__(self, args: argparse.Namespace) -> None:
        super().__init__("draco_stream_server")
        self.args = args
        self.decoder = resolve_executable("draco_decoder", args.decoder, env_var="DRACO_DECODER")
        self.work_dir = ensure_directory(FSPath(args.work_dir).resolve())
        qos = QoSProfile(depth=10)
        qos.history = HistoryPolicy.KEEP_LAST
        qos.reliability = ReliabilityPolicy.RELIABLE
        self.pub_points = self.create_publisher(PointCloud2, args.points_topic, qos)
        self.pub_pose = self.create_publisher(PoseStamped, args.pose_topic, qos)
        self.pub_path = self.create_publisher(NavPath, args.path_topic, qos)
        self.pub_twist = self.create_publisher(Twist, args.twist_topic, qos)
        self.downlink_protocol = "json" if args.downlink_json else args.downlink_protocol
        self.downlink_rate = max(float(args.downlink_rate), 0.1)
        self.heartbeat_interval = max(float(args.heartbeat_interval), 0.1)
        self.path_length = max(1, min(int(args.path_length), PATH_POSE_LIMIT))
        self.stub_stride = float(args.stub_path_stride)
        self.legacy_downlink = bool(args.legacy_downlink)
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
        self._points_frame_id = args.points_frame_id

        self._uplink_thread = threading.Thread(target=self._run_uplink, daemon=True)
        self._downlink_thread = threading.Thread(target=self._run_downlink, daemon=True)
        self._running = True

        self._downlink_timer = self.create_timer(1.0 / self.downlink_rate, self._downlink_tick)
        self._uplink_thread.start()
        self._downlink_thread.start()

    # ------------------------------------------------------------------
    # Networking

    def _run_uplink(self) -> None:
        host = self.args.host
        port = int(self.args.port)
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
                            self.get_logger().exception(f"Uplink session error: {exc}")
                        finally:
                            self.get_logger().info("Uplink session finished")
        except Exception as exc:  # pragma: no cover - defensive logging
            self.get_logger().exception(f"Failed to start uplink server: {exc}")

    def _run_downlink(self) -> None:
        port = int(self.args.downlink_port or (self.args.port + 1))
        host = self.args.host
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
            self.get_logger().exception(f"Downlink server error: {exc}")

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
                ply_bytes = decode_drc(self.decoder, msg.payload, self.work_dir, stem)
            except Exception as exc:
                error_msg = Message(kind=MSG_ERROR, name=stem, payload=str(exc).encode())
                send_message(conn, error_msg)
                self.get_logger().error(f"Failed to decode {stem}: {exc}")
                continue

            xyz = load_xyz_from_bytes(ply_bytes)
            self._publish_point_cloud(xyz)
            self._update_autonomy_outputs()

            if self.legacy_downlink:
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

    def _publish_point_cloud(self, xyz: np.ndarray) -> None:
        header = Header()
        header.stamp = self.get_clock().now().to_msg()
        header.frame_id = self._points_frame_id
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


def main(argv: list[str] | None = None) -> None:
    args = build_arg_parser().parse_args(argv)
    rclpy.init()
    node = StreamServerNode(args)
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
