import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "ros2_ws" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import tests  # noqa: F401
import pytest

from draco_roundtrip.draco_roundtrip.utils import stream_protocol


def test_legacy_request_payload_round_trip():
    payload = b"draco-bytes"
    buffer = struct.pack(
        "!BIQIB",
        stream_protocol.DATA_KIND_DRACO,
        42,
        123456789,
        len(payload),
        stream_protocol.CONTENT_TYPE_DRACO,
    ) + payload
    sequence, timestamp_ns, content_type, parsed_payload = (
        stream_protocol.parse_legacy_request_payload(buffer)
    )
    assert parsed_payload == payload
    assert sequence == 42
    assert timestamp_ns == 123456789
    assert content_type == stream_protocol.CONTENT_TYPE_DRACO


def test_response_header_round_trip():
    metrics = {"point_count": 10, "extra": {"impl": "test", "notes": ""}}
    metrics_bytes = json.dumps(metrics).encode("utf-8")
    decoded = b"ply-bytes"
    header, packed = stream_protocol.compose_response_payload(
        sequence=7,
        timestamp_ns=999,
        decoded_payload=decoded,
        metrics_json=metrics_bytes,
        decode_ms=12.3,
    )
    parsed_header, decoded_payload, parsed_metrics = stream_protocol.parse_response_payload(packed)
    assert decoded_payload == decoded
    assert parsed_metrics == metrics_bytes
    assert parsed_header.sequence == 7
    assert parsed_header.decode_ms == pytest.approx(header.decode_ms)
    assert parsed_header.metrics_len == len(metrics_bytes)
