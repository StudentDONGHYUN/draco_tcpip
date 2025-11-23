# 소프트웨어 품질 특성 카탈로그

Draco TCP/IP Roundtrip 문서와 산출물이 일관되게 **기능성, 유지보수성, 확장성, 성능, 신뢰성, 사용성, 보안성, 이식성, 테스트 가능성, 운영 가능성**을 충족하도록 사용하는 공용 참조표입니다. 각 특성별로 목표, 필수 증거, 대표 문서, 확인 방법을 제공합니다.

## 품질 특성 요약 표
| 특성 | 핵심 질문 | 필수 증거/산출물 | 대표 문서 | 확인 방법 |
| --- | --- | --- | --- | --- |
| 기능성(기능 적합성·정확성·상호운용성) | 요구한 일을 정확히, 표준대로 수행하는가? | 요구사항 ↔ 구현 ↔ 테스트 매핑, 입력/출력 규격, 인터페이스 계약 | [Traceability_Matrix](../architecture/Traceability_Matrix.md), [Protocol_and_Schema_Reference](../reference/Protocol_and_Schema_Reference.md) | 요구사항을 테이블에서 찾고 대응 테스트/CLI가 있는지 확인 |
| 유지보수성 | 변경·리팩터·온보딩이 쉬운가? | 명명 규칙, 모듈 책임, 스타일/도구 규칙, 리뷰 체크리스트 | [Development_Process](../development/Development_Process.md), [codebase_overview](../reference/codebase_overview.md) | PR 템플릿·코딩 규칙 준수 여부, 신규 기여자 온보딩 시간 |
| 확장성(성능/기능) | 부하·기능 증가에 구조가 견디는가? | 무상태/윈도우 제한, 플러그인/레이아웃 프로파일 가이드, 용량 계획 | [Architectural_Design_and_Plan](../architecture/Architectural_Design_and_Plan.md), [Configuration_Reference](../reference/Configuration_Reference.md) | 멀티 인스턴스/프로파일 추가 시 변경 범위와 테스트 영향 |
| 성능/효율성 | 목표 지연·처리량·자원 효율을 충족하는가? | 성능 목표, 측정 방법, 임계값·게이트, 프로파일별 기대치 | [Performance_Test_Plan](../development/Performance_Test_Plan.md), [quality/results_template](../quality/results_template.md) | p95 지연/CPU 메트릭과 목표 비교, 회귀 여부 |
| 신뢰성/안정성 | 장애·예외에서 잘 복구되는가? | 에러 처리 규칙, 재시도/타임아웃, 상태 전이·로그 요구사항 | [Runtime_Stability_Notes](../runtime/Runtime_Stability_Notes.md), [results_template](../reports/results_template.md) | 장애 케이스 재현 시 로그·복구 절차 일관성 |
| 사용성(UX) | 사용 흐름이 직관적이고 안내가 충분한가? | 단계별 가이드, 기본값/예시, 오류 메시지 기대치 | [User_Guide](../guides/User_Guide.md) | 신규 사용자가 예시 명령만으로 bringup 가능한지 |
| 보안성 | 인증/인가/데이터 보호가 적용되는가? | 인증/비밀 관리 규칙, 입력 검증, 네트워크 보안 프로파일 | [Protocol_and_Schema_Reference](../reference/Protocol_and_Schema_Reference.md), [Development_Process](../development/Development_Process.md) | 민감 데이터/토큰 처리 지침과 릴리즈 체크리스트 존재 여부 |
| 이식성/호환성 | 환경이 달라도 구성만으로 실행 가능한가? | 환경 변수/프로파일 분리, 플랫폼 의존성 표, 버전 요구사항 | [User_Guide](../guides/User_Guide.md), [Configuration_Reference](../reference/Configuration_Reference.md) | OS/ROS/Python 버전 매트릭스와 대체 절차 확인 |
| 테스트 가능성/품질 보증 | 자동화로 품질을 측정·유지할 수 있는가? | 테스트 스위트 위치, 커버리지 기대치, CI 파이프라인 단계 | [Performance_Test_Plan](../development/Performance_Test_Plan.md), [tests](../../tests) | CI 단계 통과 여부와 실패 시 재현 절차 |
| 운영 가능성(Observability) | 모니터링·로깅·배포/롤백이 용이한가? | 필수 메트릭/로그 필드, 알람 조건, 배포/롤백 플레이북 | [Runtime_Stability_Notes](../runtime/Runtime_Stability_Notes.md), [results_template](../reports/results_template.md) | 필수 텔레메트리 존재 여부, 알람/롤백 절차 문서화 |

## 문서별 적용 가이드
- **템플릿/보고서**: [`docs/reports/results_template.md`](../reports/results_template.md)와 [`docs/quality/results_template.md`](../quality/results_template.md)는 위 표를 그대로 복사해 실행별로 채우고, 미충족 특성은 후속 작업에 연결합니다.
- **설계·구성 문서**: 프로토콜/구성/아키텍처 문서는 각 변경 시 해당 특성의 영향(예: 성능 임계값, 신뢰성 타임아웃, 보안 검증)을 명시해야 합니다.
- **운영·가이드**: 사용자 가이드와 안정성 메모는 사용성·운영 가능성·이식성의 증거를 제공하므로, 변경 시 바로 반영합니다.
- **거버넌스 문서**: 개발 프로세스, 감사 로그, 진행 보고서는 유지보수성·테스트 가능성·보안성을 다룹니다. 체크리스트가 누락되면 카탈로그 표를 기준으로 추가합니다.

## 작성/리뷰 체크리스트
1. **특성 명시**: 신규 문서나 변경분에 대해 어떤 품질 특성에 영향을 주는지 머리말이나 표로 명시합니다.
2. **증거 위치 연결**: 표나 섹션에서 실제 아티팩트(테스트 파일, 로그, 스크립트)를 링크합니다.
3. **임계값/정책 일관성**: 성능 목표, 타임아웃, 재시도, 보안 정책은 문서/템플릿/테스트가 동일한 값을 사용하도록 교차 확인합니다.
4. **재현성 확보**: 실험/운영 절차에는 의존성 버전, 명령어, 입력 파일, 네트워크 프로파일을 포함해 이식성을 높입니다.
5. **자동화 고려**: AUTODOC 블록이나 스크립트를 활용해 표·목록이 수동 편집 없이 최신 상태를 유지하도록 합니다.
