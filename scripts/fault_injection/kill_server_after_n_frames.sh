#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <frame-count> [server-args...]" >&2
  echo "Example: $0 20 --port 5000" >&2
  exit 64
fi

FRAME_TARGET=$1
shift || true

trap '[[ -n "${SERVER_PID:-}" ]] && kill "$SERVER_PID" 2>/dev/null || true' EXIT

ros2 run draco_roundtrip stream_server "$@" &
SERVER_PID=$!
echo "[fault-injection] stream_server started with PID ${SERVER_PID}"

export FRAME_TARGET
export SERVER_PID

python - <<'PY'
import json
import os
import signal
import sys

target = int(os.environ.get("FRAME_TARGET", "0"))
pid = int(os.environ.get("SERVER_PID", "0"))
count = 0
try:
    for line in sys.stdin:
        if line.startswith("[CLIENT][TELEM] recv_data"):
            count += 1
            if count >= target:
                print(f"[fault-injection] Reached {count} frames, killing server PID {pid}")
                os.kill(pid, signal.SIGTERM)
                break
except KeyboardInterrupt:
    pass
PY
