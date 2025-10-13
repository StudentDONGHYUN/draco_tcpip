import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / 'ros2_ws' / 'src'
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import tests
from draco_roundtrip.draco_roundtrip.utils.stream_protocol import FrameFragment, iter_fragments


def test_iter_fragments_no_fragmentation():
    payload = b"hello world"
    fragments = list(iter_fragments(payload, sequence=7, fragment_size=0))
    assert len(fragments) == 1
    fragment = fragments[0]
    assert fragment.sequence == 7
    assert fragment.payload == payload
    assert fragment.total == 1
    assert fragment.frame_payload_len == len(payload)


def test_iter_fragments_fragmented_reassembles():
    payload = b"abcdefghijklmnopqrstuvwxyz" * 20
    fragments = list(iter_fragments(payload, sequence=2, fragment_size=300))
    assert len(fragments) > 1
    assembled: list[bytes] = [b"" for _ in range(len(fragments))]
    received = 0
    for fragment in fragments:
        assembled[fragment.index] = fragment.payload
        received += len(fragment.payload)
        if fragment.more_fragments:
            assert received < len(payload)
    assert b"".join(assembled) == payload
