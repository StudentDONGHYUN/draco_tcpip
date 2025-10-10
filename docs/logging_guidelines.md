# 실험 로그 구조 및 수집 절차

리팩토링 이후 모든 라운드트립 실험은 공통 디렉터리 규칙을 사용합니다. `client.profile.yaml`의 `directories` 항목과 `stream_collect_logs` CLI를 통해 폴더 생성과 메타데이터 기록을 자동화할 수 있습니다.

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

## CLI 사용법

```
ros2 run draco_roundtrip stream_collect_logs run_20240315 \
  --layout-profile client.profile.yaml \
  --data-root ./data \
  --metadata bag=sample.bag --metadata slam=rtabmap \
  --ros-log ~/.ros/log/latest \
  --attach data/ply_stream/sample_0001.ply \
  --notes "Baseline roundtrip with wifi_dense profile"
```

위 명령은 `data/results/run_20240315/`에 디렉터리를 준비하고 다음 작업을 수행합니다.

1. `~/.ros/log/latest` 디렉터리를 `ros_logs/` 아래로 복사
2. 추가 첨부 파일을 `artifacts/`에 보관
3. 실행 메모를 `notes/README.txt`에 누적
4. 모든 정보를 `manifest.json`에 기록

## 수동 로그 수집 체크리스트

자동화 스크립트를 사용하지 않을 경우 다음을 권장합니다.

1. `resolve_data_layout({'results': 'results'})`로 결과 루트를 확인하고, 없으면 생성합니다.
2. ROS 2 로그(`~/.ros/log/latest`)와 실험 산출물(PLY, CSV 등)을 각각 `ros_logs/`, `artifacts/`에 복사합니다.
3. 실험 배경(사용한 bag, 프로파일, 네트워크 조건)을 `notes/README.txt`에 텍스트로 남깁니다.
4. 최소한 `run_id`, `bag`, `netem`, `slam` 정보를 포함한 `manifest.json`을 작성합니다.

`stream_collect_logs`는 위 과정을 자동화하므로, 수동 절차는 예외 상황(예: 컨테이너 권한 제약)에서만 사용하세요.
