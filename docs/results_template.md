# Roundtrip Regression Log Template

엔드투엔드 회귀 검증(`ros2_ws/src/draco_roundtrip/tests/e2e_roundtrip.sh`)을 실행한 뒤 결과를 기록할 때 사용하는 템플릿입니다. 실제 검증에 사용한 인자, 환경, 메트릭을 빠짐없이 채워 reproducible 하게 관리하세요.

## 1. 환경 요약
- 실행 일시: <!-- 2024-05-23 14:32 KST -->
- 호스트/CI 러너: <!-- local-devbox-01 -->
- ROS 2 배포판: <!-- humble -->
- Draco encoder/decoder 경로: <!-- /opt/draco/bin/draco_encoder -->
- 추가 의존성: <!-- numpy==1.26.4, plyfile==0.9 -->

## 2. 실행 명령어
```bash
$ ros2_ws/src/draco_roundtrip/tests/e2e_roundtrip.sh -vv
```

필요 시 `pytest` 인자나 환경 변수를 함께 명시합니다.

## 3. 결과 요약
| Frame | Source pts | Decoded pts | Diff | Centroid norm | Chamfer (mean/max) | Notes |
|-------|------------|-------------|------|---------------|--------------------|-------|
| frame_00000 | <!-- 4 --> | <!-- 4 --> | <!-- 0 --> | <!-- 0.000 --> | <!-- 0.000 / 0.000 --> | <!-- stub encoder --> |

## 4. 로그 및 추가 메모
- <!-- [CLIENT] Frame 00000 metrics — Δpts=0 centroid_norm=0.000 ... -->
- <!-- 테스트는 stub encoder/decoder로 수행. 실제 바이너리 회귀 필요. -->

부가 로그는 `logs/` 하위 폴더에 보관하고, 필요 시 여기서 링크하거나 경로를 남깁니다. `stream_collect_logs` CLI를 사용했다면 `manifest.json`과 `artifacts/`, `ros_logs/` 경로를 함께 기록하세요.
