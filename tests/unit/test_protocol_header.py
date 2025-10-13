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
    FrameType,
    FragmentInfo,
    pack_frame_header,
    unpack_frame_header,
)


def test_pack_unpack_without_fragment():
    header_bytes = pack_frame_header(
        frame_type=FrameType.DATA,
        sequence=42,
        name_len=5,
        payload_len=1024,
    )
    assert len(header_bytes) == HEADER_SIZE
    parsed = unpack_frame_header(header_bytes)
    assert parsed.frame_type is FrameType.DATA
    assert parsed.sequence == 42
    assert parsed.name_len == 5
    assert parsed.payload_len == 1024
    assert parsed.fragment is None


def test_pack_unpack_with_fragment():
    fragment = FragmentInfo(index=1, total=3, frame_payload_len=4096)
    header_bytes = pack_frame_header(
        frame_type=FrameType.DATA,
        sequence=99,
        name_len=0,
        payload_len=512,
        fragment=fragment,
        more_fragments=True,
    )
    assert len(header_bytes) == HEADER_SIZE + FRAGMENT_INFO_SIZE
    parsed = unpack_frame_header(header_bytes)
    assert parsed.frame_type is FrameType.DATA
    assert parsed.sequence == 99
    assert parsed.fragment is not None
    assert parsed.fragment.index == 1
    assert parsed.fragment.total == 3
    assert parsed.fragment.frame_payload_len == 4096
    assert parsed.has_more_fragments


@pytest.mark.parametrize("index,total", [(-1, 2), (2, 2), (0, 0)])
def test_fragment_validation(index: int, total: int) -> None:
    fragment = FragmentInfo(index=index, total=total, frame_payload_len=10)
    with pytest.raises(ValueError):
        fragment.validate()
