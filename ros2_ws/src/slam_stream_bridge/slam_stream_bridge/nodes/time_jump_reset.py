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
            self.declare_parameter("reset_cooldown_sec", 2.0)
            .get_parameter_value()
            .double_value
        )
        self.pause_services: List[str] = (
            self.declare_parameter(
                "pause_services",
                ["/icp_odometry/pause", "/rtabmap/pause"],
            )
            .get_parameter_value()
            .string_array_value
        )
        self.resume_services: List[str] = (
            self.declare_parameter(
                "resume_services",
                ["/icp_odometry/resume", "/rtabmap/resume"],
            )
            .get_parameter_value()
            .string_array_value
        )
        self.reset_services: List[str] = (
            self.declare_parameter(
                "reset_services",
                ["/icp_odometry/reset", "/rtabmap/reset_odom"],
            )
            .get_parameter_value()
            .string_array_value
        )

        self._clock_subscription = self.create_subscription(
            Clock, "/clock", self._on_clock, 10
        )

        all_service_names = set(
            self.pause_services + self.resume_services + self.reset_services
        )
        self._service_clients: Dict[str, Client] = {
            name: self.create_client(Empty, name) for name in all_service_names
        }
        self._pending_calls: Set[Future] = set()
        self._missing_service_logs: Set[str] = set()
        self._last_clock_sec: Optional[float] = None
        self._last_reset_monotonic: Optional[float] = None
        self._resumed_once = False

        self.get_logger().info("노드 초기화 완료. 클라이언트 연결 및 /clock 수신 대기 중...")
        # rtabmap은 파라미터로 정지, icp_odometry는 서비스로 정지
        self._call_services(self.pause_services, silent=True)

    def _call_services(
        self, service_names: List[str], silent: bool = False
    ) -> List[Future]:
        """주어진 이름의 서비스들을 비동기적으로 호출한다."""
        futures = []
        for name in service_names:
            client = self._service_clients.get(name)
            if not client:
                if not silent:
                    self.get_logger().error(f"{name}에 대한 서비스 클라이언트가 없습니다.")
                continue

            if not client.wait_for_service(timeout_sec=0.2):
                if not silent and name not in self._missing_service_logs:
                    self.get_logger().warning(
                        f"서비스 {name} 를 사용할 수 없습니다. 이후 다시 시도합니다."
                    )
                    self._missing_service_logs.add(name)
                continue

            if name in self._missing_service_logs:
                self.get_logger().info(f"서비스 {name} 가 사용 가능해졌습니다.")
                self._missing_service_logs.remove(name)

            request = Empty.Request()
            future = client.call_async(request)
            self._pending_calls.add(future)
            futures.append(future)

            def on_call_done(fut: Future, service_name: str = name) -> None:
                try:
                    fut.result()
                    if not silent:
                        self.get_logger().info(f"서비스 {service_name} 호출을 완료했습니다.")
                except Exception as exc:
                    if not silent:
                        self.get_logger().error(
                            f"서비스 {service_name} 호출에 실패했습니다: {exc}"
                        )
                finally:
                    if fut in self._pending_calls:
                        self._pending_calls.remove(fut)

            future.add_done_callback(on_call_done)
        return futures

    def _on_clock(self, msg: Clock) -> None:
        current_sec = float(msg.clock.sec) + float(msg.clock.nanosec) * 1e-9

        if not self._resumed_once:
            self.get_logger().info("/clock 토픽 수신 시작. SLAM 시스템을 재개합니다.")
            self._call_services(self.resume_services)
            self._resumed_once = True
            self._last_clock_sec = current_sec
            return

        if self._last_clock_sec is None:
            self._last_clock_sec = current_sec
            return

        if current_sec < self._last_clock_sec - 1e-9:  # 시간 점프 감지
            jump = self._last_clock_sec - current_sec
            if jump >= self.jump_back_threshold_sec:
                now_monotonic = time.monotonic()
                if (
                    self._last_reset_monotonic is None
                    or now_monotonic - self._last_reset_monotonic
                    >= self.reset_cooldown_sec
                ):
                    self._last_reset_monotonic = now_monotonic
                    self._trigger_reset_sequence(jump)
            else:
                self.get_logger().debug(
                    f"감지된 시간 점프({jump:.3f}s)가 임계값보다 작아 무시되었습니다."
                )

        self._last_clock_sec = current_sec

    def _trigger_reset_sequence(self, jump: float) -> None:
        self.get_logger().warn(
            f"시뮬레이션 시간이 {jump:.3f}s 만큼 과거로 이동했습니다. 리셋 시퀀스를 시작합니다."
        )

        # 1. Pause
        self.get_logger().info("1/3: 노드들을 일시정지합니다.")
        pause_futures = self._call_services(self.pause_services)

        def on_pause_done(all_pause_futures: Future) -> None:
            # 2. Reset
            self.get_logger().info("2/3: 노드들의 상태를 리셋합니다.")
            reset_futures = self._call_services(self.reset_services)

            def on_reset_done(all_reset_futures: Future) -> None:
                # 3. Resume
                self.get_logger().info("3/3: 노드들을 재개합니다.")
                self._call_services(self.resume_services)
                self.get_logger().warn("리셋 시퀀스가 완료되었습니다.")

            # 모든 리셋 호출이 완료되면 on_reset_done 실행
            rclpy.task.when_all(reset_futures).add_done_callback(on_reset_done)

        # 모든 일시정지 호출이 완료되면 on_pause_done 실행
        rclpy.task.when_all(pause_futures).add_done_callback(on_pause_done)


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