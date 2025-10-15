from __future__ import annotations

from typing import List, Set, Tuple

import rclpy
from geometry_msgs.msg import TransformStamped
from rclpy.duration import Duration
from rclpy.node import Node
from tf2_ros import Buffer, TransformBroadcaster, TransformException, TransformListener


Link = Tuple[str, str]


class TfFallbackNode(Node):
    """필요한 TF가 없을 때 임시 항등 변환을 방송해 시각화가 끊기지 않도록 한다."""

    def __init__(self) -> None:
        super().__init__("tf_fallback")
        self.declare_parameter("world_frame_id", "map")
        self.declare_parameter("odom_frame_id", "odom")
        self.declare_parameter("base_frame_id", "base_link")
        self.declare_parameter("sensor_frame_id", "lidar_frame")
        self.declare_parameter("check_period_sec", 0.5)
        self.declare_parameter("timeout_sec", 0.0)

        world = self.get_parameter("world_frame_id").get_parameter_value().string_value
        odom = self.get_parameter("odom_frame_id").get_parameter_value().string_value
        base = self.get_parameter("base_frame_id").get_parameter_value().string_value
        sensor = (
            self.get_parameter("sensor_frame_id").get_parameter_value().string_value
        )
        check_period = (
            self.get_parameter("check_period_sec").get_parameter_value().double_value
        )
        timeout_sec = (
            self.get_parameter("timeout_sec").get_parameter_value().double_value
        )

        self._timeout = Duration(seconds=max(timeout_sec, 0.0))
        self._links = self._build_links(world, odom, base, sensor)
        if not self._links:
            self.get_logger().warn("모니터링할 프레임 쌍이 없습니다. 노드는 대기 상태로 유지됩니다.")

        self._buffer = Buffer(cache_time=Duration(seconds=5.0))
        self._listener = TransformListener(self._buffer, self, spin_thread=True)
        self._broadcaster = TransformBroadcaster(self)
        self._missing: Set[Link] = set()

        period = max(check_period, 0.1)
        self._timer = self.create_timer(period, self._on_timer)

    @staticmethod
    def _build_links(world: str, odom: str, base: str, sensor: str) -> List[Link]:
        links: List[Link] = []
        if world and odom and world != odom:
            links.append((world, odom))
        if odom and base and odom != base:
            links.append((odom, base))
        elif odom and sensor and odom != sensor:
            links.append((odom, sensor))
        if base and sensor and base != sensor:
            links.append((base, sensor))
        elif world and sensor and world != sensor and (world, sensor) not in links:
            links.append((world, sensor))
        return links

    def _on_timer(self) -> None:
        if not self._links:
            return
        now = self.get_clock().now()
        stamp = now.to_msg()
        for parent, child in self._links:
            try:
                if self._buffer.can_transform(
                    parent, child, rclpy.time.Time(), self._timeout
                ):
                    if (parent, child) in self._missing:
                self.get_logger().info(
                    f"TF {parent} -> {child} 가 다시 제공되고 있어 임시 변환을 중단합니다."
                )
                self._missing.remove((parent, child))
            continue
        except TransformException:
            pass

        if (parent, child) not in self._missing:
            self.get_logger().warn(
                f"TF {parent} -> {child} 를 찾을 수 없습니다. 항등 변환을 발행합니다."
            )
            self._missing.add((parent, child))
        self._broadcast_identity(parent, child, stamp)

    def _broadcast_identity(self, parent: str, child: str, stamp) -> None:
        msg = TransformStamped()
        msg.header.stamp = stamp
        msg.header.frame_id = parent
        msg.child_frame_id = child
        msg.transform.translation.x = 0.0
        msg.transform.translation.y = 0.0
        msg.transform.translation.z = 0.0
        msg.transform.rotation.w = 1.0
        msg.transform.rotation.x = 0.0
        msg.transform.rotation.y = 0.0
        msg.transform.rotation.z = 0.0
        self._broadcaster.sendTransform(msg)


def main() -> None:
    rclpy.init()
    node = TfFallbackNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
