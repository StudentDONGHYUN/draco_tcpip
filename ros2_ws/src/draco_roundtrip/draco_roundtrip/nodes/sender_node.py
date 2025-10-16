
#!/usr/bin/env python3
"""ROS 2 node for sending compressed point clouds and handling server communication."""

from __future__ import annotations

import json
import queue
import socket
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import rclpy
from draco_roundtrip.analysis.metrics import compute_basic_metrics
from draco_roundtrip.io.ply_codec import load_xyz_from_bytes
from draco_roundtrip.msg import CompressedPointCloud
from draco_roundtrip.net.control_plane import (
    PathPayload,
    PathPose,
    PosePayload,
    TwistPayload,
    decode_path_payload,
    decode_pose_payload,
    decode_twist_payload,
)
from draco_roundtrip.net.protocol import (
    ConnectionClosed,
    Message,
    MSG_ACK,
    MSG_DATA,
    MSG_ERROR,
    MSG_HEARTBEAT,
    MSG_PATH,
    MSG_POSE,
    MSG_TWIST,
    recv_message,
    send_message,
)
from draco_roundtrip.utils import ensure_directory
from geometry_msgs.msg import PoseStamped, Twist
from nav_msgs.msg import Path as NavPath
from rclpy.node import Node
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import PointCloud2
from sensor_msgs_py import point_cloud2 as pc2
from std_msgs.msg import Header


def _time_from_ns(stamp_ns: int) -> tuple[int, int]:
    sec = int(stamp_ns // 1_000_000_000)
    nsec = int(stamp_ns % 1_000_000_000)
    return sec, nsec


def _pose_to_msg(payload: PosePayload) -> PoseStamped:
    msg = PoseStamped()
    msg.header.stamp.sec, msg.header.stamp.nanosec = _time_from_ns(payload.stamp_ns)
    msg.header.frame_id = payload.frame_id or "map"
    msg.pose.position.x = payload.x
    msg.pose.position.y = payload.y
    msg.pose.position.z = payload.z
    msg.pose.orientation.x = payload.qx
    msg.pose.orientation.y = payload.qy
    msg.pose.orientation.z = payload.qz
    msg.pose.orientation.w = payload.qw
    return msg


def _path_to_msg(payload: PathPayload) -> NavPath:
    msg = NavPath()
    msg.header.stamp.sec, msg.header.stamp.nanosec = _time_from_ns(payload.stamp_ns)
    msg.header.frame_id = payload.frame_id or "map"
    msg.poses = []
    for pose in payload.poses:
        pose_msg = PoseStamped()
        pose_msg.header = msg.header
        pose_msg.pose.position.x = pose.x
        pose_msg.pose.position.y = pose.y
        pose_msg.pose.position.z = pose.z
        pose_msg.pose.orientation.x = pose.qx
        pose_msg.pose.orientation.y = pose.qy
        pose_msg.pose.orientation.z = pose.qz
        pose_msg.pose.orientation.w = pose.qw
        msg.poses.append(pose_msg)
    return msg


def _twist_to_msg(payload: TwistPayload) -> Twist:
    msg = Twist()
    msg.linear.x = payload.vx
    msg.linear.y = payload.vy
    msg.linear.z = payload.vz
    msg.angular.x = payload.wx
    msg.angular.y = payload.wy
    msg.angular.z = payload.wz
    return msg


def _decode_downlink_message(msg: Message, protocol: str) -> Optional[tuple[str, object]]:
    if protocol == "json":
        try:
            data = json.loads(msg.payload.decode("utf-8"))
        except Exception as exc:
            print(f"[SENDER] Failed to parse JSON downlink: {exc}")
            return None
        kind = data.get("type", msg.kind)
        if kind == MSG_POSE:
            payload = PosePayload(
                stamp_ns=int(data["stamp_ns"]),
                frame_id=str(data.get("frame_id", "map")),
                x=float(data["position"]["x"]),
                y=float(data["position"]["y"]),
                z=float(data["position"]["z"]),
                qx=float(data["orientation"]["x"]),
                qy=float(data["orientation"]["y"]),
                qz=float(data["orientation"]["z"]),
                qw=float(data["orientation"]["w"]),
            )
            return (MSG_POSE, _pose_to_msg(payload))
        if kind == MSG_TWIST:
            # ... (similar implementation as stream_client)
            pass
        if kind == MSG_PATH:
            # ... (similar implementation as stream_client)
            pass
        return None

    if msg.kind == MSG_POSE:
        return (MSG_POSE, _pose_to_msg(decode_pose_payload(msg.payload)))
    if msg.kind == MSG_TWIST:
        return (MSG_TWIST, _twist_to_msg(decode_twist_payload(msg.payload)))
    if msg.kind == MSG_PATH:
        return (MSG_PATH, _path_to_msg(decode_path_payload(msg.payload)))
    return None


class SenderNode(Node):
    """Node that sends compressed data and manages server communication."""

    def __init__(self) -> None:
        super().__init__("sender_node")

        # Declare parameters
        self.declare_parameter("server_host", "127.0.0.1")
        self.declare_parameter("server_port", 5000)
        self.declare_parameter("downlink_host", "")
        self.declare_parameter("downlink_port", 0)
        self.declare_parameter("downlink_protocol", "binary")
        self.declare_parameter("topic_prefix", "")
        self.declare_parameter("heartbeat_interval", 1.0)
        self.declare_parameter("telemetry_rate", 10.0)
        self.declare_parameter("socket_timeout", 3.0)
        self.declare_parameter("max_queue_size", 64)

        # Get parameters
        self.server_host = str(self.get_parameter("server_host").value)
        self.server_port = int(self.get_parameter("server_port").value)
        self.topic_prefix = str(self.get_parameter("topic_prefix").value)
        self.heartbeat_interval = max(float(self.get_parameter("heartbeat_interval").value), 0.5)
        self.telemetry_rate = float(self.get_parameter("telemetry_rate").value)
        self.socket_timeout = max(float(self.get_parameter("socket_timeout").value), 0.5)
        downlink_host_param = str(self.get_parameter("downlink_host").value)
        self.downlink_host = downlink_host_param or self.server_host
        downlink_port_param = int(self.get_parameter("downlink_port").value)
        self.downlink_port = downlink_port_param if downlink_port_param else self.server_port + 1
        self.downlink_protocol = str(self.get_parameter("downlink_protocol").value)
        max_queue_size = int(self.get_parameter("max_queue_size").value)

        # ROS Publishers for downlink messages
        qos = QoSProfile(
            depth=10, history=HistoryPolicy.KEEP_LAST, reliability=ReliabilityPolicy.RELIABLE
        )
        pose_topic = f"{self.topic_prefix}/server_pose" if self.topic_prefix else "/server_pose"
        path_topic = f"{self.topic_prefix}/planned_path" if self.topic_prefix else "/planned_path"
        twist_topic = f"{self.topic_prefix}/cmd_vel" if self.topic_prefix else "/cmd_vel"
        self.pub_pose = self.create_publisher(PoseStamped, pose_topic, qos)
        self.pub_path = self.create_publisher(NavPath, path_topic, qos)
        self.pub_twist = self.create_publisher(Twist, twist_topic, qos)

        # Inter-thread queues
        self._msg_queue: "queue.Queue[CompressedPointCloud]" = queue.Queue(maxsize=max_queue_size)

        # Subscriber for compressed data
        sub_qos = QoSProfile(depth=max_queue_size, history=HistoryPolicy.KEEP_LAST)
        sub_qos.reliability = ReliabilityPolicy.RELIABLE
        self.create_subscription(
            CompressedPointCloud, "/compressed_pointcloud", self._on_compressed_msg, sub_qos
        )

        # Telemetry and threading setup
        self._metrics_lock = threading.Lock()
        self._bytes_sent = 0
        self._bytes_received = 0
        self._frames_sent = 0
        self._start_time = time.monotonic()
        self._telemetry_timer = None
        if self.telemetry_rate > 0:
            period = 1.0 / self.telemetry_rate
            self._telemetry_timer = self.create_timer(period, self._telemetry_tick)

        self._stop_event = threading.Event()
        self._downlink_stop = threading.Event()
        self._downlink_thread: Optional[threading.Thread] = None
        self._sender_thread: Optional[threading.Thread] = None

        self._queue_keep_latest = 5

        self._dropped_frames = 0
        self._last_drop_log = 0.0

        self._sender_thread = threading.Thread(target=self._run_sender_loop, daemon=True)
        self._sender_thread.start()

    def _on_compressed_msg(self, msg: CompressedPointCloud):
        try:
            self._msg_queue.put_nowait(msg)
        except queue.Full:
            self._dropped_frames += 1
            now = time.monotonic()
            if now - self._last_drop_log > 1.0:
                self.get_logger().warning(
                    "Compressed message queue full; dropping newest frame. "
                    f"total_dropped={self._dropped_frames}"
                )
                self._last_drop_log = now
            return

    def _telemetry_tick(self) -> None:
        with self._metrics_lock:
            bytes_sent = self._bytes_sent
            bytes_received = self._bytes_received
            frames_sent = self._frames_sent
        elapsed = max(time.monotonic() - self._start_time, 1e-6)
        uplink_mbps = bytes_sent * 8 / elapsed / 1e6
        downlink_mbps = bytes_received * 8 / elapsed / 1e6
        self.get_logger().info(
            f"Telemetry: frames={frames_sent} uplink={uplink_mbps:.3f} Mbps downlink={downlink_mbps:.3f} Mbps"
        )

    def _run_sender_loop(self) -> None:
        self._start_time = time.monotonic()

        backoff = 1.0
        while not self._stop_event.is_set():
            self._downlink_stop.clear()
            self._downlink_thread = threading.Thread(
                target=self._downlink_loop,
                args=(self.downlink_host, self.downlink_port, self.downlink_protocol),
                daemon=True,
            )
            self._downlink_thread.start()

            try:
                with socket.create_connection(
                    (self.server_host, self.server_port), timeout=self.socket_timeout
                ) as sock:
                    sock.settimeout(self.socket_timeout)
                    self.get_logger().info(
                        f"Connected to {self.server_host}:{self.server_port}"
                    )
                    backoff = 1.0

                    self._trim_queue_keep_latest(self._queue_keep_latest)

                    while not self._stop_event.is_set():
                        try:
                            ros_msg = self._msg_queue.get(timeout=self.heartbeat_interval)
                        except queue.Empty:
                            send_message(sock, Message(kind=MSG_HEARTBEAT, name="hb", payload=b""))
                            ack = recv_message(sock)
                            if ack is None:
                                raise ConnectionClosed("server closed uplink during heartbeat")
                            continue

                        try:
                            drc_bytes = bytes(ros_msg.data)
                            message = Message(
                                kind=MSG_DATA,
                                name=ros_msg.frame_name,
                                payload=drc_bytes,
                                frame_id=ros_msg.header.frame_id,
                            )
                            send_message(sock, message)

                            with self._metrics_lock:
                                self._bytes_sent += len(drc_bytes)
                                self._frames_sent += 1

                            self.get_logger().info(
                                f"Sent {message.name} ({len(drc_bytes)} bytes)"
                            )

                            reply = recv_message(sock)
                            if reply is None:
                                raise ConnectionClosed("server closed uplink")
                            if reply.kind == MSG_ERROR:
                                detail = reply.payload.decode(errors="ignore")
                                self.get_logger().error(
                                    f"SERVER ERROR for {message.name}: {reply.name} -> {detail}"
                                )
                                continue

                            if reply.kind == MSG_DATA:
                                with self._metrics_lock:
                                    self._bytes_received += len(reply.payload)
                        finally:
                            self._msg_queue.task_done()

            except ConnectionClosed:
                if self._stop_event.is_set():
                    break
                self.get_logger().warning("Connection closed, will retry uplink")
            except Exception as e:
                if self._stop_event.is_set():
                    break
                self.get_logger().error(f"Sender loop error: {e}")
            finally:
                self._downlink_stop.set()
                if self._downlink_thread and self._downlink_thread.is_alive():
                    self._downlink_thread.join(timeout=2.0)

            if self._stop_event.is_set():
                break

            wait_time = backoff
            self.get_logger().info(
                f"Retrying uplink connection to {self.server_host}:{self.server_port} in {wait_time:.1f}s"
            )
            self._stop_event.wait(wait_time)
            backoff = min(backoff * 2.0, 5.0)

    def _trim_queue_keep_latest(self, keep: int) -> None:
        if keep <= 0:
            keep = 1
        kept: list[CompressedPointCloud] = []
        while True:
            try:
                item = self._msg_queue.get_nowait()
            except queue.Empty:
                break
            self._msg_queue.task_done()
            kept.append(item)
        if not kept:
            return
        to_keep = kept[-keep:]
        dropped = len(kept) - len(to_keep)
        for item in to_keep:
            try:
                self._msg_queue.put_nowait(item)
            except queue.Full:
                self._dropped_frames += 1
                break
        if dropped > 0:
            self._dropped_frames += dropped
            self.get_logger().info(
                f"Trimmed {dropped} queued frames after uplink connection "
                f"(keep_latest={keep}, total_dropped={self._dropped_frames})"
            )

    def _downlink_loop(self, host: str, port: int, protocol: str) -> None:
        backoff = 1.0
        while not self._downlink_stop.is_set():
            try:
                with socket.create_connection((host, port), timeout=self.socket_timeout) as sock:
                    sock.settimeout(self.socket_timeout)
                    self.get_logger().info(f"Downlink connected to {host}:{port}")
                    backoff = 1.0
                    while not self._downlink_stop.is_set():
                        msg = recv_message(sock)
                        if msg is None:
                            break
                        decoded = _decode_downlink_message(msg, protocol)
                        if decoded is None:
                            continue
                        kind, payload = decoded
                        if kind == MSG_POSE:
                            self.pub_pose.publish(payload)
                        elif kind == MSG_TWIST:
                            self.pub_twist.publish(payload)
                        elif kind == MSG_PATH:
                            self.pub_path.publish(payload)
            except Exception as exc:
                if self._downlink_stop.is_set():
                    break
                self.get_logger().warning(f"Downlink error: {exc}, retrying in {backoff:.1f}s")
                self._downlink_stop.wait(backoff)
                backoff = min(backoff * 2.0, 5.0)

    def destroy_node(self) -> None:
        self.get_logger().info("Shutting down sender node...")
        self._stop_event.set()
        self._downlink_stop.set()
        if self._sender_thread and self._sender_thread.is_alive():
            self._sender_thread.join(timeout=2.0)
        if self._downlink_thread and self._downlink_thread.is_alive():
            self._downlink_thread.join(timeout=2.0)
        super().destroy_node()


def main(argv=None):
    rclpy.init(args=argv)
    node = SenderNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
