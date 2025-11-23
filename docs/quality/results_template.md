# 실험 결과 템플릿
실행 메타데이터, 텔레메트리 아티팩트, 품질 게이트, 후속 작업을 표준화합니다. 모든 문서는 [`Quality_Attributes_Catalog`](../reference/Quality_Attributes_Catalog.md)을 기준으로 작성하며, 빈 셀은 `N/A`로 표시합니다. v2 프로토콜과 관련된 실행에서는 다음 정보를 추가로 기록합니다.

- 사용한 프레임 헤더 버전(`VERSION`/`LEGACY_VERSION`)과 `--legacy-mode` 여부
- 프래그먼트 GC 통계(삭제된 조각 수, 최대 누적 바이트)
- 텍스트 프로토콜 제한 위반 횟수(`_text_limit_drops`), 발생 시 타임스탬프 및 원인

## 1. 메타데이터
| 키 | 값 | 비고 |
| --- | --- | --- |
| `run_id` |  | 디렉터리 이름과 일치 |
| `profile` |  | 사용한 레이아웃/네트워크/SLAM 프로파일 |
| `bag` 또는 `live` |  | 입력 소스와 토픽 |
| `commit` |  | git SHA |
| `report_version` |  | 템플릿/스키마 버전 |

## 2. 환경 및 구성
- **하드웨어/소프트웨어**: CPU, GPU, RAM, OS, 커널, ROS 2, Python, Draco 빌드
- **구성 해시**: 프로파일 파일 체크섬 또는 git SHA
- **실행 명령어**: 서버/클라이언트/런치, netem, 추가 스크립트

## 3. 품질 게이트 요약
| 특성 | 목표 | 측정 | 합격 여부 | 근거 |
| --- | --- | --- | --- | --- |
| 기능성/정확도 | `breaches == false`, 스키마 준수 | `__ breaches` | ✅/❌ | [`<prefix>_quality.jsonl`](../../QUALITY_REPORT.md) |
| 성능/효율성 | p95 지연 `< 250 ms`, CPU/메모리 예산 | `___ ms`, 사용률 | ✅/❌ | `pytest tests/perf/test_latency_gate.py` |
| 확장성 | in-flight/세션 확장 시 목표 유지 | 측정값 | ✅/❌ | 윈도우 캡/멀티 세션 로그 |
| 신뢰성/안정성 | `0 fatal`, 재시도/타임아웃 정책 유지 | `___ fatal / ___ warn` | ✅/❌ | ROS 로그, TCP 상태 |
| 운영 가능성/관측 | 필수 메트릭·로그·알람 조건 충족 | 예/아니오 | ✅/❌ | `server_metrics`/`client_metrics`, 알람 |
| 보안성 | 비밀 관리·입력 검증 준수 | 예/아니오 | ✅/❌ | TLS/키 관리, 입력 검증 |
| 사용성 | 가이드만으로 실행 가능 | 예/아니오 | ✅/❌ | [User_Guide](../guides/User_Guide.md) 재현 |
| 테스트 가능성/CI | 회귀 테스트 통과 | 예/아니오 | ✅/❌ | pytest/CI 로그 |
| 이식성 | 다른 OS/네트워크에서 구성만 변경해 실행 가능 | 예/아니오 | ✅/❌ | 환경 변수·프로파일 표 |
| 유지보수성 | 변경 영향·롤백 절차 기록 | 예/아니오 | ✅/❌ | 변경 로그, 롤백 명령 |

## 4. 핵심 결과 요약
- **지연/처리량**: p50/p95/p99, 최대치, 계산 방법
- **품질**: Chamfer, 최근접 평균 상대 오차, 점수 카디널리티
- **트래픽**: 전송된 총 바이트, 최대 in-flight 프레임 수
- **리소스**: CPU/GPU 사용률, 메모리/디스크 스파이크, 스레드/프로세스 수

## 5. 품질 특성 레이더
| 특성 | 증거/링크 | 미충족 시 원인 및 후속 조치 |
| --- | --- | --- |
| 기능성·정확도 |  |  |
| 성능/확장성 |  |  |
| 신뢰성/안정성 |  |  |
| 운영 가능성(모니터링·로그) |  |  |
| 보안성 |  |  |
| 사용성 |  |  |
| 테스트 가능성/CI |  |  |
| 이식성 |  |  |
| 유지보수성 |  |  |

## 6. 재현 절차
1. 환경 준비 명령어 (venv, ROS 2, rosdep 등)
2. netem 적용 또는 초기화 명령어
3. 서버/클라이언트/런치 실행 명령어
4. 로그·아티팩트 수집 명령어
5. 품질 리포트 필터링 명령어(`jq`, `pandas` 등)

## 7. 자동 생성 목표
<!-- AUTODOC:PERF_TARGETS:BEGIN -->
| Metric | Target | Source | Validation |
| - | - | - | - |
| Client telemetry latency p95 | < threshold from docs/tests/perf/latency_benchmark_plan.md (default 250ms) | tests/perf/test_latency_gate.py | pytest -k test_latency_p95_gate |
| Control-plane heartbeat liveness | Heartbeat observed within 6s (HEARTBEAT_LIVENESS_NS) | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/stream_protocol.py | tests/unit/test_protocol_integration.py::test_heartbeat_timeout |
| Max inflight frames | Window clamp obeys --max-inflight and drains on EOF | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_client.py | tests/unit/test_window_enforcement.py |
<!-- AUTODOC:PERF_TARGETS:END -->
