Moved from templates/.

# 라운드트립 회귀 로그 템플릿
엔드투엔드 회귀(`ros2_ws/src/draco_roundtrip/tests/e2e_roundtrip.sh`) 실행 후 재현성 메타데이터를 기록할 때 사용하세요. 인자, 환경 상세, 메트릭을 빠짐없이 남기면 향후 조사 시 동일한 실행을 재현할 수 있습니다. 디렉터리 구조는 [사용자 가이드](../guides/User_Guide.md)와 [구성 참조](../reference/Configuration_Reference.md)를 따릅니다.

## 1. 환경 요약
- 실행 시각: <!-- 2025-03-15 14:32 KST -->
- 호스트/CI 러너: <!-- local-devbox-01 -->
- ROS 2 배포판: <!-- humble -->
- Draco 인코더/디코더 경로: <!-- /opt/draco/bin/draco_encoder -->
- 추가 의존성: <!-- numpy==1.26.4, plyfile==0.9 -->

## 2. 실행 명령
```bash
$ ros2_ws/src/draco_roundtrip/tests/e2e_roundtrip.sh -vv
```
세션에서 사용한 추가 `pytest` 플래그, 환경 변수, 런치 인자가 있다면 함께 기록하세요.

## 3. 결과 요약
| 프레임 | 원본 포인트 수 | 디코드 포인트 수 | Δ 포인트 | 중심 거리(norm) | 챔퍼 거리(avg/max) | 비고 |
|--------|----------------|------------------|----------|------------------|---------------------|------|
| frame_00000 | <!-- 4 --> | <!-- 4 --> | <!-- 0 --> | <!-- 0.000 --> | <!-- 0.000 / 0.000 --> | <!-- stub encoder --> |

## 4. 로그 및 메모
- <!-- [CLIENT] Frame 00000 Δpts=0 centroid_norm=0.000 ... -->
- <!-- 스텁 인코더/디코더로 테스트를 실행했습니다. 운영 회귀는 추후 진행 예정. -->

실행 디렉터리의 `logs/`에 관련 로그를 보관하세요. `stream_collect_logs`를 사용했다면 매니페스트 경로와 주요 아티팩트/ROS 로그를 함께 첨부합니다. 후속 작업은 [개발 프로세스](../development/Development_Process.md)와 [리팩터 및 감사 로그](../reports/Refactor_and_Audit_Log.md)를 교차 참조하세요.
