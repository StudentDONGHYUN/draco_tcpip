# 추적성 매트릭스
이 매트릭스는 Draco Roundtrip 스택 전반에서 지연 시간 단축 요구사항과 관련 설계 문서, 구현 산출물, 검증 자산을 연결합니다.
_마지막 업데이트: 2025-03-15_

**목차**
- [요구사항 매핑](#요구사항-매핑)
- [업데이트 메모](#업데이트-메모)

## 요구사항 매핑
| 요구사항 ID | 원본 문서 | 구현 산출물 | 검증(테스트/체크리스트) | PR 링크 |
|-------------|-----------|-------------|-------------------------|---------|
| RQ-CP-001 | 제어 플레인 계약 v1 ([프로토콜 및 스키마 참조](../reference/Protocol_and_Schema_Reference.md)) | `ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/stream_protocol.py` | `ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_server.py` | PR-TBD |
| RQ-TEL-001 | 텔레메트리 스키마 v1 ([프로토콜 및 스키마 참조](../reference/Protocol_and_Schema_Reference.md)) | `ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py` | `tests/unit/test_telemetry_minimal.py` | PR-TBD |
| RQ-CLI-001 | CLI 플래그 매트릭스 ([구성 참조](../reference/Configuration_Reference.md)) | `ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_client.py` (`--metrics-out`/`--telemetry-out`) | `python -m draco_roundtrip.nodes.stream_client --help` | PR-TBD |
| RQ-PERF-001 | 지연 시간 벤치마크 계획 ([성능 시험 계획](../development/Performance_Test_Plan.md)) | `scripts/ci/run_perf_gate.sh` | `tests/perf/test_latency_gate.py` | PR-TBD |

## 업데이트 메모
각 변경 이후에는 `PR-TBD` 항목을 병합된 PR 식별자로 갱신하고, [개발 프로세스](../development/Development_Process.md)의 체크리스트 상태를 함께 업데이트하십시오.

## 자동 생성 요구사항 매핑
<!-- AUTODOC:TRACEABILITY:BEGIN -->
| 요구사항 | 원본 | 구현 | 검증 | 문서 |
| - | - | - | - | - |
| RQ-CP-001 | 프로토콜 및 스키마 참조에 정의된 제어 플레인 상태 기계 | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/stream_protocol.py | tests/unit/test_protocol_integration.py | docs/reference/Protocol_and_Schema_Reference.md |
| RQ-DATA-001 | 바이너리 프레임 헤더 레이아웃 | ros2_ws/src/draco_roundtrip/draco_roundtrip/protocol/header.py | tests/unit/test_protocol_header.py | docs/reference/Protocol_and_Schema_Reference.md |
| RQ-CLI-001 | 구성 참조 CLI 매트릭스 | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_client.py | tests/unit/test_window_enforcement.py | docs/reference/Configuration_Reference.md |
| RQ-TEL-001 | 텔레메트리 스키마 JSON | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py | tests/unit/test_telemetry_minimal.py | docs/reference/Protocol_and_Schema_Reference.md |
<!-- AUTODOC:TRACEABILITY:END -->
