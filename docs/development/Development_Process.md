# 개발 프로세스
이 문서는 Draco Roundtrip의 지속적 개선 워크플로를 설명하며, 코드 품질·하이브리드 아키텍처·리팩터링 이정표를 위한 검토 결과와 실행 가능한 체크리스트를 통합합니다.
_마지막 업데이트: 2025-03-17_

**목차**
- [워크플로 개요](#워크플로-개요)
- [Spec-Driven 흐름](#spec-driven-흐름)
- [완료 정의](#완료-정의)
- [실행 체크리스트](#실행-체크리스트)
- [미해결 작업](#미해결-작업)
- [참고 자료](#참고-자료)

## 워크플로 개요
- **맥락**: Draco Roundtrip은 ROS 2 노드와 CLI 도구 사이에서 공유하는 유틸리티를 사용해 Draco로 압축한 LiDAR 프레임을 TCP로 스트리밍합니다. v2 프로토콜은 단일 헤더/단일 소켓 멀티플렉싱을 기본값으로 사용하며, 코드 구조는 [구성 참조](../reference/Configuration_Reference.md)에 요약되어 있습니다.
- **부트스트랩**: Python 3.11 가상환경을 활성화하고 `pip install -e .`를 실행합니다. IDE에서 `PYTHONPATH`에 저장소 루트를 `ros2_ws/src`보다 앞에 추가해 모듈 그림자를 방지합니다.
- **타입 검사**: Pyright strict 모드를 필수로 사용합니다. `pytest.ini`는 `tests/` 패키지만 검색하도록 제한해 ROS 패키지 충돌을 막습니다.
- **테스트 전략**: `pytest`, 목표 성능 게이트, 필요 시 `ros2_ws`에서 `colcon test`를 실행하고, 결과를 [결과 템플릿](../reports/results_template.md)에 기록합니다.

## Spec-Driven 흐름
사양을 중심으로 변경을 통제하기 위해 아래 단계를 기본 규칙으로 사용합니다. 각 단계는 [Spec-Driven 문서 재구성 지도](../reference/Spec_Driven_Documentation.md)에 매핑되어 있습니다.
- **목표 명시**: 요구사항/지연 목표가 변경되면 [추적성 매트릭스](../architecture/Traceability_Matrix.md)에 추가하고 영향을 받는 사양을 지정합니다.
- **인터페이스 우선 정리**: 새 플래그나 제어 메시지는 [프로토콜 및 스키마 참조](../reference/Protocol_and_Schema_Reference.md) 또는 [구성 참조](../reference/Configuration_Reference.md)에서 먼저 정의합니다.
- **테스트 연결**: 성능·기능 요구는 [성능 시험 계획](../development/Performance_Test_Plan.md) 또는 대응 테스트 파일로 링크해 검증 경로를 명확히 합니다.
- **운영 정합성 검증**: bringup/로그 수집/모니터링 절차가 바뀌면 [사용자 가이드](../guides/User_Guide.md)와 런타임 메모를 업데이트합니다.
- **근거 보존**: 실행 결과는 [결과 템플릿](../quality/results_template.md)으로 기록하고, 회귀 위험은 [리팩터 및 감사 로그](../reports/Refactor_and_Audit_Log.md)에 남깁니다.

### 품질 특성 점검 루틴
스펙 변경이 품질 속성에 미치는 영향을 반복적으로 확인하기 위한 공통 루틴입니다. 모든 변경 PR은 아래 항목을 충족해야 합니다.

1. **카탈로그 싱크**: 변경된 스펙의 품질 특성 영향과 증거를 [`Quality_Attributes_Catalog`](../reference/Quality_Attributes_Catalog.md)·[추적성 매트릭스](../architecture/Traceability_Matrix.md)에 반영한다.
2. **게이트 실행**: 성능/신뢰성/보안에 영향을 주는 변경이면 `pytest tests/perf/test_latency_gate.py`와 관련 단위 테스트를 실행하고, 결과를 [결과 템플릿](../reports/results_template.md) 품질 게이트 표에 기록한다.
3. **운영/이식성 확인**: 사용자 가이드와 구성 참조의 명령·기본값이 여전히 동작하는지 검증하고, 실패 시 재현 명령과 환경 변수를 문서에 추가한다.
4. **로그·알람 준비**: 신규 플래그/상수는 로그에 표준 키(pending, RTT, p50/p95/p99)를 남기며, 알람 조건을 `results_template`와 동일하게 유지한다.

## 완료 정의
### 코드 개선 스트림
1. **제어 플레인 핸드셰이크**: 종료 시 `FrameType.EOF`가 교환되고, 로그에 `EOF sent`/`EOF received`와 `pending=0` 요약이 표시됩니다.
2. **파일 시스템 워처**: 이벤트 기반 워처를 사용할 수 있을 때 활성화하고, 폴링 폴백은 처리된 항목을 정리해 RSS 증가를 방지합니다.
3. **구성 안전성**: `utils/config.py`가 얕은 설치에서도 `IndexError` 없이 동작하며 프로파일/QoS 해상도를 일관되게 유지합니다.
4. **소켓 이식성**: `SO_REUSEPORT`를 사용할 수 없을 때 서버가 정상적으로 대체 경로로 폴백합니다.
5. **디코드 위생**: `--keep-artifacts`가 명시되지 않으면 임시 디코드 아티팩트를 정리합니다.

### 하이브리드 아키텍처 스트림
1. 캡처→인코드→전송→디코드 전 구간에서 제한 큐를 사용하고 `maxsize` 및 일시정지/재개 신호를 명시합니다.
2. 오류 발생 시 정지 이벤트를 전파하는 TX/RX 분리 워커 풀을 유지합니다.
3. `--adaptive-window`, `--window-ema-alpha`로 토글되는 적응형 윈도를 지연 게이트를 통해 검증합니다.
4. 단일 TCP 소켓에서 `FrameType`을 사용해 제어/데이터를 다중화하고, MTU 안전 분할(`--tx-fragment-size`)과 프래그먼트 GC가 정상 작동하는지 확인합니다.
5. `tests/perf/test_latency_gate.py`와 CI 스크립트로 성능 게이트를 강제합니다.

### 리팩터 스트림
1. **유틸리티 통합**: 노드·도구·CLI가 `protocol`, `executable`, `ply_io`, `metrics`와 같은 공용 헬퍼를 일관되게 참조합니다.
2. **인코더 CLI 정렬**: `draco_tools.core.encoder`가 옵션 파싱/로그 형식의 단일 진입점 역할을 합니다.
3. **구성 통합**: `resolve_data_layout` 및 QoS 헬퍼를 오프라인 파이프라인과 런치 파일에서 재사용합니다.
4. **테스트와 CI**: 단위 테스트는 `ros2_ws/src/draco_roundtrip/tests/`에 위치하고, E2E 스크립트는 최소 1회의 라운드트립을 검증하며, CI는 빌드+테스트+성능 게이트를 수행합니다.
5. **문서 정합성**: 가이드와 참조 문서가 통합 구성·프로토콜 문서를 가리키며 README/HOWTO가 최신 상태로 유지됩니다.

## 실행 체크리스트
1. [아키텍처 설계 및 계획](../architecture/Architectural_Design_and_Plan.md)을 참고해 변경 사항을 계획하고 [추적성 매트릭스](../architecture/Traceability_Matrix.md)에서 영향받는 요구사항(프레임 헤더, 프래그먼트 GC, 텍스트 제한 등)을 확인합니다.
2. 새로운 플래그나 디렉터리를 도입할 때 구성 문서를 갱신하고 [구성 참조](../reference/Configuration_Reference.md)가 CLI 기본값과 일치하도록 유지합니다.
3. **구현 및 린트**:
   ```bash
   ruff check .
   pyright
   pytest --maxfail=1 --disable-warnings
   ```
4. 전송, 큐잉, 텔레메트리 경로가 변경되면 성능 게이트를 실행합니다:
   ```bash
   pytest tests/perf/test_latency_gate.py
   ```
5. `stream_collect_logs`로 텔레메트리와 로그를 수집하고, 재현 가능성을 위해 아티팩트와 함께 매니페스트를 보관합니다.
6. **결과 문서화**: 이 문서의 관련 체크리스트를 업데이트하고, [리팩터 및 감사를 위한 로그](../reports/Refactor_and_Audit_Log.md)에 회귀 증거를 남기며, [결과 템플릿](../reports/results_template.md)을 채웁니다.

## 미해결 작업
- [ ] 비 Linux 플랫폼에서 파일 시스템 워처 성능을 측정하고 필요한 경우 폴링 주기를 조정합니다.
- [ ] `--transport=quic|udp_fec` 프로토타입을 만들고 손실 시나리오에서의 성능 변화를 기록합니다.
- [ ] EOF/바이너리 제어 경로 및 단일 소켓 멀티플렉싱을 엔드투엔드로 검증하는 회귀 테스트를 확장합니다.
- [ ] 스트리밍 노드를 rclcpp + Asio로 이식하고 Python 구현과 동등성을 검증합니다.
- [ ] 저지연 커널 튜닝과 텔레메트리 대시보드를 포함한 컨테이너 기반 배포를 자동화합니다.

## 참고 자료
- [아키텍처 설계 및 지연 시간 계획](../architecture/Architectural_Design_and_Plan.md)
- [추적성 매트릭스](../architecture/Traceability_Matrix.md)
- [프로토콜 및 스키마 참조](../reference/Protocol_and_Schema_Reference.md)
- [사용자 가이드](../guides/User_Guide.md)
