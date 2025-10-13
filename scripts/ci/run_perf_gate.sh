#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export PYTHONPATH="$ROOT_DIR/ros2_ws/src:${PYTHONPATH:-}"
cd "$ROOT_DIR"

pytest -q tests/unit/test_telemetry_minimal.py
pytest -q tests/perf/test_latency_gate.py
