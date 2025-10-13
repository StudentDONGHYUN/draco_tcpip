# 리팩터 및 감사 로그
감사 결과와 리팩터 배포 일정을 결합해 완료된 작업, 검증 증거, 후속 과제를 기록합니다.
_마지막 업데이트: 2025-03-15_

**목차**
- [요약](#요약)
- [감사 항목](#감사-항목)
- [리팩터 타임라인](#리팩터-타임라인)
- [운영 가이드](#운영-가이드)
- [후속 작업](#후속-작업)

## 요약
- 제어 플레인 핸드셰이크(`MSG_EOF`, `MSG_ACK`, `MSG_HEARTBEAT`)가 클라이언트와 서버 전반에서 강제되며 종료 로그가 구조화되어 출력됩니다.
- 파일 시스템 워처, 구성 헬퍼, 소켓 옵션을 강화해 다양한 실행 환경을 지원합니다.
- 문서·CLI·자동화 아티팩트가 프로파일, QoS, 인코더 옵션에 대한 공용 참조를 사용하도록 정리되었습니다.

## 감사 항목
| 상태 | 식별자 | 위치 | 상세 | 
|------|--------|------|------|
| ✅ 수정 완료 | PYTEST-0001 | `tests/perf/test_latency_gate.py` 외 | ROS 2 워크스페이스가 저장소 `tests`를 가리는 바람에 발생한 `ModuleNotFoundError: No module named 'tests.perf'`. `sys.path` 정규화, 로컬 `tests` 패키지 생성, `pytest.ini` 검색 제한으로 해결. |
| ✅ 수정 완료 | PYTEST-0002 | `tests/unit/test_protocol_header.py` 외 | PYTEST-0001 수정 후 `sys.path`에서 ROS 2 패키지가 빠지는 문제. 저장소 루트 `conftest.py`에서 `ros2_ws/src`를 추가해 노드와 유틸리티 임포트가 정상화됨. |

증거: 조정된 부트스트랩으로 `pytest`가 통과하며, CI 로그 또는 [개발 프로세스](../development/Development_Process.md)에 기록된 로컬 실행 결과를 참고할 수 있습니다.

## 리팩터 타임라인
| 단계 | 하이라이트 |
|------|-------------|
| 1 | `ros2_ws/src/draco_roundtrip/tests` 아래에서 프로토콜/PLY/메트릭 헬퍼를 통합하고 단위 테스트를 추가했습니다. |
| 2 | `draco_tools.core.encoder`를 통해 Draco 인코더 CLI 파싱과 로깅을 통합했습니다. |
| 3 | 레이아웃/QoS 헬퍼를 확장하고 스트리밍, 오프라인 파이프라인, 런치 파일에 적용했습니다. |
| 4 | GitHub Actions에서 `colcon build`, `colcon test`, 성능 게이트를 실행하는 CI 흐름을 구축했습니다. |
| 5 | SLAM 통합 런치, 네트워크 에뮬레이션 헬퍼, 로그 수집 자동화를 제공했습니다. |
| 6 | 사용자 가이드, 구성 참조, 결과 템플릿 등 문서를 최종 갱신했습니다. |

## 운영 가이드
1. **환경 준비**: ROS 2 의존성을 설치하고 `pip install -e .`를 실행한 뒤, IDE 검색 경로를 런타임 부트스트랩 순서와 맞추세요.
2. **스트리밍 워크플로**: bringup 런치를 우선 사용하거나 [사용자 가이드](../guides/User_Guide.md)의 순서를 따라 수동 실행합니다. 레거시 호환 테스트가 아니라면 바이너리 프로토콜을 활성화하세요.
3. **로그 및 아티팩트 관리**: `stream_collect_logs`를 사용해 매니페스트를 채우고 ROS 로그를 보관합니다. 실행 문서는 [결과 템플릿](../reports/results_template.md)을 따르세요.
4. **네트워크 튜닝**: 재현 가능한 조건을 위해 `stream_netem` 프로파일을 적용하고 테스트 후 기본 상태로 복원합니다.
5. **텔레메트리 준수**: 결과를 게시하기 전에 [프로토콜 및 스키마 참조](../reference/Protocol_and_Schema_Reference.md)에 정의된 JSON 스키마를 검증하세요.

## 후속 작업
- [ ] QUIC/UDP-FEC 전송을 프로토타입하고 비교 텔레메트리를 수집합니다.
- [ ] 인프로세스 Draco 인코드/디코드를 통합해 외부 바이너리 의존성을 제거합니다.
- [ ] 텔레메트리 아티팩트를 [개발 프로세스](../development/Development_Process.md)의 체크리스트 업데이트와 연결하는 보고서 생성을 자동화합니다.

## 자동 생성 감사 업데이트
<!-- AUTODOC:AUDIT:BEGIN -->
### 2025-10-13
- `scripts/docsync/generate_docs.py --all`을 실행해 CLI, 프로토콜, 텔레메트리, 성능 참조를 갱신했습니다.
- Mermaid 다이어그램과 텔레메트리 표를 재생성했습니다.
<!-- AUTODOC:AUDIT:END -->
