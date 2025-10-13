import asyncio
from types import SimpleNamespace

import pytest

pytest.importorskip("numpy")

from draco_roundtrip.draco_roundtrip.nodes.stream_client import (
    AckTimeoutPolicy,
    EncodedFrame,
    HeartbeatWatch,
    SessionTracker,
    TrafficStats,
    WindowController,
    network_sender,
)
from draco_roundtrip.draco_roundtrip.utils.stream_protocol import (
    DataHeader,
    ControlPlane,
)


class _StubHandle:
    def __init__(self, name: str) -> None:
        self.name = name

    def on_consumed(self) -> None:  # pragma: no cover - interface stub
        return None

    def on_aborted(self) -> None:  # pragma: no cover - interface stub
        return None


class _RecordingProtocol:
    def __init__(self) -> None:
        self.sent_sequences: list[int | None] = []

    def send(self, _sock, message) -> None:  # pragma: no cover - exercised in thread
        self.sent_sequences.append(message.sequence)


@pytest.mark.asyncio
async def test_network_sender_respects_window_limit():
    network_queue: asyncio.Queue = asyncio.Queue()
    inflight: dict[int, SimpleNamespace] = {}
    acks_pending: set[int] = set()
    inflight_condition = asyncio.Condition()
    stop_event = asyncio.Event()

    stats = SimpleNamespace(encode_to_send=SimpleNamespace(record=lambda value: None))
    traffic = TrafficStats()
    window = WindowController(base_limit=4, max_limit=4, adaptive=False)
    session = SessionTracker()
    heartbeat_watch = HeartbeatWatch()
    control_plane = ControlPlane(role="client")
    ack_policy = AckTimeoutPolicy(base=0.5, minimum=0.5, maximum=2.0)
    protocol = _RecordingProtocol()

    for seq in range(8):
        header = DataHeader(
            kind=0, sequence=seq, timestamp_ns=0, payload_len=1, content_type=0
        )
        frame = EncodedFrame(
            sequence=seq,
            handle=_StubHandle(f"frame{seq}"),
            payload=b"x",
            header=header,
            captured_at=0.0,
            encoded_at=0.0,
            encode_ms=0.0,
        )
        await network_queue.put(frame)
    await network_queue.put(None)

    async def release_ack(sequence: int, delay: float) -> None:
        await asyncio.sleep(delay)
        while not stop_event.is_set():
            async with inflight_condition:
                if sequence in acks_pending:
                    acks_pending.discard(sequence)
                    inflight_condition.notify_all()
                    try:
                        control_plane.on_ack(sequence)
                    except Exception:  # pragma: no cover - best effort cleanup
                        pass
                    break
            await asyncio.sleep(0.01)

    ack_tasks = [
        asyncio.create_task(release_ack(idx, delay))
        for idx, delay in enumerate([0.01, 0.02, 0.03, 0.04, 0.25, 0.3, 0.35, 0.4])
    ]

    await network_sender(
        object(),
        protocol,
        network_queue,
        inflight,
        acks_pending,
        stats=stats,
        traffic=traffic,
        stop_event=stop_event,
        inflight_condition=inflight_condition,
        encode_workers=1,
        window=window,
        session=session,
        heartbeat_watch=heartbeat_watch,
        heartbeat_timeout=5.0,
        control=None,
        fragment_size=0,
        use_binary=False,
        control_plane=control_plane,
        ack_policy=ack_policy,
    )

    for task in ack_tasks:
        task.cancel()
    await asyncio.gather(*ack_tasks, return_exceptions=True)

    assert traffic.inflight_peak <= 4
    assert len([seq for seq in protocol.sent_sequences if seq is not None]) == 8
