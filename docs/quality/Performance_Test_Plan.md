# 성능 시험 계획
이 계획은 자동화 테스트와 수동 검증으로 강제되는 지연, 처리량, 안정성 목표를 기록합니다. v2 프로토콜 도입 이후에는 단일 TCP 멀티플렉싱, 프래그먼트 GC, 텍스트 프로토콜 제한이 회귀 대상에 포함됩니다.

## 자동 생성 목표
<!-- AUTODOC:PERF_TARGETS:BEGIN -->
| Metric | Target | Source | Validation |
| - | - | - | - |
| Client telemetry latency p95 | < threshold from docs/tests/perf/latency_benchmark_plan.md (default 250ms) | tests/perf/test_latency_gate.py | pytest -k test_latency_p95_gate |
| Control-plane heartbeat liveness | Heartbeat observed within 6s (HEARTBEAT_LIVENESS_NS) | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/stream_protocol.py | tests/unit/test_protocol_integration.py::test_heartbeat_timeout |
| Max inflight frames | Window clamp obeys --max-inflight and drains on EOF | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_client.py | tests/unit/test_window_enforcement.py |
<!-- AUTODOC:PERF_TARGETS:END -->
