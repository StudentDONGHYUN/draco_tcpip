# Quality Attribute Scorecard (Current State)

이 문서는 `docs/reference/Quality_Attributes_Catalog.md`에서 정의한 10가지 품질 특성을 기준으로 현재 코드베이스의 성숙도를 정성적으로 평가합니다. 점수는 1–5 구간이며, 5에 가까울수록 **증거(문서·테스트·구현)가 일관되고 자동화되어 있음**을 뜻합니다. 3 이하는 후속 개선이 필요함을 의미합니다.

- **5**: 문서·테스트·구현이 모두 일관되며 게이트/자동화로 보호됨
- **4**: 증거가 구체적이지만 일부 수동 절차나 부분적 공백 존재
- **3**: 핵심 구조는 있으나 자동화/증거가 부족하거나 오래됨
- **2 이하**: 구조나 검증이 부족해 리스크가 높음

## Score Summary
| 특성 | 점수 | 근거 | 개선 필요성 |
| --- | --- | --- | --- |
| 기능성/정확도 | 4.5 | 요구사항→구현→테스트 추적표가 핵심 기능(RQ-CP/FRAG/TEL/CLI/SEC)에 대해 채워져 있음.【F:docs/architecture/Traceability_Matrix.md†L9-L30】 | PR 컬럼이 `PR-TBD`로 남아 있어 변경 기록 보강 필요.【F:docs/architecture/Traceability_Matrix.md†L12-L18】 |
| 성능/효율성 | 3.5 | p95 지연 게이트가 명시돼 있고 텔레메트리 아티팩트를 활용하는 pytest가 존재.【F:tests/perf/test_latency_gate.py†L11-L18】【F:docs/guides/User_Guide.md†L94-L99】 | 자동 실행에 필요한 `artifacts/perf/client_latest.json`이 수동 준비여서 CI 연동이 미흡. |
| 확장성 | 3.5 | 적응형 윈도/프래그먼트 크기/전송 파라미터 등이 CLI 테이블로 표준화되어 부하 시 튜닝 가능.【F:docs/reference/Configuration_Reference.md†L125-L170】 | 멀티 인스턴스·대용량 부하에 대한 정량 검증 로그가 없음. |
| 신뢰성/안정성 | 3.5 | 제어 평면 상수(ACK/heartbeat 타임아웃, 상태 머신)와 품질 점검 루틴이 명시돼 장애 시 동작을 제한.【F:ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/stream_protocol.py†L57-L188】【F:docs/development/Development_Process.md†L27-L48】 | 장시간 회귀/soak 테스트 증거와 실패 복구 로그가 부족. |
| 운영 가능성(Observability) | 4.0 | 텔레메트리 빌더가 스키마 버전·필수 메트릭(지연 분위수, 큐/프레임 카운터)을 강제하고, 로그 수집 절차가 가이드에 제공됨.【F:ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py†L28-L199】【F:docs/guides/User_Guide.md†L99-L110】 | 알람 기준/대시보드 결과가 저장소에 포함돼 있지 않음. |
| 보안성 | 2.5 | 텍스트 프로토콜 입력 길이 초과 시 연결을 종료하고 로그로 남기는 단위 테스트가 존재, 사용자 가이드도 제한을 경고.【F:tests/unit/test_text_protocol_limits.py†L30-L76】【F:docs/guides/User_Guide.md†L75-L78】 | 인증/비밀 관리·암호화 지침이 부재하며, 침투/취약점 테스트가 없음. |
| 사용성 | 4.0 | bringup·netem 적용·클라이언트 실행·로그 수집이 단계별 명령과 주석으로 설명되어 초보 사용자도 따라 할 수 있음.【F:docs/guides/User_Guide.md†L64-L110】 | 에러 메시지 기대치·FAQ가 별도로 정리되어 있지 않음. |
| 테스트 가능성/CI | 3.5 | Pyright/ruff/pytest 실행과 품질 게이트를 필수 단계로 명시하는 개발 프로세스와 체크리스트가 존재.【F:docs/development/Development_Process.md†L16-L33】【F:docs/development/Development_Process.md†L60-L69】 | CI 결과/커버리지 리포트가 저장소에 없으며, 성능 게이트는 외부 텔레메트리에 의존. |
| 이식성/호환성 | 3.0 | 다양한 실행 환경을 CLI 옵션으로 노출(소켓 버퍼, adaptive window, 레이아웃/데이터 루트 등)하여 설정만으로 조정 가능.【F:docs/reference/Configuration_Reference.md†L125-L170】 | 비-Linux 성능 검증 등 플랫폼별 확인이 미해결 작업으로 남아 있음.【F:docs/development/Development_Process.md†L73-L78】 |
| 유지보수성 | 3.5 | 코드베이스 개요와 Spec-Driven 절차가 모듈 책임·문서 링크·공유 헬퍼를 정리해 온보딩을 돕고 있다.【F:docs/reference/codebase_overview.md†L5-L64】【F:docs/development/Development_Process.md†L19-L25】 | 추적성 표의 PR 열이 비어 있고, 일부 리팩터 TODO가 남아 있어 변경 추적·완료 정의가 부분적으로 미비.【F:docs/architecture/Traceability_Matrix.md†L12-L18】【F:docs/development/Development_Process.md†L73-L78】 |

## Key Observations
- **강점**: 프로토콜/구성/품질 지표가 문서와 코드, 테스트로 삼중 연결되어 기능성과 운영 가능성이 높은 수준을 유지합니다. 텔레메트리 스키마와 제어 평면 상수가 엄격히 검증되어 회귀 감지가 용이합니다.【F:ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/stream_protocol.py†L57-L188】【F:ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py†L28-L199】
- **보완점**: 보안·성능·이식성 영역은 자동화된 증거가 부족합니다. 특히 인증/암호화, 장시간 soak, 타 OS 측정은 TODO 상태이며, 성능 게이트는 외부 텔레메트리 파일에 의존합니다.【F:docs/development/Development_Process.md†L31-L33】【F:docs/development/Development_Process.md†L73-L78】【F:tests/perf/test_latency_gate.py†L11-L18】
- **우선 후속 작업 제안**:
  1. CI에 텔레메트리 생성 스텁을 추가해 `tests/perf/test_latency_gate.py`를 자동화하고, 결과를 품질 게이트 표에 적재.
  2. 텍스트 프로토콜 한계 외에 인증/비밀 관리 가이드와 정적 분석(예: `bandit`)을 추가해 보안 점수를 개선.
  3. 비-Linux 플랫폼 및 멀티 세션 부하 시나리오에 대한 측정 로그를 작성해 이식성과 확장성 근거를 강화.
