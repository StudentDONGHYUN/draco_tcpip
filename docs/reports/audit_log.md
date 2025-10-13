# Audit Log

Last updated: 2025-02-14

## Summary

| Status | Identifier | Location | Details |
| ------ | ---------- | -------- | ------- |
| ✅ Fixed | PYTEST-0001 | `tests/perf/test_latency_gate.py` et al. | `ModuleNotFoundError: No module named 'tests.perf'` during collection. Root cause: the ROS 2 workspace (`ros2_ws/src`) was injected ahead of the repository root in `sys.path`, so Python resolved `tests.*` against `ros2_ws/src/draco_roundtrip/tests`. Pytest then failed to locate the helper packages that live under the repository-level `tests/`. Fix: normalise import bootstrap to prioritise the repository root, explicitly materialise the local `tests` package in `conftest.py`, and restrict pytest discovery to the intended suite via `pytest.ini`. |
| ✅ Fixed | PYTEST-0002 | `tests/unit/test_protocol_header.py` et al. | `ModuleNotFoundError: No module named 'draco_roundtrip.draco_roundtrip'` after addressing PYTEST-0001. Cause: the ROS 2 package was no longer automatically on the path once the local `tests` package had been materialised manually. Fix: ensure the ROS 2 workspace source tree is appended to `sys.path` when the repository-level `conftest.py` loads. |

## Test Evidence

* `pytest` (passes) — see 【030c7d†L1-L16】.
