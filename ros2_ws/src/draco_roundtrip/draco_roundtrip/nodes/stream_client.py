#!/usr/bin/env python3
"""Stream rosbag frames, encode/send to server, replay decoded results to RViz."""

# README NOTE: Runtime flag behaviour is documented in README.md ("Streaming client"):
#   --max-inflight / --capture-queue gate the bounded async pipeline window.
#   --capture-transport toggles shared-memory zero-copy capture vs. filesystem legacy mode.
#   --metrics-out writes pipeline telemetry summaries for latency investigations.

from __future__ import annotations

import argparse
import asyncio
import contextlib
import itertools
import json
import math
import queue
import socket
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field as dataclass_field
from enum import Enum
from multiprocessing import shared_memory
from pathlib import Path
from typing import Callable, Deque, Dict, Iterable, Optional, Protocol

import numpy as np

from draco_tools.core.encoder import (
    add_encoder_arguments,
    encode_frame,
    find_draco_encoder,
    format_encode_log,
    resolve_encoder_options,
)
from draco_roundtrip.analysis import pointcloud_metrics
from draco_roundtrip.utils.config import resolve_data_layout, resolve_qos_override
from draco_roundtrip.io.ply_codec import save_xyz
from draco_roundtrip.utils.ply_io import (
    load_points as load_xyz,
    load_points_from_bytes as load_xyz_from_bytes,
)
from draco_roundtrip.utils.protocol import (
    ConnectionClosed,
    Message,
    MSG_ACK,
    MSG_DATA,
    MSG_EOF,
    MSG_ERROR,
    MSG_HEARTBEAT,
    ProtocolHandler,
    ProtocolError,
    available_protocols,
    resolve_protocol,
)
from draco_roundtrip.shared_memory import SharedMemoryReceiver, SharedMemoryDescriptor
from draco_roundtrip.ros.playback import start_playback_thread
from draco_roundtrip.utils.stream_protocol import (
    ACK_TIMEOUT_NS,
    CONTROL_CHANNEL,
    CONTROL_POLL_INTERVAL,
    ControlPlane,
    ControlPlaneError,
    ControlState,
    DataHeader,
    ResponseHeader,
    DATA_CHANNEL,
    ErrorCode,
    FrameFragment,
    decode_frame_address,
    encode_frame_address,
    iter_fragments,
    validate_fragment_size,
    ACK_PAYLOAD_STRUCT,
    compose_request_payload,
    parse_response_payload,
)
from draco_roundtrip.utils.telemetry import Telemetry, percentiles_block


_capture_ticket = itertools.count()
_sequence_ids = itertools.count()
_CAPTURE_SENTINEL = object()
_ENCODE_SENTINEL = object()


def _telemetry(stage: str, frame: str, **details: object) -> None:
    """Emit lightweight telemetry for per-frame stage transitions."""

    extras = " ".join(f"{key}={value}" for key, value in details.items())
    timestamp = time.monotonic()
    suffix = f" {extras}" if extras else ""
    print(f"[CLIENT][TELEM] {stage} frame={frame} ts={timestamp:.6f}{suffix}")


def _validate_client_config(args: argparse.Namespace) -> int:
    fragment_size = validate_fragment_size(args.tx_fragment_size)
    if fragment_size and args.protocol != "binary":
        raise ValueError("--tx-fragment-size requires --protocol binary")
    if args.socket_buffer_autotune and args.socket_buffer_kb > 0:
        raise ValueError("--socket-buffer-autotune cannot be combined with --socket-buffer-kb")
    if args.transport != "tcp":
        raise NotImplementedError(
            f"transport '{args.transport}' is reserved; only tcp is implemented in Python client"
        )
    return fragment_size


def _log_effective_config(args: argparse.Namespace, fragment_size: int) -> None:
    config_summary = (
        f"transport={args.transport} protocol={args.protocol} "
        f"tx_fragment_size={fragment_size} metrics_out={args.metrics_out} "
        f"socket_buffer_autotune={'on' if args.socket_buffer_autotune else 'off'}"
    )
    print(f"[CLIENT] config: {config_summary}")


async def _put_with_retry(
    queue: asyncio.Queue,
    item: object,
    *,
    stop_event: asyncio.Event | None = None,
) -> bool:
    """Insert an item even if the queue is temporarily full (backpressure friendly).

    Returns ``True`` when the item was enqueued.  If ``stop_event`` is provided and
    becomes set while waiting for space in the queue, ``False`` is returned so the
    caller can abort the pending operation.
    """

    while True:
        if stop_event is not None and stop_event.is_set():
            return False
        try:
            queue.put_nowait(item)
            return True
        except asyncio.QueueFull:
            await asyncio.sleep(0.05)


async def _signal_capture_stop(queue: "asyncio.PriorityQueue", count: int) -> None:
    for _ in range(count):
        await _put_with_retry(queue, (float("inf"), next(_capture_ticket), None))


def _safe_unlink(path: Path) -> None:
    with contextlib.suppress(FileNotFoundError):
        path.unlink()


def _terminate_process(proc: subprocess.Popen | None, name: str, *, timeout: float = 5.0) -> None:
    """Best-effort shutdown helper that avoids leaving child processes around."""

    if proc is None:
        return
    if proc.poll() is not None:
        return
    # NOTE: Terminate first to let ROS2/bag gracefully stop before resorting to kill.
    proc.terminate()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        print(f"[CLIENT] WARN: {name} did not exit after terminate, killing")
        proc.kill()
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=timeout)


@dataclass(slots=True)
class FrameContext:
    """Track inflight frames with timing metadata for RTT calculations."""

    sequence: int
    handle: "FrameHandle"
    header: DataHeader
    captured_at: float
    encoded_at: float
    sent_at: float
    payload_size: int
    encode_ms: float
    ack_at: float | None = None
    orig_metrics: dict[str, object] | None = None
    orig_points: np.ndarray | None = None


@dataclass(slots=True)
class ReplyEvent:
    kind: str
    message: Message | None = None
    error: BaseException | None = None
    sequence: int | None = None
    detail: str | None = None
    frame: str | None = None
    channel: str | None = None


@dataclass(slots=True)
class CapturePayload:
    """Represent a frame awaiting encoding with capture timing info."""

    sequence: int
    handle: "FrameHandle"
    captured_at: float


@dataclass(slots=True)
class EncodedFrame:
    """Encoded payload ready to be sent across the network."""

    sequence: int
    handle: "FrameHandle"
    payload: bytes
    header: DataHeader
    captured_at: float
    encoded_at: float
    encode_ms: float


@dataclass(slots=True)
class StageStats:
    """Aggregate simple timing statistics for a pipeline stage."""

    count: int = 0
    total: float = 0.0
    maximum: float = 0.0

    def record(self, value: float) -> None:
        self.count += 1
        self.total += value
        if value > self.maximum:
            self.maximum = value

    def summary(self) -> str:
        if self.count == 0:
            return "n/a"
        avg = self.total / self.count
        return f"avg={avg*1000:.2f} ms max={self.maximum*1000:.2f} ms ({self.count} samples)"

    def as_dict(self) -> dict[str, float | int]:
        if self.count == 0:
            return {"count": 0, "avg_ms": 0.0, "max_ms": 0.0}
        avg = self.total / self.count
        return {"count": self.count, "avg_ms": avg * 1000.0, "max_ms": self.maximum * 1000.0}


@dataclass(slots=True)
class PipelineStats:
    """Collect pipeline timing data for diagnostics."""

    capture_to_encode: StageStats = dataclass_field(default_factory=StageStats)
    encode_time: StageStats = dataclass_field(default_factory=StageStats)
    encode_to_send: StageStats = dataclass_field(default_factory=StageStats)
    round_trip: StageStats = dataclass_field(default_factory=StageStats)
    network_rtt: StageStats = dataclass_field(default_factory=StageStats)
    ack_latency: StageStats = dataclass_field(default_factory=StageStats)
    round_trip_samples: list[float] = dataclass_field(default_factory=list)
    network_rtt_samples: list[float] = dataclass_field(default_factory=list)
    ack_latency_samples: list[float] = dataclass_field(default_factory=list)
    skipped_frames: int = 0
    error_frames: int = 0

    def reset(self) -> None:
        self.capture_to_encode = StageStats()
        self.encode_time = StageStats()
        self.encode_to_send = StageStats()
        self.round_trip = StageStats()
        self.network_rtt = StageStats()
        self.ack_latency = StageStats()
        self.round_trip_samples.clear()
        self.network_rtt_samples.clear()
        self.ack_latency_samples.clear()
        self.skipped_frames = 0
        self.error_frames = 0

    def record_round_trip(self, total_latency: float, rtt: float) -> None:
        self.round_trip.record(total_latency)
        self.round_trip_samples.append(total_latency)
        if rtt > 0:
            self.network_rtt.record(rtt)
            self.network_rtt_samples.append(rtt)

    def record_ack(self, latency: float) -> None:
        if latency <= 0:
            return
        self.ack_latency.record(latency)
        self.ack_latency_samples.append(latency)

    def percentile(self, samples: list[float], percentile: float) -> float | None:
        if not samples:
            return None
        percentile = max(0.0, min(100.0, percentile))
        index = (len(samples) - 1) * percentile / 100.0
        lower = int(math.floor(index))
        upper = int(math.ceil(index))
        if lower == upper:
            return samples[lower]
        lower_val = samples[lower]
        upper_val = samples[upper]
        return lower_val + (upper_val - lower_val) * (index - lower)

    def latency_percentiles(self) -> dict[str, float]:
        ordered = sorted(self.round_trip_samples)
        percentiles: dict[str, float] = {}
        for label, value in (("p50", 50.0), ("p95", 95.0), ("p99", 99.0)):
            percentile = self.percentile(ordered, value)
            if percentile is not None:
                percentiles[label] = percentile
        return percentiles

    def percentiles_for(self, samples: list[float]) -> dict[str, float]:
        ordered = sorted(samples)
        result: dict[str, float] = {}
        for label, pct in (("p50", 50.0), ("p95", 95.0), ("p99", 99.0)):
            value = self.percentile(ordered, pct)
            if value is not None:
                result[label] = value
        return result


@dataclass(slots=True)
class TrafficStats:
    """Track aggregate byte counters for the session."""

    sent: int = 0
    received: int = 0
    inflight_peak: int = 0
    capture_depth_peak: int = 0
    network_depth_peak: int = 0
    send_mbps_samples: list[float] = dataclass_field(default_factory=list)
    _last_send_ts: float = 0.0

    def record_send(self, payload_size: int) -> None:
        now = time.monotonic()
        if self._last_send_ts == 0.0:
            self._last_send_ts = now
            return
        delta = max(now - self._last_send_ts, 1e-6)
        mbps = (payload_size * 8) / delta / 1e6
        self.send_mbps_samples.append(mbps)
        self._last_send_ts = now


class SessionState(str, Enum):
    """High level lifecycle markers for client/server coordination."""

    OK = "ok"
    SOFT_DEGRADED = "soft_degraded"
    DEGRADED = "degraded"
    CLOSING = "closing"


class SessionTracker:
    """Record session state transitions with reasons for telemetry."""

    def __init__(self) -> None:
        self._state: SessionState = SessionState.OK
        self._reason: str | None = None
        self._lock = asyncio.Lock()
        self._transitions: list[dict[str, str | None]] = [
            {"state": self._state.value, "reason": None, "ts": f"{time.monotonic():.6f}"}
        ]

    @property
    def state(self) -> SessionState:
        return self._state

    @property
    def reason(self) -> str | None:
        return self._reason

    def snapshot(self) -> dict[str, object]:
        return {
            "state": self._state.value,
            "reason": self._reason,
            "transitions": list(self._transitions),
        }

    async def transition(self, target: SessionState, reason: str | None = None) -> SessionState:
        async with self._lock:
            if target == self._state:
                if reason and reason != self._reason:
                    self._reason = reason
                    print(
                        f"[CLIENT] Session state {self._state.value} (reason updated): {reason}"
                    )
                    self._transitions.append(
                        {"state": self._state.value, "reason": reason, "ts": f"{time.monotonic():.6f}"}
                    )
                return self._state
            if self._state == SessionState.CLOSING and target != SessionState.CLOSING:
                return self._state
            if self._state == SessionState.DEGRADED and target in (
                SessionState.OK,
                SessionState.SOFT_DEGRADED,
            ):
                return self._state
            previous = self._state
            self._state = target
            self._reason = reason
            transition = {
                "from": previous.value,
                "state": target.value,
                "reason": reason,
                "ts": f"{time.monotonic():.6f}",
            }
            self._transitions.append(transition)
            print(
                f"[CLIENT] Session state {previous.value} → {target.value}"
                + (f" ({reason})" if reason else "")
            )
            return self._state


class HeartbeatWatch:
    """Track the last observed server heartbeat or reply timestamp."""

    def __init__(self) -> None:
        self._last = time.monotonic()

    def touch(self) -> None:
        self._last = time.monotonic()

    def age(self) -> float:
        return max(0.0, time.monotonic() - self._last)


@dataclass(slots=True)
class WindowController:
    """Manage the TX window based on optional adaptive heuristics."""

    base_limit: int
    max_limit: int
    adaptive: bool = False
    alpha: float = 0.2
    min_limit: int = 1
    current_limit: int = dataclass_field(init=False)
    ema_payload: float = 0.0
    ema_throughput: float = 0.0
    ema_rtt: float = 0.0

    def __post_init__(self) -> None:
        base = max(self.min_limit, self.base_limit)
        self.current_limit = max(self.min_limit, min(self.max_limit, base))

    def limit(self) -> int:
        return max(self.min_limit, min(self.max_limit, self.current_limit))

    def observe_payload(self, payload_size: int) -> None:
        if payload_size <= 0:
            return
        if self.ema_payload == 0.0:
            self.ema_payload = float(payload_size)
        else:
            self.ema_payload = (1.0 - self.alpha) * self.ema_payload + self.alpha * float(payload_size)

    def observe_ack(self, payload_size: int, rtt: float) -> None:
        if not self.adaptive or payload_size <= 0 or rtt <= 0:
            return
        throughput = float(payload_size) / rtt
        if self.ema_throughput == 0.0:
            self.ema_throughput = throughput
        else:
            self.ema_throughput = (1.0 - self.alpha) * self.ema_throughput + self.alpha * throughput
        if self.ema_rtt == 0.0:
            self.ema_rtt = rtt
        else:
            self.ema_rtt = (1.0 - self.alpha) * self.ema_rtt + self.alpha * rtt
        self.observe_payload(payload_size)
        if self.ema_payload > 0:
            bdp_bytes = self.ema_throughput * self.ema_rtt
            target = int(round(bdp_bytes / self.ema_payload)) + 1
            self.current_limit = max(self.min_limit, min(self.max_limit, target))


@dataclass(slots=True)
class AckTimeoutPolicy:
    """Adaptive ACK timeout helper honouring CLI min/max clamps."""

    base: float
    minimum: float
    maximum: float
    last: float = dataclass_field(init=False)

    def __post_init__(self) -> None:
        if self.minimum <= 0 or self.maximum <= 0:
            raise ValueError("ack timeout bounds must be positive")
        if self.minimum > self.maximum:
            raise ValueError("ack timeout min cannot exceed max")
        self.base = self._clamp(self.base)
        self.last = self.base

    def _clamp(self, value: float) -> float:
        return max(self.minimum, min(self.maximum, value))

    def compute(self, ema_rtt: float) -> float:
        if ema_rtt > 0.0:
            candidate = max(self.base, ema_rtt * 2.0 + 0.1)
        else:
            candidate = self.base
        timeout = self._clamp(candidate)
        self.last = timeout
        return timeout


@dataclass(slots=True)
class DecodedResult:
    """Hold decoded payloads awaiting publish order."""

    sequence: int | None
    base_name: str
    header: ResponseHeader
    decoded: bytes
    metrics: dict[str, object]
    context: FrameContext
    received_at: float


def _load_decoded_points(payload: bytes, fmt: str) -> np.ndarray:
    if fmt == "pcd":
        header_end = payload.find(b"\nDATA")
        if header_end == -1:
            raise ValueError("invalid PCD payload: missing DATA header")
        header = payload[:header_end].decode("utf-8", errors="ignore")
        remainder = payload[header_end:]
        first_line_end = remainder.find(b"\n")
        if first_line_end == -1:
            raise ValueError("invalid PCD payload: truncated DATA line")
        body = remainder[first_line_end + 1 :]
        points = 0
        for line in header.splitlines():
            if line.upper().startswith("POINTS"):
                parts = line.split()
                if len(parts) >= 2:
                    points = int(parts[1])
                break
        arr = np.frombuffer(body, dtype="<f4")
        if points > 0:
            expected = points * 3
            if arr.size < expected:
                raise ValueError("invalid PCD payload: insufficient binary data")
            arr = arr[:expected]
        if arr.size % 3 != 0:
            raise ValueError("invalid PCD payload: uneven XYZ components")
        return arr.reshape(-1, 3)
    return load_xyz_from_bytes(payload)


def _append_jsonl(path: Path, record: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")


class ReplyPump(threading.Thread):
    """Background thread that continuously drains replies from the server."""

    def __init__(
        self,
        sock: socket.socket,
        queue: "asyncio.Queue[ReplyEvent]",
        stop_event: threading.Event,
        protocol: ProtocolHandler,
        loop: asyncio.AbstractEventLoop,
        *,
        channel: str | None = None,
    ) -> None:
        super().__init__(daemon=True)
        self._sock = sock
        self._queue = queue
        self._stop_event = stop_event
        self._protocol = protocol
        self._loop = loop
        self._channel = channel

    def _submit(self, event: ReplyEvent) -> None:
        try:
            self._loop.call_soon_threadsafe(self._queue.put_nowait, event)
        except RuntimeError:
            # Event loop might be closed already during shutdown; drop the event.
            pass

    def run(self) -> None:  # pragma: no cover - threading behaviour is timing sensitive.
        while not self._stop_event.is_set():
            try:
                message = self._protocol.recv(self._sock)
            except socket.timeout:
                continue
            except Exception as exc:  # noqa: BLE001 - bubble up to the producer loop.
                self._submit(ReplyEvent(kind="error", error=exc, channel=self._channel))
                return
            if message is None:
                self._submit(ReplyEvent(kind="closed", channel=self._channel))
                return
            self._submit(ReplyEvent(kind="message", message=message, channel=self._channel))
            if message.kind == MSG_EOF:
                return


@dataclass(slots=True)
class ControlChannel:
    """Optional dedicated control-plane socket used when multiplexing is enabled."""

    sock: socket.socket
    protocol: ProtocolHandler


async def _send_control_message(
    control: ControlChannel | None,
    fallback_sock: socket.socket,
    fallback_protocol: ProtocolHandler,
    message: Message,
) -> None:
    """Send a control-plane message using the dedicated channel when available."""

    target_sock = control.sock if control is not None else fallback_sock
    target_protocol = control.protocol if control is not None else fallback_protocol
    await asyncio.to_thread(target_protocol.send, target_sock, message)


class FrameHandle(Protocol):
    name: str

    def ensure_encoder_input(self, work_dir: Path) -> Path:
        ...

    def load_source_points(self) -> np.ndarray:
        ...

    def priority_hint(self) -> float:
        ...

    def on_consumed(self) -> None:
        ...

    def on_aborted(self) -> None:
        ...


class FilesystemFrameHandle:
    """Adapter that exposes filesystem-backed frames via the FrameHandle protocol."""

    def __init__(self, watcher: "SpoolWatcher", path: Path):
        self._watcher = watcher
        self._path = path
        self.name = path.stem
        try:
            self._priority = path.stat().st_mtime
        except FileNotFoundError:
            self._priority = time.time()

    def ensure_encoder_input(self, work_dir: Path) -> Path:  # noqa: ARG002 - interface requirement
        return self._path

    def load_source_points(self) -> np.ndarray:
        return load_xyz(self._path)

    def priority_hint(self) -> float:
        return self._priority

    def on_consumed(self) -> None:
        self._watcher.mark_consumed(self._path)

    def on_aborted(self) -> None:
        # Files remain available for future runs, no action needed.
        return


class SharedMemoryFrameHandle:
    """Convert shared-memory published frames into encoder-compatible artifacts."""

    def __init__(self, descriptor: SharedMemoryDescriptor):
        self._descriptor = descriptor
        stem = Path(descriptor.frame).stem or descriptor.frame
        self.name = stem
        self._cached_points: np.ndarray | None = None
        self._temp_path: Path | None = None
        self._priority = descriptor.timestamp or time.time()

    def _materialize_points(self) -> np.ndarray:
        if self._cached_points is not None:
            return self._cached_points
        if not self._descriptor.shm or self._descriptor.size <= 0:
            shape = self._descriptor.shape or (0, 3)
            self._cached_points = np.empty(shape, dtype=np.float32)
            return self._cached_points
        shm = shared_memory.SharedMemory(name=self._descriptor.shm)
        try:
            dtype = np.dtype(self._descriptor.dtype)
            arr = np.ndarray(self._descriptor.shape, dtype=dtype, buffer=shm.buf)
            self._cached_points = np.asarray(arr, dtype=np.float32).copy()
        finally:
            shm.close()
            shm.unlink()
        return self._cached_points

    def ensure_encoder_input(self, work_dir: Path) -> Path:
        if self._temp_path is None:
            self._temp_path = work_dir / f"{self.name}.ply"
            save_xyz(self._temp_path, self._materialize_points())
        return self._temp_path

    def load_source_points(self) -> np.ndarray:
        return self._materialize_points()

    def priority_hint(self) -> float:
        return self._priority

    def _remove_temp(self) -> None:
        if self._temp_path is None:
            return
        with contextlib.suppress(FileNotFoundError):
            self._temp_path.unlink()
        self._temp_path = None

    def on_consumed(self) -> None:
        self._remove_temp()

    def on_aborted(self) -> None:
        self._remove_temp()


class FilesystemFrameSupplier:
    def __init__(self, watcher: "SpoolWatcher") -> None:
        self._watcher = watcher

    def drain_initial(self) -> list[FrameHandle]:
        return [FilesystemFrameHandle(self._watcher, path) for path in self._watcher.drain_initial()]

    def wait_for_new(self, timeout: float) -> list[FrameHandle]:
        paths = self._watcher.wait_for_new(timeout)
        return [FilesystemFrameHandle(self._watcher, path) for path in paths]


class SharedMemoryFrameSupplier:
    def __init__(self, receiver: SharedMemoryReceiver) -> None:
        self._receiver = receiver

    def drain_initial(self) -> list[FrameHandle]:
        return []

    def wait_for_new(self, timeout: float) -> list[FrameHandle]:
        descriptors = self._receiver.get_batch(timeout)
        return [SharedMemoryFrameHandle(desc) for desc in descriptors]


async def capture_stage(
    frame_supplier: FilesystemFrameSupplier | SharedMemoryFrameSupplier,
    capture_queue: "asyncio.PriorityQueue[tuple[float, int, CapturePayload | None]]",
    *,
    stop_event: asyncio.Event,
    bag_done: asyncio.Event,
    saver_done: asyncio.Event,
    encode_workers: int,
    traffic: TrafficStats,
    idle_rounds: int = 5,
) -> None:
    """Monitor the capture source and enqueue frames for encoding."""

    try:
        initial = frame_supplier.drain_initial()
        for handle in initial:
            sequence = next(_sequence_ids)
            payload = CapturePayload(sequence=sequence, handle=handle, captured_at=time.monotonic())
            await capture_queue.put((handle.priority_hint(), next(_capture_ticket), payload))
            depth = capture_queue.qsize()
            traffic.capture_depth_peak = max(traffic.capture_depth_peak, depth)
            _telemetry("capture_enqueue", handle.name, depth=depth, seq=sequence)
        empty_rounds = 0
        while not stop_event.is_set():
            handles = await asyncio.to_thread(frame_supplier.wait_for_new, 0.2)
            if handles:
                empty_rounds = 0
                for handle in handles:
                    sequence = next(_sequence_ids)
                    payload = CapturePayload(sequence=sequence, handle=handle, captured_at=time.monotonic())
                    await capture_queue.put((handle.priority_hint(), next(_capture_ticket), payload))
                    depth = capture_queue.qsize()
                    traffic.capture_depth_peak = max(traffic.capture_depth_peak, depth)
                    _telemetry("capture_enqueue", handle.name, depth=depth, seq=sequence)
            else:
                empty_rounds += 1
            if (
                bag_done.is_set()
                and saver_done.is_set()
                and not handles
                and empty_rounds >= idle_rounds
            ):
                break
    except asyncio.CancelledError:
        stop_event.set()
        raise
    finally:
        await _signal_capture_stop(capture_queue, encode_workers)


async def encode_worker(
    worker_id: int,
    capture_queue: "asyncio.PriorityQueue[tuple[float, int, CapturePayload | None]]",
    network_queue: "asyncio.Queue[Optional[EncodedFrame]]",
    reply_queue: "asyncio.Queue[ReplyEvent]",
    *,
    encoder_options,
    encoder_path: Path,
    work_dir: Path,
    stats: PipelineStats,
    stop_event: asyncio.Event,
    traffic: TrafficStats,
) -> None:
    """Encode frames pulled from the capture queue and forward them."""

    while not stop_event.is_set():
        priority, _, payload = await capture_queue.get()
        if payload is None:
            capture_queue.task_done()
            # Always deliver the sentinel so the network sender unblocks, even when
            # shutdown has already been requested via ``stop_event``.
            await _put_with_retry(network_queue, None)
            traffic.network_depth_peak = max(traffic.network_depth_peak, network_queue.qsize())
            break
        handle = payload.handle
        sequence = payload.sequence
        captured_at = payload.captured_at
        encode_start = time.monotonic()
        _telemetry(
            "encode_start",
            handle.name,
            wait_ms=(encode_start - captured_at) * 1000.0,
            seq=sequence,
        )
        try:
            encoder_input = await asyncio.to_thread(handle.ensure_encoder_input, work_dir)
            result = await asyncio.to_thread(
                encode_frame,
                encoder_input,
                work_dir,
                encoder_options,
                encoder_hint=encoder_path,
                skip_existing=False,
            )
            drc_bytes = await asyncio.to_thread(result.output.read_bytes)
            await asyncio.to_thread(_safe_unlink, result.output)
            encoded_at = time.monotonic()
            stats.capture_to_encode.record(encode_start - captured_at)
            stats.encode_time.record(encoded_at - encode_start)
            print(
                format_encode_log(
                    result,
                    source=Path(encoder_input),
                    prefix=f"[CLIENT][ENCODER:{worker_id}]",
                )
            )
            header, packed_payload = compose_request_payload(
                sequence,
                drc_bytes,
                timestamp_ns=time.monotonic_ns(),
            )
            encoded = EncodedFrame(
                sequence=sequence,
                handle=handle,
                payload=packed_payload,
                header=header,
                captured_at=captured_at,
                encoded_at=encoded_at,
                encode_ms=result.duration * 1000.0,
            )
            _telemetry(
                "encode_complete",
                handle.name,
                latency_ms=(encoded_at - encode_start) * 1000.0,
                seq=sequence,
            )
            if not await _put_with_retry(network_queue, encoded, stop_event=stop_event):
                break
            traffic.network_depth_peak = max(traffic.network_depth_peak, network_queue.qsize())
        except asyncio.CancelledError:
            stop_event.set()
            raise
        except Exception as exc:
            print(f"[CLIENT] ENCODE FAIL {handle.name}: {exc}")
            with contextlib.suppress(Exception):
                handle.on_consumed()
            detail = f"encode failure: {exc}"
            await _put_with_retry(
                reply_queue,
                ReplyEvent(
                    kind="local_skip",
                    sequence=sequence,
                    detail=detail,
                    frame=handle.name,
                ),
                stop_event=stop_event,
            )
        finally:
            capture_queue.task_done()


async def network_sender(
    sock: socket.socket,
    protocol: ProtocolHandler,
    network_queue: "asyncio.Queue[Optional[EncodedFrame]]",
    inflight: Dict[int, FrameContext],
    acks_pending: set[int],
    *,
    stats: PipelineStats,
    traffic: TrafficStats,
    stop_event: asyncio.Event,
    inflight_condition: asyncio.Condition,
    encode_workers: int,
    window: WindowController,
    session: SessionTracker,
    heartbeat_watch: HeartbeatWatch,
    heartbeat_timeout: float,
    control: ControlChannel | None = None,
    fragment_size: int,
    use_binary: bool,
    control_plane: ControlPlane,
    ack_policy: "AckTimeoutPolicy",
) -> None:
    """Send encoded frames while respecting inflight limits."""

    encode_finished = 0
    eof_sent = False
    drain_deadline: float | None = None

    async def _wait_with_health(predicate: Callable[[], bool]) -> bool:
        timeout_s = 0.5
        while predicate() and not stop_event.is_set():
            try:
                await asyncio.wait_for(inflight_condition.wait(), timeout=timeout_s)
            except asyncio.TimeoutError:
                if stop_event.is_set():
                    break
                if heartbeat_timeout > 0 and heartbeat_watch.age() > heartbeat_timeout:
                    await session.transition(
                        SessionState.DEGRADED,
                        "network sender heartbeat timeout",
                    )
                    stop_event.set()
                    break
        return not predicate()

    while not stop_event.is_set():
        item = await network_queue.get()
        if item is None:
            encode_finished += 1
            network_queue.task_done()
            if encode_finished >= encode_workers and not eof_sent:
                async with inflight_condition:
                    await _wait_with_health(lambda: bool(inflight or acks_pending))
                if (
                    session.state in (SessionState.OK, SessionState.SOFT_DEGRADED)
                    and not inflight
                    and not acks_pending
                    and not stop_event.is_set()
                ):
                    eof_payload = b""
                    message = Message(
                        kind=MSG_EOF,
                        name=encode_frame_address(
                            None,
                            "final",
                            channel=CONTROL_CHANNEL,
                        ),
                        payload=eof_payload,
                    )
                    try:
                        await _send_control_message(control, sock, protocol, message)
                        await session.transition(SessionState.CLOSING, "EOF sent")
                        control_plane.on_eof_sent()
                        pending_count = len(inflight)
                        pending_acks = len(acks_pending)
                        print(
                            f"[CLIENT] EOF sent to server (pending={pending_count} pending_acks={pending_acks})"
                        )
                        _telemetry("send_eof", "all")
                        eof_sent = True
                        drain_deadline = time.monotonic() + max(ack_policy.last, 1.0)
                        with contextlib.suppress(OSError):
                            sock.shutdown(socket.SHUT_WR)
                    except Exception as exc:
                        print(f"[CLIENT] ERROR sending EOF marker: {exc}")
                        stop_event.set()
                        break
            if eof_sent:
                if drain_deadline is not None and not stop_event.is_set():
                    remaining = drain_deadline - time.monotonic()
                    if remaining > 0:
                        await asyncio.sleep(min(remaining, CONTROL_POLL_INTERVAL))
                        continue
                break
            continue

        encoded = item
        async with inflight_condition:
            await _wait_with_health(lambda: len(acks_pending) >= window.limit())
            if session.state == SessionState.DEGRADED:
                stop_event.set()
                inflight_condition.notify_all()
                network_queue.task_done()
                break
        ack_timeout_s = ack_policy.compute(window.ema_rtt)
        control_plane.on_frame_sent(
            encoded.sequence,
            now_ns=time.monotonic_ns(),
            ack_timeout_ns=int(ack_timeout_s * 1_000_000_000),
        )
        fragments: Iterable[FrameFragment]
        if use_binary:
            fragments = iter_fragments(
                encoded.payload,
                sequence=encoded.sequence,
                fragment_size=fragment_size,
            )
        else:
            fragments = (
                FrameFragment(
                    sequence=encoded.sequence,
                    payload=encoded.payload,
                    index=0,
                    total=1,
                    frame_payload_len=len(encoded.payload),
                ),
            )
        try:
            for fragment in fragments:
                message = Message(
                    kind=MSG_DATA,
                    name=encode_frame_address(
                        fragment.sequence,
                        encoded.handle.name,
                        channel=DATA_CHANNEL,
                    ),
                    payload=fragment.payload,
                    sequence=fragment.sequence,
                    fragmented=fragment.total > 1,
                    fragment_index=fragment.index,
                    fragments_total=fragment.total,
                    frame_payload_len=fragment.frame_payload_len,
                )
                await asyncio.to_thread(protocol.send, sock, message)
                traffic.record_send(len(fragment.payload))
        except Exception as exc:
            print(f"[CLIENT] ERROR sending {encoded.handle.name}: {exc}")
            stop_event.set()
            with contextlib.suppress(Exception):
                encoded.handle.on_aborted()
            async with inflight_condition:
                inflight_condition.notify_all()
            network_queue.task_done()
            break
        _telemetry("send_complete", encoded.handle.name, size=len(encoded.payload))
        sent_at = time.monotonic()
        stats.encode_to_send.record(sent_at - encoded.encoded_at)
        window.observe_payload(len(encoded.payload))
        ctx = FrameContext(
            sequence=encoded.sequence,
            handle=encoded.handle,
            header=encoded.header,
            captured_at=encoded.captured_at,
            encoded_at=encoded.encoded_at,
            sent_at=sent_at,
            payload_size=len(encoded.payload),
            encode_ms=encoded.encode_ms,
        )
        async with inflight_condition:
            inflight[encoded.sequence] = ctx
            acks_pending.add(encoded.sequence)
            traffic.inflight_peak = max(traffic.inflight_peak, len(acks_pending))
            inflight_condition.notify_all()
        traffic.sent += len(encoded.payload)
        print(f"[CLIENT] Sent {encoded.handle.name} ({len(encoded.payload)} bytes)")
        async with inflight_condition:
            inflight_condition.notify_all()
        network_queue.task_done()


async def reply_consumer(
    reply_queue: "asyncio.Queue[ReplyEvent]",
    inflight: Dict[int, FrameContext],
    *,
    stats: PipelineStats,
    traffic: TrafficStats,
    stop_event: asyncio.Event,
    inflight_condition: asyncio.Condition,
    window: WindowController,
    acks_pending: set[int],
    decoded_dir: Path,
    to_play: "queue.Queue",
    play_sample: int,
    frame_counter: itertools.count,
    print_metrics: bool,
    quality_report_path: Path | None,
    quality_thresholds: dict[str, float],
    save_decoded: bool,
    metrics_sample: int,
    default_resp_format: str,
    heartbeat_timeout: float,
    session: SessionTracker,
    heartbeat_watch: HeartbeatWatch,
    control_plane: ControlPlane,
    use_binary: bool,
    ack_timeout_strikes: int,
) -> None:
    """Process replies from the server and release inflight slots."""

    reorder_buffer: Dict[int, DecodedResult] = {}
    skipped_sequences: Dict[int, str] = {}
    fragment_buffer: Dict[int, dict[str, object]] = {}
    next_sequence = 0

    async def emit_result(result: DecodedResult) -> None:
        ctx = result.context
        base_name = result.base_name or ctx.handle.name
        resp_format = result.metrics.get("extra", {}).get("resp_format", default_resp_format)
        suffix = f".{resp_format}"
        decoded_name = base_name if base_name.endswith(suffix) else f"{base_name}{suffix}"
        decoded_path = decoded_dir / decoded_name
        if save_decoded:
            await asyncio.to_thread(decoded_path.write_bytes, result.decoded)
        if ctx.orig_points is None:
            ctx.orig_points = await asyncio.to_thread(ctx.handle.load_source_points)
        pts_src = ctx.orig_points
        pts_dec = await asyncio.to_thread(_load_decoded_points, result.decoded, resp_format)
        if ctx.orig_metrics is None:
            ctx.orig_metrics = await asyncio.to_thread(
                pointcloud_metrics.compute,
                pts_src,
                sample=metrics_sample,
                frame_id=ctx.handle.name,
                encode_ms=ctx.encode_ms,
            )
        server_metrics = dict(result.metrics)
        if server_metrics.get("encode_ms") is None:
            server_metrics["encode_ms"] = ctx.encode_ms
        client_metrics = await asyncio.to_thread(
            pointcloud_metrics.compute,
            pts_dec,
            sample=metrics_sample,
            frame_id=ctx.handle.name,
        )
        chamfer_value = await asyncio.to_thread(
            pointcloud_metrics.chamfer_est,
            pts_src,
            pts_dec,
            sample=play_sample if play_sample > 0 else None,
        )
        orig = ctx.orig_metrics
        assert orig is not None

        def _rel_delta(a: float, b: float) -> float:
            if b == 0.0:
                return 0.0 if a == 0.0 else float("inf")
            return abs(a - b) / abs(b)

        quality = {
            "point_count_abs": abs(int(client_metrics["point_count"]) - int(orig["point_count"])),
            "centroid_l2": float(
                np.linalg.norm(
                    np.asarray(client_metrics["centroid"], dtype=float)
                    - np.asarray(orig["centroid"], dtype=float)
                )
            ),
            "scale_diag_rel": _rel_delta(float(client_metrics["scale_diag"]), float(orig["scale_diag"])),
            "avg_nn_rel": _rel_delta(float(client_metrics["avg_nn_dist"]), float(orig["avg_nn_dist"])),
            "chamfer_est": chamfer_value,
        }
        breaches = {key: quality[key] > value for key, value in quality_thresholds.items() if key in quality}
        if any(breaches.values()):
            stats.error_frames += 1
        status = "WARN" if any(breaches.values()) else "INFO"
        summary = (
            f"seq={ctx.sequence} frame={decoded_name} Δpts={quality['point_count_abs']} "
            f"centroid_l2={quality['centroid_l2']:.5f} scale_rel={quality['scale_diag_rel']:.5f} "
            f"avg_nn_rel={quality['avg_nn_rel']:.5f} chamfer={quality['chamfer_est']:.5f}"
        )
        print(f"[CLIENT][QUALITY][{status}] {summary}")
        if print_metrics:
            print(
                f"[CLIENT] Server metrics {decoded_name}: {server_metrics}"
            )
            print(
                f"[CLIENT] Client metrics {decoded_name}: {client_metrics}"
            )
        if quality_report_path is not None:
            record = {
                "sequence": ctx.sequence,
                "frame": decoded_name,
                "timestamp_ns": result.header.timestamp_ns,
                "server_metrics": server_metrics,
                "client_metrics": client_metrics,
                "original_metrics": orig,
                "quality": quality,
                "thresholds": quality_thresholds,
                "breaches": breaches,
            }
            await asyncio.to_thread(_append_jsonl, quality_report_path, record)
        frame_idx = next(frame_counter)
        to_play.put((frame_idx, decoded_name, pts_src, pts_dec))
        with contextlib.suppress(Exception):
            ctx.handle.on_consumed()

    async def drain_ready(force: bool = False) -> tuple[int, int]:
        nonlocal next_sequence
        flushed = 0
        skipped = 0
        while True:
            if next_sequence in skipped_sequences:
                detail = skipped_sequences.pop(next_sequence)
                print(f"[CLIENT] Skipping frame seq={next_sequence}: {detail}")
                stats.skipped_frames += 1
                skipped += 1
                next_sequence += 1
                continue
            result = reorder_buffer.get(next_sequence)
            if result is None:
                break
            reorder_buffer.pop(next_sequence, None)
            await emit_result(result)
            next_sequence += 1
            flushed += 1
        if force:
            for sequence in sorted(reorder_buffer):
                await emit_result(reorder_buffer[sequence])
                flushed += 1
            reorder_buffer.clear()
            if skipped_sequences:
                for sequence in sorted(skipped_sequences):
                    detail = skipped_sequences[sequence]
                    print(f"[CLIENT] Skipped pending seq={sequence}: {detail}")
                    stats.skipped_frames += 1
                    skipped += 1
                skipped_sequences.clear()
        return flushed, skipped

    heartbeat_timeout = max(heartbeat_timeout, CONTROL_POLL_INTERVAL)
    heartbeat_watch.touch()
    timeout_strikes = 0
    max_timeout_strikes = max(1, ack_timeout_strikes)

    try:
        while not stop_event.is_set():
            try:
                event = await asyncio.wait_for(
                    reply_queue.get(), timeout=CONTROL_POLL_INTERVAL
                )
            except asyncio.TimeoutError:
                if stop_event.is_set():
                    break
                now_ns = time.monotonic_ns()
                expired = control_plane.expired_sequences(now_ns=now_ns)
                if expired:
                    detail = ",".join(str(seq) for seq in expired)
                    timeout_strikes += 1
                    if timeout_strikes >= max_timeout_strikes:
                        print(
                            f"[CLIENT] ERROR: ACK timeout strike {timeout_strikes}/{max_timeout_strikes}"
                            f" for sequences {detail}"
                        )
                        control_plane.on_error(
                            ErrorCode.TIMEOUT,
                            f"ack timeout ({detail})",
                        )
                        await session.transition(
                            SessionState.DEGRADED,
                            f"ack timeout x{timeout_strikes}",
                        )
                        stop_event.set()
                        async with inflight_condition:
                            inflight_condition.notify_all()
                        continue
                    print(
                        f"[CLIENT] WARN: ACK timeout strike {timeout_strikes}/{max_timeout_strikes}"
                        f" for sequences {detail}"
                    )
                    await session.transition(
                        SessionState.SOFT_DEGRADED,
                        f"ack timeout pending ({detail})",
                    )
                    continue
                if control_plane.heartbeat_timed_out(now_ns=now_ns):
                    print("[CLIENT] ERROR: Heartbeat timeout detected")
                    control_plane.on_error(ErrorCode.TIMEOUT, "heartbeat timeout")
                    await session.transition(SessionState.DEGRADED, "heartbeat timeout")
                    stop_event.set()
                    async with inflight_condition:
                        inflight_condition.notify_all()
                    continue
                if heartbeat_timeout > 0 and heartbeat_watch.age() > heartbeat_timeout:
                    print(
                        "[CLIENT] WARN: No server reply within heartbeat window;",
                        f" pending={len(inflight)} inflight",
                    )
                    await session.transition(
                        SessionState.DEGRADED, "reply heartbeat window expired"
                    )
                    stop_event.set()
                    async with inflight_condition:
                        inflight_condition.notify_all()
                    continue
                continue

            now = time.monotonic()
            heartbeat_watch.touch()
            if event.kind == "local_skip":
                sequence = event.sequence
                detail = event.detail or "local failure"
                frame_name = event.frame or (
                    str(sequence) if sequence is not None else "unknown"
                )
                if sequence is not None:
                    skipped_sequences[sequence] = detail
                    async with inflight_condition:
                        acks_pending.discard(sequence)
                        inflight_condition.notify_all()
                print(f"[CLIENT] Local skip seq={sequence}: {frame_name} ({detail})")
                stats.error_frames += 1
                await drain_ready()
                reply_queue.task_done()
                continue
            if event.kind == "error" and event.error:
                channel = event.channel or DATA_CHANNEL
                detail = str(event.error)
                if isinstance(event.error, ProtocolError):
                    print(
                        f"[CLIENT] PROTOCOL ERROR on {channel}: {detail} (binary framing)"
                    )
                else:
                    print(f"[CLIENT] ERROR from reply pump ({channel}): {detail}")
                control_plane.on_error(ErrorCode.INTERNAL_ERROR, detail)
                await session.transition(
                    SessionState.DEGRADED, f"reply pump error ({channel})"
                )
                stop_event.set()
                async with inflight_condition:
                    acks_pending.clear()
                    inflight_condition.notify_all()
                reply_queue.task_done()
                break
            if event.kind == "closed":
                channel = event.channel or DATA_CHANNEL
                print(f"[CLIENT] Connection closed by server on {channel} channel")
                control_plane.on_error(
                    ErrorCode.PROTOCOL_VIOLATION, "connection closed"
                )
                await session.transition(SessionState.DEGRADED, "connection closed")
                stop_event.set()
                async with inflight_condition:
                    acks_pending.clear()
                    inflight_condition.notify_all()
                reply_queue.task_done()
                break
            if event.kind != "message" or event.message is None:
                reply_queue.task_done()
                continue

            message = event.message
            address = decode_frame_address(message.name)
            body = message.payload


            if message.kind == MSG_HEARTBEAT:
                heartbeat_watch.touch()
                control_plane.on_heartbeat(now_ns=time.monotonic_ns())
                _telemetry("recv_heartbeat", address.name or "all")
                async with inflight_condition:
                    inflight_condition.notify_all()
                reply_queue.task_done()
                continue

            if message.kind == MSG_ACK:
                sequence = message.sequence if message.sequence is not None else address.sequence
                if sequence is None and len(body) >= ACK_PAYLOAD_STRUCT.size:
                    sequence = ACK_PAYLOAD_STRUCT.unpack_from(body)[0]
                ctx: FrameContext | None = None
                async with inflight_condition:
                    if sequence is not None:
                        ctx = inflight.get(sequence)
                        acks_pending.discard(sequence)
                    inflight_condition.notify_all()
                if ctx is None:
                    print(f"[CLIENT] WARN: ACK for unknown frame {message.name}")
                else:
                    ctx.ack_at = now
                    ack_latency = max(0.0, ctx.ack_at - ctx.sent_at)
                    stats.record_ack(ack_latency)
                    window.observe_ack(ctx.payload_size, ack_latency)
                    try:
                        control_plane.on_ack(ctx.sequence)
                    except ControlPlaneError as exc:
                        print(f"[CLIENT] ERROR: {exc}")
                        control_plane.on_error(ErrorCode.PROTOCOL_VIOLATION, str(exc))
                        stop_event.set()
                    timeout_strikes = 0
                    if session.state == SessionState.SOFT_DEGRADED:
                        await session.transition(SessionState.OK, "ack recovered")
                _telemetry(
                    "recv_ack",
                    address.name or (ctx.handle.name if ctx else "unknown"),
                    seq=sequence,
                    latency_ms=(ctx.ack_at - ctx.sent_at) * 1000.0 if ctx and ctx.ack_at else None,
                )
                reply_queue.task_done()
                continue

            if message.kind == MSG_EOF:
                pending_count = len(inflight)
                pending_acks_count = len(acks_pending)
                try:
                    control_plane.on_eof_received()
                except ControlPlaneError as exc:
                    print(f"[CLIENT] ERROR: {exc}")
                    control_plane.on_error(ErrorCode.PROTOCOL_VIOLATION, str(exc))
                await session.transition(SessionState.CLOSING, "server EOF")
                stop_event.set()
                async with inflight_condition:
                    pending_count = len(inflight)
                    pending_acks_count = len(acks_pending)
                    acks_pending.clear()
                    inflight_condition.notify_all()
                print(
                    "[CLIENT] EOF received from server "
                    f"(pending={pending_count} pending_acks={pending_acks_count})"
                )
                _telemetry("recv_eof", "all")
                await drain_ready(force=True)
                reply_queue.task_done()
                break

            async with inflight_condition:
                ctx = None
                sequence = message.sequence if message.sequence is not None else address.sequence
                if sequence is not None:
                    ctx = inflight.pop(sequence, None)
                    acks_pending.discard(sequence)
                if ctx is None:
                    for key, candidate in list(inflight.items()):
                        if candidate.handle.name == address.name or candidate.sequence == sequence:
                            ctx = inflight.pop(key)
                            acks_pending.discard(candidate.sequence)
                            break
                inflight_condition.notify_all()
            if ctx is None:
                print(f"[CLIENT] WARN: Received reply for unknown frame {message.name}")
                reply_queue.task_done()
                continue

            if message.kind == MSG_ERROR:
                detail = body.decode("utf-8", errors="replace") if body else ErrorCode.INTERNAL_ERROR.name
                print(f"[CLIENT] SERVER ERROR for seq={ctx.sequence}: {detail}")
                stats.error_frames += 1
                skipped_sequences[ctx.sequence] = detail
                control_plane.on_error(ErrorCode.INTERNAL_ERROR, detail)
                await session.transition(SessionState.DEGRADED, f"server error {ErrorCode.INTERNAL_ERROR.name}")
                _telemetry("recv_error", address.name or str(ctx.sequence), detail=detail)
                with contextlib.suppress(Exception):
                    ctx.handle.on_aborted()
                await drain_ready()
                reply_queue.task_done()
                continue

            if use_binary and message.fragmented and ctx.sequence is not None:
                bucket = fragment_buffer.setdefault(
                    ctx.sequence,
                    {"chunks": {}, "total": message.fragments_total or 1, "expected": message.frame_payload_len},
                )
                bucket["chunks"][message.fragment_index or 0] = body
                if len(bucket["chunks"]) < bucket["total"]:
                    reply_queue.task_done()
                    continue
                ordered = [bucket["chunks"][idx] for idx in range(bucket["total"]) if idx in bucket["chunks"]]
                body = b"".join(ordered)
                fragment_buffer.pop(ctx.sequence, None)

            try:
                header, decoded_payload, metrics_payload = parse_response_payload(body)
            except ValueError as exc:
                print(
                    f"[CLIENT] ERROR parsing response for seq={ctx.sequence}: {exc}"
                )
                stats.error_frames += 1
                reply_queue.task_done()
                continue
            try:
                metrics = json.loads(metrics_payload.decode("utf-8")) if metrics_payload else {}
            except json.JSONDecodeError as exc:
                print(
                    f"[CLIENT] ERROR decoding metrics JSON for seq={ctx.sequence}: {exc}"
                )
                stats.error_frames += 1
                reply_queue.task_done()
                continue
            control_plane.on_first_data()
            rtt = max(0.0, now - ctx.sent_at)
            total_latency = max(0.0, now - ctx.captured_at)
            stats.record_round_trip(total_latency, rtt)
            if ctx.ack_at is None:
                window.observe_ack(ctx.payload_size, rtt)
            traffic.received += len(body)
            _telemetry(
                "recv_data",
                address.name or ctx.handle.name,
                size=len(body),
                seq=ctx.sequence,
            )
            result = DecodedResult(
                sequence=ctx.sequence,
                base_name=address.name or f"{ctx.handle.name}.decoded",
                header=header,
                decoded=decoded_payload,
                metrics=metrics,
                context=ctx,
                received_at=now,
            )
            if result.sequence is None:
                await emit_result(result)
            else:
                if result.sequence < next_sequence:
                    print(
                        f"[CLIENT] WARN: Late arrival for already published seq={result.sequence}, dropping"
                    )
                else:
                    reorder_buffer[result.sequence] = result
                await drain_ready()
            reply_queue.task_done()
    except asyncio.CancelledError:
        await session.transition(SessionState.DEGRADED, "reply consumer cancelled")
        flushed, skipped = await drain_ready(force=True)
        if flushed or skipped:
            print(
                f"[CLIENT] Reply consumer cancelled; drained={flushed} skipped={skipped}"
            )
        async with inflight_condition:
            acks_pending.clear()
            inflight_condition.notify_all()
        raise
    except Exception as exc:
        await session.transition(SessionState.DEGRADED, f"reply consumer error: {exc}")
        flushed, skipped = await drain_ready(force=True)
        print(
            f"[CLIENT] ERROR in reply consumer tail drain: drained={flushed} skipped={skipped}"
        )
        async with inflight_condition:
            acks_pending.clear()
            inflight_condition.notify_all()
        raise
    finally:
        heartbeat_watch.touch()

async def monitor_process(
    proc: subprocess.Popen | None,
    event: asyncio.Event,
    name: str,
    stop_event: asyncio.Event,
) -> None:
    """Set an event once the given process completes."""

    if proc is None:
        event.set()
        return
    try:
        while proc.poll() is None and not stop_event.is_set():
            await asyncio.sleep(0.5)
    finally:
        event.set()

try:  # NOTE: Prefer inotify when available to honor event-driven spool monitoring.
    from inotify_simple import INotify, flags as inotify_flags
except Exception:  # pragma: no cover - fall back to portable polling when missing.
    INotify = None  # type: ignore
    inotify_flags = None  # type: ignore


class SpoolWatcher:
    """Track new PLY frames using filesystem events when possible."""

    # NOTE: Bounded history prevents the previous unbounded processed set growth.
    _history_limit = 65536

    def __init__(self, directory: Path, prefix: str, *, gc_window: int | None = None):
        self.directory = directory
        self.prefix = prefix
        self._inotify: Optional[INotify] = None
        self._watch_descriptor: Optional[int] = None
        self._known: set[str] = set()
        self._retired: Deque[str] = deque(maxlen=self._history_limit)
        self._retired_set: set[str] = set()
        self._known_order: Deque[str] = deque()
        self._gc_window = max(0, gc_window or 0)

    def __enter__(self) -> "SpoolWatcher":
        if INotify is not None:
            self._inotify = INotify()
            # NOTE: CLOSE_WRITE/MOVED_TO ensure we only process fully-written files.
            mask = (
                inotify_flags.CLOSE_WRITE
                | inotify_flags.MOVED_TO
                | inotify_flags.CREATE
            )
            self._watch_descriptor = self._inotify.add_watch(
                str(self.directory), mask
            )
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._inotify is not None and self._watch_descriptor is not None:
            with contextlib.suppress(Exception):
                self._inotify.rm_watch(self._watch_descriptor)
        if self._inotify is not None:
            with contextlib.suppress(Exception):
                self._inotify.close()

    def _remember(self, name: str) -> bool:
        if name in self._retired_set:
            return False
        if name in self._known:
            return False
        self._known.add(name)
        self._known_order.append(name)
        self._gc_known()
        return True

    def _gc_known(self) -> None:
        if not self._gc_window:
            return
        while len(self._known) > self._gc_window and self._known_order:
            candidate = self._known_order.popleft()
            if candidate in self._retired_set:
                continue
            self._known.discard(candidate)

    def _discover_existing(self) -> list[Path]:
        paths = sorted(self.directory.glob(f"{self.prefix}_*.ply"))
        fresh: list[Path] = []
        for path in paths:
            if self._remember(path.name):
                fresh.append(path)
        return fresh

    def drain_initial(self) -> list[Path]:
        """Return any files created before the watcher started."""

        return self._discover_existing()

    def wait_for_new(self, timeout: float = 1.0) -> list[Path]:
        """Block until new files arrive (event-driven when supported)."""

        if self._inotify is None:
            # NOTE: Maintain compatibility on systems lacking inotify by pausing
            # briefly before re-scanning.
            time.sleep(timeout)
            return self._discover_existing()

        try:
            events = self._inotify.read(timeout=int(timeout * 1000))
        except TimeoutError:
            return self._discover_existing()

        fresh: list[Path] = []
        for event in events:
            if not event.name:
                continue
            name = event.name
            if not name.startswith(f"{self.prefix}_") or not name.endswith(".ply"):
                continue
            if not self._remember(name):
                continue
            candidate = self.directory / name
            if candidate.exists():
                fresh.append(candidate)

        if not fresh:
            return self._discover_existing()
        return sorted(fresh)

    def mark_consumed(self, path: Path) -> None:
        """Release memory for processed files while avoiding re-processing."""

        name = path.name
        self._known.discard(name)
        with contextlib.suppress(ValueError):
            self._known_order.remove(name)
        if name in self._retired_set:
            return
        if len(self._retired) == self._retired.maxlen:
            oldest = self._retired.popleft()
            self._retired_set.discard(oldest)
        self._retired.append(name)
        self._retired_set.add(name)



def launch_bag_to_ply(
    args: argparse.Namespace,
    ply_dir: Path,
    *,
    shared_memory_host: str | None = None,
    shared_memory_port: int | None = None,
    shared_memory_only: bool = False,
) -> subprocess.Popen:
    cmd = [sys.executable, '-m', 'draco_roundtrip.io.bag_recorder',
           '--topic', args.topic,
           '--out', str(ply_dir),
           '--prefix', args.prefix,
           '--idle-timeout-sec', str(args.idle_timeout)]
    if args.best_effort:
        cmd.append('--best-effort')
    if args.max_frames:
        cmd += ['--max-frames', str(args.max_frames)]
    if shared_memory_host and shared_memory_port:
        cmd += [
            '--shared-memory-host',
            shared_memory_host,
            '--shared-memory-port',
            str(shared_memory_port),
        ]
        if shared_memory_only:
            cmd.append('--shared-memory-only')
    elif shared_memory_only:
        raise ValueError('shared_memory_only requires shared memory host/port')
    return subprocess.Popen(cmd, stdout=sys.stdout, stderr=sys.stderr)


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Streaming client with live playback")
    ap.add_argument('--bag', required=True)
    ap.add_argument('--topic', required=True)
    ap.add_argument('--prefix', required=True)
    ap.add_argument('--layout-profile', default=None,
                    help='Name or path of a layout profile (configs/*.profile.{yaml,json})')
    ap.add_argument('--data-root', default=None,
                    help='Base directory for generated artifacts (overrides profile/data root)')
    ap.add_argument('--ply-dir', default=None,
                    help='Override the spool directory for captured PLY frames')
    ap.add_argument(
        '--spool-gc-window',
        type=int,
        default=0,
        help='Maximum number of discovered spool files to remember before pruning (0 disables)',
    )
    add_encoder_arguments(
        ap,
        hint_option='--encoder',
        hint_dest='encoder',
        extra_option='--encoder-extra',
        extra_dest='encoder_extra',
    )
    ap.add_argument('--idle-timeout', type=float, default=10.0)
    ap.add_argument('--max-frames', type=int, default=0)
    ap.add_argument('--best-effort', action='store_true')
    ap.add_argument('--work-dir', default=None,
                    help='Override temporary directory for encoder scratch data')
    ap.add_argument('--decoded-dir', default=None,
                    help='Override directory where decoded frames from the server are stored')
    ap.add_argument('--quality-thresholds', default='{}',
                    help='JSON object describing max deltas for quality metrics (empty for informational only)')
    ap.add_argument('--quality-report-dir', default='artifacts/quality',
                    help='Directory where per-frame quality JSONL reports are written')
    ap.add_argument('--no-save-decoded', action='store_true',
                    help='Do not persist decoded responses from the server to disk')
    ap.add_argument('--server-host', default='127.0.0.1')
    ap.add_argument('--server-port', type=int, default=5000)
    ap.add_argument('--control-port', type=int, default=0,
                    help='Optional TCP port for a dedicated control-plane connection (0 disables)')
    ap.add_argument('--play-frame-id', default='lidar_link')
    ap.add_argument('--play-topic-prefix', default='stream_pair')
    ap.add_argument('--play-hz', type=float, default=10.0)
    ap.add_argument('--play-sample', type=int, default=50000)
    ap.add_argument('--metrics-sample', type=int, default=50000,
                    help='Maximum number of points sampled for client-side metrics (0 means use all points)')
    ap.add_argument('--resp-format', choices=('ply', 'pcd'), default='ply',
                    help='Expected format for decoded payloads returned by the server (default: %(default)s)')
    ap.add_argument('--qos-override', default=None,
                    help='Override QoS profile file. Defaults to layout profile or package configs')
    ap.add_argument('--socket-timeout', type=float, default=15.0,
                    help='Timeout (seconds) for socket operations; 0 disables the safeguard')
    protocol_help = available_protocols()
    ap.add_argument('--protocol',
                    choices=sorted(protocol_help.keys()),
                    default='binary',
                    help='Framing protocol to use (default: %(default)s). Options: '
                    + ', '.join(f"{name}={desc}" for name, desc in protocol_help.items()))
    ap.add_argument(
        '--transport',
        choices=('tcp', 'quic', 'udp_fec'),
        default='tcp',
        help='Transport layer for data plane. tcp만 구현되어 있으며 quic/udp_fec는 예약 상태입니다.',
    )
    ap.add_argument(
        '--tx-fragment-size',
        type=int,
        default=0,
        help='Binary 프로토콜에서 payload를 MTU 안전 조각으로 분할한다 (0은 비활성).',
    )
    ap.add_argument('--max-inflight', '--max-pending', dest='max_inflight', type=int, default=4,
                    help='Upper bound on in-flight frames awaiting ACK/decoded replies')
    ap.add_argument('--initial-inflight', type=int, default=None,
                    help='Initial TX window before adaptive control adjusts it (defaults to max)')
    ap.add_argument('--adaptive-window', action='store_true',
                    help='Enable RTT/throughput based TX window adaptation')
    ap.add_argument('--window-ema-alpha', type=float, default=0.2,
                    help='EMA smoothing factor for adaptive window telemetry (0-1)')
    ap.add_argument('--heartbeat-timeout', type=float, default=10.0,
                    help='Fail the session if no ACK/heartbeat is observed within this many seconds')
    ap.add_argument(
        '--ack-timeout',
        type=float,
        default=0.5,
        help='Base ACK timeout in seconds before adaptive adjustments (minimum clamp)',
    )
    ap.add_argument(
        '--ack-timeout-min',
        type=float,
        default=0.5,
        help='Lower bound for adaptive ACK timeout (seconds)',
    )
    ap.add_argument(
        '--ack-timeout-max',
        type=float,
        default=2.0,
        help='Upper bound for adaptive ACK timeout (seconds)',
    )
    ap.add_argument(
        '--ack-timeout-strikes',
        type=int,
        default=3,
        help='Number of consecutive ACK timeout strikes before failing the session',
    )
    ap.add_argument('--capture-queue', type=int, default=4,
                    help='Maximum capture queue depth before applying backpressure')
    ap.add_argument('--encode-workers', type=int, default=2,
                    help='Number of concurrent encoder workers for the async pipeline')
    ap.add_argument('--tcp-nodelay', action='store_true',
                    help='Disable Nagle aggregation to reduce latency for interactive playback')
    ap.add_argument('--socket-buffer-kb', type=int, default=0,
                    help='Resize socket send/receive buffers (KiB) to better saturate fast links')
    ap.add_argument(
        '--socket-buffer-autotune',
        action='store_true',
        help='커널 소켓 버퍼 자동 튜닝을 요청한다 (SO_SNDBUF/SO_RCVBUF=0).',
    )
    ap.add_argument('--capture-transport',
                    choices=('filesystem', 'shared-memory'),
                    default='shared-memory',
                    help='Frame capture backend: filesystem spool (legacy) or shared-memory zero copy')
    ap.add_argument(
        '--metrics-out',
        '--telemetry-out',
        dest='metrics_out',
        default='artifacts/perf/client_latest.json',
        help='텔레메트리 JSON 출력 경로 (스키마 준수).',
    )
    ap.add_argument('--print-metrics', action='store_true',
                    help='Stream per-frame latency/accuracy metrics to stdout during playback')
    return ap



async def run_client(args: argparse.Namespace) -> None:
    session_summary: dict[str, object] | None = None
    fragment_size = _validate_client_config(args)
    _log_effective_config(args, fragment_size)
    layout = resolve_data_layout(
        {
            'ply_dir': 'ply_stream',
            'work_dir': 'client_work',
            'decoded_dir': 'decoded_from_server',
        },
        profile=args.layout_profile,
        overrides={
            'ply_dir': args.ply_dir,
            'work_dir': args.work_dir,
            'decoded_dir': args.decoded_dir,
        },
        base=args.data_root,
        ensure=True,
    )

    encoder_hint, encoder_options, _ = resolve_encoder_options(args)
    encoder_path = find_draco_encoder(encoder_hint)

    ply_dir = layout['ply_dir']
    work_dir = layout['work_dir']
    decoded_dir = layout['decoded_dir']

    try:
        thresholds_raw = json.loads(args.quality_thresholds) if args.quality_thresholds else {}
        if not isinstance(thresholds_raw, dict):
            raise ValueError("quality thresholds must be a JSON object")
        quality_thresholds = {str(key): float(value) for key, value in thresholds_raw.items()}
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"invalid --quality-thresholds payload: {exc}") from exc
    quality_report_path: Path | None = None
    if args.quality_report_dir:
        quality_dir = Path(args.quality_report_dir).expanduser()
        quality_report_path = (quality_dir / f"{args.prefix}_quality.jsonl").resolve()
        quality_report_path.parent.mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(OSError):
            quality_report_path.unlink()

    bag_cmd = ['ros2', 'bag', 'play', str(Path(args.bag).expanduser().resolve())]
    qos_override = resolve_qos_override(args.qos_override, profile=layout.profile)
    if qos_override is not None:
        bag_cmd += ['--qos-profile-overrides-path', str(qos_override)]
    else:
        print('[CLIENT] WARN: QoS override file not found, falling back to recorded QoS', file=sys.stderr)

    bag_process = subprocess.Popen(bag_cmd)
    saver_proc: subprocess.Popen | None = None
    shared_receiver: SharedMemoryReceiver | None = None

    to_play: queue.Queue = queue.Queue()
    playback_thread = start_playback_thread(to_play, args.play_frame_id, args.play_topic_prefix, args.play_hz)

    stop_event = asyncio.Event()
    bag_done = asyncio.Event()
    saver_done = asyncio.Event()

    traffic = TrafficStats()
    pipeline_stats = PipelineStats()
    frame_counter = itertools.count()
    inflight: Dict[int, FrameContext] = {}
    acks_pending: set[int] = set()
    pending_inflight = 0
    pending_acks = 0
    max_window = max(1, args.max_inflight)
    initial_window = max(1, min(args.initial_inflight or max_window, max_window))
    window_controller = WindowController(
        base_limit=initial_window,
        max_limit=max_window,
        adaptive=args.adaptive_window,
        alpha=max(0.01, min(0.99, args.window_ema_alpha)),
    )
    ack_policy = AckTimeoutPolicy(
        base=args.ack_timeout,
        minimum=args.ack_timeout_min,
        maximum=args.ack_timeout_max,
    )
    telemetry = Telemetry(
        role="client",
        transport=args.transport,
        protocol=args.protocol,
        fragment_size=fragment_size,
        socket_buffer_autotune=args.socket_buffer_autotune,
    )
    control_plane = ControlPlane(role="client")
    session_tracker = SessionTracker()
    heartbeat_watch = HeartbeatWatch()
    start_time = time.monotonic()

    try:
        with contextlib.ExitStack() as conn_stack:
            sock = conn_stack.enter_context(
                socket.create_connection(
                    (args.server_host, args.server_port),
                    timeout=args.socket_timeout if args.socket_timeout > 0 else None,
                )
            )
            if args.socket_timeout > 0:
                sock.settimeout(args.socket_timeout)
            if args.tcp_nodelay:
                with contextlib.suppress(OSError):
                    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            if args.socket_buffer_kb > 0:
                buf_size = args.socket_buffer_kb * 1024
                for opt in (socket.SO_SNDBUF, socket.SO_RCVBUF):
                    with contextlib.suppress(OSError):
                        sock.setsockopt(socket.SOL_SOCKET, opt, buf_size)
            elif args.socket_buffer_autotune:
                for opt in (socket.SO_SNDBUF, socket.SO_RCVBUF):
                    with contextlib.suppress(OSError):
                        sock.setsockopt(socket.SOL_SOCKET, opt, 0)
            protocol = resolve_protocol(args.protocol)
            print(
                f"[CLIENT] Connected to {args.server_host}:{args.server_port} using {protocol.name} protocol"
            )
            control_plane.on_connected(time.monotonic_ns())

            control_channel: ControlChannel | None = None
            control_sock: socket.socket | None = None
            if args.control_port > 0:
                control_sock = conn_stack.enter_context(
                    socket.create_connection(
                        (args.server_host, args.control_port),
                        timeout=args.socket_timeout if args.socket_timeout > 0 else None,
                    )
                )
                if args.socket_timeout > 0:
                    control_sock.settimeout(args.socket_timeout)
                if args.tcp_nodelay:
                    with contextlib.suppress(OSError):
                        control_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                if args.socket_buffer_kb > 0:
                    buf_size = args.socket_buffer_kb * 1024
                    for opt in (socket.SO_SNDBUF, socket.SO_RCVBUF):
                        with contextlib.suppress(OSError):
                            control_sock.setsockopt(socket.SOL_SOCKET, opt, buf_size)
                elif args.socket_buffer_autotune:
                    for opt in (socket.SO_SNDBUF, socket.SO_RCVBUF):
                        with contextlib.suppress(OSError):
                            control_sock.setsockopt(socket.SOL_SOCKET, opt, 0)
                control_protocol = resolve_protocol(args.protocol)
                control_channel = ControlChannel(sock=control_sock, protocol=control_protocol)
                print(
                    f"[CLIENT] Control channel connected to {args.server_host}:{args.control_port}"
                    f" using {control_protocol.name} protocol"
                )

            loop = asyncio.get_running_loop()
            reply_queue: "asyncio.Queue[ReplyEvent]" = asyncio.Queue()
            pump_stop = threading.Event()
            pump = ReplyPump(
                sock,
                reply_queue,
                pump_stop,
                protocol,
                loop,
                channel=DATA_CHANNEL,
            )
            control_pump: ReplyPump | None = None
            if control_channel is not None:
                control_pump = ReplyPump(
                    control_channel.sock,
                    reply_queue,
                    pump_stop,
                    control_channel.protocol,
                    loop,
                    channel=CONTROL_CHANNEL,
                )

            with contextlib.ExitStack() as stack:
                frame_supplier: FilesystemFrameSupplier | SharedMemoryFrameSupplier
                if args.capture_transport == 'filesystem':
                    watcher = stack.enter_context(
                        SpoolWatcher(ply_dir, args.prefix, gc_window=args.spool_gc_window)
                    )
                    frame_supplier = FilesystemFrameSupplier(watcher)
                elif args.capture_transport == 'shared-memory':
                    shared_receiver = SharedMemoryReceiver()
                    shared_receiver.start()
                    stack.callback(shared_receiver.stop)
                    frame_supplier = SharedMemoryFrameSupplier(shared_receiver)
                else:
                    raise ValueError(f"unknown capture transport '{args.capture_transport}'")

                shared_host = shared_receiver.host if shared_receiver else None
                shared_port = shared_receiver.port if shared_receiver else None
                saver_proc = launch_bag_to_ply(
                    args,
                    ply_dir,
                    shared_memory_host=shared_host,
                    shared_memory_port=shared_port,
                    shared_memory_only=(args.capture_transport == 'shared-memory'),
                )

                if args.encode_workers <= 0:
                    raise ValueError('encode_workers must be positive')

                capture_queue: "asyncio.PriorityQueue[tuple[float, int, CapturePayload | None]]" = (
                    asyncio.PriorityQueue(maxsize=max(1, args.capture_queue))
                )
                network_queue: "asyncio.Queue[Optional[EncodedFrame]]" = asyncio.Queue(
                    maxsize=max(1, args.max_inflight)
                )
                inflight_condition = asyncio.Condition()

                tasks: list[asyncio.Task[None]] = []
                tasks.append(
                    asyncio.create_task(
                        capture_stage(
                            frame_supplier,
                            capture_queue,
                            stop_event=stop_event,
                            bag_done=bag_done,
                            saver_done=saver_done,
                            encode_workers=args.encode_workers,
                            traffic=traffic,
                        )
                    )
                )
                for worker_id in range(args.encode_workers):
                    tasks.append(
                        asyncio.create_task(
                            encode_worker(
                                worker_id,
                                capture_queue,
                                network_queue,
                                reply_queue,
                                encoder_options=encoder_options,
                                encoder_path=encoder_path,
                                work_dir=work_dir,
                                stats=pipeline_stats,
                                stop_event=stop_event,
                                traffic=traffic,
                            )
                        )
                    )
                tasks.append(
                    asyncio.create_task(
                        network_sender(
                            sock,
                            protocol,
                            network_queue,
                            inflight,
                            acks_pending,
                            stats=pipeline_stats,
                            traffic=traffic,
                            stop_event=stop_event,
                            inflight_condition=inflight_condition,
                            encode_workers=args.encode_workers,
                            window=window_controller,
                            session=session_tracker,
                            heartbeat_watch=heartbeat_watch,
                            heartbeat_timeout=args.heartbeat_timeout,
                            control=control_channel,
                            fragment_size=fragment_size,
                            use_binary=(protocol.name == "binary"),
                            control_plane=control_plane,
                            ack_policy=ack_policy,
                        )
                    )
                )
                tasks.append(
                    asyncio.create_task(
                        reply_consumer(
                            reply_queue,
                            inflight,
                            stats=pipeline_stats,
                            traffic=traffic,
                            stop_event=stop_event,
                            inflight_condition=inflight_condition,
                            window=window_controller,
                            acks_pending=acks_pending,
                            decoded_dir=decoded_dir,
                            to_play=to_play,
                            play_sample=args.play_sample,
                            frame_counter=frame_counter,
                            print_metrics=args.print_metrics,
                            quality_report_path=quality_report_path,
                            quality_thresholds=quality_thresholds,
                            save_decoded=not args.no_save_decoded,
                            metrics_sample=args.metrics_sample,
                            default_resp_format=args.resp_format,
                            heartbeat_timeout=args.heartbeat_timeout,
                            session=session_tracker,
                            heartbeat_watch=heartbeat_watch,
                            control_plane=control_plane,
                            use_binary=(protocol.name == "binary"),
                            ack_timeout_strikes=args.ack_timeout_strikes,
                        )
                    )
                )
                tasks.append(
                    asyncio.create_task(
                        monitor_process(bag_process, bag_done, 'ros2 bag', stop_event)
                    )
                )
                if saver_proc is not None:
                    tasks.append(
                        asyncio.create_task(
                            monitor_process(saver_proc, saver_done, 'bag_to_ply', stop_event)
                        )
                    )
                else:
                    saver_done.set()

                pump.start()
                if control_pump is not None:
                    control_pump.start()
                try:
                    await asyncio.gather(*tasks)
                except Exception:
                    stop_event.set()
                    for task in tasks:
                        task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
                    raise
                finally:
                    pump_stop.set()
                    for thread in (pump, control_pump):
                        if thread is not None and thread.is_alive():
                            thread.join(timeout=1.0)
    finally:
        session_summary = session_tracker.snapshot()
        if session_tracker.state not in (
            SessionState.DEGRADED,
            SessionState.CLOSING,
            SessionState.SOFT_DEGRADED,
        ):
            await session_tracker.transition(SessionState.CLOSING, "client shutdown")
        stop_event.set()
        pending_inflight = len(inflight)
        pending_acks = len(acks_pending)
        for ctx in list(inflight.values()):
            with contextlib.suppress(Exception):
                ctx.handle.on_aborted()
        inflight.clear()
        to_play.put(None)
        if playback_thread.is_alive():
            playback_thread.join(timeout=1.0)
        _terminate_process(bag_process, 'ros2 bag')
        if saver_proc is not None:
            _terminate_process(saver_proc, 'bag_to_ply')

    control_plane.on_shutdown()
    elapsed = max(time.monotonic() - start_time, 1e-6)
    frames_processed = pipeline_stats.round_trip.count
    frames_sent = pipeline_stats.encode_to_send.count
    latency_percentiles = pipeline_stats.latency_percentiles()
    rtt_percentiles = pipeline_stats.percentiles_for(pipeline_stats.network_rtt_samples)
    ack_percentiles = pipeline_stats.percentiles_for(pipeline_stats.ack_latency_samples)

    throughput_avg_mbps = (traffic.sent * 8 / elapsed) / 1e6
    throughput_peak_mbps = max(traffic.send_mbps_samples or [throughput_avg_mbps])
    receive_mbps = (traffic.received * 8 / elapsed) / 1e6

    session_snapshot = session_summary or session_tracker.snapshot()
    session_state = session_snapshot.get("state", SessionState.OK.value)
    session_reason = session_snapshot.get("reason")

    print('[CLIENT] ---- Transfer summary ----')
    print(f"  elapsed: {elapsed:.2f} s")
    print(f"  frames: sent={frames_sent} completed={frames_processed}")
    print(f"  sent: {traffic.sent} bytes ({throughput_avg_mbps:.3f} Mbps)")
    print(f"  received: {traffic.received} bytes ({receive_mbps:.3f} Mbps)")
    if latency_percentiles:
        print("  latency percentiles (capture→reply):")
        for label in ("p50", "p95", "p99"):
            if label in latency_percentiles:
                print(f"    {label}: {latency_percentiles[label] * 1000.0:.2f} ms")
    print(f"  session: {session_state} reason={session_reason}")
    print('  stage metrics:')
    print(f"    capture→encode: {pipeline_stats.capture_to_encode.summary()}")
    print(f"    encode latency: {pipeline_stats.encode_time.summary()}")
    print(f"    encode→send: {pipeline_stats.encode_to_send.summary()}")
    print(f"    round-trip: {pipeline_stats.round_trip.summary()}")
    print(f"    network RTT: {pipeline_stats.network_rtt.summary()}")
    print(f"    ACK latency: {pipeline_stats.ack_latency.summary()}")
    print(
        f"  inflight_peak: {traffic.inflight_peak} window_limit={window_controller.limit()}"
        f" adaptive={'on' if args.adaptive_window else 'off'}"
    )
    print(
        f"  queue peaks: capture={traffic.capture_depth_peak} network={traffic.network_depth_peak}"
    )
    control_pending = control_plane.pending
    print(
        f"  drops/skipped: {pipeline_stats.skipped_frames} errors={pipeline_stats.error_frames}"
        f" pending={pending_inflight} pending_acks={pending_acks} control_pending={control_pending}"
    )

    latency_summary = {
        label: (latency_percentiles[label] * 1000.0 if label in latency_percentiles else None)
        for label in ("p50", "p95", "p99")
    }
    summary_line = {
        "elapsed_sec": elapsed,
        "bytes_out": traffic.sent,
        "bytes_in": traffic.received,
        "mbps": {
            "send_avg": throughput_avg_mbps,
            "send_peak": throughput_peak_mbps,
            "recv_avg": receive_mbps,
        },
        "frames_sent": frames_sent,
        "frames_completed": frames_processed,
        "latency_ms": latency_summary,
        "max_queue_depths": {
            "capture": traffic.capture_depth_peak,
            "network": traffic.network_depth_peak,
        },
        "pending": pending_inflight,
        "acks_pending": pending_acks,
        "control_pending": control_pending,
        "errors": pipeline_stats.error_frames,
        "skipped": pipeline_stats.skipped_frames,
        "session_state": session_state,
        "session_reason": session_reason,
    }
    print(json.dumps(summary_line, sort_keys=True))

    metrics_out_path = Path(args.metrics_out).expanduser()
    metrics_out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        control_pending = control_plane.pending
        control_state = control_plane.state
        pending_ack_total = max(pending_acks, control_pending)
        queue_pending = (
            pending_inflight + pending_ack_total if control_state == ControlState.FAILED else 0
        )
        if control_state != ControlState.FAILED:
            if pending_inflight != 0 or pending_acks != 0 or control_pending != 0:
                raise ValueError(
                    "pending frames remain at shutdown: "
                    f"inflight={pending_inflight} pending_acks={pending_acks} "
                    f"control_plane={control_pending}"
                )
            if control_state != ControlState.TERMINATED:
                raise ValueError(
                    "control plane must reach TERMINATED before telemetry export: "
                    f"state={control_state.value}"
                )
        metrics_block = {
            "latency_ms": percentiles_block(latency_percentiles, scale=1000.0),
            "rtt_ms": percentiles_block(rtt_percentiles, scale=1000.0),
            "ack_latency_ms": percentiles_block(ack_percentiles, scale=1000.0),
            "throughput_mbps": {
                "avg": throughput_avg_mbps,
                "peak": throughput_peak_mbps,
            },
            "queues": {
                "capture_max": traffic.capture_depth_peak,
                "encode_max": traffic.network_depth_peak,
                "decode_max": 0,
                "pending": queue_pending,
            },
            "frames": {
                "sent": frames_sent,
                "acked": max(0, frames_sent - pending_ack_total),
                "dropped": pipeline_stats.error_frames,
                "skipped": pipeline_stats.skipped_frames,
            },
        }
        session_overrides_payload = {
            "client_state": session_state,
            "client_state_reason": session_reason,
        }
        if control_state == ControlState.FAILED:
            session_overrides_payload.setdefault("state", ControlState.FAILED.value)
        telemetry_payload = telemetry.build(
            control_plane=control_plane,
            metrics=metrics_block,
            session_overrides=session_overrides_payload,
            inflight_pending=pending_inflight,
        )
        metrics_out_path.write_text(json.dumps(telemetry_payload, indent=2), encoding='utf-8')
        print(f"[CLIENT] Wrote telemetry to {metrics_out_path}")
    except Exception as exc:
        print(f"[CLIENT] WARN: Failed to write telemetry file: {exc}")


def main(argv: Iterable[str] | None = None) -> None:
    args = build_arg_parser().parse_args(argv)
    asyncio.run(run_client(args))


if __name__ == '__main__':
    main()

# 변경 요약:
# - 비동기 큐 기반 파이프라인으로 캡처→인코딩→전송 단계를 병렬화하고 역압을 구현했습니다.
# - 인플라이트 제어와 우선순위 캡처를 통해 설계 문서의 흐름 제어 전략을 코드에 반영했습니다.
# - 파이프라인 계측치를 로그 및 JSON 파일로 기록해 왕복 지연 최적화 실험을 지원합니다.
