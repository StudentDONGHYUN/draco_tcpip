import asyncio
import itertools
import json
import queue
import socket
import threading
from pathlib import Path

import pytest

pytest.importorskip("numpy")

from draco_roundtrip.protocol import (
    FLAGS_FRAGMENTED,
    FLAGS_FRAGMENT_END,
    FLAGS_FRAGMENT_START,
    FragmentMetadata,
    HeaderType,
    HEADER_SIZE,
    METADATA_SIZE,
    iter_fragment_payloads,
    pack_header,
    pack_metadata,
    recv_exact,
    unpack_header,
    unpack_metadata,
)
from draco_roundtrip.nodes.stream_client import (
    FrameContext,
    HeartbeatWatch,
    PipelineStats,
    ReplyEvent,
    SessionTracker,
    TrafficStats,
    WindowController,
    reply_consumer,
)
from draco_roundtrip.utils.protocol import (
    MSG_ACK,
    MSG_DATA,
    MSG_ERROR,
    MSG_HEARTBEAT,
    Message,
    resolve_protocol,
)
from draco_roundtrip.utils.stream_protocol import (
    CONTROL_CHANNEL,
    DATA_CHANNEL,
    ControlPlane,
    encode_frame_address,
)


class DummyHandle:
    def __init__(self, name: str) -> None:
        self.name = name
        self.aborted = False

    def ensure_encoder_input(self, work_dir: Path) -> Path:  # pragma: no cover - unused
        return work_dir / f"{self.name}.ply"

    def load_source_points(self):  # pragma: no cover - unused
        raise RuntimeError("not implemented")

    def load_source_points_from_bytes(self, payload):  # pragma: no cover - unused
        raise RuntimeError("not implemented")

    def priority_hint(self) -> float:  # pragma: no cover - unused
        return 0.0

    def on_consumed(self) -> None:  # pragma: no cover - unused
        pass

    def on_aborted(self) -> None:
        self.aborted = True


def test_header_roundtrip() -> None:
    header_bytes = pack_header(
        flags=FLAGS_FRAGMENT_START | FLAGS_FRAGMENTED,
        msg_type=HeaderType.DATA,
        sequence=42,
        name_length=5,
        payload_length=1024,
    )
    header = unpack_header(header_bytes)
    assert header.flags & FLAGS_FRAGMENT_START
    assert header.is_fragmented()
    assert header.sequence == 42
    assert header.payload_length == 1024
    assert header.name_length == 5


def test_header_bad_magic() -> None:
    bogus = b"BADC" + b"\x00" * (HEADER_SIZE - 4)
    with pytest.raises(ValueError):
        unpack_header(bogus)


def test_recv_exact_partial_reads() -> None:
    left, right = socket.socketpair()
    data = b"hello-world"

    def writer() -> None:
        try:
            for chunk in (b"he", b"llo", b"-world"):
                right.sendall(chunk)
        finally:
            right.close()

    thread = threading.Thread(target=writer)
    thread.start()
    result = recv_exact(left, len(data))
    assert result == data
    thread.join()
    left.close()

    left2, right2 = socket.socketpair()
    right2.sendall(b"short")
    right2.close()
    with pytest.raises(ConnectionError):
        recv_exact(left2, 10)
    left2.close()


def test_fragment_iter_and_reassemble() -> None:
    payload = b"draco" * 100
    fragments = list(iter_fragment_payloads(payload, fragment_size=64))
    assembly = bytearray(len(payload))
    for flags, chunk, meta in fragments:
        assert isinstance(meta, FragmentMetadata)
        assert meta.chunk_length == len(chunk)
        assembly[meta.offset : meta.offset + meta.chunk_length] = chunk
    assert bytes(assembly) == payload
    assert fragments[0][0] & FLAGS_FRAGMENT_START
    assert fragments[-1][0] & FLAGS_FRAGMENT_END


def _send_and_receive(protocol_name: str, message: Message) -> Message:
    protocol = resolve_protocol(protocol_name)
    s1, s2 = socket.socketpair()
    try:
        protocol.send(s1, message)
        received = protocol.recv(s2)
        assert received is not None
        return received
    finally:
        s1.close()
        s2.close()


def test_binary_single_frame_roundtrip() -> None:
    payload = b"\x90draco-bits"
    msg = Message(
        kind=MSG_DATA,
        name=encode_frame_address(7, "frame.drc", channel=DATA_CHANNEL),
        payload=payload,
        sequence=7,
    )
    received = _send_and_receive("binary", msg)
    assert received.payload == payload
    assert received.sequence == 7
    assert received.flags == 0


def test_binary_fragment_reassembly_roundtrip() -> None:
    protocol = resolve_protocol("binary")
    payload = bytes(range(64)) * 8
    fragments = list(iter_fragment_payloads(payload, fragment_size=96))
    s1, s2 = socket.socketpair()
    try:
        for flags, chunk, meta in fragments:
            protocol.send(
                s1,
                Message(
                    kind=MSG_DATA,
                    name=encode_frame_address(12, "scan.drc", channel=DATA_CHANNEL),
                    payload=pack_metadata(meta) + chunk,
                    sequence=12,
                    flags=flags,
                ),
            )
        assembly: dict[int, dict[str, object]] = {}
        reconstructed = bytearray()
        while True:
            message = protocol.recv(s2)
            assert message is not None
            assert message.sequence == 12
            if not (message.flags & FLAGS_FRAGMENTED):
                reconstructed = bytearray(message.payload)
                break
            meta = unpack_metadata(message.payload)
            chunk = message.payload[METADATA_SIZE : METADATA_SIZE + meta.chunk_length]
            bucket = assembly.setdefault(
                12,
                {"buffer": bytearray(meta.total_length), "expected": meta.total_length},
            )
            buffer = bucket["buffer"]
            buffer[meta.offset : meta.offset + meta.chunk_length] = chunk
            if message.flags & FLAGS_FRAGMENT_END:
                reconstructed = buffer
                break
        assert bytes(reconstructed) == payload
    finally:
        s1.close()
        s2.close()


def test_binary_control_frame_sequence() -> None:
    protocol = resolve_protocol("binary")
    s1, s2 = socket.socketpair()
    try:
        control_messages = [
            Message(
                kind=MSG_HEARTBEAT,
                name=encode_frame_address(None, "hb", channel=CONTROL_CHANNEL),
                payload=b"",
            ),
            Message(
                kind=MSG_ACK,
                name=encode_frame_address(3, "frame", channel=CONTROL_CHANNEL),
                payload=json.dumps({"seq": 3}).encode(),
                sequence=3,
            ),
            Message(
                kind=MSG_ERROR,
                name=encode_frame_address(4, "frame", channel=CONTROL_CHANNEL),
                payload=json.dumps({"seq": 4, "msg": "fail"}).encode(),
                sequence=4,
            ),
        ]
        for message in control_messages:
            protocol.send(s1, message)
        received = [protocol.recv(s2) for _ in control_messages]
        assert [m.kind for m in received] == [msg.kind for msg in control_messages]
        assert received[1].sequence == 3
        assert received[2].sequence == 4
    finally:
        s1.close()
        s2.close()


@pytest.mark.asyncio
async def test_reply_consumer_handles_legacy_plaintext_error(tmp_path: Path, capsys) -> None:
    reply_queue: "asyncio.Queue" = asyncio.Queue()
    handle = DummyHandle("frame")
    ctx = FrameContext(
        sequence=1,
        handle=handle,
        captured_at=0.0,
        encoded_at=0.0,
        sent_at=0.0,
        payload_size=10,
    )
    inflight = {1: ctx}
    stats = PipelineStats()
    traffic = TrafficStats()
    stop_event = asyncio.Event()
    inflight_condition = asyncio.Condition()
    window = WindowController(base_limit=1, max_limit=1)
    acks_pending = {1}
    decoded_dir = tmp_path
    to_play: "queue.Queue" = queue.Queue()
    frame_counter = itertools.count()
    session = SessionTracker()
    heartbeat_watch = HeartbeatWatch()
    control_plane = ControlPlane(role="client")
    control_plane.on_connected()

    legacy_error = Message(
        kind=MSG_ERROR,
        name=encode_frame_address(1, "frame", channel=CONTROL_CHANNEL),
        payload=b"decode failed",
        sequence=1,
    )
    await reply_queue.put(
        ReplyEvent(
            kind="message",
            message=legacy_error,
            channel=CONTROL_CHANNEL,
        )
    )
    consumer = asyncio.create_task(
        reply_consumer(
            reply_queue,
            inflight,
            stats=stats,
            traffic=traffic,
            stop_event=stop_event,
            inflight_condition=inflight_condition,
            window=window,
            acks_pending=acks_pending,
            decoded_dir=decoded_dir,
            to_play=to_play,
            play_sample=0,
            frame_counter=frame_counter,
            print_metrics=False,
            heartbeat_timeout=0.0,
            session=session,
            heartbeat_watch=heartbeat_watch,
            control_plane=control_plane,
            use_binary=True,
        )
    )

    await asyncio.sleep(0.1)
    captured = capsys.readouterr()
    assert "legacy plaintext" in captured.out
    assert handle.aborted
    assert stats.error_frames == 1

    stop_event.set()
    await reply_queue.put(ReplyEvent(kind="closed", channel=CONTROL_CHANNEL))
    await asyncio.sleep(0)
    consumer.cancel()
    with pytest.raises(asyncio.CancelledError):
        await consumer

