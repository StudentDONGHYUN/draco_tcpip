# 계획-설계-체크리스트 추적 매트릭스

본 매트릭스는 네트워크 지연 감축 계획(`docs/plans/network_latency_reduction_plan.md`),
관련 설계 문서, 체크리스트, 테스트 사이의 추적 가능성을 제공한다. PR을 생성할 때는
각 요구사항이 어떤 테스트와 문서 변경으로 검증되는지 아래 표에 추가한다.

| 요구사항 ID | 계획/설계 근거 | 구현 아티팩트 | 검증 (테스트/체크리스트) | PR 링크 |
|-------------|----------------|---------------|--------------------------|---------|
| RQ-CP-001 | Control plane contract v1 (`docs/contracts/control_plane_contract.md`) | `ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/stream_protocol.py` | `ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_server.py` | PR-TBD |
| RQ-TEL-001 | Telemetry schema v1 (`docs/specs/telemetry_schema.md`) | `ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py` | `tests/unit/test_telemetry_minimal.py` | PR-TBD |
| RQ-CLI-001 | CLI flags matrix (`docs/config/cli_flags_matrix.md`) | `ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_client.py` (`--metrics-out/--telemetry-out`) | `python -m draco_roundtrip.nodes.stream_client --help` | PR-TBD |
| RQ-PERF-001 | Latency benchmark plan (`docs/tests/perf/latency_benchmark_plan.md`) | `scripts/ci/run_perf_gate.sh` | `tests/perf/test_latency_gate.py` | PR-TBD |

> PR 병합 시 `TBD` 필드를 채워 넣고, 체크리스트 항목(`docs/checklists/hybrid_architecture_checklist.md`)
> 상태를 업데이트해야 한다.
