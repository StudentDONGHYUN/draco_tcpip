<!-- Path: docs/designs/hybrid_pipeline_v2.md -->

# Hybrid Streaming Pipeline v2

_Last updated: 2025-02-14_

## Changelog
- 2025-02-14: 테스트 모듈 경로 충돌 완화와 타입 체킹 가드레일을 명시했습니다.

## Type-Checking, Packaging & IDE Integration
- 하이브리드 파이프라인 구현을 편집 가능한 패키지로 사용하려면 리포지토리 루트의 `conftest.py`에서 수행하는 경로 설정을 동일하게 유지하십시오.
- Pyright/Pylance는 `tests` 네임스페이스를 ROS 2 패키지보다 먼저 해석해야 하므로, `pyrightconfig.json`의 `executionEnvironments`에 루트와 `ros2_ws/src`를 모두 포함시키세요.
- GitHub Actions나 로컬 CI에서 `pytest` 실행 시에는 루트에 있는 `pytest.ini` 구성을 재사용하여 `tests` 디렉터리만 수집하도록 고정합니다.

본 문서는 `async_pipeline_design.md`, `network_latency_reduction_plan.md`, 그리고 Multiprocess Pipeline Design에서 제안한 장점을 통합한 신규 하이브리드 아키텍처를 요약합니다. Python 기반 파이프라인을 유지하면서도 ROS 2/멀티프로세스 확장과 향후 C++ 포팅을 고려하여 단계별 개선 계획을 재정의했습니다.

## 핵심 목표
- **결정적 종료**: MSG_EOF와 MSG_ACK, MSG_HEARTBEAT를 포함한 제어 평면을 정의해 파이프라인 전 구간에서 종료 조건을 명확히 합니다.
- **안정적 역압 제어**: 송신 윈도우(`max_inflight`)는 ACK 기반으로 동작하며, 큐는 모두 유한 크기입니다.
- **네트워크 효율**: 기본 바이너리 프로토콜은 MTU 안전한 조각 전송을 수행하고, 제어/데이터 채널을 분리합니다.
- **관측 가능성**: 각 스테이지의 대기 시간, RTT, ACK 지연을 수집하고 종료 시 요약을 제공합니다.
- **플래그 기반 호환성**: `--protocol legacy|binary`, `--heartbeat-interval`, `--heartbeat-timeout` 등으로 기존 워크플로를 보존하면서 확장 기능을 점진적으로 적용합니다.

## 파이프라인 다이어그램
```
[Capture Thread]
    │  (bounded priority queue)
    ▼
[Encode Worker Pool N]
    │  (bounded asyncio.Queue)
    ▼
[TX Loop ─ non-blocking socket send]
    │  (ACK window ≤ max_inflight)
    ▼          ▲
[Network]  (MSG_ACK/MSG_HEARTBEAT on control channel)
    ▼          │
[RX Pump Thread]
    │  (bounded decode queue)
    ▼
[Decode Worker Pool M]
    │  (bounded reorder buffer keyed by next_seq)
    ▼
[Publish Thread → ROS 2 topic]
```
- 캡처 단계는 단조 증가 시퀀스를 배정하고 EOF 시나리오에서 즉시 MSG_EOF를 전파합니다.
- TX 루프는 송신 성공 시 `acks_pending`에 시퀀스를 추가하고, ACK를 수신하면 윈도우를 해제합니다.
- RX 펌프는 제어/데이터 채널을 구분해 ACK, HEARTBEAT, DATA를 파이프라인에 전달합니다.
- 디코더 풀은 성공/실패를 모두 퍼블리셔에게 알리며, 재정렬 버퍼는 `next_seq` 기준으로 프레임을 방출합니다.

## 제어 평면 메시지
| Kind | Channel | 용도 |
|------|---------|------|
| `MSG_ACK` | `control/<seq>|<name>` | 프레임을 수신 및 큐잉했음을 알리고, 송신 윈도우를 해제합니다. |
| `MSG_HEARTBEAT` | `control/server-heartbeat` | 유휴 기간에도 세션이 활성 상태임을 나타냅니다. 클라이언트는 `--heartbeat-timeout` 초 동안 수신하지 못하면 오류로 간주합니다. |
| `MSG_EOF` | `control/final` | 모든 큐가 비워졌음을 나타내며 종료를 트리거합니다. |
| `MSG_ERROR` | `control/<seq>|<name>` | 디코드 실패 등 오류 정보를 전송합니다. |

## 단계별 실행 계획
| Phase | 초점 | DoD |
|-------|------|-----|
| 0. Stability | EOF/ACK/Heartbeat 제어 평면, 유한 큐, 고정 `max_inflight`, 텔레메트리 요약 | 로그에 `EOF sent/received`, 요약에 `pending=0` 및 p50/p95/p99, ACK 지연 출력 |
| 1. Performance | 적응형 윈도우(`--adaptive-window`), MTU 안전한 조각 전송, 하트비트 기반 혼잡 감지 | RTT/ACK 지연 추적, `--heartbeat-*` 플래그 제공 |
| 2. Transport | QUIC/UDP+FEC 실험 플래그, PMTU/버퍼 자동 튜닝 | 추가 전송 계층 플래그 및 테스트 스크립트 |
| 3. Future | rclcpp/Asio 이식, 인프로세스 Draco, Python 호환 계층 | C++ 경로와 Python 툴 간 동등성 확보 |

## 텔레메트리 및 요약
- 스테이지별 대기 시간: capture→encode, encode latency, encode→send, round-trip, network RTT, ACK latency
- 큐 최대 깊이: 캡처, 네트워크, 인플라이트(ACK 대기)
- 종료 요약: elapsed, bytes sent/received(Mbps), p50/p95/p99, skipped/error 수, `pending`/`pending_acks`
- JSON 메트릭은 동일 필드를 포함하며 CI/대시보드 연계를 위한 스키마로 사용합니다.

## 후속 과제
- `--tx-fragment-size`, `--socket-buffer-autotune` 추가로 사용자 정의 및 자동 튜닝 제공
- bag 기반 회귀 벤치마크와 CI 임계값 (`p95 < 250 ms`) 구현
- QUIC/UDP-FEC 및 인프로세스 Draco 실험 모드 도입

이 설계는 현재 Python 구현에 즉시 적용되며, 향후 멀티프로세스/멀티언어 확장 시 동일한 제어 평면과 텔레메트리 계약을 유지하도록 합니다.
