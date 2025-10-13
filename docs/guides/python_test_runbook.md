# Python Test Runbook

This runbook explains how to execute and troubleshoot the Python-only verification suite that guards the Draco TCP/IP streaming stack.

## 1. Prerequisites
- Python 3.11 (matching the ROS 2 Foxy developer image).
- Virtual environment activated with project requirements installed (`pip install -r requirements.txt`, if present).
- ROS 2 workspace checked out under `ros2_ws/` (already present in this repository).

## 2. Running the Test Matrix
1. **Unit & protocol guards**
   ```bash
   pytest
   ```
   - The `pytest.ini` in the repository root constrains discovery to `tests/`, ensuring deterministic collection.
   - Expect `14 passed, 1 skipped` in ~0.1 s on a development laptop.
2. **Focused suites**
   ```bash
   pytest tests/unit/test_protocol_header.py::test_header_round_trip
   pytest tests/perf/test_latency_gate.py
   ```

## 3. Debug & Trace Modes
- Set `PYTHONASYNCIODEBUG=1` to surface coroutine scheduling issues.
- Export `DRACO_TCPIP_LOG_LEVEL=DEBUG` to increase structured log verbosity inside stream utilities.

## 4. Simulating Network Pathologies
- Leverage the canned netem profiles under `configs/netem.profiles.yaml` with the existing shell tooling:
  ```bash
  scripts/netem/apply_profile.sh configs/netem.profiles.yaml loss_burst
  ```
- Re-run `pytest` to confirm graceful handling under induced loss.

## 5. Interpreting Results
- **Success**: All tests green, latency guard below threshold, no unexpected warnings.
- **Failure**: Inspect stack trace. The meta-path importer registered in `conftest.py` ensures `tests.*` helpers resolve correctly; import errors now indicate missing files, not path skew.
- **Cleanup**: `scripts/netem/clear.sh` resets the loopback shaping rules.
