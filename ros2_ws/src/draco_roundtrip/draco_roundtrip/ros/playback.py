"""ROS helper nodes for publishing point clouds."""

from __future__ import annotations

import queue
import threading
from typing import Optional

import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import PointCloud2
from sensor_msgs_py import point_cloud2 as pc2
from std_msgs.msg import Header


QueueItem = Optional[tuple[int, str, np.ndarray, np.ndarray]]


class PlaybackNode(Node):
    """Publish source/decoded point clouds to paired topics."""

    def __init__(self, queue_obj: "queue.Queue[QueueItem]", frame_id: str,
                 topic_prefix: str, hz: float) -> None:
        super().__init__('draco_roundtrip_playback')
        qos = QoSProfile(depth=1)
        qos.history = HistoryPolicy.KEEP_LAST
        qos.reliability = ReliabilityPolicy.RELIABLE
        self.pub_src = self.create_publisher(PointCloud2, f"/{topic_prefix}/source", qos)
        self.pub_dec = self.create_publisher(PointCloud2, f"/{topic_prefix}/decoded", qos)
        self.queue = queue_obj
        self.frame_id = frame_id
        self.period = 1.0 / hz if hz > 0 else 0.01
        self.timer = self.create_timer(self.period, self._tick)

    def _tick(self) -> None:
        try:
            item = self.queue.get_nowait()
        except queue.Empty:
            return
        if item is None:
            self.get_logger().info("Playback finished")
            rclpy.shutdown()
            return
        frame_idx, name, pts_src, pts_dec = item
        header = Header()
        header.stamp = self.get_clock().now().to_msg()
        header.frame_id = self.frame_id
        msg_src = pc2.create_cloud_xyz32(header, pts_src)
        msg_dec = pc2.create_cloud_xyz32(header, pts_dec)
        self.pub_src.publish(msg_src)
        self.pub_dec.publish(msg_dec)
        self.get_logger().debug(f"Published frame {frame_idx}: {name}")


def start_playback_thread(queue_obj: "queue.Queue[QueueItem]",
                          frame_id: str,
                          topic_prefix: str,
                          hz: float) -> threading.Thread:
    """Run a background thread that publishes queued point clouds."""

    def _run() -> None:
        rclpy.init()
        node = PlaybackNode(queue_obj, frame_id, topic_prefix, hz)
        try:
            rclpy.spin(node)
        except KeyboardInterrupt:
            pass
        finally:
            node.destroy_node()
            if rclpy.ok():
                rclpy.shutdown()

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return thread
