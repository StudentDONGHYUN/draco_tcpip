# Pytest Import Audit (2025-10-13)

## Summary of Failures
- **Pytest collection aborted** with `ModuleNotFoundError: No module named 'tests.unit'` when executing `pytest` from the repository root.
  - **Root Cause**: Pytest manipulates `sys.path` during collection, prioritising per-test directories (e.g., `tests/unit`). This removed the repository root from the import search order, so the top-level `tests` package (which houses helper utilities and namespace initialisers) was not discoverable. The collection process failed before any tests executed.
  - **Impact**: All unit, property, and perf guard tests were skipped, preventing regression coverage and blocking CI.

## Fix Plan
1. **Stabilise package resolution (`A-1`)**
   - Install a deterministic meta-path finder that always resolves modules under the in-repo `tests` package, regardless of how pytest mutates `sys.path`.
   - Ensure ROS 2 source tree helpers remain importable by re-asserting the `ros2_ws/src` path.
   - ✅ Guarded by existing unit suites that now execute end-to-end (see `tests/unit/test_protocol_header.py`).
2. **Pin pytest discovery scope (`A-2`)**
   - Limit `pytest` collection to the curated `tests/` tree so auxiliary ROS 2 integration suites are not double-imported during Python-only runs.
   - ✅ Validated by `pytest` run after the fix (see Testing section below).

## Verification
- `pytest` (Python-only suite) now executes 14 tests with 1 expected skip in 0.11s.
