# 리팩터 및 감사 로그
리팩터 결정, 검증 증거, 후속 과제를 한 문서에 기록합니다. 각 항목은 **변경 목적 → 구현 위치 → 검증 방법 → 후속 조치** 순으로 작성해 추적성을 확보합니다.

## 1. 요약 (현재 스냅샷)
- 단일 TCP 연결에서 FrameType(DATA/ACK/HEARTBEAT/EOF/ERROR) 다중화와 v2 헤더 사용이 표준이며, 별도 제어 포트는 경고만 출력한다.
- 프래그먼트 GC와 텍스트 프로토콜 크기 제한(4096 B/100 MiB)이 서버/클라이언트에 적용되어 장기 세션 안정성을 높였다.
- CLI·문서·자동화가 프로파일, QoS, 인코더 옵션, 프로토콜 버전 정보를 공유하는 방향으로 정렬되었다.

## 2. 감사 항목 및 증거
| 상태 | 식별자 | 위치 | 검증 방법 |
| --- | --- | --- | --- |
| ✅ 완료 | PYTEST-0001 | `tests/perf/test_latency_gate.py` 외 | `ModuleNotFoundError` 해결: `tests` 패키지 생성, `sys.path` 정규화, `pytest.ini` 검색 경로 제한 후 `pytest` 통과 로그 확보 |
| ✅ 완료 | PYTEST-0002 | `tests/unit/test_protocol_header.py` 외 | ROS 2 패키지 임포트 누락 수정: 루트 `conftest.py`에서 `ros2_ws/src` 추가 후 정상 임포트 확인 |

> 증거는 최신 `colcon test`/`pytest` 실행 로그 및 CI 아티팩트에서 확인합니다. 감사 결과를 갱신할 때는 링크를 남기고, 스코프에 맞는 테스트가 실패하면 즉시 롤백 계획을 기입합니다.

## 3. 리팩터 타임라인 (누적)
| 단계 | 하이라이트 | 후속 조치 |
| --- | --- | --- |
| 1 | 프로토콜/PLY/메트릭 유틸을 `ros2_ws/src/draco_roundtrip/tests` 기반으로 통합 | 신규 utils를 코드에도 반영하고 회귀 테스트를 추가 |
| 2 | `draco_tools.core.encoder`로 Draco 인코더 CLI 파싱·로그를 통합 | 실시간 경로가 동일 모듈을 호출하도록 정리 |
| 3 | 레이아웃/QoS 헬퍼 확장, 스트리밍·오프라인·런치 파일에 적용 | 구성 참조/사용자 가이드와 동기화 |
| 4 | GitHub Actions에서 `colcon build`, `colcon test`, 성능 게이트 실행 | 성능 기준 업데이트 시 게이트 값도 함께 수정 |
| 5 | SLAM 통합 런치, 네트워크 에뮬레이션, 로그 수집 자동화 제공 | bringup 기본값과 netem 프로파일 문서 일치 여부 확인 |
| 6 | 사용자 가이드, 구성 참조, 결과 템플릿 최종 갱신 | 새 플래그 추가 시 문서/CLI/테스트를 동시 수정 |
| 7 | 단일 소켓 멀티플렉싱, 프래그먼트 GC, 텍스트 제한을 코드/문서/테스트에 반영 | 텔레메트리 필드·스키마가 최신인지 주기적 확인 |

## 4. 운영 가이드 (감사 대비)
1. 환경: ROS 2 + `pip install -e .` 후 IDE 경로를 `tests`·`ros2_ws/src`와 맞춘다.
2. 워크플로: bringup 런치 또는 사용자 가이드 순서를 따르며, 레거시 모드가 아니라면 바이너리 프로토콜을 기본 사용.
3. 로그/아티팩트: `stream_collect_logs`로 매니페스트를 채우고 ROS 로그·품질 리포트를 함께 보관한다.
4. 네트워크: `stream_netem` 프로파일 적용 후 원복, 프로파일 변경 시 문서와 테스트를 동시에 갱신한다.
5. 텔레메트리: 저장 전 `Protocol_and_Schema_Reference`의 JSON 스키마로 검증한다.

## 5. 후속 작업 (감사 대응용)
- [ ] QUIC/UDP-FEC 프로토타입 및 손실 시나리오별 비교 텔레메트리 수집.
- [ ] 인프로세스 Draco 경로(Python↔C++ 호환)를 통합하고 외부 바이너리 의존성을 축소.
- [ ] 텍스트 제한/프래그먼트 GC 경고를 운영 대시보드에 노출하도록 텔레메트리 파이프라인 확장.

## 6. 자동 생성 감사 업데이트
<!-- AUTODOC:AUDIT:BEGIN -->
### 2025-10-13
- Ran `scripts/docsync/generate_docs.py --all` to refresh CLI, protocol, telemetry, and performance references.
- Updated Mermaid diagrams and regenerated telemetry tables.
<!-- AUTODOC:AUDIT:END -->
