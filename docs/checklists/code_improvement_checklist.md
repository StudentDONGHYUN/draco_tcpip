# 코드 개선 체크리스트

_Last updated: 2025-02-14_

## Changelog
- 2025-02-14: 테스트 경로 표준과 Pyright 연동 지침을 포함했습니다.

## Type-Checking, Packaging & IDE Integration
- 코드 개선 작업 시 Pyright strict 모드가 기본이며, 루트의 `conftest.py` 덕분에 `tests` 패키지가 올바르게 해석됩니다.
- 새 기능을 도입할 때는 `pytest.ini`의 `testpaths = tests` 구성을 준수하여 회귀 테스트가 ROS 2 패키지 테스트와 충돌하지 않도록 합니다.
- VS Code 작업 시 `.vscode/settings.json`에서 `python.analysis.extraPaths`에 `ros2_ws/src`를 추가하고, 가상환경을 활성화한 상태로 편집 가능한 설치를 유지합니다.

이 문서는 `../reports/code_improvement_review.md`에 정리된 권장 사항과 후속 작업을 구현할 때 참고하는 체크리스트입니다. 패키지 구조와 관련 코드는 `../references/codebase_overview.md`를 참고하세요.

## 권장 사항 이행 현황
- [x] **MSG_EOF 송수신 핸드셰이크 도입**
  - 관련 파일: `draco_roundtrip/nodes/stream_client.py`, `draco_roundtrip/nodes/stream_server.py`
  - 요약: 스트림 종료 시 `MSG_EOF`를 교환해 rosbag 재생이 끝나면 즉시 종료하도록 프로토콜을 강화했습니다.
  - 메모: 재연결 시나리오 테스트 추가 고려.
- [x] **파일 감시 로직의 이벤트 기반 전환**
  - 관련 파일: `draco_roundtrip/nodes/stream_client.py`
  - 요약: inotify 기반 `SpoolWatcher`를 도입하고, 폴백 폴링 시 처리 기록을 제한해 메모리 사용량을 제어합니다.
  - 메모: 비 Linux 환경에서 폴백 성능 검증 필요.
- [x] **config.py 경로 탐색 안전화**
  - 관련 파일: `draco_roundtrip/utils/config.py`
  - 요약: 얕은 설치 경로에서도 IndexError 없이 루트 탐색이 가능하도록 보호 로직을 추가했습니다.
  - 메모: site-packages 배포 형태 회귀 테스트 유지.
- [x] **socket `reuse_port` 예외 처리 추가**
  - 관련 파일: `draco_roundtrip/nodes/stream_server.py`
  - 요약: `SO_REUSEPORT` 미지원 커널에서 예외를 처리하고 기본 설정으로 재시도하도록 변경했습니다.
  - 메모: Windows/WSL 동작 검증 예정.
- [x] **`decode_drc()` 임시 파일 정리 개선**
  - 관련 파일: `draco_roundtrip/nodes/stream_server.py`
  - 요약: 디코딩 후 생성된 임시 파일을 정리해 작업 디렉터리 누적을 방지합니다.
  - 메모: 장기 세션에서 디스크 사용량 모니터링.

## 향후 점검 항목
- [x] 운영 문서(`../guides/HOWTO.md`, `../guides/logging_guidelines.md`)에 EOF 핸드셰이크와 파일 정리 정책을 추가로 예시화. (2024-05-23 업데이트)
- [ ] 이벤트 기반 감시가 비활성화된 플랫폼에서의 성능 측정 및 최적화.
- [ ] 신규 기능(EOF 핸드셰이크, 감시자 등)에 대한 통합 테스트/엔드투엔드 시나리오 추가.
- [ ] 서버 소켓 예외 처리 경로에 대한 로깅 개선 여부 평가.

체크리스트는 변경 사항 반영 시마다 업데이트하고, 완료된 항목은 `[x]`로 표시합니다. 수정이 끝나면 결과를 `../templates/results_template.md`에 기록해 추후 회귀 시 참고하세요.
