import asyncio
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

np = pytest.importorskip("numpy")

from draco_roundtrip.draco_roundtrip.nodes import stream_client, stream_server
from draco_roundtrip.draco_roundtrip.nodes.stream_client import (
    AckTimeoutPolicy,
    EncodedFrame,
    HeartbeatWatch,
    SessionTracker,
    TrafficStats,
    WindowController,
    _put_with_retry,
)
from draco_roundtrip.draco_roundtrip.nodes.stream_server import (
    ControlPlane,
    DecodeJob,
    PipelineStats,
    StreamState,
    StreamStateMachine,
    _queue_put as server_queue_put,  # type: ignore[attr-defined]
)
from draco_roundtrip.draco_roundtrip.utils.stream_protocol import (
    ControlPlane as ProtocolControlPlane,
    ControlState,
    DataHeader,
)
from draco_roundtrip.draco_roundtrip.common.timers import AckDeadlineHeap


class TrackingQueue(asyncio.Queue):
    def __init__(self, maxsize: int) -> None:
        super().__init__(maxsize)
        self.max_depth = 0

    async def put(self, item) -> None:  # type: ignore[override]
        await super().put(item)
        self.max_depth = max(self.max_depth, self.qsize())


@pytest.mark.asyncio
async def test_queue_put_blocks_until_space(monkeypatch):
    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=1)
    await queue.put("initial")
    stop_event = asyncio.Event()

    started = asyncio.Event()

    async def producer() -> bool:
        started.set()
        return await _put_with_retry(
            queue, "second", stop_event=stop_event, timeout=0.05
        )

    task = asyncio.create_task(producer())
    await started.wait()
    await asyncio.sleep(0.1)
    assert not task.done()
    assert queue.get_nowait() == "initial"
    queue.task_done()
    await asyncio.sleep(0)
    assert await task


@pytest.mark.asyncio
async def test_queue_put_cancels_with_stop_event():
    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=1)
    await queue.put("initial")
    stop_event = asyncio.Event()
    task = asyncio.create_task(
        _put_with_retry(queue, "second", stop_event=stop_event, timeout=0.05)
    )
    await asyncio.sleep(0.05)
    stop_event.set()
    assert not await task


@pytest.mark.asyncio
async def test_client_network_sender_queue_bound(monkeypatch):
    class DummyHandle:
        def __init__(self, name: str) -> None:
            self.name = name

        def on_consumed(self) -> None:
            return None

        def on_aborted(self) -> None:
            return None

        def load_source_points(self):  # pragma: no cover - not exercised
            raise NotImplementedError

    queue_size = 2
    network_queue = TrackingQueue(queue_size)
    inflight: dict[int, stream_client.FrameContext] = {}
    acks_pending: set[int] = set()
    inflight_condition = asyncio.Condition()
    stop_event = asyncio.Event()

    stats = SimpleNamespace(encode_to_send=SimpleNamespace(record=lambda _: None))
    traffic = TrafficStats()
    window = WindowController(
        base_limit=queue_size, max_limit=queue_size, adaptive=False
    )
    session = SessionTracker()
    heartbeat_watch = HeartbeatWatch()
    control_plane = ProtocolControlPlane(role="client")
    ack_policy = AckTimeoutPolicy(base=0.5, minimum=0.5, maximum=2.0)
    ack_deadlines = AckDeadlineHeap()
    ack_deadline_event = asyncio.Event()
    lifecycle = StreamStateMachine(role="client")

    class SlowProtocol:
        def __init__(self) -> None:
            self.sent: list[int | None] = []

        def send(self, _sock, message) -> None:
            time.sleep(0.02)
            self.sent.append(message.sequence)

    protocol = SlowProtocol()

    async def release_ack(sequence: int, delay: float) -> None:
        await asyncio.sleep(delay)
        async with inflight_condition:
            if sequence in acks_pending:
                acks_pending.discard(sequence)
                inflight_condition.notify_all()
                control_plane.on_ack(sequence)

    ack_tasks = [
        asyncio.create_task(release_ack(idx, 0.05 + idx * 0.02)) for idx in range(4)
    ]

    async def produce() -> None:
        for seq in range(4):
            header = DataHeader(
                kind=0, sequence=seq, timestamp_ns=0, payload_len=1, content_type=0
            )
            frame = EncodedFrame(
                sequence=seq,
                handle=DummyHandle(f"frame{seq}"),
                payload=b"x",
                header=header,
                captured_at=0.0,
                encoded_at=0.0,
                encode_ms=0.0,
            )
            await _put_with_retry(
                network_queue, frame, stop_event=stop_event, timeout=0.05
            )
        await _put_with_retry(network_queue, None, stop_event=stop_event, timeout=0.05)

    sender = asyncio.create_task(
        stream_client.network_sender(
            object(),
            protocol,
            network_queue,
            inflight,
            acks_pending,
            ack_deadlines,
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
            ack_deadline_event=ack_deadline_event,
            lifecycle=lifecycle,
        )
    )
    await produce()
    await sender

    for task in ack_tasks:
        task.cancel()
    await asyncio.gather(*ack_tasks, return_exceptions=True)

    assert traffic.network_depth_peak <= queue_size
    assert network_queue.max_depth <= queue_size
    assert len(protocol.sent) >= 4


@pytest.mark.asyncio
async def test_server_pipeline_bounded_shutdown(monkeypatch, tmp_path):
    queue_size = 2

    decode_queue: TrackingQueue = TrackingQueue(queue_size)
    send_queue: TrackingQueue = TrackingQueue(queue_size)
    stop_event = asyncio.Event()
    producer_done = asyncio.Event()
    stats = PipelineStats()
    totals = {"bytes_in": 0, "bytes_out": 0}
    control_plane = ControlPlane(role="server")
    lifecycle = StreamStateMachine(role="server")
    lifecycle.transition(StreamState.HANDSHAKING, reason="test")

    def fake_decode_drc(
        _decoder,
        drc_bytes: bytes,
        _out_dir: Path,
        stem: str,
        *,
        timeout: float | None = None,
        keep_artifacts: bool = False,
        zero_copy: bool = False,
        resp_format: str = "ply",
        metrics_sample: int | None = None,
        frame_id: str | None = None,
        draco_bytes_len: int | None = None,
        timestamp_ns: int | None = None,
        encode_ms: float | None = None,
    ):
        del (
            timeout,
            keep_artifacts,
            zero_copy,
            resp_format,
            metrics_sample,
            frame_id,
            encode_ms,
        )
        time.sleep(0.01)
        points = np.zeros((1, 3), dtype=np.float32)
        metrics = {"extra": {}}
        return stream_server.DecodedArtifact(
            payload=b"decoded",
            points=points,
            metrics=metrics,
            timestamp_ns=timestamp_ns or time.monotonic_ns(),
            draco_bytes=draco_bytes_len or len(drc_bytes),
            decode_ms=0.0,
            cleanup=lambda: None,
        )

    async def fake_send_control_message(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(stream_server, "decode_drc", fake_decode_drc)
    monkeypatch.setattr(
        stream_server, "_send_control_message", fake_send_control_message
    )

    args = SimpleNamespace(
        decode_timeout=1.0,
        keep_artifacts=False,
        zero_copy_reply=False,
        resp_format="ply",
        metrics_sample=None,
    )
    decoder = Path(tmp_path / "decoder")
    work_dir = tmp_path

    class SlowProtocol:
        def __init__(self) -> None:
            self.sent: list[int | None] = []

        def send(self, _sock, message) -> None:
            time.sleep(0.01)
            self.sent.append(message.sequence)

    decode_task = asyncio.create_task(
        stream_server._decode_worker(
            0,
            args,
            decoder,
            work_dir,
            decode_queue,
            send_queue,
            stats,
            stop_event,
        )
    )
    send_task = asyncio.create_task(
        stream_server._send_loop(
            SlowProtocol(),
            object(),
            None,
            send_queue,
            stats,
            totals,
            stop_event,
            producer_done,
            worker_count=1,
            control_plane=control_plane,
            lifecycle=lifecycle,
            resp_format="ply",
        )
    )

    for seq in range(3):
        job = DecodeJob(
            sequence=seq,
            name=f"frame{seq}",
            payload=b"input",
            received_at=time.monotonic(),
            frame_payload_len=5,
            fragments=1,
        )
        await server_queue_put(decode_queue, job, stop_event=stop_event)
    producer_done.set()
    await server_queue_put(decode_queue, None, stop_event=stop_event)

    await decode_queue.join()
    await send_queue.join()
    stop_event.set()
    await asyncio.gather(decode_task, send_task)

    assert decode_queue.max_depth <= queue_size
    assert send_queue.max_depth <= queue_size
    assert lifecycle.state in (StreamState.DRAINING, StreamState.TERMINATED)
    assert control_plane.state in (
        ControlState.DRAINING,
        ControlState.TERMINATED,
        ControlState.FAILED,
    )
