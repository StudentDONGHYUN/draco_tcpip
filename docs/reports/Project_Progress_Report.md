# 프로젝트 진행 보고서 (Spec-Driven)
실제 코드와 테스트, 문서를 한 흐름으로 유지하기 위한 진행 현황을 요약합니다. 각 섹션은 목표(What) → 근거(Why) → 다음 단계(How) 순으로 구성했습니다. 업데이트 시에는 관련 PR과 테스트 로그를 링크하여 추적성을 확보합니다.

## 1. 핵심 목표와 성공 지표
- **제어 플레인 안정화**: 단일 TCP 소켓에서 v2 헤더(DATA/ACK/HEARTBEAT/EOF/ERROR)만 허용하고, 하트비트/ACK 타임아웃·조각화 범위를 코드와 문서에 일치시킨다. 성공 기준: 루프백 e2e 테스트가 `TERMINATED`로 종료되고 `_text_limit_drops=0` 유지.
- **성능 기준선**: rosbag 기반 회귀 벤치마크에서 p95 지연 < 250 ms, 드롭률 0%를 CI에서 강제한다. 성공 기준: `tests/perf` 스위트가 통과하고 결과가 `artifacts/perf/*.json`에 저장됨.
- **운영 재현성**: 레이아웃 프로파일/QoS/프로토콜 설정이 사용자 가이드·구성 참조·런치 파일에서 동일하게 동작한다. 성공 기준: `stream_collect_logs` 매니페스트가 필요한 모든 파일(프로파일, QoS, 로그, 메타데이터)을 포함.

## 2. 단기 계획 (이번 이터레이션)
1. 회귀 벤치마크 하네스 확정: rosbag+netem 프로파일을 `tests/perf`에서 호출하도록 정리하고 p95 지연 게이트를 CI에 연결.
2. 바이너리 프로토콜 검증 확대: TEXT 제한 경고, 프래그먼트 GC, 하트비트 타임아웃을 포함한 통합 테스트 추가.
3. 구성 통합 완료: `utils/config` 로더를 문서·런치·CLI에서 동일하게 사용하도록 가이드/참조 업데이트.
4. 로그·아티팩트 표준화: `stream_collect_logs` 매니페스트 스키마를 결과 템플릿과 맞추고 필수 필드 누락 시 실패하도록 문서화.

## 3. 중기 계획 (다음 분기)
- QUIC/UDP-FEC 전송 모드의 실험적 구현과 손실 시나리오 카탈로그 작성.
- Draco C++ 인프로세스 인코더/디코더를 추가하고 Python 호환 레이어를 유지.
- 텔레메트리 대시보드를 포함한 자동 배포 파이프라인 구축(GitHub Actions + 컨테이너 이미지).
- SLAM 통합 bringup을 확장해 QoS/토픽 remap, layout profile을 인자화.

## 4. 상태 표 (요약)
| 영역 | 상태 | 근거/메모 |
| --- | --- | --- |
| 제어 플레인 v2 | ✅ 안정 | 단일 소켓, FrameType 다중화, 텍스트 제한 문서/코드 반영 |
| 회귀 벤치마킹 | ⏳ 진행 | 테스트 스켈레톤 존재, p95 게이트/CI 연결 진행 중 |
| 전송 실험(QUIC/UDP-FEC) | 🟡 계획 | 설계 초안만 존재, 구현 미착수 |
| C++/공유 메모리 경로 | 🟡 계획 | 아키텍처 구상 단계, 코드 없음 |
| 텔레메트리 자동화 | ⏳ 진행 | 스키마 정의 완료, 대시보드/보고서 자동화 대기 |

## 5. 잔여 체크리스트 (선행 조건 → 후속)
- [ ] rosbag 회귀 벤치마크 + p95 지연 게이트를 CI에 연결 (선행: netem 프로파일 문서화).
- [ ] 텍스트 프로토콜 제한/프래그먼트 GC/하트비트 타임아웃 통합 테스트 추가 (선행: 프로토콜 참조 업데이트).
- [ ] Draco C++ 경로 설계서 초안 작성 및 Python 호환성 요구 정의.
- [ ] 텔레메트리 스키마 검증을 `stream_collect_logs`에 기본 적용하고 실패 시 경고.
- [ ] 컨테이너/런치 기반 SLAM bringup에 QoS/레이아웃 프로파일 전달 경로 검증.

## 6. 링크드 참조
- 아키텍처: `docs/architecture/Architectural_Design_and_Plan.md`
- 프로토콜: `docs/architecture/Control_Plane_Design.md`, `docs/reference/Protocol_and_Schema_Reference.md`
- 구성/가이드: `docs/reference/Configuration_Reference.md`, `docs/guides/User_Guide.md`
- 리팩터 로그: `docs/reports/Refactor_and_Audit_Log.md`
