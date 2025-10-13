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
import mmap
import socket
import subprocess
import sys
import time
from contextlib import suppress, ExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable

from draco_roundtrip.utils import ensure_directory, resolve_executable
from draco_roundtrip.utils.protocol import (
    Message,
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
    DATA_CHANNEL,
    ControlPlane,
    ControlState,
    ErrorCode,
    decode_frame_address,
    encode_frame_address,
)
from draco_roundtrip.utils.telemetry import Telemetry, percentiles_block


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
class ControlChannel:
    sock: socket.socket
    protocol: ProtocolHandler


@dataclass(slots=True)
class DecodeJob:
    sequence: int | None
    name: str
    payload: bytes
    received_at: float


@dataclass(slots=True)
class DecodedArtifact:
    payload: bytes | memoryview
    cleanup: Callable[[], None]

    def close(self) -> None:
        try:
            self.cleanup()
        finally:
            if isinstance(self.payload, memoryview):
                try:
                    self.payload.release()
                except Exception:
                    pass


@dataclass(slots=True)
class PipelineResult:
    job: DecodeJob
    decoded_at: float
    artifact: DecodedArtifact | None = None
    error: str | None = None


def _telemetry(stage: str, frame: str, **details: object) -> None:
    extras = " ".join(f"{key}={value}" for key, value in details.items())
    suffix = f" {extras}" if extras else ""
    print(f"[SERVER][TELEM] {stage} frame={frame} ts={time.monotonic():.6f}{suffix}")


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
        print(f"[SERVER] Wrote telemetry to {target}")
    except Exception as exc:  # pragma: no cover - best effort logging
        print(f"[SERVER] WARN: Failed to export telemetry: {exc}")


async def _send_control_message(
    control: ControlChannel | None,
    fallback_protocol: ProtocolHandler,
    fallback_sock: socket.socket,
    message: Message,
) -> None:
    target = control.sock if control is not None else fallback_sock
    protocol = control.protocol if control is not None else fallback_protocol
    await asyncio.to_thread(protocol.send, target, message)


def decode_drc(
    decoder: Path,
    drc_bytes: bytes,
    out_dir: Path,
    stem: str,
    *,
    timeout: float | None = None,
    keep_artifacts: bool = False,
    zero_copy: bool = False,
) -> DecodedArtifact:
    ensure_directory(out_dir)
    drc_path = out_dir / f"{stem}.drc"
    ply_path = out_dir / f"{stem}.decoded.ply"
    drc_path.write_bytes(drc_bytes)
    cmd = [str(decoder), "-i", str(drc_path), "-o", str(ply_path)]
    cleanup_files = not keep_artifacts
    mmap_obj: mmap.mmap | None = None
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
        if zero_copy:
            with ply_path.open("rb") as fh:
                mmap_obj = mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ)
            payload = memoryview(mmap_obj)

            def cleanup() -> None:
                if mmap_obj is not None:
                    mmap_obj.close()
                if cleanup_files:
                    with suppress(FileNotFoundError):
                        ply_path.unlink()

            return DecodedArtifact(payload=payload, cleanup=cleanup)
        data = ply_path.read_bytes()

        def cleanup() -> None:
            if cleanup_files:
                with suppress(FileNotFoundError):
                    ply_path.unlink()

        return DecodedArtifact(payload=data, cleanup=cleanup)
    except subprocess.TimeoutExpired as exc:  # pragma: no cover - depends on external tool
        raise RuntimeError(
            f"draco_decoder timed out after {exc.timeout:.1f}s"
        ) from exc
    finally:
        if cleanup_files:
            with suppress(FileNotFoundError):
                drc_path.unlink()


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Draco streaming server")
    ap.add_argument('--host', default='0.0.0.0')
    ap.add_argument('--port', type=int, default=5000)
    ap.add_argument('--control-port', type=int, default=0,
                    help='Optional TCP port dedicated to control-plane messages (0 disables)')
    ap.add_argument('--decoder', default=None, help="Path to draco_decoder")
    ap.add_argument('--work-dir', default='data/server_tmp')
    ap.add_argument('--decode-timeout', type=float, default=30.0,
                    help='Fail decoding if the external tool exceeds this timeout (seconds)')
    ap.add_argument('--tcp-nodelay', action='store_true',
                    help='Disable Nagle aggregation on accepted sockets for lower latency')
    ap.add_argument('--socket-buffer-kb', type=int, default=0,
                    help='Resize socket send/receive buffers (KiB) for high-throughput links')
    ap.add_argument('--socket-timeout', type=float, default=30.0,
                    help='Timeout (seconds) for socket operations; 0 disables the safeguard')
    ap.add_argument('--max-inflight', type=int, default=2,
                    help='Maximum number of frames to decode concurrently before backpressuring the client')
    ap.add_argument('--decode-workers', type=int, default=2,
                    help='Number of concurrent decode workers in the async pipeline')
    ap.add_argument('--keep-artifacts', action='store_true',
                    help='Retain .drc/.ply decode artifacts for debugging (default cleans up)')
    ap.add_argument('--zero-copy-reply', action='store_true',
                    help='Memory-map decoded PLY payloads to reduce copy overhead when sending replies')
    ap.add_argument('--legacy-mode', action='store_true',
                    help='Fallback to the synchronous legacy loop for troubleshooting')
    ap.add_argument('--heartbeat-interval', type=float, default=2.0,
                    help='Interval (seconds) for control-plane heartbeat messages; 0 disables keepalive')
    protocol_help = available_protocols()
    ap.add_argument('--protocol',
                    choices=sorted(protocol_help.keys()),
                    default='binary',
                    help='Framing protocol expected from clients (default: %(default)s). Options: '
                    + ', '.join(f"{name}={desc}" for name, desc in protocol_help.items()))
    return ap


async def _recv_loop(
    protocol,
    conn: socket.socket,
    control: ControlChannel | None,
    decode_queue: "asyncio.Queue[DecodeJob | None]",
    stop_event: asyncio.Event,
    producer_done: asyncio.Event,
    totals: Dict[str, int],
    heartbeat_interval: float,
    control_plane: ControlPlane,
) -> None:
    heartbeat_interval = max(0.0, heartbeat_interval)
    last_heartbeat = time.monotonic()
    while not stop_event.is_set():
        try:
            message = await asyncio.to_thread(protocol.recv, conn)
        except socket.timeout:
            if producer_done.is_set():
                break
            if heartbeat_interval > 0 and (time.monotonic() - last_heartbeat) >= heartbeat_interval:
                try:
                    await _send_control_message(
                        control,
                        protocol,
                        conn,
                        Message(
                            kind=MSG_HEARTBEAT,
                            name=encode_frame_address(
                                None,
                                "server-heartbeat",
                                channel=CONTROL_CHANNEL,
                            ),
                            payload=b"",
                        ),
                    )
                    _telemetry("send_heartbeat", "all")
                except Exception as exc:
                    print(f"[SERVER] WARN: Failed to send heartbeat: {exc}")
                    stop_event.set()
                    break
                finally:
                    last_heartbeat = time.monotonic()
            continue
        except Exception as exc:
            print(f"[SERVER] ERROR receiving frame: {exc}")
            stop_event.set()
            break
        if message is None:
            print("[SERVER] Client closed connection")
            stop_event.set()
            break
        last_heartbeat = time.monotonic()
        address = decode_frame_address(message.name)
        if message.kind == MSG_HEARTBEAT:
            control_plane.on_heartbeat()
            _telemetry("recv_heartbeat", address.name or "all")
            continue
        if message.kind == MSG_ERROR:
            detail = message.payload.decode("utf-8", errors="ignore") if message.payload else ""
            print(f"[SERVER] ERROR from client: {detail or 'unspecified'}")
            control_plane.on_error(ErrorCode.PROTOCOL_VIOLATION, detail or None)
            stop_event.set()
            break
        if message.kind == MSG_EOF:
            print("[SERVER] Received EOF marker from client")
            _telemetry("recv_eof", "all")
            control_plane.on_eof_received()
            producer_done.set()
            break
        if message.kind != MSG_DATA:
            print(f"[SERVER] Ignoring unexpected message kind: {message.kind}")
            continue
        if address.channel != DATA_CHANNEL:
            print(f"[SERVER] WARN: Received data on control channel: {message.name}")
        if control_plane.state in (ControlState.INIT, ControlState.HANDSHAKING):
            control_plane.on_first_data()
        job = DecodeJob(
            sequence=address.sequence,
            name=address.name or "frame",
            payload=message.payload,
            received_at=time.monotonic(),
        )
        totals["bytes_in"] += len(message.payload)
        # ``asyncio.Queue`` enforces the backpressure window shared with decode/send stages.
        await decode_queue.put(job)
        _telemetry(
            "recv_data",
            job.name,
            size=len(job.payload),
            depth=decode_queue.qsize(),
            seq=job.sequence,
        )
        try:
            ack_payload = (
                ACK_PAYLOAD_STRUCT.pack(job.sequence)
                if job.sequence is not None
                else b""
            )
            await _send_control_message(
                control,
                protocol,
                conn,
                Message(
                    kind=MSG_ACK,
                    name=encode_frame_address(job.sequence, job.name, channel=CONTROL_CHANNEL),
                    payload=ack_payload,
                ),
            )
            _telemetry("send_ack", job.name, seq=job.sequence)
        except Exception as exc:
            print(f"[SERVER] WARN: Failed to send ACK for {job.name}: {exc}")
            stop_event.set()
            break
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
        job = await decode_queue.get()
        if job is None:
            decode_queue.task_done()
            # Propagate shutdown to the sender so the EOF handshake can trigger once workers drain.
            await send_queue.put(None)
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
            artifact = await asyncio.to_thread(
                decode_drc,
                decoder,
                job.payload,
                work_dir,
                job.name,
                timeout=args.decode_timeout,
                keep_artifacts=args.keep_artifacts,
                zero_copy=args.zero_copy_reply,
            )
            decoded_at = time.monotonic()
            stats.decode_time.record(decoded_at - decode_start)
            _telemetry(
                "decode_complete",
                job.name,
                worker=worker_id,
                seq=job.sequence,
                latency_ms=(decoded_at - decode_start) * 1000.0,
            )
            await send_queue.put(PipelineResult(job=job, decoded_at=decoded_at, artifact=artifact))
        except Exception as exc:
            print(f"[SERVER] ERROR decoding {job.name}: {exc}")
            _telemetry("decode_error", job.name, worker=worker_id, seq=job.sequence)
            await send_queue.put(
                PipelineResult(job=job, decoded_at=time.monotonic(), error=str(exc))
            )
        finally:
            decode_queue.task_done()


async def _send_loop(
    protocol,
    conn: socket.socket,
    control: ControlChannel | None,
    send_queue: "asyncio.Queue[PipelineResult | None]",
    stats: PipelineStats,
    totals: Dict[str, int],
    stop_event: asyncio.Event,
    producer_done: asyncio.Event,
    worker_count: int,
    control_plane: ControlPlane,
) -> None:
    finished_workers = 0
    eof_sent = False
    while not stop_event.is_set():
        item = await send_queue.get()
        if item is None:
            finished_workers += 1
            send_queue.task_done()
            if finished_workers >= worker_count:
                break
            continue
        result = item
        send_start = time.monotonic()
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
            )
            stage_label = "send_error"
            if control_plane.state != ControlState.FAILED:
                control_plane.on_error(ErrorCode.INTERNAL_ERROR, result.error)
        else:
            name = result.job.name
            reply_name = name if name.endswith(".decoded") else f"{name}.decoded"
            message = Message(
                kind=MSG_DATA,
                name=encode_frame_address(
                    result.job.sequence,
                    reply_name,
                    channel=DATA_CHANNEL,
                ),
                payload=result.artifact.payload,
            )
            stage_label = "send_data"
        try:
            if message.kind == MSG_DATA:
                await asyncio.to_thread(protocol.send, conn, message)
            else:
                await _send_control_message(control, protocol, conn, message)
        except Exception as exc:
            print(f"[SERVER] ERROR sending {message.name or result.job.name}: {exc}")
            stop_event.set()
        else:
            if message.kind == MSG_DATA and result.artifact is not None:
                totals["bytes_out"] += len(result.artifact.payload)
                stats.decode_to_send.record(send_start - result.decoded_at)
                _telemetry(
                    stage_label,
                    result.job.name,
                    size=len(result.artifact.payload),
                    seq=result.job.sequence,
                )
            else:
                _telemetry(stage_label, result.job.name, seq=result.job.sequence)
        finally:
            if result.artifact is not None:
                try:
                    result.artifact.close()
                except Exception as cleanup_exc:
                    print(
                        f"[SERVER] WARN: Failed to cleanup artifact for {result.job.name}: {cleanup_exc}"
                    )
            send_queue.task_done()
    if not eof_sent and producer_done.is_set():
        if control_plane.state not in (ControlState.FAILED, ControlState.TERMINATED):
            control_plane.on_eof_sent()
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
            print(f"[SERVER] ERROR sending EOF marker: {exc}")
        with suppress(OSError):
            # ``SHUT_WR`` triggers a FIN after the MSG_EOF handshake reaches the client.
            conn.shutdown(socket.SHUT_WR)
        if control is not None:
            with suppress(OSError):
                control.sock.shutdown(socket.SHUT_WR)


async def handle_connection(
    conn: socket.socket,
    addr,
    args: argparse.Namespace,
    decoder: Path,
    work_dir: Path,
    stats: PipelineStats,
    totals: Dict[str, int],
    control_conn: socket.socket | None = None,
) -> ControlPlane:
    with ExitStack() as stack:
        data_conn = stack.enter_context(conn)
        control_socket = stack.enter_context(control_conn) if control_conn is not None else None
        if args.tcp_nodelay:
            with suppress(OSError):
                data_conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            if control_socket is not None:
                with suppress(OSError):
                    control_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        if args.socket_buffer_kb > 0:
            buf_size = args.socket_buffer_kb * 1024
            for opt in (socket.SO_SNDBUF, socket.SO_RCVBUF):
                with suppress(OSError):
                    data_conn.setsockopt(socket.SOL_SOCKET, opt, buf_size)
                if control_socket is not None:
                    with suppress(OSError):
                        control_socket.setsockopt(socket.SOL_SOCKET, opt, buf_size)
        if args.socket_timeout > 0:
            data_conn.settimeout(args.socket_timeout)
            if control_socket is not None:
                control_socket.settimeout(args.socket_timeout)
        protocol = resolve_protocol(args.protocol)
        print(f"[SERVER] Connection from {addr} using {protocol.name} protocol")
        control_channel: ControlChannel | None = None
        if control_socket is not None:
            control_protocol = resolve_protocol(args.protocol)
            control_channel = ControlChannel(sock=control_socket, protocol=control_protocol)
            try:
                peer = control_socket.getpeername()
            except OSError:
                peer = "unknown"
            print(
                f"[SERVER] Control channel paired from {peer} using {control_protocol.name} protocol"
            )

        control_plane = ControlPlane(role="server")
        control_plane.on_connected(time.monotonic_ns())

        max_inflight = max(1, args.max_inflight)
        if args.decode_workers <= 0:
            raise ValueError("decode_workers must be positive")
        decode_queue: "asyncio.Queue[DecodeJob | None]" = asyncio.Queue(maxsize=max_inflight)
        send_queue: "asyncio.Queue[PipelineResult | None]" = asyncio.Queue(maxsize=max_inflight)
        stop_event = asyncio.Event()
        producer_done = asyncio.Event()

        recv_task = asyncio.create_task(
            _recv_loop(
                protocol,
                data_conn,
                control_channel,
                decode_queue,
                stop_event,
                producer_done,
                totals,
                args.heartbeat_interval,
                control_plane,
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
                control_channel,
                send_queue,
                stats,
                totals,
                stop_event,
                producer_done,
                args.decode_workers,
                control_plane,
            )
        )

        tasks: Iterable[asyncio.Task[None]] = [recv_task, *worker_tasks, send_task]
        try:
            await recv_task
        except Exception:
            stop_event.set()
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
        return control_plane


async def run_server(args: argparse.Namespace) -> None:
    decoder = resolve_executable('draco_decoder', args.decoder, env_var='DRACO_DECODER')
    work_dir = ensure_directory(Path(args.work_dir).resolve())
    stats = PipelineStats()
    totals: Dict[str, int] = {"bytes_in": 0, "bytes_out": 0}
    start_time = time.monotonic()

    if args.control_port and args.control_port == args.port:
        raise ValueError("control-port must differ from data port when enabled")

    try:
        server = socket.create_server((args.host, args.port), reuse_port=True)
    except OSError as exc:
        print(f"[SERVER] WARN: reuse_port failed ({exc}), retrying without it")
        server = socket.create_server((args.host, args.port))

    control_server: socket.socket | None = None
    if args.control_port > 0:
        try:
            control_server = socket.create_server((args.host, args.control_port), reuse_port=True)
        except OSError as exc:
            print(
                f"[SERVER] WARN: control reuse_port failed ({exc}), retrying without it")
            control_server = socket.create_server((args.host, args.control_port))

    with ExitStack() as stack:
        stack.enter_context(server)
        if control_server is not None:
            stack.enter_context(control_server)
        print(f"[SERVER] Listening on {args.host}:{args.port}")
        if control_server is not None:
            print(f"[SERVER] Control channel listening on {args.host}:{args.control_port}")
        conn, addr = await asyncio.to_thread(server.accept)
        print(f"[SERVER] Accepted connection from {addr}")
        control_conn: socket.socket | None = None
        control_addr = None
        if control_server is not None:
            control_conn, control_addr = await asyncio.to_thread(control_server.accept)
            print(f"[SERVER] Accepted control connection from {control_addr}")
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
                control_conn=control_conn,
            )
        finally:
            with suppress(Exception):
                conn.close()
            if control_conn is not None:
                with suppress(Exception):
                    control_conn.close()

    elapsed = max(time.monotonic() - start_time, 1e-6)
    if control_plane is not None:
        _export_server_telemetry(
            control_plane,
            stats,
            totals,
            protocol=args.protocol,
            elapsed=elapsed,
        )
    print("[SERVER] ---- Bandwidth summary ----")
    print(f"  elapsed: {elapsed:.2f} s")
    print(
        f"  inbound: {totals['bytes_in']} bytes ({totals['bytes_in'] * 8 / elapsed / 1e6:.3f} Mbps)"
    )
    print(
        f"  outbound: {totals['bytes_out']} bytes ({totals['bytes_out'] * 8 / elapsed / 1e6:.3f} Mbps)"
    )
    total = totals['bytes_in'] + totals['bytes_out']
    print(f"  total: {total} bytes ({total * 8 / elapsed / 1e6:.3f} Mbps)")
    print("  stage metrics:")
    print(f"    recv→decode: {stats.recv_to_decode.summary()}")
    print(f"    decode time: {stats.decode_time.summary()}")
    print(f"    decode→send: {stats.decode_to_send.summary()}")


def run_server_legacy(args: argparse.Namespace) -> None:
    decoder = resolve_executable('draco_decoder', args.decoder, env_var='DRACO_DECODER')
    work_dir = ensure_directory(Path(args.work_dir).resolve())
    start_time = time.monotonic()
    bytes_in = 0
    bytes_out = 0
    if args.control_port > 0:
        print(
            "[SERVER][LEGACY] WARN: control-port ignored in legacy mode; using single channel"
        )
    try:
        server = socket.create_server((args.host, args.port), reuse_port=True)
    except OSError as exc:
        print(f"[SERVER] WARN: reuse_port failed ({exc}), retrying without it")
        server = socket.create_server((args.host, args.port))

    with server:
        print(f"[SERVER][LEGACY] Listening on {args.host}:{args.port}")
        conn, addr = server.accept()
        print(f"[SERVER][LEGACY] Connection from {addr}")
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
                            name=encode_frame_address(None, "final", channel=CONTROL_CHANNEL),
                            payload=b"",
                        ),
                    )
                    eof_sent = True
                    break
                if msg.kind != MSG_DATA:
                    continue
                if address.channel != DATA_CHANNEL:
                    print(f"[SERVER][LEGACY] WARN: data on control channel: {msg.name}")
                stem = address.name or "frame"
                try:
                    protocol.send(
                        conn,
                        Message(
                            kind=MSG_ACK,
                            name=encode_frame_address(address.sequence, stem, channel=CONTROL_CHANNEL),
                            payload=b"",
                        ),
                    )
                    _telemetry("send_ack", stem, seq=address.sequence if address.sequence is not None else -1)
                except Exception as exc:
                    print(f"[SERVER][LEGACY] WARN: Failed to send ACK for {stem}: {exc}")
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
                        name=encode_frame_address(address.sequence, stem, channel=CONTROL_CHANNEL),
                        payload=str(exc).encode(),
                    )
                    protocol.send(conn, error_msg)
                    continue
                reply_name = stem if stem.endswith(".decoded") else f"{stem}.decoded"
                reply = Message(
                    kind=MSG_DATA,
                    name=encode_frame_address(address.sequence, reply_name, channel=DATA_CHANNEL),
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
                        name=encode_frame_address(None, "final", channel=CONTROL_CHANNEL),
                        payload=b"",
                    ),
                )
    elapsed = max(time.monotonic() - start_time, 1e-6)
    total = bytes_in + bytes_out
    print("[SERVER][LEGACY] ---- Bandwidth summary ----")
    print(f"  elapsed: {elapsed:.2f} s")
    print(f"  inbound: {bytes_in} bytes ({bytes_in * 8 / elapsed / 1e6:.3f} Mbps)")
    print(f"  outbound: {bytes_out} bytes ({bytes_out * 8 / elapsed / 1e6:.3f} Mbps)")
    print(f"  total: {total} bytes ({total * 8 / elapsed / 1e6:.3f} Mbps)")


def main(argv: list[str] | None = None) -> None:
    args = build_arg_parser().parse_args(argv)
    if args.legacy_mode:
        run_server_legacy(args)
    else:
        asyncio.run(run_server(args))


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
