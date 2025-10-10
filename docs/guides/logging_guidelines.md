# 실험 로그 구조 및 수집 절차

리팩토링 이후 모든 라운드트립 실험은 공통 디렉터리 규칙을 사용합니다. `client.profile.yaml`의 `directories` 항목과 `stream_collect_logs` CLI(`draco_roundtrip/tools/log_collection.py`)를 통해 폴더 생성과 메타데이터 기록을 자동화할 수 있습니다.【F:ros2_ws/src/draco_roundtrip/setup.py†L18-L29】

## 디렉터리 구조
기본적으로 `data/results/<run_id>/` 하위에 다음 폴더가 생성됩니다.
```
results/
  <run_id>/
    artifacts/      # PLY, DRC, CSV 등 부가 산출물
    metrics/        # 분석 결과(통계, 그래프)
    ros_logs/       # ROS 2 로그 스냅샷 (ros2 bag, rcl_logging 등)
    notes/          # 운영자가 남긴 자유 양식 메모
    manifest.json   # 실행 시각, 사용한 프로파일, 메타데이터를 담은 기록
```
`manifest.json`에는 다음 정보가 포함됩니다.
- `run_id`: 실행 식별자 (CLI에서 전달)
- `timestamp`: UTC 타임스탬프
- `layout_root`: 프로파일이 가리킨 데이터 루트 경로
- `profile`: 사용한 프로파일 파일 경로와 내용
- `metadata`: CLI `--metadata` 플래그로 전달한 키-값 쌍 (예: `bag`, `netem`, `slam`)
- `directories`: 생성된 서브 디렉터리의 절대 경로
- `handoff`: 스트리밍 세션 종료 시 `MSG_EOF` 핸드셰이크와 큐 드레인 상태를 요약한 로그 스니펫 (선택).

## CLI 사용법
```bash
ros2 run draco_roundtrip stream_collect_logs run_20240315 \
  --layout-profile client.profile.yaml \
  --data-root ./data \
  --metadata bag=sample.bag --metadata slam=rtabmap \
  --ros-log ~/.ros/log/latest \
  --attach data/ply_stream/sample_0001.ply \
  --notes "Baseline roundtrip with wifi_dense profile"
```
위 명령은 `data/results/run_20240315/`에 디렉터리를 준비하고 다음 작업을 수행합니다.
1. `draco_roundtrip.utils.config.ensure_directory`를 이용해 프로파일이 정의한 결과 디렉터리를 생성합니다.【F:ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/config.py†L1-L140】
2. `manifest.json`에 ROS 2 환경, 메타데이터, 첨부 파일 목록을 기록합니다.
3. `--attach` 인자를 통해 지정한 파일을 `artifacts/`에 복사합니다.
4. `--ros-log`로 전달한 디렉터리는 `ros_logs/`로 동기화합니다.
5. 스트림 종료 로그(`[CLIENT] Sent EOF marker to server`, `[CLIENT] EOF handshake complete`, `[SERVER][TELEM] pending=0` 등)를 함께 남기면, 세션이 정상 종료됐는지 사후 검증이 쉬워집니다.

## 수동 절차 체크리스트
CLI 사용이 어려운 환경(예: 제한된 컨테이너 권한)에서는 아래 절차로 동일한 구조를 수동 구성할 수 있습니다.
1. `client.profile.yaml`의 `directories` 값을 참고해 디렉터리를 생성합니다. (`../references/layout_profiles.md` 참고)
2. `manifest.json`을 수동으로 작성하고, `metadata`와 `profile` 경로를 기록합니다.
3. 결과 CSV/PLY 파일은 `artifacts/` 또는 `metrics/`에 정리하고, 로그는 `ros_logs/`에 보관합니다. 서버는 기본적으로 디코딩 산출물을 정리하므로, 필요하면 실행 시 `--keep-artifacts`를 지정하거나 디코딩 디렉터리를 즉시 백업하세요.【F:ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_server.py†L1-L120】

## 연관 문서
- 프로파일 필드와 기본 경로: `../references/config_reference.md`
- 전체 데이터 레이아웃 규칙: `../references/layout_profiles.md`
- 템플릿 기반 결과 보고: `../templates/results_template.md`
- 코드 구조 개요: `../references/codebase_overview.md`

### 관련 코드 살펴보기
- 로그 수집 CLI: `ros2_ws/src/draco_roundtrip/draco_roundtrip/tools/log_collection.py`
- 디렉터리 헬퍼: `ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/config.py`
- 결과 템플릿: `../templates/results_template.md`
