#!/usr/bin/env python3
"""Server-centric Draco streaming bridge with control-plane downlink."""

from __future__ import annotations

import io
import socket
import struct
import sys
import threading
import time
import base64
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path as FSPath
from typing import Optional

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
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
        session_start_time = time.monotonic()
        session_metrics = []

        try:
            while self._running and rclpy.ok():
                msg = recv_message(conn)
                if msg is None:
                    raise ConnectionClosed("uplink closed")
                
                receive_time_ns = time.monotonic_ns()

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
                    metadata_size = struct.calcsize('!IQQQ')
                    metadata = struct.unpack('!IQQQ', msg.payload[:metadata_size])
                    seq, original_size, compression_time_ns, send_time_ns = metadata
                    drc_bytes = msg.payload[metadata_size:]

                    decompress_start_ns = time.monotonic_ns()
                    points = decode_drc_to_points(drc_bytes)
                    decompress_end_ns = time.monotonic_ns()
                    decompression_time_ns = decompress_end_ns - decompress_start_ns

                except Exception as exc:
                    error_msg = Message(kind=MSG_ERROR, name=stem, payload=str(exc).encode())
                    send_message(conn, error_msg)
                    self.get_logger().error(f"Failed to decode {stem}: {exc}")
                    continue

                self._publish_point_cloud(points, frame_id=msg.frame_id)
                self._update_autonomy_outputs()

                session_metrics.append({
                    'seq': seq,
                    'original_size': original_size,
                    'compressed_size': len(drc_bytes),
                    'compression_time_ns': compression_time_ns,
                    'decompression_time_ns': decompression_time_ns,
                    'send_time_ns': send_time_ns,
                    'receive_time_ns': receive_time_ns,
                    'decompress_end_ns': decompress_end_ns,
                })

                if self.legacy_downlink:
                    ply_bytes = points_to_ply_bytes(points)
                    reply = Message(kind=MSG_DATA, name=f"{stem}.decoded", payload=ply_bytes)
                    send_message(conn, reply)
                    bytes_out += len(reply.payload)
                else:
                    ack = Message(kind=MSG_ACK, name=stem, payload=b"")
                    send_message(conn, ack)
        finally:
            self.get_logger().info(
                f"Uplink session summary: in={bytes_in} bytes, out={bytes_out} bytes"
            )
            self._generate_session_report(session_metrics, session_start_time)

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

    def _create_plot_base64(
        self, x_data, y_data, title, xlabel, ylabel, color='b'
    ) -> str:
        """Create a matplotlib plot and return it as a base64 encoded string."""
        try:
            fig, ax = plt.subplots(figsize=(12, 6), dpi=100)
            ax.plot(x_data, y_data, marker='.', linestyle='-', color=color)
            ax.set_title(title, fontsize=16)
            ax.set_xlabel(xlabel, fontsize=12)
            ax.set_ylabel(ylabel, fontsize=12)
            ax.grid(True)
            fig.tight_layout()

            buf = BytesIO()
            fig.savefig(buf, format="png")
            plt.close(fig)
            return base64.b64encode(buf.getvalue()).decode('ascii')
        except Exception as e:
            self.get_logger().error(f"Failed to create plot '{title}': {e}")
            return ""

    def _generate_session_report(self, metrics: list, start_time: float):
        if not metrics:
            self.get_logger().info("No metrics recorded for session, skipping report.")
            return

        total_time = time.monotonic() - start_time
        num_received = len(metrics)
        
        # --- Data Calculation ---
        seq_numbers = sorted([m['seq'] for m in metrics])
        expected_frames = seq_numbers[-1] - seq_numbers[0] + 1 if seq_numbers else 0
        lost_frames = expected_frames - num_received
        loss_rate = (lost_frames / expected_frames) * 100 if expected_frames > 0 else 0

        total_original_size = sum(m['original_size'] for m in metrics)
        total_compressed_size = sum(m['compressed_size'] for m in metrics)
        compression_ratio = total_original_size / total_compressed_size if total_compressed_size > 0 else 0
        bandwidth_mbps = (total_compressed_size * 8) / (total_time * 1e6) if total_time > 0 else 0
        fps = num_received / total_time if total_time > 0 else 0

        latencies_ms = [(m['decompress_end_ns'] - m['send_time_ns']) / 1e6 for m in metrics]
        avg_latency_ms = (sum(latencies_ms) / len(latencies_ms)) if latencies_ms else 0

        avg_compression_time_ms = sum(m['compression_time_ns'] for m in metrics) / num_received / 1e6
        avg_decompression_time_ms = sum(m['decompression_time_ns'] for m in metrics) / num_received / 1e6

        # --- Plotting ---
        frame_indices = [m['seq'] for m in metrics]
        latency_plot_b64 = self._create_plot_base64(
            frame_indices, latencies_ms, 'End-to-End Latency per Frame', 'Frame Sequence', 'Latency (ms)', 'r'
        )
        throughput_kb = [m['compressed_size'] / 1024 for m in metrics]
        throughput_plot_b64 = self._create_plot_base64(
            frame_indices, throughput_kb, 'Per-Frame Throughput', 'Frame Sequence', 'Compressed Size (KB)', 'g'
        )
        ratios = [m['original_size'] / m['compressed_size'] if m['compressed_size'] > 0 else 0 for m in metrics]
        ratio_plot_b64 = self._create_plot_base64(
            frame_indices, ratios, 'Per-Frame Compression Ratio', 'Frame Sequence', 'Ratio', 'b'
        )

        # --- HTML Generation ---
        html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Server Session Performance Report</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; margin: 0; padding: 2rem; background-color: #f4f7f9; color: #333; }}
        .container {{ max-width: 1200px; margin: auto; background: white; padding: 2rem; box-shadow: 0 4px 8px rgba(0,0,0,0.1); border-radius: 8px; }}
        h1, h2 {{ color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 10px; }}
        table {{ width: 100%; border-collapse: collapse; margin-bottom: 2rem; }}
        th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }}
        th {{ background-color: #ecf0f1; }}
        .summary-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1.5rem; margin-bottom: 2rem; }}
        .metric-card {{ background: #ecf0f1; padding: 1.5rem; border-radius: 8px; text-align: center; }}
        .metric-card .value {{ font-size: 2.5rem; font-weight: bold; color: #3498db; }}
        .metric-card .label {{ font-size: 1rem; color: #7f8c8d; }}
        .plot {{ margin-top: 2rem; text-align: center; }}
        img {{ max-width: 100%; height: auto; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Server Session Performance Report</h1>
        <p><strong>Report Generated:</strong> {datetime.now().isoformat()}</p>
        
        <h2>Summary</h2>
        <div class="summary-grid">
            <div class="metric-card"><div class="value">{num_received}</div><div class="label">Frames Received</div></div>
            <div class="metric-card"><div class="value">{lost_frames}</div><div class="label">Frames Lost ({loss_rate:.2f}%)</div></div>
            <div class="metric-card"><div class="value">{fps:.2f}</div><div class="label">Average FPS</div></div>
            <div class="metric-card"><div class="value">{bandwidth_mbps:.3f}</div><div class="label">Avg Throughput (Mbps)</div></div>
        </div>

        <h2>Latency & Processing</h2>
        <table>
            <tr><th>Metric</th><th>Value</th></tr>
            <tr><td>Avg. End-to-End Latency</td><td>{avg_latency_ms:.3f} ms</td></tr>
            <tr><td>Avg. Compression Time (client)</td><td>{avg_compression_time_ms:.3f} ms</td></tr>
            <tr><td>Avg. Decompression Time (server)</td><td>{avg_decompression_time_ms:.3f} ms</td></tr>
        </table>

        <h2>Compression</h2>
        <table>
            <tr><th>Metric</th><th>Value</th></tr>
            <tr><td>Avg. Compression Ratio</td><td>{compression_ratio:.2f} : 1</td></tr>
            <tr><td>Total Original Size</td><td>{total_original_size / 1e6:.2f} MB</td></tr>
            <tr><td>Total Compressed Size</td><td>{total_compressed_size / 1e6:.2f} MB</td></tr>
        </table>

        <h2>Per-Frame Analysis</h2>
        <div class="plot">
            <h2>End-to-End Latency</h2>
            <img src="data:image/png;base64,{latency_plot_b64}" alt="Latency Plot">
        </div>
        <div class="plot">
            <h2>Throughput</h2>
            <img src="data:image/png;base64,{throughput_plot_b64}" alt="Throughput Plot">
        </div>
        <div class="plot">
            <h2>Compression Ratio</h2>
            <img src="data:image/png;base64,{ratio_plot_b64}" alt="Compression Ratio Plot">
        </div>
    </div>
</body>
</html>
"""

        log_dir = FSPath('logs')
        log_dir.mkdir(exist_ok=True)
        report_file = log_dir / f"server_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
        report_file.write_text(html_content)
        self.get_logger().info(f"Server session report saved to {report_file}")

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
