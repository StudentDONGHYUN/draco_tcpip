# 실험 결과 템플릿
실행 메타데이터, 텔레메트리 아티팩트, 성공/실패 요약을 기록할 때 사용하세요.

## 자동 생성 목표
<!-- AUTODOC:PERF_TARGETS:BEGIN -->
| 메트릭 | 목표 | 출처 | 검증 |
| - | - | - | - |
| 클라이언트 텔레메트리 지연 p95 | docs/tests/perf/latency_benchmark_plan.md의 임계값(기본 250ms) 미만 | tests/perf/test_latency_gate.py | pytest -k test_latency_p95_gate |
| 제어 플레인 하트비트 생존성 | 6초 이내 하트비트 수신(HEARTBEAT_LIVENESS_NS) | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/stream_protocol.py | tests/unit/test_protocol_integration.py::test_heartbeat_timeout |
| 최대 인플라이트 프레임 수 | 윈도 제한이 `--max-inflight`를 준수하고 EOF 시 Drain | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_client.py | tests/unit/test_window_enforcement.py |
<!-- AUTODOC:PERF_TARGETS:END -->
