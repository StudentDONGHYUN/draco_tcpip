# Changelog

## Unreleased
- Control-plane alignment & Perf gate: control-plane constants synced with `docs/contracts/control_plane_contract.md`, telemetry gating aligned with `docs/specs/telemetry_schema.md`, and latency regression harness (`tests/perf/test_latency_gate.py`, `scripts/ci/run_perf_gate.sh`) added.
- Runtime stability hardening for the Python streaming stack (session state tracking,
  heartbeat-aware waits, shared-memory cleanup, control-plane retries, and saver
  watchdog).  No breaking changes.
- Fix: Restored deterministic pytest collection by installing an in-repo `tests`
  meta-path finder and constraining discovery to `tests/`, unblocking the Python
  regression suite.
