# Draco Roundtrip 유틸리티 사용 참조

`draco_roundtrip.utils`는 상위 레벨 노드, CLI 래퍼, 개발 도구가 의존하는 공용 인터페이스를 제공합니다. 이 문서는 각 헬퍼가 어디에서 사용되는지 기록해 향후 리팩토링 시 import 경로를 빠르게 검토할 수 있도록 돕습니다.

## 주요 사용처

| 유틸리티 모듈 | 핵심 심볼 | 주 사용처 | 비고 |
| --- | --- | --- | --- |
| `draco_roundtrip.utils.protocol` | `Message`, `ProtocolHandler`, `resolve_protocol`, `available_protocols` | `nodes/stream_client.py`, `nodes/stream_server.py` | 스트리밍 클라이언트와 서버가 동일한 프로토콜 업데이트를 유지하도록 TCP 프레이밍 레이어를 공유하며, `binary`/`text` 선택지를 제공해 지연을 줄입니다. |
| `draco_roundtrip.utils.ply_io` | `collect_matching_pairs`, `load_points`, `load_points_from_bytes` | `nodes/stream_client.py`, `tools/monitor.py`, `tools/replay.py` | 스트리밍 임포터는 레거시 이름(`load_xyz*`)을 유지하면서도 일관된 I/O 동작을 보장하기 위해 헬퍼를 재사용합니다. |
| `draco_roundtrip.utils.metrics` | `compute_basic_metrics`, `sample_indices` | `nodes/stream_client.py`, `tools/monitor.py` | 실시간 스트림과 오프라인 모니터링 모두 동일한 메트릭 계산을 사용하도록 중앙에서 SciPy 선택 의존성 가드를 제공합니다. |
| `draco_roundtrip.utils.executable` | `resolve_executable` | `nodes/stream_server.py` | 디코더 경로 해석 시 환경 변수와 공통 폴백을 우선 적용하며, 추가 CLI 래퍼도 이 헬퍼를 사용하는 것이 바람직합니다. |

새로운 소비자가 추가될 때에는 위에서 정리한 심 모듈을 통해 가져오고, `draco_roundtrip.net`, `draco_roundtrip.io`, `draco_roundtrip.analysis` 등 하위 패키지를 직접 참조하지 않는 것이 좋습니다. 이렇게 하면 향후 디렉터리 구조가 바뀌어도 모든 호출 코드를 일일이 수정할 필요가 없습니다.
