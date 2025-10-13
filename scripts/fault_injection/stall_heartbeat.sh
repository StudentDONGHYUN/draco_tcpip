#!/usr/bin/env bash
set -euo pipefail

cat <<'MSG'
This helper demonstrates a heartbeat stall scenario.

1. Launch the server normally:
   ros2 run draco_roundtrip stream_server --heartbeat-interval 2.0

2. Run the client with an aggressive timeout while piping stdout through this script
   so the kill helper can react to the JSON summary:
   ros2 run draco_roundtrip stream_client --heartbeat-timeout 3.0 --max-frames 100 |
       python - <<'PY'
import json
import sys

for line in sys.stdin:
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        continue
    if payload.get('session_state') == 'degraded':
        print('[fault-injection] Heartbeat timeout observed; client degraded as expected.')
        break
PY

3. While the client is running, pause the control-plane port using netem, e.g.:
   sudo tc qdisc add dev lo root netem delay 2000ms 200ms distribution normal
   # let the client detect the stall, then restore the network
   sudo tc qdisc del dev lo root netem
MSG
