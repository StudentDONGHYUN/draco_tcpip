# 문서 색인

Draco TCP/IP Roundtrip 문서를 범주별로 탐색할 수 있는 색인입니다. 각 링크는 저장소 내부 문서로 직접 연결되며, 업데이트 일자는 각 문서 상단의 메타데이터를 참조하세요.

## 가이드
- [사용자 가이드](../guides/User_Guide.md): 환경 준비, 스트리밍/SLAM bringup, 로그 수집, 문제 해결 절차를 순차적으로 안내합니다.

## 아키텍처
- [아키텍처 설계 및 지연 시간 계획](../architecture/Architectural_Design_and_Plan.md): 비동기 파이프라인, 제어 플레인 상태 기계, 지연 단축 로드맵과 Mermaid 시퀀스 다이어그램을 제공합니다.
- [추적성 매트릭스](../architecture/Traceability_Matrix.md): 요구사항, 구현 산출물, 테스트, 문서 간 연결을 표 형식으로 정리합니다.

## 참조
- [구성 참조](../reference/Configuration_Reference.md): 레이아웃 프로파일, CLI 플래그 매트릭스, 구성 검색 규칙을 명세합니다.
- [프로토콜 및 스키마 참조](../reference/Protocol_and_Schema_Reference.md): 제어 메시지, 상태 기계, 텔레메트리 스키마와 바이너리 헤더를 정의합니다.
- [코드베이스 개요](../reference/codebase_overview.md): ROS 2 패키지 구조, 데이터 흐름, 콘솔 엔트리포인트를 요약합니다.
- [유틸리티 사용 참조](../reference/utils_usage.md): `draco_roundtrip.utils` 모듈과 주요 소비자 매핑을 제공합니다.

## 개발
- [개발 프로세스](../development/Development_Process.md): 워크플로, 완료 정의, 실행 체크리스트, 미해결 작업을 정리합니다.
- [성능 시험 계획](../development/Performance_Test_Plan.md): rosbag 기반 회귀 벤치마크 구성과 실행 절차를 정의합니다.
- [런타임 안정성 메모](../development/Runtime_Stability_Notes.md): 스트리밍 클라이언트/서버, 공유 메모리, 오프라인 파이프라인의 실패 완화 전략을 기록합니다.

## 운영 품질 및 런타임
- [성능 시험 계획 (요약)](../quality/Performance_Test_Plan.md): 자동화된 성능 목표와 검증 테스트를 추적합니다.
- [실험 결과 템플릿](../quality/results_template.md): 실행 리포트 작성 시 필요한 메트릭 및 목표를 표준화합니다.
- [런타임 안정성 메모 (운영)](../runtime/Runtime_Stability_Notes.md): 장시간 세션의 텔레메트리 검증 상태를 요약합니다.

## 보고서
- [프로젝트 진행 보고서](../reports/Project_Progress_Report.md): 단기/중기 계획, 상태 표, 잔여 체크리스트를 제공합니다.
- [리팩터 및 감사 로그](../reports/Refactor_and_Audit_Log.md): 감사 항목, 리팩터 타임라인, 운영 가이드, 후속 작업을 추적합니다.
- [리포트/결과 템플릿](../reports/results_template.md): 실험 결과 수집 시 사용되는 템플릿을 제공합니다.

## 자동 생성 섹션 갱신 방법
<!-- AUTODOC:HOWTO:BEGIN -->
자동 생성 섹션을 갱신하려면 `python scripts/docsync/generate_docs.py --all`을 실행하세요. 스크립트는 멱등성이 보장되며 AUTODOC 앵커 내부만 다시 작성합니다.
<!-- AUTODOC:HOWTO:END -->
