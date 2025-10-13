# 추적성 매트릭스
이 매트릭스는 Draco Roundtrip 스택 전반에서 지연 시간 단축 요구사항과 최신 프로토콜(v2) 구현, 검증 자산을 연결합니다.
_마지막 업데이트: 2025-03-16_

**목차**
- [요구사항 매핑](#요구사항-매핑)
- [업데이트 메모](#업데이트-메모)

## 요구사항 매핑
| 요구사항 ID | 원본 문서 | 구현 산출물 | 검증(테스트/체크리스트) | PR 링크 |
|-------------|-----------|-------------|-------------------------|---------|
| RQ-CP-001 | 제어 플레인 계약 v2 ([프로토콜 및 스키마 참조](../reference/Protocol_and_Schema_Reference.md)) | `ros2_ws/src/draco_roundtrip/draco_roundtrip/protocol/header.py`, `ros2_ws/src/draco_roundtrip/draco_roundtrip/net/protocol.py` | `tests/unit/test_protocol_header.py`, `tests/unit/test_single_channel_mux.py` | PR-TBD |
| RQ-FRAG-001 | 프래그먼트 GC/메모리 상한 ([아키텍처 설계](../architecture/Architectural_Design_and_Plan.md)) | `ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_server.py` | `tests/unit/test_fragment_buffer.py` | PR-TBD |
| RQ-TEL-001 | 텔레메트리 스키마 v1 ([프로토콜 및 스키마 참조](../reference/Protocol_and_Schema_Reference.md)) | `ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py` | `tests/unit/test_telemetry_minimal.py` | PR-TBD |
| RQ-CLI-001 | CLI 플래그 매트릭스 ([구성 참조](../reference/Configuration_Reference.md)) | `ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_client.py` (`--metrics-out`/`--telemetry-out`) | `python -m draco_roundtrip.nodes.stream_client --help` | PR-TBD |
| RQ-SEC-001 | 텍스트 프로토콜 크기 제한 ([프로토콜 참조](../reference/Protocol_and_Schema_Reference.md)) | `ros2_ws/src/draco_roundtrip/draco_roundtrip/net/protocol.py` | `tests/unit/test_text_protocol_limits.py` | PR-TBD |

## 업데이트 메모
각 변경 이후에는 `PR-TBD` 항목을 병합된 PR 식별자로 갱신하고, [개발 프로세스](../development/Development_Process.md)의 체크리스트 상태를 함께 업데이트하십시오.

## 자동 생성 요구사항 매핑
<!-- AUTODOC:TRACEABILITY:BEGIN -->
| Requirement | Source | Implementation | Verification | Documentation |
| - | - | - | - | - |
| RQ-CP-001 | Control-plane state machine defined in Protocol and Schema Reference | ros2_ws/src/draco_roundtrip/draco_roundtrip/net/protocol.py | tests/unit/test_single_channel_mux.py | docs/reference/Protocol_and_Schema_Reference.md |
| RQ-DATA-001 | Binary frame header layout | ros2_ws/src/draco_roundtrip/draco_roundtrip/protocol/header.py | tests/unit/test_protocol_header.py | docs/reference/Protocol_and_Schema_Reference.md |
| RQ-FRAG-001 | Fragment buffer TTL and eviction | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_server.py | tests/unit/test_fragment_buffer.py | docs/architecture/Architectural_Design_and_Plan.md |
| RQ-SEC-001 | Text protocol limits | ros2_ws/src/draco_roundtrip/draco_roundtrip/net/protocol.py | tests/unit/test_text_protocol_limits.py | docs/reference/Protocol_and_Schema_Reference.md |
| RQ-CLI-001 | Configuration Reference CLI matrix | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_client.py | tests/unit/test_cli_help.py | docs/reference/Configuration_Reference.md |
<!-- AUTODOC:TRACEABILITY:END -->
