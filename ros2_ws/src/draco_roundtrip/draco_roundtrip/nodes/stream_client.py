#!/usr/bin/env python3
"""Stream rosbag frames, encode/send to server, replay decoded results to RViz."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import itertools
import json
import queue
import socket
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field as dataclass_field
from multiprocessing import shared_memory
from pathlib import Path
from typing import Deque, Dict, Iterable, Optional, Protocol

import numpy as np

from draco_tools.core.encoder import (
    add_encoder_arguments,
    encode_frame,
    find_draco_encoder,
    format_encode_log,
    resolve_encoder_options,
)
from draco_roundtrip.utils.config import resolve_data_layout, resolve_qos_override
from draco_roundtrip.utils.metrics import compute_basic_metrics
from draco_roundtrip.io.ply_codec import save_xyz
from draco_roundtrip.utils.ply_io import (
    load_points as load_xyz,
    load_points_from_bytes as load_xyz_from_bytes,
)
from draco_roundtrip.utils.protocol import (
    ConnectionClosed,
    Message,
    MSG_DATA,
    MSG_EOF,
    MSG_ERROR,
    ProtocolHandler,
    available_protocols,
    resolve_protocol,
)
from draco_roundtrip.shared_memory import SharedMemoryReceiver, SharedMemoryDescriptor
from draco_roundtrip.ros.playback import start_playback_thread


_capture_seq = itertools.count()
_CAPTURE_SENTINEL = object()
_ENCODE_SENTINEL = object()


async def _put_with_retry(
    queue: asyncio.Queue,
    item: object,
    *,
    stop_event: asyncio.Event | None = None,
) -> bool:
    """Insert an item even if the queue is temporarily full (backpressure friendly).

    Returns ``True`` if the item was enqueued. When ``stop_event`` is provided and
    set while waiting for space, the enqueue is abandoned and ``False`` is
    returned so callers can bail out instead of deadlocking on a full queue.
    """

    while True:
        if stop_event is not None and stop_event.is_set():
            return False
        try:
            queue.put_nowait(item)
            return True
        except asyncio.QueueFull:
            if stop_event is not None and stop_event.is_set():
                return False
            await asyncio.sleep(0.05)


async def _signal_capture_stop(queue: "asyncio.PriorityQueue", count: int) -> None:
    for _ in range(count):
        await _put_with_retry(queue, (float("inf"), next(_capture_seq), None))


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

    handle: "FrameHandle"
    captured_at: float
    encoded_at: float
    sent_at: float
    payload_size: int


@dataclass(slots=True)
class ReplyEvent:
    kind: str
    message: Message | None = None
    error: BaseException | None = None


@dataclass(slots=True)
class CapturePayload:
    """Represent a frame awaiting encoding with capture timing info."""

    handle: "FrameHandle"
    captured_at: float


@dataclass(slots=True)
class EncodedFrame:
    """Encoded payload ready to be sent across the network."""

    handle: "FrameHandle"
    payload: bytes
    captured_at: float
    encoded_at: float


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

    def reset(self) -> None:
        self.capture_to_encode = StageStats()
        self.encode_time = StageStats()
        self.encode_to_send = StageStats()
        self.round_trip = StageStats()


@dataclass(slots=True)
class TrafficStats:
    """Track aggregate byte counters for the session."""

    sent: int = 0
    received: int = 0


class ReplyPump(threading.Thread):
    """Background thread that continuously drains replies from the server."""

    def __init__(
        self,
        sock: socket.socket,
        queue: "asyncio.Queue[ReplyEvent]",
        stop_event: threading.Event,
        protocol: ProtocolHandler,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        super().__init__(daemon=True)
        self._sock = sock
        self._queue = queue
        self._stop_event = stop_event
        self._protocol = protocol
        self._loop = loop

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
                self._submit(ReplyEvent(kind="error", error=exc))
                return
            if message is None:
                self._submit(ReplyEvent(kind="closed"))
                return
            self._submit(ReplyEvent(kind="message", message=message))
            if message.kind == MSG_EOF:
                return


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
    idle_rounds: int = 5,
) -> None:
    """Monitor the capture source and enqueue frames for encoding."""

    try:
        initial = frame_supplier.drain_initial()
        for handle in initial:
            payload = CapturePayload(handle=handle, captured_at=time.monotonic())
            await capture_queue.put((handle.priority_hint(), next(_capture_seq), payload))
        empty_rounds = 0
        while not stop_event.is_set():
            handles = await asyncio.to_thread(frame_supplier.wait_for_new, 0.2)
            if handles:
                empty_rounds = 0
                for handle in handles:
                    payload = CapturePayload(handle=handle, captured_at=time.monotonic())
                    await capture_queue.put((handle.priority_hint(), next(_capture_seq), payload))
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
    *,
    encoder_options,
    encoder_path: Path,
    work_dir: Path,
    stats: PipelineStats,
    stop_event: asyncio.Event,
) -> None:
    """Encode frames pulled from the capture queue and forward them."""

    while not stop_event.is_set():
        priority, _, payload = await capture_queue.get()
        if payload is None:
            capture_queue.task_done()
            await _put_with_retry(network_queue, None, stop_event=stop_event)
            break
        handle = payload.handle
        captured_at = payload.captured_at
        encode_start = time.monotonic()
        try:
            encoder_input = await asyncio.to_thread(handle.ensure_encoder_input, work_dir)
            result = await asyncio.to_thread(
                encode_frame,
                encoder_input,
                work_dir,
                encoder_options,
                encoder_path,
                False,
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
            encoded = EncodedFrame(
                handle=handle,
                payload=drc_bytes,
                captured_at=captured_at,
                encoded_at=encoded_at,
            )
            if not await _put_with_retry(network_queue, encoded, stop_event=stop_event):
                with contextlib.suppress(Exception):
                    handle.on_aborted()
                break
        except asyncio.CancelledError:
            stop_event.set()
            raise
        except Exception as exc:
            print(f"[CLIENT] ENCODE FAIL {handle.name}: {exc}")
            with contextlib.suppress(Exception):
                handle.on_consumed()
        finally:
            capture_queue.task_done()


async def network_sender(
    sock: socket.socket,
    protocol: ProtocolHandler,
    network_queue: "asyncio.Queue[Optional[EncodedFrame]]",
    inflight: Dict[str, FrameContext],
    *,
    stats: PipelineStats,
    traffic: TrafficStats,
    stop_event: asyncio.Event,
    inflight_condition: asyncio.Condition,
    encode_workers: int,
    max_inflight: int,
) -> None:
    """Send encoded frames while respecting inflight limits."""

    encode_finished = 0
    eof_sent = False
    while not stop_event.is_set():
        item = await network_queue.get()
        if item is None:
            encode_finished += 1
            network_queue.task_done()
            if encode_finished >= encode_workers and not eof_sent:
                async with inflight_condition:
                    while inflight and not stop_event.is_set():
                        await inflight_condition.wait()
                if not inflight and not stop_event.is_set():
                    message = Message(kind=MSG_EOF, name="", payload=b"")
                    try:
                        await asyncio.to_thread(protocol.send, sock, message)
                        print("[CLIENT] Sent EOF marker to server")
                        eof_sent = True
                    except Exception as exc:
                        print(f"[CLIENT] ERROR sending EOF marker: {exc}")
                        stop_event.set()
                        break
            if eof_sent:
                break
            continue

        encoded = item
        async with inflight_condition:
            while len(inflight) >= max_inflight and not stop_event.is_set():
                await inflight_condition.wait()
        message = Message(kind=MSG_DATA, name=encoded.handle.name, payload=encoded.payload)
        try:
            await asyncio.to_thread(protocol.send, sock, message)
        except Exception as exc:
            print(f"[CLIENT] ERROR sending {encoded.handle.name}: {exc}")
            stop_event.set()
            with contextlib.suppress(Exception):
                encoded.handle.on_aborted()
            async with inflight_condition:
                inflight_condition.notify_all()
            network_queue.task_done()
            break
        sent_at = time.monotonic()
        stats.encode_to_send.record(sent_at - encoded.encoded_at)
        inflight[encoded.handle.name] = FrameContext(
            handle=encoded.handle,
            captured_at=encoded.captured_at,
            encoded_at=encoded.encoded_at,
            sent_at=sent_at,
            payload_size=len(encoded.payload),
        )
        traffic.sent += len(encoded.payload)
        print(f"[CLIENT] Sent {encoded.handle.name} ({len(encoded.payload)} bytes)")
        network_queue.task_done()


async def reply_consumer(
    reply_queue: "asyncio.Queue[ReplyEvent]",
    inflight: Dict[str, FrameContext],
    *,
    stats: PipelineStats,
    traffic: TrafficStats,
    stop_event: asyncio.Event,
    inflight_condition: asyncio.Condition,
    decoded_dir: Path,
    to_play: "queue.Queue",
    play_sample: int,
    frame_counter: itertools.count,
) -> None:
    """Process replies from the server and release inflight slots."""

    while not stop_event.is_set():
        event = await reply_queue.get()
        if event.kind == "error" and event.error:
            print(f"[CLIENT] ERROR from reply pump: {event.error}")
            stop_event.set()
            reply_queue.task_done()
            break
        if event.kind == "closed":
            print("[CLIENT] Connection closed by server")
            stop_event.set()
            reply_queue.task_done()
            break
        if event.kind != "message" or event.message is None:
            reply_queue.task_done()
            continue
        message = event.message
        if message.kind == MSG_EOF:
            print("[CLIENT] EOF handshake complete")
            stop_event.set()
            reply_queue.task_done()
            break
        stem = Path(message.name or "").stem
        async with inflight_condition:
            ctx = inflight.pop(stem, None)
            inflight_condition.notify_all()
        if ctx is None:
            print(f"[CLIENT] WARN: Received reply for unknown frame {message.name}")
            reply_queue.task_done()
            continue
        if message.kind == MSG_ERROR:
            detail = message.payload.decode(errors="ignore")
            print(f"[CLIENT] SERVER ERROR for {message.name or stem}: {detail}")
            with contextlib.suppress(Exception):
                ctx.handle.on_consumed()
            reply_queue.task_done()
            continue
        traffic.received += len(message.payload)
        decoded_name = message.name or f"{stem}.decoded"
        if not decoded_name.endswith(".ply"):
            decoded_name = f"{decoded_name}.ply"
        decoded_path = decoded_dir / decoded_name
        await asyncio.to_thread(decoded_path.write_bytes, message.payload)
        pts_src = await asyncio.to_thread(ctx.handle.load_source_points)
        pts_dec = await asyncio.to_thread(load_xyz_from_bytes, message.payload)
        metrics = await asyncio.to_thread(compute_basic_metrics, pts_src, pts_dec, play_sample)
        stats.round_trip.record(time.monotonic() - ctx.sent_at)
        frame_idx = next(frame_counter)
        to_play.put((frame_idx, decoded_name, pts_src, pts_dec))
        print(f"[CLIENT] Metrics {decoded_name}: {metrics}")
        with contextlib.suppress(Exception):
            ctx.handle.on_consumed()
        reply_queue.task_done()


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

    def __init__(self, directory: Path, prefix: str):
        self.directory = directory
        self.prefix = prefix
        self._inotify: Optional[INotify] = None
        self._watch_descriptor: Optional[int] = None
        self._known: set[str] = set()
        self._retired: Deque[str] = deque(maxlen=self._history_limit)
        self._retired_set: set[str] = set()

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
        return True

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
    ap.add_argument('--server-host', default='127.0.0.1')
    ap.add_argument('--server-port', type=int, default=5000)
    ap.add_argument('--play-frame-id', default='lidar_link')
    ap.add_argument('--play-topic-prefix', default='stream_pair')
    ap.add_argument('--play-hz', type=float, default=10.0)
    ap.add_argument('--play-sample', type=int, default=50000)
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
    ap.add_argument('--max-inflight', type=int, default=1,
                    help='Maximum number of frames to pipeline before waiting for replies')
    ap.add_argument('--capture-queue', type=int, default=4,
                    help='Maximum capture queue depth before applying backpressure')
    ap.add_argument('--encode-workers', type=int, default=2,
                    help='Number of concurrent encoder workers for the async pipeline')
    ap.add_argument('--tcp-nodelay', action='store_true',
                    help='Disable Nagle aggregation to reduce latency for interactive playback')
    ap.add_argument('--socket-buffer-kb', type=int, default=0,
                    help='Resize socket send/receive buffers (KiB) to better saturate fast links')
    ap.add_argument('--capture-transport',
                    choices=('filesystem', 'shared-memory'),
                    default='shared-memory',
                    help='Frame capture backend: filesystem spool (legacy) or shared-memory zero copy')
    ap.add_argument('--metrics-out', default=None,
                    help='Optional path to write pipeline timing/throughput metrics as JSON')
    return ap



async def run_client(args: argparse.Namespace) -> None:
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
    inflight: Dict[str, FrameContext] = {}
    start_time = time.monotonic()

    try:
        with socket.create_connection(
            (args.server_host, args.server_port),
            timeout=args.socket_timeout if args.socket_timeout > 0 else None,
        ) as sock:
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
            protocol = resolve_protocol(args.protocol)
            print(
                f"[CLIENT] Connected to {args.server_host}:{args.server_port} using {protocol.name} protocol"
            )

            loop = asyncio.get_running_loop()
            reply_queue: "asyncio.Queue[ReplyEvent]" = asyncio.Queue()
            pump_stop = threading.Event()
            pump = ReplyPump(sock, reply_queue, pump_stop, protocol, loop)

            with contextlib.ExitStack() as stack:
                frame_supplier: FilesystemFrameSupplier | SharedMemoryFrameSupplier
                if args.capture_transport == 'filesystem':
                    watcher = stack.enter_context(SpoolWatcher(ply_dir, args.prefix))
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
                                encoder_options=encoder_options,
                                encoder_path=encoder_path,
                                work_dir=work_dir,
                                stats=pipeline_stats,
                                stop_event=stop_event,
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
                            stats=pipeline_stats,
                            traffic=traffic,
                            stop_event=stop_event,
                            inflight_condition=inflight_condition,
                            encode_workers=args.encode_workers,
                            max_inflight=max(1, args.max_inflight),
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
                            decoded_dir=decoded_dir,
                            to_play=to_play,
                            play_sample=args.play_sample,
                            frame_counter=frame_counter,
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
                    if pump.is_alive():
                        pump.join(timeout=1.0)
    finally:
        stop_event.set()
        for ctx in list(inflight.values()):
            with contextlib.suppress(Exception):
                ctx.handle.on_aborted()
        to_play.put(None)
        if playback_thread.is_alive():
            playback_thread.join(timeout=1.0)
        _terminate_process(bag_process, 'ros2 bag')
        if saver_proc is not None:
            _terminate_process(saver_proc, 'bag_to_ply')

    elapsed = max(time.monotonic() - start_time, 1e-6)
    frames_processed = pipeline_stats.round_trip.count
    print('[CLIENT] ---- Transfer summary ----')
    print(f"  elapsed: {elapsed:.2f} s")
    print(f"  frames: {frames_processed}")
    print(f"  sent: {traffic.sent} bytes ({traffic.sent * 8 / elapsed / 1e6:.3f} Mbps)")
    print(
        f"  received: {traffic.received} bytes"
        f" ({traffic.received * 8 / elapsed / 1e6:.3f} Mbps)"
    )
    print('  stage metrics:')
    print(f"    capture→encode: {pipeline_stats.capture_to_encode.summary()}")
    print(f"    encode latency: {pipeline_stats.encode_time.summary()}")
    print(f"    encode→send: {pipeline_stats.encode_to_send.summary()}")
    print(f"    round-trip: {pipeline_stats.round_trip.summary()}")

    metrics_out_path = Path(args.metrics_out).expanduser() if args.metrics_out else work_dir / 'pipeline_metrics.json'
    metrics_out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        metrics_payload = {
            'elapsed_sec': elapsed,
            'frames': frames_processed,
            'bytes_sent': traffic.sent,
            'bytes_received': traffic.received,
            'capture_to_encode': pipeline_stats.capture_to_encode.as_dict(),
            'encode_latency': pipeline_stats.encode_time.as_dict(),
            'encode_to_send': pipeline_stats.encode_to_send.as_dict(),
            'round_trip': pipeline_stats.round_trip.as_dict(),
        }
        metrics_out_path.write_text(json.dumps(metrics_payload, indent=2), encoding='utf-8')
        print(f"[CLIENT] Wrote pipeline metrics to {metrics_out_path}")
    except Exception as exc:
        print(f"[CLIENT] WARN: Failed to write metrics file: {exc}")


def main(argv: Iterable[str] | None = None) -> None:
    args = build_arg_parser().parse_args(argv)
    asyncio.run(run_client(args))


if __name__ == '__main__':
    main()

# 변경 요약:
# - 비동기 큐 기반 파이프라인으로 캡처→인코딩→전송 단계를 병렬화하고 역압을 구현했습니다.
# - 인플라이트 제어와 우선순위 캡처를 통해 설계 문서의 흐름 제어 전략을 코드에 반영했습니다.
# - 파이프라인 계측치를 로그 및 JSON 파일로 기록해 왕복 지연 최적화 실험을 지원합니다.
