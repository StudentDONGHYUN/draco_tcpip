from __future__ import annotations

import json
from pathlib import Path

from tests.perf.utils import load_latency_threshold

CLIENT_TELEMETRY = Path("artifacts/perf/client_latest.json")


def test_latency_p95_gate() -> None:
    threshold = load_latency_threshold()
    if not CLIENT_TELEMETRY.exists():
        raise AssertionError(f"Telemetry file missing: {CLIENT_TELEMETRY}")
    payload = json.loads(CLIENT_TELEMETRY.read_text(encoding="utf-8"))
    latency = payload.get("metrics", {}).get("latency_ms", {})
    p95 = float(latency.get("p95", float("inf")))
    assert p95 < threshold, f"p95 latency {p95}ms exceeds threshold {threshold}ms"
