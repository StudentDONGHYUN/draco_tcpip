from __future__ import annotations

import json
import time
from pathlib import Path

from draco_roundtrip.utils.stream_protocol import ControlPlane
from draco_roundtrip.utils.telemetry import Telemetry


def test_minimal_telemetry_export(tmp_path: Path) -> None:
    telemetry = Telemetry(
        role="client",
        transport="tcp",
        protocol="binary",
        fragment_size=512,
        socket_buffer_autotune=False,
    )
    control = ControlPlane(role="client")
    now_ns = time.monotonic_ns()
    control.on_connected(now_ns)
    control.on_first_data()
    control.on_frame_sent(1, now_ns=now_ns)
    control.on_ack(1)
    control.on_eof_sent()
    control.on_eof_received()
    control.on_shutdown()

    metrics = {
        "latency_ms": {"p50": 12.5, "p95": 18.2, "p99": 21.7},
        "rtt_ms": {"p50": 20.0, "p95": 25.0, "p99": 30.0},
        "ack_latency_ms": {"p50": 5.0, "p95": 7.0, "p99": 9.0},
        "throughput_mbps": {"avg": 12.0, "peak": 20.0},
        "queues": {"capture_max": 2, "encode_max": 1, "decode_max": 0, "pending": 0},
        "frames": {"sent": 1, "acked": 1, "dropped": 0, "skipped": 0},
    }

    payload = telemetry.build(control_plane=control, metrics=metrics, inflight_pending=0)
    telemetry.validate(payload)

    output = tmp_path / "telemetry.json"
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    assert output.exists()
