<!-- Path: docs/reports/refactor_report.md -->

# Draco TCP/IP Roundtrip 리팩토링 요약 보고서

본 문서는 `refac.md`에 정리된 목표를 완료한 뒤, 핵심 변경 사항과 운영 전환 지침을 요약한 보고서입니다. 세부 경로와 추가 문서는 `../references/codebase_overview.md`에서 빠르게 찾을 수 있습니다.

## 타임라인 하이라이트

| 단계 | 주요 내용 |
| --- | --- |
| 1단계 | 프로토콜/PLY/metrics 유틸리티 통합, 단위 테스트 추가 (`ros2_ws/src/draco_roundtrip/tests`). |
| 2단계 | Draco 인코더 CLI/스트리밍 경로 통합, 공용 로그 포맷 도입. |
| 3단계 | 레이아웃 프로파일과 QoS 헬퍼 확장, 스트리밍/오프라인 파이프라인에 적용. |
| 4단계 | 테스트 스위트, 엔드투엔드 회귀, GitHub Actions CI 정착. |
| 5단계 | SLAM/모니터링/도구가 공용 유틸리티 계층을 사용하도록 통합. |
| 6단계 | 라운드트립 회귀 및 결과 기록 템플릿 확보. |
| 7단계 | CI 파이프라인과 문서 전면 개편 (README, HOWTO, SLAM 가이드). |
| 8단계 | 통합 런치, 네트워크 에뮬레이션 헬퍼, 로그 수집 자동화, 설정 문서화 정비. |

## 핵심 산출물

- **문서화**
  - `../references/config_reference.md`: `configs/*.yaml`, `draco.json` 사용법과 예시를 집대성.
  - `../guides/logging_guidelines.md`: 실험 결과 저장 구조와 `stream_collect_logs` 활용법.
  - README/HOWTO/SLAM 가이드 갱신으로 레거시 지침 제거 및 bringup 런치 예시 제공.
- **운영 자동화**
  - `slam_stream_bridge/launch/bringup.launch.py`: 스트리밍 서버/클라이언트/SLAM을 단일 명령으로 기동.
  - `stream_netem` CLI: `configs/netem.profiles.yaml` 기반 네트워크 에뮬레이션 프로파일 적용.
  - `stream_collect_logs` CLI: 결과 디렉터리 생성, 로그/산출물 수집, 메타데이터 기록 자동화.
- **구성 리소스**
  - `client.profile.yaml`, `server.profile.yaml`, `draco.json`, `ros_topics.yaml`의 기본값 정비.
  - 네트워크/SLAM 관련 프로파일이 README 및 런치 인자와 연결되도록 구조화.

## 마이그레이션 체크리스트

1. `pip install` 또는 apt 패키지를 통해 `tc`, `net-tools`, `rtabmap`, `hdl_graph_slam` 등 런치 종속성을 준비합니다.
2. 새 `client.profile.yaml`을 검토하여 결과 디렉터리(`data/results/`) 권한을 확인합니다.
3. 스트리밍 이전에 다음 명령으로 네트워크 조건을 설정합니다.
   ```bash
   sudo ros2 run draco_roundtrip stream_netem wifi_dense --iface eno1 --clear
   ```
4. 통합 런치 실행:
   ```bash
   ros2 launch slam_stream_bridge bringup.launch.py \
     bag:=/data/bags/sample.bag topic:=/sensing/lidar/top/pointcloud \
     layout_profile:=client.profile.yaml slam:=rtabmap
   ```
5. 실험 종료 후 로그 정리:
   ```bash
   ros2 run draco_roundtrip stream_collect_logs run_20240315 \
     --metadata bag=sample.bag --metadata netem=wifi_dense --metadata slam=rtabmap
   ```

## 향후 과제

- `slam_stream_bridge` 런치에서 RTAB-Map/HDL Graph SLAM 외의 알고리즘 확장.
- `stream_collect_logs`와 CI 파이프라인을 연계해 자동 업로드(아티팩트 저장) 흐름 구축.
- Open3D/NumPy 의존성 유무에 따른 테스트 매트릭스 확장.

본 보고서는 `../checklists/refactor_checklist.md`의 모든 항목이 충족된 시점의 상태를 반영합니다.
