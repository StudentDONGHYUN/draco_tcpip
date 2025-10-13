import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / 'ros2_ws' / 'src'
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import tests
import pytest

from draco_roundtrip.draco_roundtrip.protocol.header import (
    FRAGMENT_INFO_SIZE,
    HEADER_SIZE,
    LEGACY_HEADER_SIZE,
    LEGACY_VERSION,
    VERSION,
    FrameHeader,
    FrameType,
    FragmentInfo,
    HeaderError,
    FLAG_MORE_FRAGMENTS,
)


def test_frame_header_v2_round_trip() -> None:
    fragment = FragmentInfo(index=1, total=3, frame_payload_len=4096)
    header = FrameHeader(
        frame_type=FrameType.DATA,
        sequence=42,
        name_len=5,
        payload_len=1024,
        timestamp_ns=123456789,
        content_type=0x20,
        flags=FLAG_MORE_FRAGMENTS,
        fragment=fragment,
    )
    payload = header.to_bytes()
    assert len(payload) == HEADER_SIZE + FRAGMENT_INFO_SIZE
    parsed = FrameHeader.from_bytes(payload)
    assert parsed.version == VERSION
    assert parsed.frame_type is FrameType.DATA
    assert parsed.sequence == 42
    assert parsed.timestamp_ns == 123456789
    assert parsed.content_type == 0x20
    assert parsed.fragment is not None
    assert parsed.fragment.index == 1
    assert parsed.fragment.total == 3
    assert parsed.fragment.frame_payload_len == 4096
    assert parsed.has_more_fragments


def test_frame_header_invalid_magic() -> None:
    header = FrameHeader(
        frame_type=FrameType.ACK,
        sequence=7,
        name_len=0,
        payload_len=0,
        timestamp_ns=0,
        content_type=0,
        flags=0,
    )
    payload = bytearray(header.to_bytes())
    payload[0:4] = b"BADD"
    with pytest.raises(HeaderError):
        FrameHeader.from_bytes(bytes(payload))


def test_frame_header_legacy_requires_opt_in() -> None:
    header = FrameHeader(
        frame_type=FrameType.DATA,
        sequence=99,
        name_len=2,
        payload_len=10,
        timestamp_ns=0,
        content_type=0,
        flags=0,
        version=LEGACY_VERSION,
    )
    payload = header.to_bytes()
    assert len(payload) == LEGACY_HEADER_SIZE
    with pytest.raises(HeaderError):
        FrameHeader.from_bytes(payload)
    parsed = FrameHeader.from_bytes(payload, allow_legacy=True)
    assert parsed.version == LEGACY_VERSION
    assert parsed.timestamp_ns == 0
    assert parsed.content_type == 0


@pytest.mark.parametrize("index,total", [(-1, 2), (2, 2), (0, 0)])
def test_fragment_validation(index: int, total: int) -> None:
    fragment = FragmentInfo(index=index, total=total, frame_payload_len=10)
    with pytest.raises(ValueError):
        fragment.validate()
