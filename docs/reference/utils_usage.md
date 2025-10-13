<!-- Path: docs/references/utils_usage.md -->

# Draco Roundtrip 유틸리티 사용 참조

`draco_roundtrip.utils`는 상위 레벨 노드, CLI 래퍼, 개발 도구가 의존하는 공용 인터페이스를 제공합니다. 이 문서는 각 헬퍼가 어디에서 사용되는지 기록해 향후 리팩토링 시 import 경로를 빠르게 검토할 수 있도록 돕습니다. 전체 패키지 구조는 `codebase_overview.md`(동일 폴더)를 참고하세요.

## 주요 사용처

| 유틸리티 모듈 | 핵심 심볼 | 주 사용처 | 비고 |
| --- | --- | --- | --- |
| `draco_roundtrip.utils.protocol` | `Message`, `ProtocolHandler`, `resolve_protocol`, `available_protocols` | `nodes/stream_client.py`, `nodes/stream_server.py` | 스트리밍 클라이언트와 서버가 동일한 프로토콜 업데이트를 유지하도록 TCP 프레이밍 레이어를 공유하며, `binary`/`text` 선택지를 제공합니다. |
| `draco_roundtrip.utils.stream_protocol` | `CONTROL_CHANNEL`, `DATA_CHANNEL`, `encode_frame_address`, `decode_frame_address` | `nodes/stream_client.py`, `nodes/stream_server.py` | 제어/데이터 채널을 분리해 메시지 순서를 유지합니다. |
| `draco_roundtrip.utils.ply_io` | `collect_matching_pairs`, `load_points`, `load_points_from_bytes` | `nodes/stream_client.py`, `tools/monitor.py`, `tools/replay.py` | 스트리밍 임포터와 오프라인 도구가 일관된 I/O 동작을 유지합니다. |
| `draco_roundtrip.utils.metrics` | `compute_basic_metrics`, `sample_indices` | `nodes/stream_client.py`, `tools/monitor.py`, `draco_tools/offline_pipeline.py` | 실시간 스트림과 오프라인 분석이 동일한 메트릭 계산을 사용합니다. |
| `draco_roundtrip.utils.config` | `resolve_data_layout`, `resolve_profile_path`, `resolve_qos_override`, `ensure_directory` | `nodes/stream_client.py`, `slam_stream_bridge/launch/bringup.launch.py`, `draco_tools/offline_pipeline.py` | 디렉터리와 QoS 구성 로직을 중앙에서 재사용합니다.【F:ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/config.py†L1-L140】 |
| `draco_roundtrip.utils.executable` | `resolve_executable` | `nodes/stream_server.py`, `draco_roundtrip/draco/encoder.py` | Draco 실행 파일 경로 해석 시 환경 변수와 공통 폴백을 우선 적용합니다. |

새로운 소비자가 추가될 때에는 위에서 정리한 심볼을 통해 가져오고, `draco_roundtrip.net`, `draco_roundtrip.io`, `draco_roundtrip.analysis` 등 하위 패키지를 직접 참조하지 않는 것이 좋습니다. 이렇게 하면 디렉터리 구조가 바뀌어도 모든 호출 코드를 일일이 수정할 필요가 없습니다.

## 연관 문서
- 네트워크 및 지연 설계: `../architecture/Architectural_Design_and_Plan.md`
- 설정/레이아웃 참조: `Configuration_Reference.md`
- 사용자 시나리오: `../guides/User_Guide.md`
- 로그 수집 및 템플릿: `../reports/results_template.md`

유틸리티 모듈을 확장하거나 이동할 때에는 위 표를 업데이트해 최신 사용처를 기록해 주세요.
