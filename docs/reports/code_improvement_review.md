<!-- Path: docs/reports/code_improvement_review.md -->

# 코드베이스 개선 리뷰

## 개요
이 리포지터리는 Draco로 압축한 LiDAR 포인트클라우드를 TCP로 왕복 전송하며 평가하는 ROS 2 워크스페이스입니다. 스트리밍은 `draco_roundtrip` 패키지가, 배치 도구는 `draco_tools` 패키지가 담당하고, 공통 유틸리티는 `draco_roundtrip.utils` 아래에 모여 있습니다. 엔트리포인트와 데이터 흐름은 `../references/codebase_overview.md`에서 확인할 수 있습니다.

## 개선 기회
### 1. 스트림 종료 핸드셰이크 정교화
`nodes/stream_client.py`는 스풀 디렉터리를 지속적으로 폴링하며 서버가 소켓을 닫거나 예외가 발생할 때까지 종료하지 않습니다. 명시적인 스트림 종료 메시지를 전송하지 않아 rosbag 재생과 PLY 기록이 모두 끝났어도 연결이 살아 있습니다.【F:ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_client.py†L135-L202】 서버 역시 `recv_message`가 `None`을 반환(소켓 종료)할 때만 정리합니다.【F:ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_server.py†L57-L91】 프로토콜에 이미 정의된 `MSG_EOF`를 사용하거나 bag→PLY 서브프로세스 종료를 감지해 마지막 플러시/종료 메시지를 보내면 불필요한 대기와 재연결의 불확실성을 줄일 수 있습니다.

### 2. 파일시스템 이벤트 바쁜 대기
클라이언트는 100ms마다 파일시스템을 폴링하고, 처리된 경로 집합을 계속 누적합니다.【F:ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_client.py†L139-L187】 긴 캡처에서는 이 집합이 정리되지 않아 CPU와 메모리를 낭비합니다. `inotify_simple` 같은 디렉터리 감시자를 우선 사용하고, 폴백으로 폴링을 유지하더라도 디코딩 응답이 도착한 파일은 즉시 제거하는 방식이 더 확장성 있습니다.

### 3. 설정 경로 해석 방어 로직
`utils/config.py`는 프로젝트 루트의 `data/`, `configs/` 디렉터리를 찾을 때 `Path(__file__).parents[5]`와 `[4]`가 존재한다고 가정합니다.【F:ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/config.py†L134-L140】【F:ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/config.py†L242-L249】 소스 트리에서는 성립하지만, 얕은 구조로 설치된 site-packages나 압축 배포본에서는 `IndexError`가 발생할 수 있습니다. `len(here.parents)` 범위로 순회하도록 보호 로직을 추가하면 패키징된 환경에서도 안전하게 동작합니다.

### 4. 서버 소켓 이식성
서버는 리스닝 소켓을 생성할 때 `reuse_port=True`를 설정합니다.【F:ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_server.py†L57-L83】 `SO_REUSEPORT`를 지원하지 않는 일부 리눅스 커널이나 Windows 환경에서는 `OSError`가 발생합니다. `try/except`로 감싸 실패 시 해당 옵션 없이 재생성하는 폴백을 두면 정상 경로에 영향을 주지 않으면서 이식성이 좋아집니다.

### 5. 디코딩 작업 디렉터리 정리
`decode_drc`는 작업 디렉터리에 원본 `.drc`와 디코딩된 `.ply` 파일을 생성하지만 정리하지 않습니다.【F:ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_server.py†L23-L35】 장시간 세션에서는 디스크 사용량이 기하급수적으로 늘 수 있습니다. `TemporaryDirectory` 사용, 성공 시 중간 파일 삭제, 혹은 `--keep-artifacts` 토글을 제공해 기본적으로 정리하도록 하면 작업 공간을 깔끔하게 유지할 수 있습니다.

## 제안된 다음 단계
1. TCP 프로토콜에 `MSG_EOF` 전송/수신을 추가하고, 예상 프레임이 모두 처리되면 클라이언트 루프가 종료하도록 수정합니다.
2. 스풀 감시를 추상화해 중복 처리를 제거하고, 가능하다면 이벤트 기반 통지를 우선 적용해 장시간 캡처에서도 메모리를 안정적으로 유지합니다.
3. `resolve_data_layout`과 `_default_data_root`에 얕은 설치 경로 대비 방어 로직을 추가하고, site-packages 스타일 배포를 아우르는 회귀 테스트를 마련합니다.
4. `SO_REUSEPORT`가 없는 환경에서도 서버 소켓이 정상적으로 초기화되도록 폴백 경로를 구현합니다.
5. 디코딩 산출물에 대한 정리 정책을 마련하고 README 및 `../guides/HOWTO.md`에 옵션을 문서화해 필요한 경우에만 결과물을 보존할 수 있도록 합니다.

이 문서를 기반으로 한 체크리스트는 `../checklists/code_improvement_checklist.md`에서 추적하며, 진행 상황을 업데이트할 때에는 관련 코드 변경과 테스트 결과를 함께 남겨 주세요.
