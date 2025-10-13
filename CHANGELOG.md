# Changelog

## Unreleased
- 스트리밍 클라이언트/서버 파이프라인 큐를 소형 고정 크기로 제한하고 공용 취소 신호에 응답하도록 조정했습니다. `--queue-size`
  플래그를 통해 서버 디코드/송신 큐 깊이를 구성할 수 있으며, 관련 단위·통합 테스트가 추가되었습니다.
- ACK 타임아웃을 최소 힙 스케줄러로 전환하여 폴링 없이 만료를 감지하고, 해당 보조 유틸리티와 단위 테스트를 추가했습니다.
- 스트리밍 클라이언트/서버가 공유하는 상태 머신을 도입하고 EOF 처리 멱등성과 일관된 취소 경로를 확보하여 예외 발생 시 교착 없이 종료되도록 개선했습니다.
- Control-plane alignment & Perf gate: control-plane constants synced with `docs/contracts/control_plane_contract.md`, telemetry gating aligned with `docs/specs/telemetry_schema.md`, and latency regression harness (`tests/perf/test_latency_gate.py`, `scripts/ci/run_perf_gate.sh`) added.
- Runtime stability hardening for the Python streaming stack (session state tracking,
  heartbeat-aware waits, shared-memory cleanup, control-plane retries, and saver
  watchdog).  No breaking changes.
- Test bootstrap harmonised with ROS workspace layout: resolved `tests.*` namespace collisions, documented Pyright/Pylance path requirements, and added runbook coverage for the new workflow (`conftest.py`, `pytest.ini`, docs/*).
- Draco-only upstream pipeline: client now transmits Draco bytes with a binary `DataHeader`, server responds with decoded cloud + metrics (`ResponseHeader`), and client-side quality checks persist JSONL reports and threshold breaches. See `pointcloud_metrics` module, updated CLI flags, and new tests under `tests/unit/test_metrics.py` and `ros2_ws/src/draco_roundtrip/tests/test_roundtrip_quality.py`.
