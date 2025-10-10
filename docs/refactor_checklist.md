# 리팩토링 완료 체크리스트

`refac.md`에 정리된 리팩토링 목표를 달성하기 위해 필요한 후속 작업을 체크리스트로 정리했습니다. 각 항목은 완료 조건과 산출물을 명시해 추적이 용이하도록 구성했습니다.

## 1. 공용 유틸리티 정합성 검증
- [x] `draco_roundtrip/utils/{protocol, executable, ply_io, metrics}.py`가 스트리밍 노드(`nodes/`), CLI(`cli/`), 툴(`tools/`) 전반에서 일관되게 사용되는지 코드 감사 및 문서화한다. → 모든 호출부에 대한 참조 표 업데이트. (문서: `docs/utils_usage.md`)
- [x] `draco_tools/core/encoder.py`를 단일 진입점으로 사용하도록 `draco_roundtrip.nodes.stream_client`와 `draco_tools.cli.encode_ply_to_draco`가 동일 함수 시그니처를 호출하도록 리팩토링한다. → 중복 옵션 파싱 제거, 통합된 로그 포맷 문서화. (PR: encoder CLI helper + shared log formatter, 테스트: `tests/test_core_encoder_cli.py`)
- [x] `draco_roundtrip/utils/config.py`가 QoS override, 출력 디렉터리, 프로필 파일을 단일 소스로 관리하도록 확장한다. → `offline_pipeline`, `stream_client`, 쉘 스크립트에서 해당 헬퍼를 사용하도록 수정하고 회귀 테스트. (PR: 레이아웃 프로필 헬퍼, 테스트: `tests/test_utils_config.py`)

## 2. 테스트 및 품질 보증 체계
- [x] `ros2_ws/src/draco_roundtrip/tests/` 디렉터리를 생성하고 TCP 프로토콜, PLY 로딩, metric 계산에 대한 단위 테스트를 추가한다. → `colcon test` 통과 여부를 CI에 등록. (테스트 파일: `test_utils_protocol.py`, `test_utils_ply_io.py`, `test_utils_metrics.py`, `pytest.ini`)
- [x] 최소 1회 왕복을 수행하는 엔드투엔드 스크립트(`tests/e2e_roundtrip.sh` 또는 pytest 기반)를 추가하고, 로컬/CI에서 실행 가능한 의존성 조건을 정리한다. → 실행 로그를 `docs/results_template.md`와 연계. (스크립트: `ros2_ws/src/draco_roundtrip/tests/e2e_roundtrip.sh`, 테스트: `tests/test_e2e_roundtrip.py`)
- [x] GitHub Actions 등 자동화 파이프라인에 `colcon build` + `colcon test` + 품질 스크립트를 추가해 리팩토링 후 회귀 검증을 자동화한다. → `.github/workflows/ros-ci.yaml`에서 ROS Humble 환경을 프로비저닝하고 `ros2_ws/src/draco_roundtrip/tests/e2e_roundtrip.sh`를 포함한 회귀 루틴을 실행하도록 구성.

## 3. 레거시 자산 정리
- [x] 루트 수준의 `draco-ros2-roundtrip/` Python 스크립트가 남아 있다면 `draco_roundtrip`/`draco_tools` 모듈을 thin wrapper로 호출하도록 단순화하거나, 사용 중단 안내와 함께 제거한다. → README에 레거시 스크립트 제거 공지와 대체 명령을 문서화하고, 루트 트리에서 중복 실행 파일이 남지 않았음을 확인.
- [ ] `migrate_refactor.sh`와 연계된 워크플로를 최신 디렉터리 구조에 맞춰 검증하고, 필요 시 대체 스크립트를 제안한다.
- [ ] 남아 있는 `legacy/` 디렉터리(또는 유사 명칭)에 deprecation 정책을 명시하고 삭제 시점을 결정한다.

## 4. 문서 및 설정 일원화
- [x] `docs/HOWTO.md`, `docs/3d_slam_setup.md`, `README.md` 간 중복 설명을 교차 링크 기반으로 정리하고 최신 경로/옵션으로 업데이트한다. → HOWTO 문서를 재작성하고 SLAM 가이드를 `slam_stream_bridge` 런치/CLI 명령으로 갱신했으며, README에 레거시 대체 경로를 명시.
- [ ] `configs/*.yaml`과 `configs/draco.json`에 대한 설명 및 사용 예시를 문서화하고, `utils/config.py`에서 불러오는 기본값과 맞춘다.
- [ ] 리팩토링 완료 후 배포 노트(CHANGELOG 또는 `docs/refactor_report.md`)를 작성해 주요 변경점과 마이그레이션 지침을 남긴다.

## 5. SLAM 연동 및 운영 자동화
- [ ] `slam_stream_bridge`에 통합 런치(`bringup.launch.py`)를 추가해 server → client → SLAM → RViz 플로우를 한 번에 기동하도록 한다. → QoS/Remap 인자화 및 문서 반영.
- [ ] 네트워크 에뮬레이션(`configs/netem.profiles.yaml`)과 프로파일 기반 스트리밍(`configs/*.profile.yaml`)을 CLI/런치 인자로 쉽게 적용할 수 있도록 헬퍼 스크립트를 제공한다.
- [ ] 실험 로그(`data/results/`, `logs/ros/`)의 디렉터리 구조와 네이밍 규칙을 정의하고 자동 회수 스크립트를 마련한다.

각 항목을 완료할 때마다 체크박스를 갱신하고 관련 PR/커밋 링크를 기록해 진행 상황을 추적하세요.
