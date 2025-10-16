from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Dict, Optional

import rclpy
from rclpy.client import Client
from rclpy.node import Node
from rclpy.qos import (
    DurabilityPolicy,
    HistoryPolicy,
    QoSProfile,
    ReliabilityPolicy,
)
from rclpy.subscription import Subscription
from rclpy.task import Future

from nav_msgs.msg import Odometry
from rtabmap_msgs.msg import MapData
from sensor_msgs.msg import PointCloud2
from std_srvs.srv import Empty


@dataclass
class _Watchdog:
    key: str
    label: str
    topic: str
    timeout_sec: float
    grace_sec: float
    on_timeout: Callable[[float, int], None]
    on_recovered: Optional[Callable[[float], None]] = None
    last_seen: Optional[float] = None
    last_feedback: Optional[float] = None
    fail_count: int = 0
    issue_started: Optional[float] = None
    subscription: Optional[Subscription] = None
    first_message_logged: bool = False


class RtabmapFeedbackLoopNode(Node):
    """RTAB-Map이 멈추는 다양한 상황을 감시하고 자동으로 복구를 시도한다."""

    def __init__(self) -> None:
        super().__init__("rtabmap_feedback_loop")

        self._startup_monotonic = time.monotonic()

        self.cloud_topic: str = self._declare_string(
            "cloud_topic", "/stream_pair/decoded"
        )
        self.odometry_topic: str = self._declare_string("odometry_topic", "/odom")
        self.map_data_topic: str = self._declare_string(
            "map_data_topic", "/rtabmap/map_data"
        )

        self.cloud_timeout_sec: float = self._declare_float("cloud_timeout_sec", 5.0)
        self.cloud_startup_grace_sec: float = self._declare_float(
            "cloud_startup_grace_sec", 8.0
        )
        self.odom_timeout_sec: float = self._declare_float("odometry_timeout_sec", 3.0)
        self.odom_startup_grace_sec: float = self._declare_float(
            "odometry_startup_grace_sec", 8.0
        )
        self.map_timeout_sec: float = self._declare_float("map_timeout_sec", 10.0)
        self.map_startup_grace_sec: float = self._declare_float(
            "map_startup_grace_sec", 12.0
        )
        self.feedback_cooldown_sec: float = self._declare_float(
            "feedback_cooldown_sec", 5.0
        )

        self.max_icp_reset_attempts: int = int(
            self.declare_parameter("max_icp_reset_attempts", 2)
            .get_parameter_value()
            .integer_value
        )
        self.max_map_failures_before_reset: int = int(
            self.declare_parameter("max_map_failures_before_reset", 3)
            .get_parameter_value()
            .integer_value
        )

        self.cloud_restart_service: str = self._declare_string(
            "cloud_restart_service", ""
        )
        self.icp_reset_service: str = self._declare_string(
            "icp_reset_service", "/icp_odometry/reset"
        )
        self.rtabmap_reset_service: str = self._declare_string(
            "rtabmap_reset_service", "/rtabmap/reset"
        )
        self.rtabmap_cleanup_service: str = self._declare_string(
            "rtabmap_cleanup_service", "/rtabmap/cleanup"
        )

        self._service_clients: Dict[str, Client] = {}
        self._missing_service_logs: Dict[str, bool] = {}
        self._pending_calls: Dict[str, Future] = {}

        self._watchdogs: Dict[str, _Watchdog] = {}

        self._register_watchdogs()

        check_period_sec = self._declare_float("check_period_sec", 1.0)
        self.create_timer(check_period_sec, self._periodic_check)

        self.get_logger().info(
            "RTAB-Map 피드백 루프 노드를 시작했습니다. 토픽과 서비스 상태를 모니터링합니다."
        )

    def _declare_string(self, name: str, default: str) -> str:
        return self.declare_parameter(name, default).get_parameter_value().string_value

    def _declare_float(self, name: str, default: float) -> float:
        return self.declare_parameter(name, default).get_parameter_value().double_value

    def _register_watchdogs(self) -> None:
        sensor_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=10,
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
        )
        default_qos = QoSProfile(depth=10)

        self._add_watchdog(
            key="cloud",
            label="포인트클라우드 입력",
            topic=self.cloud_topic,
            msg_type=PointCloud2,
            qos=sensor_qos,
            timeout_sec=self.cloud_timeout_sec,
            grace_sec=self.cloud_startup_grace_sec,
            on_timeout=self._handle_cloud_timeout,
        )

        self._add_watchdog(
            key="odom",
            label="ICP Odometry",
            topic=self.odometry_topic,
            msg_type=Odometry,
            qos=default_qos,
            timeout_sec=self.odom_timeout_sec,
            grace_sec=self.odom_startup_grace_sec,
            on_timeout=self._handle_odometry_timeout,
            on_recovered=self._handle_odometry_recovered,
        )

        self._add_watchdog(
            key="map",
            label="RTAB-Map 누적 맵",
            topic=self.map_data_topic,
            msg_type=MapData,
            qos=default_qos,
            timeout_sec=self.map_timeout_sec,
            grace_sec=self.map_startup_grace_sec,
            on_timeout=self._handle_map_timeout,
            on_recovered=self._handle_map_recovered,
        )

    def _add_watchdog(
        self,
        *,
        key: str,
        label: str,
        topic: str,
        msg_type,
        qos: QoSProfile,
        timeout_sec: float,
        grace_sec: float,
        on_timeout: Callable[[float, int], None],
        on_recovered: Optional[Callable[[float], None]] = None,
    ) -> None:
        subscription = self.create_subscription(
            msg_type,
            topic,
            lambda msg, watch_key=key: self._on_watchdog_message(watch_key),
            qos,
        )
        self._watchdogs[key] = _Watchdog(
            key=key,
            label=label,
            topic=topic,
            timeout_sec=timeout_sec,
            grace_sec=grace_sec,
            on_timeout=on_timeout,
            on_recovered=on_recovered,
            subscription=subscription,
        )

    def _on_watchdog_message(self, key: str) -> None:
        watchdog = self._watchdogs[key]
        now = time.monotonic()
        previous_last_seen = watchdog.last_seen
        watchdog.last_seen = now

        if not watchdog.first_message_logged:
            self.get_logger().info(
                f"{watchdog.label} 토픽({watchdog.topic}) 수신을 시작했습니다."
            )
            watchdog.first_message_logged = True

        if watchdog.fail_count > 0:
            downtime_start = watchdog.issue_started or watchdog.last_feedback or now
            downtime = now - downtime_start
            self.get_logger().info(
                f"{watchdog.label} 토픽({watchdog.topic}) 수신이 {downtime:.1f}s 만에 복구되었습니다."
            )
            if watchdog.on_recovered is not None:
                watchdog.on_recovered(downtime)
            watchdog.fail_count = 0
            watchdog.issue_started = None
            watchdog.last_feedback = None

        if previous_last_seen is None:
            watchdog.issue_started = None

    def _periodic_check(self) -> None:
        now = time.monotonic()
        for watchdog in self._watchdogs.values():
            if watchdog.last_seen is None:
                since_startup = now - self._startup_monotonic
                if since_startup < watchdog.grace_sec:
                    continue
                elapsed = since_startup
            else:
                elapsed = now - watchdog.last_seen
                if elapsed < watchdog.timeout_sec:
                    continue

            if (
                watchdog.last_feedback is not None
                and now - watchdog.last_feedback < self.feedback_cooldown_sec
            ):
                continue

            if watchdog.fail_count == 0:
                watchdog.issue_started = now

            watchdog.fail_count += 1
            watchdog.last_feedback = now
            watchdog.on_timeout(elapsed, watchdog.fail_count)

    def _handle_cloud_timeout(self, elapsed: float, fail_count: int) -> None:
        self.get_logger().error(
            (
                f"포인트클라우드 입력 토픽({self.cloud_topic})이 "
                f"{elapsed:.1f}s 동안 수신되지 않았습니다."
            )
        )

        if self.cloud_restart_service:
            self._call_empty_service(
                service_name=self.cloud_restart_service,
                description="포인트클라우드 공급 재시작",
                key="cloud_restart",
            )
        else:
            self.get_logger().info(
                "스트리밍 노드 상태를 확인해 주세요. cloud_restart_service 파라미터가 비어 있어 자동 복구를 수행하지 않습니다."
            )

    def _handle_odometry_timeout(self, elapsed: float, fail_count: int) -> None:
        self.get_logger().warn(
            (
                f"ICP Odometry 토픽({self.odometry_topic})이 {elapsed:.1f}s 동안 갱신되지 않았습니다. "
                "추정이 멈춘 것으로 판단합니다."
            )
        )

        if fail_count <= self.max_icp_reset_attempts:
            self._call_empty_service(
                service_name=self.icp_reset_service,
                description="ICP Odometry 리셋",
                key="icp_reset",
            )
        else:
            self.get_logger().error(
                "ICP Odometry가 연속으로 실패해 RTAB-Map 전체 리셋을 시도합니다."
            )
            self._call_empty_service(
                service_name=self.rtabmap_reset_service,
                description="RTAB-Map 리셋",
                key="rtabmap_reset",
            )

    def _handle_odometry_recovered(self, downtime: float) -> None:
        self.get_logger().info(
            f"ICP Odometry가 {downtime:.1f}s 정지 후 정상화되었습니다."
        )

    def _handle_map_timeout(self, elapsed: float, fail_count: int) -> None:
        self.get_logger().warn(
            (
                f"RTAB-Map 누적 맵 토픽({self.map_data_topic})이 {elapsed:.1f}s 동안 업데이트되지 않았습니다. "
                "그래프 최적화가 멈춘 것 같습니다."
            )
        )

        if fail_count == 1 and self.rtabmap_cleanup_service:
            self._call_empty_service(
                service_name=self.rtabmap_cleanup_service,
                description="RTAB-Map 캐시 정리",
                key="rtabmap_cleanup",
            )

        if fail_count >= self.max_map_failures_before_reset:
            self.get_logger().error("맵 정체가 지속되어 RTAB-Map 리셋을 요청합니다.")
            self._call_empty_service(
                service_name=self.rtabmap_reset_service,
                description="RTAB-Map 리셋",
                key="rtabmap_reset",
            )

    def _handle_map_recovered(self, downtime: float) -> None:
        self.get_logger().info(
            f"RTAB-Map 누적 맵이 {downtime:.1f}s 중단 후 다시 업데이트되고 있습니다."
        )

    def _call_empty_service(
        self, *, service_name: str, description: str, key: str
    ) -> None:
        if not service_name:
            self.get_logger().debug(
                f"{description} 서비스를 건너뜁니다(파라미터 비활성화)."
            )
            return

        client = self._service_clients.get(key)
        if client is None:
            client = self.create_client(Empty, service_name)
            self._service_clients[key] = client

        if key in self._pending_calls:
            self.get_logger().debug(f"{description} 서비스 호출이 이미 진행 중입니다.")
            return

        if not client.wait_for_service(timeout_sec=0.0):
            if not self._missing_service_logs.get(key, False):
                self.get_logger().warning(
                    f"{description} 서비스({service_name})를 아직 사용할 수 없습니다."
                )
                self._missing_service_logs[key] = True
            return

        if self._missing_service_logs.get(key, False):
            self.get_logger().info(
                f"{description} 서비스({service_name})가 사용 가능해졌습니다."
            )
            self._missing_service_logs[key] = False

        request = Empty.Request()
        future = client.call_async(request)
        self._pending_calls[key] = future
        future.add_done_callback(
            lambda fut, call_key=key, desc=description: self._on_service_call_done(
                call_key, desc, fut
            )
        )

    def _on_service_call_done(self, key: str, description: str, future: Future) -> None:
        try:
            future.result()
        except Exception as exc:  # noqa: BLE001 - 구체 오류 전달 목적
            self.get_logger().error(f"{description} 서비스 호출에 실패했습니다: {exc}")
        else:
            self.get_logger().info(f"{description} 서비스를 성공적으로 호출했습니다.")
        finally:
            self._pending_calls.pop(key, None)


def main() -> None:
    rclpy.init()
    node = RtabmapFeedbackLoopNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
