import pytest

pytest.importorskip("numpy")

from draco_roundtrip.draco_roundtrip.nodes.stream_server import (
    FragmentBuffer,
    FragmentDrop,
)


def test_fragment_buffer_ttl_eviction() -> None:
    buffer = FragmentBuffer(ttl=1.0, max_bytes=1024)
    complete, assembled, drops = buffer.add(
        sequence=1,
        name="frame",
        total=2,
        expected_len=None,
        index=0,
        payload=b"abc",
        now=0.0,
    )
    assert not complete
    assert assembled is None
    assert drops == []

    drops = buffer.gc(now=1.5)
    assert len(drops) == 1
    drop = drops[0]
    assert isinstance(drop, FragmentDrop)
    assert drop.sequence == 1
    assert drop.reason == "ttl"
    assert drop.state.name == "frame"
    assert buffer.states == {}
    assert buffer.buffered_bytes == 0


def test_fragment_buffer_memory_cap() -> None:
    buffer = FragmentBuffer(ttl=10.0, max_bytes=5)
    complete, assembled, drops = buffer.add(
        sequence=1,
        name="frame-a",
        total=2,
        expected_len=None,
        index=0,
        payload=b"1234",
        now=0.0,
    )
    assert not complete
    assert assembled is None
    assert drops == []

    complete, assembled, drops = buffer.add(
        sequence=2,
        name="frame-b",
        total=1,
        expected_len=None,
        index=0,
        payload=b"xx",
        now=0.1,
    )
    assert not complete
    assert assembled is None
    assert drops and drops[0].sequence == 1
    assert drops[0].reason == "buffer-limit"
    assert buffer.states.keys() == {2}
    assert buffer.buffered_bytes <= buffer.max_bytes

    shutdown_drops = buffer.clear()
    assert len(shutdown_drops) == 1
    assert shutdown_drops[0].sequence == 2
    assert shutdown_drops[0].reason == "shutdown"
    assert buffer.states == {}
    assert buffer.buffered_bytes == 0
