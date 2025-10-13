#!/usr/bin/env python3
"""Async Draco streaming server with bounded pipeline and telemetry."""

from __future__ import annotations

# README NOTE: Runtime flag behaviour is documented in README.md ("Streaming server"):
#   --max-inflight / --decode-workers control the bounded async decode/send pipeline.
#   --keep-artifacts retains on-disk decode intermediates for debugging runs.
#   --zero-copy-reply enables memory-mapped replies to minimise extra copies.

import argparse
import asyncio
import json
import logging
import socket
import subprocess
import sys
import time
from contextlib import suppress, ExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable

import numpy as np

from draco_roundtrip.analysis import pointcloud_metrics
from draco_roundtrip.common.state_machine import StreamState, StreamStateMachine

from draco_roundtrip.protocol.header import LEGACY_VERSION, VERSION
from draco_roundtrip.utils import ensure_directory, resolve_executable
from draco_roundtrip.utils.ply_io import load_points_from_bytes
from draco_roundtrip.utils.protocol import (
    Message,
    ProtocolHandler,
    MSG_ACK,
    MSG_DATA,
    MSG_EOF,
    MSG_ERROR,
    MSG_HEARTBEAT,
    available_protocols,
    resolve_protocol,
)
from draco_roundtrip.utils.stream_protocol import (
    ACK_PAYLOAD_STRUCT,
    CONTROL_CHANNEL,
    CONTENT_TYPE_DRACO,
    DATA_CHANNEL,
    ControlPlane,
    ControlState,
    ErrorCode,
    compose_response_payload,
    decode_frame_address,
    encode_frame_address,
    parse_legacy_request_payload,
)
from draco_roundtrip.utils.telemetry import Telemetry, percentiles_block


logger = logging.getLogger(__name__)


_HAS_ASYNCIO_TIMEOUT = hasattr(asyncio, "timeout")

FRAGMENT_GC_INTERVAL = 60.0
FRAGMENT_TTL_SEC = 300.0
FRAGMENT_BUFFER_MAX_BYTES = 128 * 1024 * 1024


class QueueStopped(Exception):
    """Raised when a queue consumer should halt due to cancellation."""


async def _queue_put(
    queue: "asyncio.Queue[object]",
    item: object,
    *,
    stop_event: asyncio.Event | None = None,
    timeout: float = 0.1,
) -> bool:
    while True:
        if stop_event is not None and stop_event.is_set():
            return False
        try:
            if _HAS_ASYNCIO_TIMEOUT:
                async with asyncio.timeout(timeout):
                    await queue.put(item)
            else:  # pragma: no cover - fallback for Python < 3.11
                await asyncio.wait_for(queue.put(item), timeout)
            return True
        except asyncio.TimeoutError:
            if stop_event is not None and stop_event.is_set():
                return False


async def _queue_get(
    queue: "asyncio.Queue[object]",
    *,
    stop_event: asyncio.Event | None = None,
    timeout: float = 0.1,
) -> object:
    while True:
        if stop_event is not None and stop_event.is_set():
            raise QueueStopped
        try:
            if _HAS_ASYNCIO_TIMEOUT:
                async with asyncio.timeout(timeout):
                    item = await queue.get()
            else:  # pragma: no cover - fallback for Python < 3.11
                item = await asyncio.wait_for(queue.get(), timeout)
            return item
        except asyncio.TimeoutError:
            if stop_event is not None and stop_event.is_set():
                raise QueueStopped


def _drain_queue(queue: "asyncio.Queue[object]") -> None:
    """Remove any pending items so join() observers do not hang on shutdown."""

    while True:
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            return
        else:
            queue.task_done()


@dataclass(slots=True)
class StageStats:
    count: int = 0
    total: float = 0.0
    maximum: float = 0.0

    def record(self, value: float) -> None:
        self.count += 1
        self.total += value
        if value > self.maximum:
            self.maximum = value

    def summary(self) -> str:
        if not self.count:
            return "n/a"
        avg = self.total / self.count
        return f"avg={avg * 1000:.2f} ms max={self.maximum * 1000:.2f} ms ({self.count} samples)"


@dataclass(slots=True)
class PipelineStats:
    recv_to_decode: StageStats = field(default_factory=StageStats)
    decode_time: StageStats = field(default_factory=StageStats)
    decode_to_send: StageStats = field(default_factory=StageStats)


@dataclass(slots=True)
class DecodeJob:
    sequence: int | None
    name: str
    payload: bytes
    received_at: float
    frame_payload_len: int | None = None
    fragments: int = 1
    flags: int | None = None
    timestamp_ns: int | None = None
    content_type: int | None = None
    header_version: int | None = None


@dataclass(slots=True)
class FragmentAssembly:
    sequence: int
    name: str
    total: int
    expected_len: int | None
    chunks: Dict[int, bytes] = field(default_factory=dict)
    received: int = 0
    last_update: float = field(default_factory=time.monotonic)

    def add(self, index: int, payload: bytes, *, now: float | None = None) -> bool:
        if index in self.chunks:
            return False
        self.chunks[index] = payload
        self.received += len(payload)
        self.last_update = now if now is not None else time.monotonic()
        return len(self.chunks) == self.total

    def assemble(self) -> bytes:
        return b"".join(self.chunks[i] for i in range(self.total))


@dataclass(slots=True)
class FragmentDrop:
    sequence: int
    state: FragmentAssembly
    reason: str


@dataclass(slots=True)
class FragmentBuffer:
    ttl: float
    max_bytes: int
    states: Dict[int, FragmentAssembly] = field(default_factory=dict)
    buffered_bytes: int = 0

    def add(
        self,
        *,
        sequence: int,
        name: str,
        total: int,
        expected_len: int | None,
        index: int,
        payload: bytes,
        now: float,
    ) -> tuple[bool, bytes | None, list[FragmentDrop]]:
        state = self.states.get(sequence)
        if state is None:
            state = FragmentAssembly(
                sequence=sequence,
                name=name,
                total=total,
                expected_len=expected_len,
            )
            self.states[sequence] = state
        complete = state.add(index, payload, now=now)
        self.buffered_bytes += len(payload)
        drops = self._evict_for_memory(exclude=sequence)
        if complete and sequence in self.states:
            assembled = state.assemble()
            self.states.pop(sequence, None)
            self.buffered_bytes = max(0, self.buffered_bytes - state.received)
            return True, assembled, drops
        if sequence not in self.states:
            drops.append(FragmentDrop(sequence, state, "buffer-limit"))
            return False, None, drops
        return False, None, drops

    def gc(self, now: float) -> list[FragmentDrop]:
        drops: list[FragmentDrop] = []
        for seq, state in list(self.states.items()):
            if now - state.last_update >= self.ttl:
                self.states.pop(seq, None)
                self.buffered_bytes = max(0, self.buffered_bytes - state.received)
                drops.append(FragmentDrop(seq, state, "ttl"))
        return drops

    def clear(self) -> list[FragmentDrop]:
        drops = [FragmentDrop(seq, state, "shutdown") for seq, state in self.states.items()]
        self.states.clear()
        self.buffered_bytes = 0
        return drops

    def _evict_for_memory(self, *, exclude: int | None = None) -> list[FragmentDrop]:
        if self.buffered_bytes <= self.max_bytes:
            return []
        drops: list[FragmentDrop] = []
        ordered = sorted(
            self.states.items(), key=lambda item: item[1].last_update
        )
        for seq, state in ordered:
            if exclude is not None and seq == exclude and self.buffered_bytes <= self.max_bytes:
                continue
            if self.buffered_bytes <= self.max_bytes:
                break
            removed = self.states.pop(seq, None)
            if removed is None:
                continue
            self.buffered_bytes = max(0, self.buffered_bytes - removed.received)
            drops.append(FragmentDrop(seq, removed, "buffer-limit"))
        return drops

@dataclass(slots=True)
class DecodedArtifact:
    payload: bytes
    points: "np.ndarray"
    metrics: dict[str, object]
    timestamp_ns: int
    draco_bytes: int
    decode_ms: float
    cleanup: Callable[[], None]

    def close(self) -> None:
        try:
            self.cleanup()
        except Exception:
            # Best-effort cleanup; swallow errors to avoid crashing the server
            return


@dataclass(slots=True)
class PipelineResult:
    job: DecodeJob
    decoded_at: float
    artifact: DecodedArtifact | None = None
    error: str | None = None


def _telemetry(stage: str, frame: str, **details: object) -> None:
    extras = " ".join(f"{key}={value}" for key, value in details.items())
    suffix = f" {extras}" if extras else ""
    logger.info(
        "[SERVER][TELEM] %s frame=%s ts=%.6f%s",
        stage,
        frame,
        time.monotonic(),
        suffix,
    )


def _export_server_telemetry(
    control_plane: ControlPlane,
    stats: PipelineStats,
    totals: Dict[str, int],
    *,
    protocol: str,
    elapsed: float,
    output_path: Path | None = None,
) -> None:
    """Write server telemetry aligned with docs/specs/telemetry_schema.md."""

    target = Path(output_path or "artifacts/perf/server_latest.json")
    telemetry = Telemetry(
        role="server",
        transport="tcp",
        protocol=protocol,
        fragment_size=0,
        socket_buffer_autotune=False,
    )
    frames_processed = stats.decode_time.count
    total_bytes = totals.get("bytes_out", 0) + totals.get("bytes_in", 0)
    throughput_avg = (total_bytes * 8 / max(elapsed, 1e-6)) / 1e6
    metrics = {
        "latency_ms": percentiles_block(None, scale=1.0),
        "rtt_ms": percentiles_block(None, scale=1.0),
        "ack_latency_ms": percentiles_block(None, scale=1.0),
        "throughput_mbps": {
            "avg": throughput_avg,
            "peak": throughput_avg,
        },
        "queues": {
            "capture_max": 0,
            "encode_max": 0,
            "decode_max": 0,
            "pending": 0,
        },
        "frames": {
            "sent": frames_processed,
            "acked": frames_processed,
            "dropped": 0,
            "skipped": 0,
        },
    }
    try:
        payload = telemetry.build(control_plane=control_plane, metrics=metrics)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        logger.info("[SERVER] Wrote telemetry to %s", target)
    except Exception as exc:  # pragma: no cover - best effort logging
        logger.warning("[SERVER] Failed to export telemetry: %s", exc)


async def _fail_and_signal(
    lifecycle: StreamStateMachine,
    stop_event: asyncio.Event,
    reason: str,
) -> None:
    lifecycle.fail(reason)
    stop_event.set()


def _points_to_pcd_bytes(points: np.ndarray) -> bytes:
    header = (
        "# .PCD v0.7 - Point Cloud Data file format\n"
        "VERSION 0.7\n"
        "FIELDS x y z\n"
        "SIZE 4 4 4\n"
        "TYPE F F F\n"
        "COUNT 1 1 1\n"
        f"WIDTH {points.shape[0]}\n"
        "HEIGHT 1\n"
        "VIEWPOINT 0 0 0 1 0 0 0\n"
        f"POINTS {points.shape[0]}\n"
        "DATA binary\n"
    )
    body = points.astype("<f4", copy=False).tobytes()
    return header.encode("ascii") + body


def decode_drc(
    decoder: Path,
    drc_bytes: bytes,
    out_dir: Path,
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
) -> DecodedArtifact:
    ensure_directory(out_dir)
    drc_path = out_dir / f"{stem}.drc"
    ply_path = out_dir / f"{stem}.decoded.ply"
    drc_path.write_bytes(drc_bytes)
    cmd = [str(decoder), "-i", str(drc_path), "-o", str(ply_path)]
    cleanup_files = not keep_artifacts
    if zero_copy:
        logger.warning(
            "[SERVER] zero-copy replies are not supported in metrics mode; using copy path"
        )
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout if timeout and timeout > 0 else None,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"draco_decoder failed (rc={proc.returncode}):\n"
                f"STDOUT: {proc.stdout.strip()}\nSTDERR: {proc.stderr.strip()}"
            )
        decoded_ply = ply_path.read_bytes()
        points = load_points_from_bytes(decoded_ply)
        if resp_format == "pcd":
            payload = _points_to_pcd_bytes(points)
        else:
            payload = decoded_ply

        def cleanup() -> None:
            if cleanup_files:
                with suppress(FileNotFoundError):
                    ply_path.unlink()

        metrics = pointcloud_metrics.compute(
            points,
            sample=metrics_sample,
            frame_id=frame_id,
            bits_per_point=(
                (draco_bytes_len * 8) / max(points.shape[0], 1)
                if draco_bytes_len is not None
                else None
            ),
            encode_ms=encode_ms,
        )
        metrics["extra"]["resp_format"] = resp_format
        artifact = DecodedArtifact(
            payload=payload,
            points=points,
            metrics=metrics,
            timestamp_ns=timestamp_ns or time.monotonic_ns(),
            draco_bytes=draco_bytes_len or len(drc_bytes),
            decode_ms=0.0,
            cleanup=cleanup,
        )
        return artifact
    except (
        subprocess.TimeoutExpired
    ) as exc:  # pragma: no cover - depends on external tool
        raise RuntimeError(f"draco_decoder timed out after {exc.timeout:.1f}s") from exc
    finally:
        if cleanup_files:
            with suppress(FileNotFoundError):
                drc_path.unlink()


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Draco streaming server")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=5000)
    ap.add_argument(
        "--control-port",
        type=int,
        default=0,
        help="[DEPRECATED] Ignored; control-plane messages reuse the data port",
    )
    ap.add_argument("--decoder", default=None, help="Path to draco_decoder")
    ap.add_argument("--work-dir", default="data/server_tmp")
    ap.add_argument(
        "--decode-timeout",
        type=float,
        default=30.0,
        help="Fail decoding if the external tool exceeds this timeout (seconds)",
    )
    ap.add_argument(
        "--tcp-nodelay",
        action="store_true",
        help="Disable Nagle aggregation on accepted sockets for lower latency",
    )
    ap.add_argument(
        "--socket-buffer-kb",
        type=int,
        default=0,
        help="Resize socket send/receive buffers (KiB) for high-throughput links",
    )
    ap.add_argument(
        "--socket-timeout",
        type=float,
        default=30.0,
        help="Timeout (seconds) for socket operations; 0 disables the safeguard",
    )
    ap.add_argument(
        "--max-inflight",
        type=int,
        default=2,
        help="Maximum number of frames to decode concurrently before backpressuring the client",
    )
    ap.add_argument(
        "--queue-size",
        type=int,
        default=0,
        help="Maximum server queue depth before applying backpressure (0 uses --max-inflight)",
    )
    ap.add_argument(
        "--decode-workers",
        type=int,
        default=2,
        help="Number of concurrent decode workers in the async pipeline",
    )
    ap.add_argument(
        "--keep-artifacts",
        action="store_true",
        help="Retain .drc/.ply decode artifacts for debugging (default cleans up)",
    )
    ap.add_argument(
        "--resp-format",
        choices=("ply", "pcd"),
        default="ply",
        help="Format used for decoded payloads returned to the client (default: %(default)s)",
    )
    ap.add_argument(
        "--metrics-sample",
        type=int,
        default=50000,
        help="Maximum number of points sampled when computing quality metrics (0 disables sampling)",
    )
    ap.add_argument(
        "--zero-copy-reply",
        action="store_true",
        help="Memory-map decoded PLY payloads to reduce copy overhead when sending replies",
    )
    ap.add_argument(
        "--legacy-mode",
        action="store_true",
        help="Fallback to the synchronous legacy loop for troubleshooting",
    )
    ap.add_argument(
        "--heartbeat-interval",
        type=float,
        default=2.0,
        help="Interval (seconds) for control-plane heartbeat messages; 0 disables keepalive",
    )
    protocol_help = available_protocols()
    ap.add_argument(
        "--protocol",
        choices=sorted(protocol_help.keys()),
        default="binary",
        help="Framing protocol expected from clients (default: %(default)s). Options: "
        + ", ".join(f"{name}={desc}" for name, desc in protocol_help.items()),
    )
    return ap


async def _recv_loop(
    protocol,
    conn: socket.socket,
    decode_queue: "asyncio.Queue[DecodeJob | None]",
    stop_event: asyncio.Event,
    producer_done: asyncio.Event,
    totals: Dict[str, int],
    heartbeat_interval: float,
    control_plane: ControlPlane,
    lifecycle: StreamStateMachine,
    legacy_mode: bool = False,
) -> None:
    heartbeat_interval = max(0.0, heartbeat_interval)
    last_heartbeat = time.monotonic()
    fragment_buffer = FragmentBuffer(
        ttl=FRAGMENT_TTL_SEC, max_bytes=FRAGMENT_BUFFER_MAX_BYTES
    )
    use_binary = protocol.name == "binary"

    def _log_fragment_drops(drops: list[FragmentDrop]) -> None:
        for drop in drops:
            logger.warning(
                "[SERVER] Dropping fragment seq=%s (%s, %d bytes buffered)",
                drop.sequence,
                drop.reason,
                drop.state.received,
            )
            _telemetry(
                "fragment_drop",
                drop.state.name,
                seq=drop.sequence,
                reason=drop.reason,
                buffered=drop.state.received,
            )

    async def _fragment_gc_loop() -> None:
        try:
            while not stop_event.is_set():
                await asyncio.sleep(FRAGMENT_GC_INTERVAL)
                drops = fragment_buffer.gc(time.monotonic())
                if drops:
                    _log_fragment_drops(drops)
        except asyncio.CancelledError:  # pragma: no cover - shutdown path
            return

    async def send_control_with_retry(message: Message, label: str) -> bool:
        delay = 0.05
        attempts = 3
        for attempt in range(1, attempts + 1):
            try:
                await asyncio.to_thread(protocol.send, conn, message)
                return True
            except Exception as exc:
                logger.warning(
                    "[SERVER] Failed to send %s attempt %d/%d: %s",
                    label,
                    attempt,
                    attempts,
                    exc,
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2.0, 0.5)
        logger.error("[SERVER] Control send failed for %s", label)
        return False

    fragment_gc_task: asyncio.Task | None = (
        asyncio.create_task(_fragment_gc_loop()) if use_binary else None
    )

    try:
        while not stop_event.is_set():
            try:
                message = await asyncio.to_thread(protocol.recv, conn)
            except socket.timeout:
                if producer_done.is_set():
                    break
                if (
                    heartbeat_interval > 0
                    and (time.monotonic() - last_heartbeat) >= heartbeat_interval
                ):
                    heartbeat = Message(
                        kind=MSG_HEARTBEAT,
                        name=encode_frame_address(
                            None,
                            "server-heartbeat",
                            channel=CONTROL_CHANNEL,
                        ),
                        payload=b"",
                    )
                    if await send_control_with_retry(heartbeat, "heartbeat"):
                        _telemetry("send_heartbeat", "all")
                    else:
                        await _fail_and_signal(
                            lifecycle,
                            stop_event,
                            "heartbeat send failure",
                        )
                        break
                    last_heartbeat = time.monotonic()
                continue
            except Exception as exc:
                logger.error("[SERVER] ERROR receiving frame: %s", exc)
                await _fail_and_signal(lifecycle, stop_event, f"recv error: {exc}")
                break
            if message is None:
                logger.info("[SERVER] Client closed connection")
                await _fail_and_signal(lifecycle, stop_event, "client closed connection")
                break
            last_heartbeat = time.monotonic()
            address = decode_frame_address(message.name)
            if message.kind == MSG_HEARTBEAT:
                control_plane.on_heartbeat()
                _telemetry("recv_heartbeat", address.name or "all")
                continue
            if message.kind == MSG_ERROR:
                detail = (
                    message.payload.decode("utf-8", errors="ignore")
                    if message.payload
                    else ""
                )
                logger.error("[SERVER] ERROR from client: %s", detail or "unspecified")
                control_plane.on_error(ErrorCode.PROTOCOL_VIOLATION, detail or None)
                await _fail_and_signal(
                    lifecycle,
                    stop_event,
                    f"client error: {detail or 'unspecified'}",
                )
                break
            if message.kind == MSG_EOF:
                logger.info("[SERVER] Received EOF marker from client")
                _telemetry("recv_eof", "all")
                control_plane.on_eof_received()
                lifecycle.transition(StreamState.DRAINING, reason="client EOF")
                if control_plane.state == ControlState.TERMINATED:
                    lifecycle.transition(StreamState.TERMINATED, reason="client EOF")
                producer_done.set()
                break
            if message.kind != MSG_DATA:
                logger.warning(
                    "[SERVER] Ignoring unexpected message kind: %s", message.kind
                )
                continue
            if address.channel != DATA_CHANNEL:
                logger.warning(
                    "[SERVER] Received data on control channel: %s", message.name
                )
            if control_plane.state in (ControlState.INIT, ControlState.HANDSHAKING):
                control_plane.on_first_data()
                lifecycle.transition(StreamState.STREAMING, reason="first frame")
            sequence = (
                message.sequence if message.sequence is not None else address.sequence
            )
            frame_name = address.name or "frame"
            payload_bytes = message.payload
            totals["bytes_in"] += len(payload_bytes)
            if use_binary and message.fragmented:
                if sequence is None:
                    logger.error(
                        "[SERVER] ERROR: fragmented frame missing sequence metadata"
                    )
                    control_plane.on_error(
                        ErrorCode.PROTOCOL_VIOLATION, "fragment missing sequence"
                    )
                    continue
                total = message.fragments_total or 1
                expected_len = message.frame_payload_len
                complete, assembled, drops = fragment_buffer.add(
                    sequence=sequence,
                    name=frame_name,
                    total=total,
                    expected_len=expected_len,
                    index=message.fragment_index or 0,
                    payload=payload_bytes,
                    now=time.monotonic(),
                )
                if drops:
                    _log_fragment_drops(drops)
                _telemetry(
                    "recv_fragment",
                    frame_name,
                    seq=sequence,
                    index=message.fragment_index or 0,
                    total=total,
                )
                if not complete:
                    continue
                if assembled is None:  # pragma: no cover - defensive
                    logger.error(
                        "[SERVER] fragment assembly returned no payload for seq=%s",
                        sequence,
                    )
                    continue
                payload_bytes = assembled
            timestamp_ns = (
                message.timestamp_ns
                if message.timestamp_ns is not None
                else time.monotonic_ns()
            )
            content_type = message.content_type or CONTENT_TYPE_DRACO
            draco_payload = payload_bytes
            header_version = message.header_version if use_binary else None
            if use_binary and header_version == LEGACY_VERSION:
                if not legacy_mode:
                    detail = "legacy frame received but --legacy-mode is disabled"
                    logger.error("[SERVER] %s", detail)
                    error_message = Message(
                        kind=MSG_ERROR,
                        name=encode_frame_address(
                            sequence, frame_name, channel=CONTROL_CHANNEL
                        ),
                        payload=str(detail).encode(),
                        sequence=sequence,
                    )
                    await send_control_with_retry(
                        error_message, f"legacy-deny-{sequence}"
                    )
                    continue
                try:
                    legacy_seq, legacy_ts, legacy_content_type, legacy_payload = (
                        parse_legacy_request_payload(payload_bytes)
                    )
                except ValueError as exc:
                    detail = f"invalid legacy payload: {exc}"
                    logger.error("[SERVER] ERROR parsing frame %s: %s", frame_name, detail)
                    error_message = Message(
                        kind=MSG_ERROR,
                        name=encode_frame_address(
                            sequence, frame_name, channel=CONTROL_CHANNEL
                        ),
                        payload=str(detail).encode(),
                        sequence=sequence,
                    )
                    await send_control_with_retry(
                        error_message, f"legacy-parse-error-{sequence}"
                    )
                    continue
                draco_payload = legacy_payload
                timestamp_ns = legacy_ts
                if sequence is None:
                    sequence = legacy_seq
                elif legacy_seq != sequence:
                    logger.warning(
                        "[SERVER] Sequence mismatch legacy header=%s message=%s",
                        legacy_seq,
                        sequence,
                    )
                content_type = legacy_content_type or CONTENT_TYPE_DRACO
            elif use_binary and header_version not in (None, VERSION):
                detail = f"unsupported frame header version {header_version}"
                logger.error("[SERVER] %s", detail)
                error_message = Message(
                    kind=MSG_ERROR,
                    name=encode_frame_address(
                        sequence, frame_name, channel=CONTROL_CHANNEL
                    ),
                    payload=str(detail).encode(),
                    sequence=sequence,
                )
                await send_control_with_retry(error_message, f"version-error-{sequence}")
                continue
            job = DecodeJob(
                sequence=sequence,
                name=frame_name,
                payload=draco_payload,
                received_at=time.monotonic(),
                frame_payload_len=(
                    message.frame_payload_len
                    if message.frame_payload_len
                    else len(draco_payload)
                ),
                fragments=message.fragments_total or 1,
                flags=message.flags,
                timestamp_ns=timestamp_ns,
                content_type=content_type,
                header_version=header_version,
            )
            ack_payload = (
                ACK_PAYLOAD_STRUCT.pack(job.sequence) if job.sequence is not None else b""
            )
            ack_message = Message(
                kind=MSG_ACK,
                name=encode_frame_address(
                    job.sequence, job.name, channel=CONTROL_CHANNEL
                ),
                payload=ack_payload,
                sequence=job.sequence,
            )
            if not await send_control_with_retry(ack_message, f"ack-{job.sequence}"):
                producer_done.set()
                await _fail_and_signal(
                    lifecycle,
                    stop_event,
                    f"ack send failure seq={job.sequence}",
                )
                break
            _telemetry("send_ack", job.name, seq=job.sequence)
            if not await _queue_put(decode_queue, job, stop_event=stop_event):
                stop_event.set()
                break
            _telemetry(
                "recv_data",
                job.name,
                size=len(job.payload),
                depth=decode_queue.qsize(),
                seq=job.sequence,
            )
    finally:
        if fragment_gc_task is not None:
            fragment_gc_task.cancel()
            with suppress(Exception):
                await fragment_gc_task
        drops = fragment_buffer.clear()
        if drops:
            _log_fragment_drops(drops)
        producer_done.set()


async def _decode_worker(
    worker_id: int,
    args: argparse.Namespace,
    decoder: Path,
    work_dir: Path,
    decode_queue: "asyncio.Queue[DecodeJob | None]",
    send_queue: "asyncio.Queue[PipelineResult | None]",
    stats: PipelineStats,
    stop_event: asyncio.Event,
) -> None:
    while not stop_event.is_set():
        try:
            job = await _queue_get(decode_queue, stop_event=stop_event)
        except QueueStopped:
            _drain_queue(decode_queue)
            break
        if job is None:
            decode_queue.task_done()
            # Propagate shutdown to the sender so the EOF handshake can trigger once workers drain.
            await _queue_put(send_queue, None)
            break
        decode_start = time.monotonic()
        stats.recv_to_decode.record(decode_start - job.received_at)
        _telemetry(
            "decode_start",
            job.name,
            worker=worker_id,
            seq=job.sequence,
            wait_ms=(decode_start - job.received_at) * 1000.0,
        )
        try:
            prefix = job.payload[:8].hex() if job.payload else ""
            logger.debug(
                "[SERVER] decode %s: seq=%s prefix=%s", job.name, job.sequence, prefix
            )
            artifact = await asyncio.to_thread(
                decode_drc,
                decoder,
                job.payload,
                work_dir,
                job.name,
                timeout=args.decode_timeout,
                keep_artifacts=args.keep_artifacts,
                zero_copy=args.zero_copy_reply,
                resp_format=args.resp_format,
                metrics_sample=getattr(args, "metrics_sample", None),
                frame_id=job.name,
                draco_bytes_len=(
                    job.frame_payload_len if job.frame_payload_len else len(job.payload)
                ),
                timestamp_ns=job.timestamp_ns,
            )
            decoded_at = time.monotonic()
            stats.decode_time.record(decoded_at - decode_start)
            artifact.decode_ms = (decoded_at - decode_start) * 1000.0
            artifact.metrics["decode_ms"] = artifact.decode_ms
            _telemetry(
                "decode_complete",
                job.name,
                worker=worker_id,
                seq=job.sequence,
                latency_ms=(decoded_at - decode_start) * 1000.0,
            )
            await _queue_put(
                send_queue,
                PipelineResult(job=job, decoded_at=decoded_at, artifact=artifact),
                stop_event=stop_event,
            )
        except Exception as exc:
            logger.exception(
                "[SERVER] ERROR decoding %s: %s seq=%s flags=%s payload_len=%d expected_len=%s fragments=%d",
                job.name,
                exc,
                job.sequence,
                job.flags,
                len(job.payload),
                job.frame_payload_len,
                job.fragments,
            )
            _telemetry("decode_error", job.name, worker=worker_id, seq=job.sequence)
            await _queue_put(
                send_queue,
                PipelineResult(job=job, decoded_at=time.monotonic(), error=str(exc)),
                stop_event=stop_event,
            )
            stop_event.set()
            _drain_queue(decode_queue)
            break
        finally:
            decode_queue.task_done()


async def _send_loop(
    protocol,
    conn: socket.socket,
    send_queue: "asyncio.Queue[PipelineResult | None]",
    stats: PipelineStats,
    totals: Dict[str, int],
    stop_event: asyncio.Event,
    producer_done: asyncio.Event,
    worker_count: int,
    control_plane: ControlPlane,
    lifecycle: StreamStateMachine,
    resp_format: str,
) -> None:
    finished_workers = 0
    eof_sent = False
    while not stop_event.is_set():
        try:
            item = await _queue_get(send_queue, stop_event=stop_event)
        except QueueStopped:
            break
        if item is None:
            finished_workers += 1
            send_queue.task_done()
            if finished_workers >= worker_count:
                break
            continue
        result = item
        send_start = time.monotonic()
        fatal_reason: str | None = None
        should_break = False
        if result.artifact is None or result.error:
            payload = (result.error or "decode failed").encode()
            message = Message(
                kind=MSG_ERROR,
                name=encode_frame_address(
                    result.job.sequence,
                    result.job.name,
                    channel=CONTROL_CHANNEL,
                ),
                payload=payload,
                sequence=result.job.sequence,
            )
            stage_label = "send_error"
            if control_plane.state != ControlState.FAILED:
                control_plane.on_error(ErrorCode.INTERNAL_ERROR, result.error)
            fatal_reason = result.error or "decode failed"
        else:
            name = result.job.name
            reply_name = (
                name
                if name.endswith(f".decoded.{resp_format}")
                else f"{name}.decoded.{resp_format}"
            )
            metrics_json = json.dumps(result.artifact.metrics, sort_keys=True).encode(
                "utf-8"
            )
            seq_for_header = (
                result.job.sequence if result.job.sequence is not None else 0
            )
            _, packed_payload = compose_response_payload(
                sequence=seq_for_header,
                timestamp_ns=result.artifact.timestamp_ns,
                decoded_payload=result.artifact.payload,
                metrics_json=metrics_json,
                decode_ms=result.artifact.decode_ms,
            )
            reply_payload_len = len(packed_payload)
            message = Message(
                kind=MSG_DATA,
                name=encode_frame_address(
                    result.job.sequence,
                    reply_name,
                    channel=DATA_CHANNEL,
                ),
                payload=packed_payload,
                sequence=result.job.sequence,
            )
            stage_label = "send_data"
        try:
            await asyncio.to_thread(protocol.send, conn, message)
        except Exception as exc:
            logger.error(
                "[SERVER] ERROR sending %s: %s",
                message.name or result.job.name,
                exc,
            )
            await _fail_and_signal(
                lifecycle,
                stop_event,
                f"send failure: {exc}",
            )
        else:
            if message.kind == MSG_DATA and result.artifact is not None:
                totals["bytes_out"] += reply_payload_len
                stats.decode_to_send.record(send_start - result.decoded_at)
                _telemetry(
                    stage_label,
                    result.job.name,
                    size=reply_payload_len,
                    seq=result.job.sequence,
                )
            else:
                _telemetry(stage_label, result.job.name, seq=result.job.sequence)
            if fatal_reason is not None:
                await _fail_and_signal(
                    lifecycle,
                    stop_event,
                    f"pipeline error: {fatal_reason}",
                )
                should_break = True
        finally:
            if result.artifact is not None:
                try:
                    result.artifact.close()
                except Exception as cleanup_exc:
                    logger.warning(
                        "[SERVER] Failed to cleanup artifact for %s: %s",
                        result.job.name,
                        cleanup_exc,
                    )
            send_queue.task_done()
            if should_break:
                break
    if not eof_sent and producer_done.is_set():
        if control_plane.state not in (ControlState.FAILED, ControlState.TERMINATED):
            control_plane.on_eof_sent()
        lifecycle.transition(StreamState.DRAINING, reason="EOF sent")
        try:
            await _send_control_message(
                control,
                protocol,
                conn,
                Message(
                    kind=MSG_EOF,
                    name=encode_frame_address(None, "final", channel=CONTROL_CHANNEL),
                    payload=b"",
                ),
            )
            _telemetry("send_eof", "all")
            eof_sent = True
        except Exception as exc:
            logger.error("[SERVER] ERROR sending EOF marker: %s", exc)
        with suppress(OSError):
            # ``SHUT_WR`` triggers a FIN after the MSG_EOF handshake reaches the client.
            conn.shutdown(socket.SHUT_WR)


async def handle_connection(
    conn: socket.socket,
    addr,
    args: argparse.Namespace,
    decoder: Path,
    work_dir: Path,
    stats: PipelineStats,
    totals: Dict[str, int],
) -> ControlPlane:
    with ExitStack() as stack:
        data_conn = stack.enter_context(conn)
        def _adapt_protocol(handler: ProtocolHandler) -> ProtocolHandler:
            if handler.name != "binary" or not args.legacy_mode:
                return handler

            def recv(sock: socket.socket, *, _recv=handler.recv):
                return _recv(sock, allow_legacy=True)

            return ProtocolHandler(
                name=handler.name,
                send=handler.send,
                recv=recv,
                description=handler.description,
            )

        if args.tcp_nodelay:
            with suppress(OSError):
                data_conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        if args.socket_buffer_kb > 0:
            buf_size = args.socket_buffer_kb * 1024
            for opt in (socket.SO_SNDBUF, socket.SO_RCVBUF):
                with suppress(OSError):
                    data_conn.setsockopt(socket.SOL_SOCKET, opt, buf_size)
        if args.socket_timeout > 0:
            data_conn.settimeout(args.socket_timeout)
        protocol = _adapt_protocol(resolve_protocol(args.protocol))
        logger.info(
            "[SERVER] Connection from %s using %s protocol", addr, protocol.name
        )

        control_plane = ControlPlane(role="server")
        control_plane.on_connected(time.monotonic_ns())
        lifecycle = StreamStateMachine(role="server")
        lifecycle.transition(StreamState.HANDSHAKING, reason="connected")

        max_inflight = max(1, args.max_inflight)
        queue_bound = (
            max_inflight
            if getattr(args, "queue_size", 0) <= 0
            else max(1, args.queue_size)
        )
        if args.decode_workers <= 0:
            raise ValueError("decode_workers must be positive")
        decode_queue: "asyncio.Queue[DecodeJob | None]" = asyncio.Queue(
            maxsize=queue_bound
        )
        send_queue: "asyncio.Queue[PipelineResult | None]" = asyncio.Queue(
            maxsize=queue_bound
        )
        stop_event = asyncio.Event()
        producer_done = asyncio.Event()
        recv_task = asyncio.create_task(
            _recv_loop(
                protocol,
                data_conn,
                decode_queue,
                stop_event,
                producer_done,
                totals,
                args.heartbeat_interval,
                control_plane,
                lifecycle,
                legacy_mode=args.legacy_mode,
            )
        )
        worker_tasks = [
            asyncio.create_task(
                _decode_worker(
                    worker_id,
                    args,
                    decoder,
                    work_dir,
                    decode_queue,
                    send_queue,
                    stats,
                    stop_event,
                )
            )
            for worker_id in range(args.decode_workers)
        ]
        send_task = asyncio.create_task(
            _send_loop(
                protocol,
                data_conn,
                send_queue,
                stats,
                totals,
                stop_event,
                producer_done,
                args.decode_workers,
                control_plane,
                lifecycle,
                args.resp_format,
            )
        )

        tasks: Iterable[asyncio.Task[None]] = [recv_task, *worker_tasks, send_task]
        try:
            await recv_task
        except Exception as exc:
            await _fail_and_signal(
                lifecycle,
                stop_event,
                f"recv loop failure: {exc}",
            )
            raise
        finally:
            producer_done.set()
            for _ in worker_tasks:
                await decode_queue.put(None)
            await decode_queue.join()

        await asyncio.gather(*worker_tasks, return_exceptions=True)
        await send_queue.join()
        await send_task
        stop_event.set()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        control_plane.on_shutdown()
        if (
            control_plane.state == ControlState.TERMINATED
            and lifecycle.state != StreamState.FAILED
        ):
            lifecycle.transition(StreamState.TERMINATED, reason="session complete")
        setattr(control_plane, "lifecycle", lifecycle)
        return control_plane


async def run_server(args: argparse.Namespace) -> None:
    decoder = resolve_executable("draco_decoder", args.decoder, env_var="DRACO_DECODER")
    work_dir = ensure_directory(Path(args.work_dir).resolve())
    stats = PipelineStats()
    totals: Dict[str, int] = {"bytes_in": 0, "bytes_out": 0}
    start_time = time.monotonic()

    if args.control_port:
        logger.warning(
            "[SERVER] --control-port is deprecated and ignored; using single data channel"
        )
        args.control_port = 0

    try:
        server = socket.create_server((args.host, args.port), reuse_port=True)
    except OSError as exc:
        logger.warning("[SERVER] reuse_port failed (%s), retrying without it", exc)
        server = socket.create_server((args.host, args.port))

    with ExitStack() as stack:
        stack.enter_context(server)
        logger.info("[SERVER] Listening on %s:%d", args.host, args.port)
        conn, addr = await asyncio.to_thread(server.accept)
        logger.info("[SERVER] Accepted connection from %s", addr)
        control_plane: ControlPlane | None = None
        try:
            control_plane = await handle_connection(
                conn,
                addr,
                args,
                decoder,
                work_dir,
                stats,
                totals,
            )
        finally:
            with suppress(Exception):
                conn.close()

    elapsed = max(time.monotonic() - start_time, 1e-6)
    if control_plane is not None:
        lifecycle: StreamStateMachine | None = getattr(control_plane, "lifecycle", None)
        _export_server_telemetry(
            control_plane,
            stats,
            totals,
            protocol=args.protocol,
            elapsed=elapsed,
        )
        shutdown_summary = {
            "role": "server",
            "elapsed_sec": elapsed,
            "state": lifecycle.state.value if lifecycle else control_plane.state.value,
            "state_reason": (
                lifecycle.reason if lifecycle else control_plane.error_message
            ),
            "control_state": control_plane.state.value,
            "control_pending": control_plane.pending,
            "pending_inflight": control_plane.pending,
            "frames": {
                "processed": stats.decode_time.count,
                "dropped": 0,
                "sent": stats.decode_time.count,
            },
            "bytes_in": totals["bytes_in"],
            "bytes_out": totals["bytes_out"],
            "latency": {
                "recv_to_decode": stats.recv_to_decode.summary(),
                "decode_time": stats.decode_time.summary(),
                "decode_to_send": stats.decode_to_send.summary(),
            },
        }
        logger.info(
            "[SERVER] shutdown_summary %s",
            json.dumps(shutdown_summary, sort_keys=True),
        )
    logger.info("[SERVER] ---- Bandwidth summary ----")
    logger.info("  elapsed: %.2f s", elapsed)
    logger.info(
        "  inbound: %d bytes (%.3f Mbps)",
        totals["bytes_in"],
        totals["bytes_in"] * 8 / elapsed / 1e6,
    )
    logger.info(
        "  outbound: %d bytes (%.3f Mbps)",
        totals["bytes_out"],
        totals["bytes_out"] * 8 / elapsed / 1e6,
    )
    total = totals["bytes_in"] + totals["bytes_out"]
    logger.info("  total: %d bytes (%.3f Mbps)", total, total * 8 / elapsed / 1e6)
    logger.info("  stage metrics:")
    logger.info("    recv→decode: %s", stats.recv_to_decode.summary())
    logger.info("    decode time: %s", stats.decode_time.summary())
    logger.info("    decode→send: %s", stats.decode_to_send.summary())


def run_server_legacy(args: argparse.Namespace) -> None:
    decoder = resolve_executable("draco_decoder", args.decoder, env_var="DRACO_DECODER")
    work_dir = ensure_directory(Path(args.work_dir).resolve())
    start_time = time.monotonic()
    bytes_in = 0
    bytes_out = 0
    if args.control_port > 0:
        logger.warning(
            "[SERVER][LEGACY] control-port ignored in legacy mode; using single channel"
        )
    try:
        server = socket.create_server((args.host, args.port), reuse_port=True)
    except OSError as exc:
        logger.warning("[SERVER] reuse_port failed (%s), retrying without it", exc)
        server = socket.create_server((args.host, args.port))

    with server:
        logger.info("[SERVER][LEGACY] Listening on %s:%d", args.host, args.port)
        conn, addr = server.accept()
        logger.info("[SERVER][LEGACY] Connection from %s", addr)
        with conn:
            if args.tcp_nodelay:
                with suppress(OSError):
                    conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            if args.socket_buffer_kb > 0:
                buf_size = args.socket_buffer_kb * 1024
                for opt in (socket.SO_SNDBUF, socket.SO_RCVBUF):
                    with suppress(OSError):
                        conn.setsockopt(socket.SOL_SOCKET, opt, buf_size)
            protocol = resolve_protocol(args.protocol)
            eof_sent = False
            while True:
                msg = protocol.recv(conn)
                if msg is None:
                    break
                address = decode_frame_address(msg.name)
                if msg.kind == MSG_EOF:
                    protocol.send(
                        conn,
                        Message(
                            kind=MSG_EOF,
                            name=encode_frame_address(
                                None, "final", channel=CONTROL_CHANNEL
                            ),
                            payload=b"",
                        ),
                    )
                    eof_sent = True
                    break
                if msg.kind != MSG_DATA:
                    continue
                if address.channel != DATA_CHANNEL:
                    logger.warning(
                        "[SERVER][LEGACY] data on control channel: %s", msg.name
                    )
                stem = address.name or "frame"
                try:
                    protocol.send(
                        conn,
                        Message(
                            kind=MSG_ACK,
                            name=encode_frame_address(
                                address.sequence, stem, channel=CONTROL_CHANNEL
                            ),
                            payload=b"",
                        ),
                    )
                    _telemetry(
                        "send_ack",
                        stem,
                        seq=address.sequence if address.sequence is not None else -1,
                    )
                except Exception as exc:
                    logger.warning(
                        "[SERVER][LEGACY] Failed to send ACK for %s: %s", stem, exc
                    )
                bytes_in += len(msg.payload)
                try:
                    artifact = decode_drc(
                        decoder,
                        msg.payload,
                        work_dir,
                        stem,
                        timeout=args.decode_timeout,
                        keep_artifacts=args.keep_artifacts,
                        zero_copy=args.zero_copy_reply,
                    )
                except Exception as exc:
                    error_msg = Message(
                        kind=MSG_ERROR,
                        name=encode_frame_address(
                            address.sequence, stem, channel=CONTROL_CHANNEL
                        ),
                        payload=str(exc).encode(),
                    )
                    protocol.send(conn, error_msg)
                    continue
                reply_name = stem if stem.endswith(".decoded") else f"{stem}.decoded"
                reply = Message(
                    kind=MSG_DATA,
                    name=encode_frame_address(
                        address.sequence, reply_name, channel=DATA_CHANNEL
                    ),
                    payload=artifact.payload,
                )
                protocol.send(conn, reply)
                bytes_out += len(artifact.payload)
                artifact.close()
            if not eof_sent:
                protocol.send(
                    conn,
                    Message(
                        kind=MSG_EOF,
                        name=encode_frame_address(
                            None, "final", channel=CONTROL_CHANNEL
                        ),
                        payload=b"",
                    ),
                )
    elapsed = max(time.monotonic() - start_time, 1e-6)
    total = bytes_in + bytes_out
    logger.info("[SERVER][LEGACY] ---- Bandwidth summary ----")
    logger.info("  elapsed: %.2f s", elapsed)
    logger.info(
        "  inbound: %d bytes (%.3f Mbps)",
        bytes_in,
        bytes_in * 8 / elapsed / 1e6,
    )
    logger.info(
        "  outbound: %d bytes (%.3f Mbps)",
        bytes_out,
        bytes_out * 8 / elapsed / 1e6,
    )
    logger.info(
        "  total: %d bytes (%.3f Mbps)",
        total,
        total * 8 / elapsed / 1e6,
    )


def main(argv: list[str] | None = None) -> None:
    args = build_arg_parser().parse_args(argv)
    if args.legacy_mode:
        run_server_legacy(args)
    else:
        asyncio.run(run_server(args))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
