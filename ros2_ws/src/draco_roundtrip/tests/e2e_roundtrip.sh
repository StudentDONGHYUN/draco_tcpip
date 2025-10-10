#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

if ! command -v pytest >/dev/null 2>&1; then
  echo "pytest is required to run the roundtrip regression" >&2
  exit 2
fi

export PYTHONPATH="${SRC_ROOT}:${PYTHONPATH:-}"

if ! python - <<'PY' >/dev/null 2>&1
import importlib
import sys

try:
    importlib.import_module("numpy")
except ModuleNotFoundError:
    sys.exit(1)
PY
then
  echo "[WARN] numpy not available; skipping roundtrip regression." >&2
  exit 0
fi

pytest -q "${SCRIPT_DIR}/test_e2e_roundtrip.py" "$@"
