# 실험 결과 템플릿
실행 메타데이터, 텔레메트리 아티팩트, 성공/실패 요약을 기록할 때 사용하세요.

## 자동 생성 목표
<!-- AUTODOC:PERF_TARGETS:BEGIN -->
| Metric | Target | Source | Validation |
| - | - | - | - |
| Client telemetry latency p95 | < threshold from docs/tests/perf/latency_benchmark_plan.md (default 250ms) | tests/perf/test_latency_gate.py | pytest -k test_latency_p95_gate |
| Control-plane heartbeat liveness | Heartbeat observed within 6s (HEARTBEAT_LIVENESS_NS) | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/stream_protocol.py | tests/unit/test_protocol_integration.py::test_heartbeat_timeout |
| Max inflight frames | Window clamp obeys --max-inflight and drains on EOF | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_client.py | tests/unit/test_window_enforcement.py |
<!-- AUTODOC:PERF_TARGETS:END -->
