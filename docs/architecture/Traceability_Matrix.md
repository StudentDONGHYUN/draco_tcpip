# 추적성 매트릭스 (Spec-Driven)
요구사항 ↔ 구현 ↔ 검증 ↔ 문서 간 링크를 유지합니다. 변경 시에는 ID를 업데이트하고, PR/테스트 증거를 추가하십시오.

## 1. 사용 지침
- 새로운 요구사항을 추가할 때는 **Source 문서 → 코드 → 테스트 → 문서** 순으로 연결합니다.
- `PR` 열은 병합된 식별자를 기록하며, 누락 시 `TBD`로 표시하고 후속 업데이트를 강제합니다.
- 구현 경로가 변경되면 동일한 요구사항 ID로 행을 교체하고, 폐기된 항목은 별도 섹션으로 옮깁니다.

## 2. 요구사항 매핑
| 요구사항 ID | 원본 문서 | 구현 산출물 | 검증(테스트/체크리스트) | PR |
| --- | --- | --- | --- | --- |
| RQ-CP-001 | 제어 플레인 계약 v2 (`Protocol_and_Schema_Reference`) | `ros2_ws/src/draco_roundtrip/draco_roundtrip/protocol/header.py`, `.../net/protocol.py` | `tests/unit/test_protocol_header.py`, `tests/unit/test_single_channel_mux.py` | PR-TBD |
| RQ-FRAG-001 | 프래그먼트 GC/메모리 상한 (`Architectural_Design_and_Plan`) | `ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_server.py` | `tests/unit/test_fragment_buffer.py` | PR-TBD |
| RQ-TEL-001 | 텔레메트리 스키마 v1 (`Protocol_and_Schema_Reference`) | `ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py` | `tests/unit/test_telemetry_minimal.py` | PR-TBD |
| RQ-CLI-001 | CLI 플래그 매트릭스 (`Configuration_Reference`) | `ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_client.py` | `python -m draco_roundtrip.nodes.stream_client --help` | PR-TBD |
| RQ-SEC-001 | 텍스트 프로토콜 크기 제한 (`Protocol_and_Schema_Reference`) | `ros2_ws/src/draco_roundtrip/draco_roundtrip/net/protocol.py` | `tests/unit/test_text_protocol_limits.py` | PR-TBD |

> 변경 시 **PR-TBD**를 실제 병합 PR 번호로 교체하고, 신규 테스트 경로가 있으면 같은 행에 추가합니다.

## 2-1. 품질 특성 매핑
요구사항이 품질 특성에 어떻게 기여하는지와 검증 위치를 명시합니다. 새로운 요구사항을 추가하면 [`Quality_Attributes_Catalog`](../reference/Quality_Attributes_Catalog.md)와 함께 업데이트하십시오.

| 요구사항 ID | 품질 특성 | 검증/증거 | 게이트 |
| --- | --- | --- | --- |
| RQ-CP-001 | 신뢰성·운영 가능성 | 상태 전이 로그(FAILED/TERMINATED), 하트비트 타이머 테스트 | `docs/reports/results_template.md` 품질 게이트(신뢰성, 운영) |
| RQ-FRAG-001 | 성능·신뢰성 | 프래그먼트 TTL/GC 단위 테스트, 메모리 상한 로그 | `tests/unit/test_fragment_buffer.py`, 퍼포먼스 회귀 보고서 |
| RQ-TEL-001 | 관측 가능성·테스트 가능성 | 텔레메트리 스키마 검증, 필드 누락 시 실패 | `docs/quality/results_template.md` 텔레메트리/게이트 섹션 |
| RQ-CLI-001 | 유지보수성·이식성 | CLI 도움말/플래그 표 일치, OS/네트워크 프로파일별 기본값 검토 | `docs/reference/Configuration_Reference.md` 플래그 매트릭스 |
| RQ-SEC-001 | 보안성 | 텍스트 프로토콜 상한 초과 시 즉시 종료/로깅 | `tests/unit/test_text_protocol_limits.py`, 보안 리뷰 체크리스트 |

## 3. 업데이트 메모
- 개발 프로세스 체크리스트의 상태를 함께 조정하고, 삭제된 요구사항은 별도 아카이브 테이블에 이동합니다.

## 4. 자동 생성 요구사항 매핑
<!-- AUTODOC:TRACEABILITY:BEGIN -->
| Requirement | Source | Implementation | Verification | Documentation |
| - | - | - | - | - |
| RQ-CP-001 | Control-plane state machine defined in Protocol and Schema Reference | ros2_ws/src/draco_roundtrip/draco_roundtrip/net/protocol.py | tests/unit/test_single_channel_mux.py | docs/reference/Protocol_and_Schema_Reference.md |
| RQ-DATA-001 | Binary frame header layout | ros2_ws/src/draco_roundtrip/draco_roundtrip/protocol/header.py | tests/unit/test_protocol_header.py | docs/reference/Protocol_and_Schema_Reference.md |
| RQ-FRAG-001 | Fragment buffer TTL and eviction | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_server.py | tests/unit/test_fragment_buffer.py | docs/architecture/Architectural_Design_and_Plan.md |
| RQ-SEC-001 | Text protocol limits | ros2_ws/src/draco_roundtrip/draco_roundtrip/net/protocol.py | tests/unit/test_text_protocol_limits.py | docs/reference/Protocol_and_Schema_Reference.md |
| RQ-CLI-001 | Configuration Reference CLI matrix | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_client.py | tests/unit/test_cli_help.py | docs/reference/Configuration_Reference.md |
<!-- AUTODOC:TRACEABILITY:END -->
