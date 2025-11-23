# 리팩터 제안서 (System Architecture)
본 문서는 기존 코드 흐름과 문서 구조를 재정렬해 **Spec-Driven Development**에 맞춘 리팩터 목표와 실행 단계를 정의합니다. 모든 제안은 추적 가능한 작업 단위로 쪼개어 테스트·문서·코드의 동기화를 보장합니다.

## 1. 리팩터 목표와 성공 기준
- **단일 진실 공급원(SSOT)**: TCP 프로토콜, Draco 인코더/디코더 호출, PLY 로딩·메트릭 계산을 공용 유틸리티로 승격해 노드·CLI·레거시 스크립트가 동일한 코드를 사용한다.
- **동일 실행 경험**: ROS 2 노드와 순수 Python CLI가 같은 엔트리 포인트를 호출하고, `console_scripts`/`ros2 run`에서 옵션·로그 포맷이 일치한다.
- **추적 가능한 품질 게이트**: 성능/기능 테스트와 텔레메트리 검증을 CI에 묶어 회귀를 방지하고, 실패 시 재현 지침(데이터·프로파일·명령)을 문서화한다.
- **단순한 경로와 설정**: 레이아웃 프로파일과 QoS, 작업 디렉터리 해석 규칙을 `utils/config.py`로 단일화해 실험과 SLAM 런치가 같은 규칙을 따른다.

## 2. 현 구조 요약 (문제 진술)
- **프로토콜/네트워크 코드 중복**: `stream_client.py`, `stream_server.py`가 동일한 length-prefixed 전송·에러 문자열을 중복 구현함.
- **PLY 입출력·메트릭 반복**: `_load_xyz`/Chamfer 변종 로직이 노드·모니터·분석 스크립트에 복제되어 유지보수 비용 증가.
- **인코딩 경로 분산**: 실시간 인코더와 배치 인코더가 옵션/로그 처리 방식을 공유하지 않아 회귀 가능성 존재.
- **경로/QoS 해석 파편화**: `configs/*.yaml`, CLI 인자, 런치 파일이 서로 다른 규칙을 사용하여 결과 디렉터리와 QoS가 어긋날 수 있음.
- **레거시 스크립트 동시 유지**: `draco-ros2-roundtrip/` 하위 스크립트가 최신 패키지와 기능이 다르고 삭제 경로가 불분명함.

## 3. 목표 상태 설계 (제안 구조)
```
ros2_ws/src/
  draco_roundtrip/draco_roundtrip/
    nodes/{stream_client.py,stream_server.py}
    tools/{replay.py,monitor.py}
    utils/{protocol.py,executable.py,ply_io.py,metrics.py,config.py}
    cli/{stream_client.py,stream_server.py,monitor.py}
  draco_tools/draco_tools/
    core/{encoder.py,bag.py}
    analysis/quality.py
    cli/{encode_ply_to_draco.py,offline_pipeline.py}
draco-ros2-roundtrip/scripts/
  # 얇은 wrapper 또는 삭제 대상
```
- **공용 utils**는 length-prefixed 전송, 실행 파일 탐색, PLY 로딩/샘플링, Chamfer·bbox 계산, QoS/디렉터리 해석을 제공한다.
- **CLI와 노드**는 동일한 라이브러리 함수를 호출하고, 패키지 `setup.cfg`/`package.xml`의 `entry_points`로 배포한다.
- **레거시 스크립트**는 새 CLI 모듈을 import하는 얇은 wrapper로 축소하거나 `legacy/`로 이동해 삭제 일정을 명시한다.

## 4. 실행 계획 (단계별 작업)
1. **공용 프로토콜/IO 유틸 도입**: `utils/{protocol.py, executable.py, ply_io.py, metrics.py}`를 작성하고 클라이언트/서버/툴에서 참조하도록 교체한다.
2. **Draco 인코더 정규화**: `draco_tools/core/encoder.py`를 중심으로 옵션 파싱과 로그 포맷을 정의하고, 실시간·배치 경로 모두 이 모듈을 호출하도록 통합한다.
3. **구성 로딩 통합**: `utils/config.py`가 레이아웃 프로파일, QoS, data root를 해석하도록 만들고, 런치 파일과 CLI의 동일 동작을 문서·테스트한다.
4. **레거시 스크립트 축소**: `draco-ros2-roundtrip/scripts/*.py`는 새 CLI 호출로 단순화하거나 `legacy/` 폴더로 이동하며 삭제 버전과 마이그레이션 가이드를 남긴다.
5. **테스트 및 CI 갱신**: 프로토콜·메트릭 단위 테스트와 간단한 e2e 루프백 테스트를 추가하고, `colcon test`/`pytest`/성능 게이트를 CI에 연결한다.
6. **문서/가이드 재동기화**: 변경된 CLI 경로·플래그·디렉터리 규칙을 사용자 가이드와 구성 참조, SLAM 연계 문서에 반영하고, 추적성 매트릭스를 최신 PR로 연결한다.

## 5. 품질 게이트 및 검증
- **단위 테스트**: 프로토콜 파싱, PLY 로딩 샘플링, 메트릭 계산, QoS/레이아웃 해석 함수에 대한 테스트를 추가한다.
- **엔드투엔드 연계 검증**: 최소 1–2 프레임의 클라이언트↔서버 루프백 실행으로 EOF/ACK/하트비트·조각화·디렉터리 해석을 검증한다.
- **성능 회귀**: rosbag 재생 기반 p95 지연 목표를 `tests/perf` 스위트로 강제하고, 기준 초과 시 실패 로그에 재현 명령을 포함한다.

## 6. 마이그레이션 체크리스트
- [ ] 공용 utils 모듈이 모든 호출 지점에서 사용되는지 확인
- [ ] CLI/노드 도움말, 구성 참조, 사용자 가이드가 동일한 기본값을 가리키는지 검증
- [ ] 레거시 스크립트 삭제 또는 wrapper 전환 후 README 업데이트
- [ ] CI에서 `colcon build && colcon test` + `pytest` + 성능 게이트를 실행하도록 설정
- [ ] 새 구조에 맞춘 텔레메트리/아티팩트 경로가 추적성 매트릭스에 반영

## 7. 의사결정 기록
- 단일 TCP 제어/데이터 소켓을 유지하고, 별도 제어 포트는 경고만 남기는 방식으로 통일한다.
- 텍스트 프로토콜은 제한된 레거시 모드로만 지원하며, 기본은 v2 바이너리 헤더로 고정한다.
- QoS/프로파일 경로 해석 규칙을 문서·코드·런치·테스트에서 동일하게 유지하기 위해 `utils/config.py`에 집중한다.
