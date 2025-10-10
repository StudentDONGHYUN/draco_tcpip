# Hybrid Streaming Architecture Progress Checklist

본 체크리스트는 `../designs/async_pipeline_design.md`, `../plans/network_latency_reduction_plan.md`, 그리고 기존 멀티프로세스 파이프라인 설계를 통합한 하이브리드 아키텍처 작업 현황을 추적하기 위해 작성했습니다. 단계별 완료 기준(DoD)을 명확히 하여 미완료 항목을 후속 작업으로 이어갈 수 있도록 합니다.

## Phase 0 — Stability & Determinism
- [x] MSG_EOF 핸드셰이크를 클라이언트↔서버 전 구간에 전파하여 종료 시점의 큐 드레인과 순차 퍼블리시를 보장한다. (DoD: 로그에 `EOF sent/received` 출력, `pending=0` 요약)
- [x] 캡처→인코드→송신→수신→디코드 사이 모든 경계에 유한 큐를 적용하고, 송신 측에는 고정 `max_inflight` 윈도우를 둔다. (DoD: `asyncio.Queue(maxsize=…)`/`PriorityQueue(maxsize=…)` 확인)
- [x] TX/RX를 분리된 루프/스레드로 구성하여 블로킹을 제거하고, 작업자 풀이 에러 시 stop 이벤트로 전파되도록 한다. (DoD: `ReplyPump` 스레드 + `stop_event` 경로)
- [x] 서버 포트 바인딩 시 `reuse_port=True` 시도 후 실패 시 경고 로그와 함께 폴백한다.
- [x] `draco_roundtrip/utils/config.py`의 경로 탐색이 얕은 설치에서도 IndexError 없이 동작하도록 가드 로직을 추가한다.
- [x] 디코드 임시 산출물은 기본적으로 삭제하고, `--keep-artifacts` 플래그로만 유지한다.
- [x] 스테이지별 텔레메트리(큐 길이, 처리 지연, RTT 등)와 종료 요약(p50/p95/p99, 대역폭, pending)을 수집한다.

## Phase 1 — Performance & Backpressure
- [x] RTT/BDP 기반 적응형 `max_inflight` 제어기를 구현하고, 플래그(`--adaptive-window`, `--window-ema-alpha`)로 토글 가능하게 한다. (DoD: `WindowController.observe_ack()` 적용)
- [x] 바이너리 프로토콜에서 데이터/제어 채널을 분리하여 ACK/오류/EOF를 제어 평면으로 라우팅한다. (DoD: `encode_frame_address(channel=…)`)
- [x] PMTU/소켓 버퍼 튜닝과 조각 전송 정책을 플래그로 노출한다. (DoD: 바이너리 프로토콜이 1400B 단편 전송으로 MTU를 보호하고, `--heartbeat-interval/--heartbeat-timeout`으로 혼잡 감지를 노출한다. TODO: `--tx-fragment-size`, `--socket-buffer-autotune` 플래그로 사용자 제어 확대)
- [ ] 회귀 벤치마크 하네스(rosbag 기반)와 CI 게이트에서 p95 지연 임계값을 검증한다. (TODO: `tests/perf/` 추가 및 CI 워크플로 업데이트)

## Phase 2 — Experimental Transports & Loss Resilience
- [ ] `--transport=quic|udp_fec` 실험 모드를 추가하고, 손실/지터 시나리오 스크립트를 제공한다.
- [ ] 제로-카피 경로 커버리지를 늘리기 위한 In-process Draco 준비(메모리 버퍼 전달)를 진행한다.

## Phase 3 — Future Enhancements
- [ ] `rclcpp` + Asio 기반 고성능 경로를 설계하고 Python 래퍼를 유지한다.
- [ ] In-process Draco 인코더/디코더와의 통합을 위한 API 호환 계층을 마련한다.
- [ ] Python 도구군이 신규 파이프라인과 호환되도록 마이그레이션 레이어/문서화를 완성한다.

## Follow-up Notes
- Phase 1 미완료 항목부터 우선 처리하며, 관련 설계/테스트 문서를 `docs/` 하위에 추가 예정입니다.
- 각 단계 완료 시 본 체크리스트를 업데이트하고 PR/커밋 링크를 주석으로 남겨 추적성을 확보합니다.
