from __future__ import annotations

import threading
import time
from typing import Dict, List, Optional, Tuple

import rclpy
from rclpy.client import Client
from rclpy.node import Node
from rclpy.qos import (
    DurabilityPolicy,
    HistoryPolicy,
    QoSDurabilityPolicy,
    QoSProfile,
    QoSReliabilityPolicy,
)
from rosgraph_msgs.msg import Clock
from sensor_msgs.msg import PointCloud2
from std_srvs.srv import Empty

from lifecycle_msgs.msg import Transition
from lifecycle_msgs.srv import ChangeState


class TimeJumpResetNode(Node):
    """
    SLAM 관련 노드들의 라이프사이클을 관리하고, 시뮬레이션 시간이 점프했을 때 리셋을 수행한다.
    - 시작 시: 관리 대상 노드를 'inactive' 상태로 전환하여 대기시킨다.
    - 데이터 토픽 수신 시작 시: 노드를 'active' 상태로 전환한다.
    - 시간 점프 감지 시: 비활성화 -> 리셋 -> 재활성화 시퀀스를 수행한다.
    """

    def __init__(self) -> None:
        super().__init__("lifecycle_manager_node")

        # 파라미터 선언
        self.managed_nodes: List[str] = (
            self.declare_parameter("managed_nodes", ["icp_odometry", "rtabmap"])
            .get_parameter_value()
            .string_array_value
        )
        self.reset_services: List[str] = (
            self.declare_parameter(
                "reset_services", ["/icp_odometry/reset", "/rtabmap/reset"]
            )
            .get_parameter_value()
            .string_array_value
        )
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
        self.cloud_topic: str = (
            self.declare_parameter("cloud_topic", "/stream_pair/decoded")
            .get_parameter_value()
            .string_value
        )

        # 내부 상태 변수
        self._last_clock_sec: Optional[float] = None
        self._last_reset_monotonic: Optional[float] = None
        self._is_system_active = False

        self._sequence_lock = threading.Lock()
        self._state_lock = threading.Lock()

        # 서비스 클라이언트 생성
        self._change_state_clients: Dict[str, Tuple[str, Client]] = {}
        self._change_state_candidates: Dict[str, List[str]] = {}
        for node_name in self.managed_nodes:
            candidates = self._candidate_change_state_service_names(node_name)
            self._change_state_candidates[node_name] = candidates
            service_name = self._select_available_change_state_service(candidates)
            if service_name is None:
                self.get_logger().warn(
                    f"{node_name} 노드의 change_state 서비스가 아직 발견되지 않았습니다. 추후 재시도합니다."
                )
                continue
            self._change_state_clients[node_name] = (
                service_name,
                self.create_client(ChangeState, service_name),
            )

        self._reset_clients: Dict[str, Client] = {
            name: self.create_client(Empty, name) for name in self.reset_services
        }

        # 데이터 및 Clock 구독자
        # 데이터가 처음 들어올 때 활성화를 트리거하기 위한 구독
        data_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
            reliability=QoSReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.VOLATILE,
        )
        self._data_subscription = self.create_subscription(
            PointCloud2, self.cloud_topic, self._on_data_received, data_qos
        )

        clock_qos = QoSProfile(
            depth=10,
            reliability=QoSReliabilityPolicy.BEST_EFFORT,
            durability=QoSDurabilityPolicy.VOLATILE,
        )
        self._clock_subscription = self.create_subscription(
            Clock, "/clock", self._on_clock, clock_qos
        )

        # 초기 configure 시퀀스 예약
        self.get_logger().info(f"라이프사이클 매니저 시작. 관리 대상: {self.managed_nodes}")
        self.get_logger().info(f"데이터 수신 대기 중... 토픽: {self.cloud_topic}")
        self._initial_configuration_timer = self.create_timer(
            1.0, self._initial_configuration_sequence
        )

    def _initial_configuration_sequence(self) -> None:
        """노드 시작 시, 관리 대상 노드들을 'inactive' 상태로 만든다."""
        if self._initial_configuration_timer is None:
            return
        self._initial_configuration_timer.cancel()
        self._initial_configuration_timer = None

        threading.Thread(target=self._run_initial_configuration, daemon=True).start()

    def _run_initial_configuration(self) -> None:
        with self._sequence_lock:
            self.get_logger().info("초기 설정 시퀀스 시작: 모든 노드를 'inactive' 상태로 전환합니다.")
            success = self._call_transition_for_all(Transition.TRANSITION_CONFIGURE)
            if success:
                self.get_logger().info("초기 설정 완료. 모든 노드가 데이터 수신을 대기 중입니다.")
            else:
                self.get_logger().warn("일부 노드에서 configure 전환에 실패했습니다.")

    def _on_data_received(self, msg: PointCloud2) -> None:
        """데이터가 처음 수신되면 시스템을 활성화하고, 이 구독은 파괴한다."""
        with self._state_lock:
            if self._is_system_active:
                return

        self.get_logger().info(f"'{self.cloud_topic}' 토픽에서 첫 데이터 수신. SLAM 시스템을 활성화합니다.")
        
        # 활성화는 한 번만 수행
        if self._data_subscription:
            self.destroy_subscription(self._data_subscription)
            self._data_subscription = None

        threading.Thread(target=self._activate_system, daemon=True).start()

    def _activate_system(self) -> None:
        with self._sequence_lock:
            with self._state_lock:
                if self._is_system_active:
                    return
            self.get_logger().info("시스템 활성화: 모든 노드를 'active' 상태로 전환합니다.")
            success = self._call_transition_for_all(Transition.TRANSITION_ACTIVATE)
            with self._state_lock:
                self._is_system_active = success
            if success:
                self.get_logger().info("시스템 활성화 완료.")
            else:
                self.get_logger().error("시스템 활성화 실패.")

    def _deactivate_system(self) -> None:
        with self._sequence_lock:
            with self._state_lock:
                if not self._is_system_active:
                    return
            self.get_logger().info("시스템 비활성화: 모든 노드를 'inactive' 상태로 전환합니다.")
            success = self._call_transition_for_all(Transition.TRANSITION_DEACTIVATE)
            if success:
                with self._state_lock:
                    self._is_system_active = False
                self.get_logger().info("시스템 비활성화 완료.")
            else:
                self.get_logger().error("시스템 비활성화 실패.")

    def _trigger_reset_sequence(self) -> None:
        if not self._sequence_lock.acquire(blocking=False):
            self.get_logger().warn("다른 상태 전환이 진행 중이므로 리셋을 건너뜁니다.")
            return
        try:
            self.get_logger().info("1/3: 노드들을 비활성화합니다.")
            deactivate_success = self._call_transition_for_all(
                Transition.TRANSITION_DEACTIVATE
            )
            if deactivate_success:
                with self._state_lock:
                    self._is_system_active = False

            self.get_logger().info("2/3: 노드들의 상태를 리셋합니다.")
            self._call_reset_services()

            self.get_logger().info("3/3: 노드들을 다시 활성화합니다.")
            activate_success = self._call_transition_for_all(
                Transition.TRANSITION_ACTIVATE
            )
            with self._state_lock:
                self._is_system_active = activate_success

            if activate_success:
                self.get_logger().warn("리셋 시퀀스가 완료되었습니다.")
            else:
                self.get_logger().error("리셋 시퀀스 실패: 활성화 단계에서 오류가 발생했습니다.")
        finally:
            self._sequence_lock.release()

    def _call_reset_services(self) -> None:
        for service_name, client in self._reset_clients.items():
            if not self._wait_for_service(client, service_name):
                self.get_logger().error(f"{service_name} 리셋 서비스를 사용할 수 없습니다.")
                continue
            try:
                client.call(Empty.Request())
            except Exception as exc:  # pylint: disable=broad-except
                self.get_logger().error(f"{service_name} 리셋 호출 실패: {exc}")

    def _call_transition_for_all(self, transition_id: int) -> bool:
        overall_success = True
        for node_name in self.managed_nodes:
            client_entry = self._ensure_change_state_client(node_name)
            if client_entry is None:
                self.get_logger().error(
                    f"{node_name} 전환 실패(id={transition_id}): change_state 서비스를 사용할 수 없습니다."
                )
                overall_success = False
                continue

            service_name, client = client_entry
            if not self._wait_for_service(client, service_name):
                self.get_logger().error(f"{service_name} 서비스를 사용할 수 없습니다.")
                overall_success = False
                continue

            request = ChangeState.Request()
            request.transition.id = transition_id
            try:
                response = client.call(request)
            except Exception as exc:  # pylint: disable=broad-except
                self.get_logger().error(
                    f"{node_name} 전환 실패(id={transition_id}): {exc}"
                )
                overall_success = False
                continue

            if not response.success:
                self.get_logger().error(
                    f"{node_name} 전환 실패(id={transition_id}). 성공=False"
                )
                overall_success = False
        return overall_success

    @staticmethod
    def _wait_for_service(client: Client, _name: str, retries: int = 5) -> bool:
        for _ in range(retries):
            if client.wait_for_service(timeout_sec=1.0):
                return True
        return False

    def _candidate_change_state_service_names(self, node_name: str) -> List[str]:
        expected_type = "lifecycle_msgs/srv/ChangeState"
        namespace, base_name = self._split_namespace(node_name)

        names: List[str] = []
        try:
            service_entries = self.get_service_names_and_types_by_node(
                base_name, namespace
            )
        except Exception as exc:  # pylint: disable=broad-except
            self.get_logger().debug(
                f"{node_name} 서비스 목록을 아직 조회할 수 없습니다: {exc}"
            )
            service_entries = []

        for service_name, service_types in service_entries:
            if (
                service_name.endswith("/change_state")
                and expected_type in service_types
            ):
                names.append(service_name)

        normalized = node_name if node_name.startswith("/") else f"/{node_name}"
        fallback = [f"{normalized}/change_state"]
        for candidate in fallback:
            if candidate not in names:
                names.append(candidate)

        seen: Dict[str, None] = {}
        for name in names:
            if name not in seen:
                seen[name] = None
        return list(seen.keys())

    def _select_available_change_state_service(
        self, candidates: List[str]
    ) -> Optional[str]:
        expected_type = "lifecycle_msgs/srv/ChangeState"
        for candidate in candidates:
            if self._service_exists(candidate, expected_type):
                return candidate
        return None

    def _ensure_change_state_client(
        self, node_name: str
    ) -> Optional[Tuple[str, Client]]:
        candidates = self._change_state_candidates.get(node_name)
        refreshed = self._candidate_change_state_service_names(node_name)
        if refreshed:
            candidates = refreshed
            self._change_state_candidates[node_name] = refreshed
        elif candidates is None:
            candidates = []

        service_name = self._select_available_change_state_service(candidates or [])
        if service_name is None:
            existing = self._change_state_clients.get(node_name)
            if existing is not None:
                return existing
            return None

        existing = self._change_state_clients.get(node_name)
        if existing and existing[0] == service_name:
            return existing

        client = self.create_client(ChangeState, service_name)
        self._change_state_clients[node_name] = (service_name, client)
        self.get_logger().info(
            f"{node_name} change_state 서비스 경로를 {service_name} 로 설정했습니다."
        )
        return self._change_state_clients[node_name]

    def _service_exists(self, service_name: str, expected_type: str) -> bool:
        for name, service_types in self.get_service_names_and_types():
            if name == service_name and expected_type in service_types:
                return True
        return False

    @staticmethod
    def _split_namespace(node_name: str) -> Tuple[str, str]:
        if not node_name:
            return "/", ""
        full_name = node_name if node_name.startswith("/") else f"/{node_name}"
        namespace, _, base_name = full_name.rpartition("/")
        if namespace == "":
            namespace = "/"
        return namespace, base_name

    def _on_clock(self, msg: Clock) -> None:
        """Clock 메시지를 수신하면 시간 점프를 감지한다."""
        with self._state_lock:
            if not self._is_system_active:
                return  # 시스템이 활성화되기 전에는 시간 점프를 감지하지 않음

        current_sec = float(msg.clock.sec) + float(msg.clock.nanosec) * 1e-9

        if self._last_clock_sec is not None:
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
                        self.get_logger().warn(
                            f"시뮬레이션 시간이 {jump:.3f}s 만큼 과거로 이동했습니다. 리셋 시퀀스를 시작합니다."
                        )
                        threading.Thread(
                            target=self._trigger_reset_sequence, daemon=True
                        ).start()

        self._last_clock_sec = current_sec


def main() -> None:
    rclpy.init()
    node = TimeJumpResetNode()
    executor = rclpy.executors.MultiThreadedExecutor()
    executor.add_node(node)
    try:
        executor.spin()
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()