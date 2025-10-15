from __future__ import annotations

import time
from typing import Dict, List, Optional, Set

import rclpy
from rclpy.client import Client
from rclpy.node import Node
from rclpy.task import Future
from rosgraph_msgs.msg import Clock
from std_srvs.srv import Empty


class TimeJumpResetNode(Node):
    """감시 중인 시뮬레이션 시간이 과거로 되돌아갈 때 odom 관련 노드를 리셋한다."""

    def __init__(self) -> None:
        super().__init__("time_jump_reset")

        self.jump_back_threshold_sec: float = (
            self.declare_parameter("jump_back_threshold_sec", 0.5)
            .get_parameter_value()
            .double_value
        )
        self.reset_cooldown_sec: float = (
            self.declare_parameter("reset_cooldown_sec", 1.0)
            .get_parameter_value()
            .double_value
        )
        self.reset_services: List[str] = (
            self.declare_parameter(
                "reset_services",
                [
                    "/icp_odometry/reset",
                    "/rtabmap/reset",
                ],
            )
            .get_parameter_value()
            .string_array_value
        )

        self._clock_subscription = self.create_subscription(
            Clock, "/clock", self._on_clock, 100
        )

        self._service_clients: Dict[str, Client] = {
            name: self.create_client(Empty, name) for name in self.reset_services
        }
        self._pending_calls: List[Future] = []
        self._missing_service_logs: Set[str] = set()
        self._last_clock_sec: Optional[float] = None
        self._last_reset_monotonic: Optional[float] = None

        if not self.reset_services:
            self.get_logger().warn("reset_services 파라미터가 비어 있어 감시만 수행합니다.")

    def _on_clock(self, msg: Clock) -> None:
        current_sec = float(msg.clock.sec) + float(msg.clock.nanosec) * 1e-9
        if self._last_clock_sec is None:
            self._last_clock_sec = current_sec
            return

        if current_sec < self._last_clock_sec - 1e-9:
            jump = self._last_clock_sec - current_sec
            if jump >= self.jump_back_threshold_sec:
                now_monotonic = time.monotonic()
                if (
                    self._last_reset_monotonic is None
                    or now_monotonic - self._last_reset_monotonic
                    >= self.reset_cooldown_sec
                ):
                    self._last_reset_monotonic = now_monotonic
                    self._trigger_reset(jump)
            else:
                self.get_logger().debug(
                    "감지된 시간 점프(%fs)가 임계값보다 작아 무시되었습니다.", jump
                )

        self._last_clock_sec = current_sec

    def _trigger_reset(self, jump: float) -> None:
        self.get_logger().warn(
            "시뮬레이션 시간이 %0.3fs 만큼 과거로 이동했습니다. 관련 노드를 리셋합니다.",
            jump,
        )
        for name, client in self._service_clients.items():
            if not client.wait_for_service(timeout_sec=0.0):
                if name not in self._missing_service_logs:
                    self.get_logger().warning(
                        "리셋 서비스 %s 를 아직 사용할 수 없습니다. 이후 다시 시도합니다.", name
                    )
                    self._missing_service_logs.add(name)
                continue

            if name in self._missing_service_logs:
                self.get_logger().info("리셋 서비스 %s 가 사용 가능해졌습니다.", name)
                self._missing_service_logs.remove(name)

            request = Empty.Request()
            future = client.call_async(request)
            self._pending_calls.append(future)
            future.add_done_callback(
                lambda fut, service_name=name: self._on_reset_call_done(
                    service_name, fut
                )
            )

    def _on_reset_call_done(self, service_name: str, future: Future) -> None:
        try:
            future.result()
        except Exception as exc:  # noqa: BLE001 - 구체 오류 메시지 전달이 목적
            self.get_logger().error(
                "리셋 서비스 %s 호출에 실패했습니다: %s", service_name, exc
            )
        else:
            self.get_logger().info("리셋 서비스 %s 호출을 완료했습니다.", service_name)
        finally:
            if future in self._pending_calls:
                self._pending_calls.remove(future)


def main() -> None:
    rclpy.init()
    node = TimeJumpResetNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
