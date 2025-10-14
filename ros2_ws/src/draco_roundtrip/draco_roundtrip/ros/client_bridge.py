"""Client-side ROS bridge for playback and control-plane telemetry."""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np
import rclpy
from geometry_msgs.msg import PoseStamped, Twist
from nav_msgs.msg import Path
from rclpy.node import Node
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import PointCloud2
from sensor_msgs_py import point_cloud2 as pc2
from std_msgs.msg import Header


QueueItem = tuple[str, object]
CmdVelCallback = Callable[[Twist], None]


def _resolve_topic(prefix: str, base: str) -> str:
    if not prefix:
        return base
    prefix = prefix.strip()
    if not prefix.startswith("/"):
        prefix = f"/{prefix}"
    prefix = prefix.rstrip("/")
    return f"{prefix}/{base.lstrip('/')}"


@dataclass(slots=True)
class PlaybackJob:
    frame_idx: int
    name: str
    source: np.ndarray
    decoded: np.ndarray
    frame_id: str


class ClientBridgeNode(Node):
    """ROS node that publishes playback clouds and downlink telemetry."""

    def __init__(
        self,
        queue_obj: "queue.Queue[QueueItem]",
        playback_prefix: str,
        playback_frame_id: str,
        playback_period: float,
        pose_topic: str,
        path_topic: str,
        twist_topic: str,
        execute_cmdvel: bool,
        cmdvel_callback: Optional[CmdVelCallback],
    ) -> None:
        super().__init__("draco_client_bridge")
        qos = QoSProfile(depth=10)
        qos.history = HistoryPolicy.KEEP_LAST
        qos.reliability = ReliabilityPolicy.RELIABLE
        self.pub_src = self.create_publisher(PointCloud2, f"/{playback_prefix}/source" if playback_prefix else "/stream_pair/source", qos)
        self.pub_dec = self.create_publisher(PointCloud2, f"/{playback_prefix}/decoded" if playback_prefix else "/stream_pair/decoded", qos)
        self.pub_pose = self.create_publisher(PoseStamped, pose_topic, qos)
        self.pub_path = self.create_publisher(Path, path_topic, qos)
        self.pub_twist = self.create_publisher(Twist, twist_topic, qos)
        self.queue = queue_obj
        self.playback_frame_id = playback_frame_id
        self.execute_cmdvel = execute_cmdvel
        self.cmdvel_callback = cmdvel_callback
        self.playback_period = playback_period
        period = playback_period if playback_period > 0 else 0.1
        self.timer = self.create_timer(period, self._tick)

    def _tick(self) -> None:
        processed = 0
        while processed < 16:
            try:
                item = self.queue.get_nowait()
            except queue.Empty:
                return
            processed += 1
            kind, payload = item
            if kind == "shutdown":
                self.get_logger().info("Client bridge shutting down")
                rclpy.shutdown()
                return
            if kind == "playback":
                job = payload  # type: ignore[assignment]
                assert isinstance(job, PlaybackJob)
                self._publish_playback(job)
            elif kind == "pose":
                assert isinstance(payload, PoseStamped)
                self.pub_pose.publish(payload)
            elif kind == "path":
                assert isinstance(payload, Path)
                self.pub_path.publish(payload)
            elif kind == "twist":
                assert isinstance(payload, Twist)
                self.pub_twist.publish(payload)
                if self.execute_cmdvel and self.cmdvel_callback:
                    try:
                        self.cmdvel_callback(payload)
                    except Exception as exc:  # pragma: no cover - user callback
                        self.get_logger().warning(f"cmd_vel callback failed: {exc}")
            else:
                self.get_logger().warning(f"Unknown queue command: {kind}")

    def _publish_playback(self, job: PlaybackJob) -> None:
        now = self.get_clock().now().to_msg()
        header = Header()
        header.stamp = now
        header.frame_id = job.frame_id or self.playback_frame_id
        msg_src = pc2.create_cloud_xyz32(header, job.source)
        msg_dec = pc2.create_cloud_xyz32(header, job.decoded)
        self.pub_src.publish(msg_src)
        self.pub_dec.publish(msg_dec)
        self.get_logger().debug(f"Published playback frame {job.frame_idx}: {job.name}")


class ClientBridge:
    """Background thread helper exposing ROS publishing primitives."""

    def __init__(
        self,
        playback_frame_id: str,
        playback_prefix: str,
        playback_hz: float,
        topic_prefix: str,
        execute_cmdvel: bool,
        cmdvel_callback: Optional[CmdVelCallback] = None,
    ) -> None:
        self.queue: "queue.Queue[QueueItem]" = queue.Queue()
        pose_topic = _resolve_topic(topic_prefix, "/server_pose")
        path_topic = _resolve_topic(topic_prefix, "/planned_path")
        twist_topic = _resolve_topic(topic_prefix, "/cmd_vel")
        playback_prefix = playback_prefix.strip("/")
        playback_period = 1.0 / playback_hz if playback_hz > 0 else 0.1

        def _run() -> None:
            rclpy.init()
            node = ClientBridgeNode(
                self.queue,
                playback_prefix,
                playback_frame_id,
                playback_period,
                pose_topic,
                path_topic,
                twist_topic,
                execute_cmdvel,
                cmdvel_callback,
            )
            try:
                rclpy.spin(node)
            except KeyboardInterrupt:  # pragma: no cover - user interrupt
                pass
            finally:
                node.destroy_node()
                if rclpy.ok():
                    rclpy.shutdown()

        self.thread = threading.Thread(target=_run, daemon=True)
        self.thread.start()

    # ------------------------------------------------------------------
    def publish_playback(self, frame_idx: int, name: str, source: np.ndarray, decoded: np.ndarray, frame_id: str) -> None:
        self.queue.put(("playback", PlaybackJob(frame_idx, name, source, decoded, frame_id)))

    def publish_pose(self, pose: PoseStamped) -> None:
        self.queue.put(("pose", pose))

    def publish_path(self, path: Path) -> None:
        self.queue.put(("path", path))

    def publish_twist(self, twist: Twist) -> None:
        self.queue.put(("twist", twist))

    def close(self) -> None:
        self.queue.put(("shutdown", None))
        if self.thread.is_alive():
            self.thread.join(timeout=1.0)

