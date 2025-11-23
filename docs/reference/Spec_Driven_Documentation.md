# Spec-Driven 문서 재구성 지도
Draco TCP/IP Roundtrip 문서를 **Spec-Driven Development** 흐름에 맞춰 재구성한 네비게이션입니다. 요구사항→설계 사양→인터페이스 계약→검증→운영 근거까지 일관된 체인을 유지하는 것을 목표로 합니다.
_마지막 업데이트: 2025-03-17_

## 개요
- **목적**: 성능·지연 목표, 제어 플레인 계약, 텔레메트리 스키마 등 모든 변경을 사양 중심으로 검토하고 추적합니다.
- **사용 대상**: 신규 기여자(온보딩), 리뷰어(변경 영향 확인), 운영자(사양 준수 여부 점검).
- **참고 규칙**: 새 기능은 _사양 문서와 추적성_을 먼저 갱신한 뒤 구현·테스트·운영 문서를 업데이트합니다.

## 사양 계층 구조
1. **제품/성능 사양** — 시스템이 제공해야 하는 최종 결과와 목표.
   - [아키텍처 설계 및 지연 시간 계획](../architecture/Architectural_Design_and_Plan.md): 비동기 파이프라인, 단일 소켓 멀티플렉싱, 지연 단축 로드맵.
   - [추적성 매트릭스](../architecture/Traceability_Matrix.md): 요구사항 ↔ 구현 ↔ 테스트 연결.
2. **인터페이스·프로토콜 계약** — 구현이 준수해야 하는 입력/출력 제약과 데이터 형식.
   - [프로토콜 및 스키마 참조](../reference/Protocol_and_Schema_Reference.md): 제어 메시지, 상태 기계, 텔레메트리 스키마, 바이너리 헤더.
   - [구성 참조](../reference/Configuration_Reference.md): 레이아웃 프로파일, QoS 검색 규칙, CLI 기본값.
   - [유틸리티 사용 참조](../reference/utils_usage.md) & [코드베이스 개요](../reference/codebase_overview.md): 공용 헬퍼와 소비자.
3. **운영 시나리오** — 사양을 어떻게 실행·관찰·복구할지에 대한 절차.
   - [사용자 가이드](../guides/User_Guide.md): bringup, 스트리밍/SLAM, 로그 수집 순서.
   - [런타임 안정성 메모 (운영)](../runtime/Runtime_Stability_Notes.md): 장시간 세션 모니터링, 알람·복구 규칙.
4. **검증·증거** — 사양을 만족함을 입증하는 테스트와 보고.
   - [성능 시험 계획](../development/Performance_Test_Plan.md) & [성능 시험 계획 (요약)](../quality/Performance_Test_Plan.md): p95 지연 목표, 회귀 벤치마크.
   - [테스트 스위트](../../tests): 단위/성능/회귀 테스트 위치.
   - [결과 템플릿](../quality/results_template.md) & [리포트/결과 템플릿](../reports/results_template.md): 실행 보고서 표준.
5. **프로젝트 거버넌스** — 변경을 통제하고 후속 조치를 기록.
   - [개발 프로세스](../development/Development_Process.md): 체크리스트 기반 워크플로, 완료 정의.
   - [리팩터 및 감사 로그](../reports/Refactor_and_Audit_Log.md) & [프로젝트 진행 보고서](../reports/Project_Progress_Report.md): 감사/로드맵/상태 추적.

## 사양 기반 변경 절차
1. **요구사항/목표 명세**: 새로운 기능이나 성능 목표가 생기면 [추적성 매트릭스](../architecture/Traceability_Matrix.md)에 요구사항을 추가하고, 영향받는 사양 문서를 찾습니다.
2. **사양 업데이트**: 인터페이스·구성·프로토콜 변경은 참조 문서에서 먼저 정의한 뒤 구현을 시작합니다.
3. **테스트 계획 연결**: 사양별로 대응하는 테스트를 [성능 시험 계획](../development/Performance_Test_Plan.md) 또는 관련 테스트 파일에 연결해 검증 경로를 명확히 합니다.
4. **운영 가이드 정합성**: 사용 흐름이나 로그 수집 방식이 달라지면 [사용자 가이드](../guides/User_Guide.md)와 런타임 메모를 업데이트합니다.
5. **근거 수집**: 실행 결과를 [결과 템플릿](../quality/results_template.md)으로 기록하고, 회귀 위험은 [리팩터 및 감사 로그](../reports/Refactor_and_Audit_Log.md)에 남깁니다.

## 빠른 링크 요약
| 영역 | 핵심 문서 | 질문에 대한 답 | 업데이트 시 체크 |
| --- | --- | --- | --- |
| 제품/목표 | [Architectural_Design_and_Plan](../architecture/Architectural_Design_and_Plan.md) | 지연 목표? 파이프라인 경계? | 추적성 매트릭스에 요구사항 추가 |
| 인터페이스 | [Protocol_and_Schema_Reference](../reference/Protocol_and_Schema_Reference.md) | 헤더/제어/스키마는? | 구성 참조와 CLI 기본값 동기화 |
| 운영 | [User_Guide](../guides/User_Guide.md) | 어떻게 실행/모니터링? | 런타임 안정성 메모와 일치 여부 |
| 검증 | [Performance_Test_Plan](../development/Performance_Test_Plan.md) | 어떤 테스트로 증명? | 테스트/CI 스크립트와 임계값 정합 |
| 거버넌스 | [Development_Process](../development/Development_Process.md) | 체크리스트? 완료 정의? | 감사 로그와 진행 보고서 갱신 |

## 유지보수 팁
- **사양 우선 리뷰**: PR 설명에는 어떤 사양을 변경했는지, 어느 테스트로 입증했는지 명시합니다.
- **자동화 활용**: `python scripts/docsync/generate_docs.py --all`로 AUTODOC 구간을 갱신해 참조 문서와 코드의 불일치를 줄입니다.
- **버전 스냅샷**: 주요 사양 변경 시 결과 템플릿과 로그 아티팩트를 함께 보관해 회귀 원인을 신속히 파악합니다.
