# Changelog

## Unreleased
- 스트리밍 클라이언트/서버가 공유하는 상태 머신을 도입하고 EOF 처리 멱등성과 일관된 취소 경로를 확보하여 예외 발생 시 교착 없이 종료되도록 개선했습니다.
- Control-plane alignment & Perf gate: control-plane constants synced with `docs/contracts/control_plane_contract.md`, telemetry gating aligned with `docs/specs/telemetry_schema.md`, and latency regression harness (`tests/perf/test_latency_gate.py`, `scripts/ci/run_perf_gate.sh`) added.
- Runtime stability hardening for the Python streaming stack (session state tracking,
  heartbeat-aware waits, shared-memory cleanup, control-plane retries, and saver
  watchdog).  No breaking changes.
- Test bootstrap harmonised with ROS workspace layout: resolved `tests.*` namespace collisions, documented Pyright/Pylance path requirements, and added runbook coverage for the new workflow (`conftest.py`, `pytest.ini`, docs/*).
- Draco-only upstream pipeline: client now transmits Draco bytes with a binary `DataHeader`, server responds with decoded cloud + metrics (`ResponseHeader`), and client-side quality checks persist JSONL reports and threshold breaches. See `pointcloud_metrics` module, updated CLI flags, and new tests under `tests/unit/test_metrics.py` and `ros2_ws/src/draco_roundtrip/tests/test_roundtrip_quality.py`.
