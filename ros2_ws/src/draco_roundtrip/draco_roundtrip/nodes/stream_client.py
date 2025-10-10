#!/usr/bin/env python3
"""Stream rosbag frames, encode/send to server, replay decoded results to RViz."""

from __future__ import annotations

import argparse
import contextlib
import queue
import socket
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass
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
    """Track inflight frames so replies can be matched without stalling the sender."""

    handle: FrameHandle
    sent_at: float
    payload_size: int


@dataclass(slots=True)
class ReplyEvent:
    kind: str
    message: Message | None = None
    error: BaseException | None = None


class ReplyPump(threading.Thread):
    """Background thread that continuously drains replies from the server."""

    def __init__(
        self,
        sock: socket.socket,
        queue: "queue.Queue[ReplyEvent]",
        stop_event: threading.Event,
        protocol: ProtocolHandler,
    ) -> None:
        super().__init__(daemon=True)
        self._sock = sock
        self._queue = queue
        self._stop_event = stop_event
        self._protocol = protocol

    def run(self) -> None:  # pragma: no cover - threading behaviour is timing sensitive.
        while not self._stop_event.is_set():
            try:
                message = self._protocol.recv(self._sock)
            except socket.timeout:
                continue
            except Exception as exc:  # noqa: BLE001 - bubble up to the producer loop.
                self._queue.put(ReplyEvent(kind="error", error=exc))
                return
            if message is None:
                self._queue.put(ReplyEvent(kind="closed"))
                return
            self._queue.put(ReplyEvent(kind="message", message=message))
            if message.kind == MSG_EOF:
                return


class FrameHandle(Protocol):
    name: str

    def ensure_encoder_input(self, work_dir: Path) -> Path:
        ...

    def load_source_points(self) -> np.ndarray:
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

    def ensure_encoder_input(self, work_dir: Path) -> Path:  # noqa: ARG002 - interface requirement
        return self._path

    def load_source_points(self) -> np.ndarray:
        return load_xyz(self._path)

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
    ap.add_argument('--tcp-nodelay', action='store_true',
                    help='Disable Nagle aggregation to reduce latency for interactive playback')
    ap.add_argument('--socket-buffer-kb', type=int, default=0,
                    help='Resize socket send/receive buffers (KiB) to better saturate fast links')
    ap.add_argument('--capture-transport',
                    choices=('filesystem', 'shared-memory'),
                    default='shared-memory',
                    help='Frame capture backend: filesystem spool (legacy) or shared-memory zero copy')
    return ap


def main(argv: Iterable[str] | None = None) -> None:
    args = build_arg_parser().parse_args(argv)

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

    to_play: queue.Queue = queue.Queue()
    playback_thread = start_playback_thread(to_play, args.play_frame_id, args.play_topic_prefix, args.play_hz)

    frame_idx = 0
    start_time = time.monotonic()
    bytes_sent = 0
    bytes_received = 0
    pending: Deque[FrameHandle] = deque()
    inflight: Dict[str, FrameContext] = {}
    shared_receiver: SharedMemoryReceiver | None = None

    try:
        with socket.create_connection(
            (args.server_host, args.server_port),
            timeout=args.socket_timeout if args.socket_timeout > 0 else None,
        ) as sock:
            if args.socket_timeout > 0:
                # NOTE: Guard against stalled reads when the server crashes mid-transfer.
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
            with contextlib.ExitStack() as stack:
                frame_supplier: FilesystemFrameSupplier | SharedMemoryFrameSupplier
                if args.capture_transport == "filesystem":
                    watcher = stack.enter_context(SpoolWatcher(ply_dir, args.prefix))
                    frame_supplier = FilesystemFrameSupplier(watcher)
                elif args.capture_transport == "shared-memory":
                    shared_receiver = SharedMemoryReceiver()
                    shared_receiver.start()
                    stack.callback(shared_receiver.stop)
                    frame_supplier = SharedMemoryFrameSupplier(shared_receiver)
                else:
                    raise ValueError(f"unknown capture transport '{args.capture_transport}'")

                pending = deque(frame_supplier.drain_initial())
                eof_sent = False
                shutdown_ack = False
                stop_event = threading.Event()
                reply_queue: "queue.Queue[ReplyEvent]" = queue.Queue()
                pump = ReplyPump(sock, reply_queue, stop_event, protocol)
                pump.start()
                shared_host = shared_receiver.host if shared_receiver else None
                shared_port = shared_receiver.port if shared_receiver else None
                saver_proc = launch_bag_to_ply(
                    args,
                    ply_dir,
                    shared_memory_host=shared_host,
                    shared_memory_port=shared_port,
                    shared_memory_only=(args.capture_transport == "shared-memory"),
                )
                try:
                    while True:
                        max_inflight = max(1, args.max_inflight)
                        progress_made = False

                        while pending and len(inflight) < max_inflight and not eof_sent:
                            handle = pending.popleft()
                            try:
                                encoder_input = handle.ensure_encoder_input(work_dir)
                                result = encode_frame(
                                    encoder_input,
                                    work_dir,
                                    encoder_options,
                                    encoder_hint=encoder_path,
                                    skip_existing=False,
                                )
                                drc_bytes = result.output.read_bytes()
                                with contextlib.suppress(FileNotFoundError):
                                    result.output.unlink()
                            except Exception as exc:
                                print(f"[CLIENT] ENCODE FAIL {handle.name}: {exc}")
                                handle.on_consumed()
                                continue
                            encoder_input_path = Path(encoder_input)
                            print(
                                format_encode_log(
                                    result,
                                    source=encoder_input_path,
                                    prefix='[CLIENT][ENCODER]'
                                )
                            )
                            message = Message(kind=MSG_DATA, name=handle.name, payload=drc_bytes)
                            try:
                                protocol.send(sock, message)
                            except socket.timeout:
                                print(f"[CLIENT] ERROR: Timeout sending {handle.name}")
                                handle.on_consumed()
                                eof_sent = True
                                break
                            inflight[handle.name] = FrameContext(
                                handle=handle,
                                sent_at=time.monotonic(),
                                payload_size=len(drc_bytes),
                            )
                            bytes_sent += len(drc_bytes)
                            print(f"[CLIENT] Sent {encoder_input_path.name} ({len(drc_bytes)} bytes)")
                            progress_made = True

                        def handle_reply(event: ReplyEvent) -> None:
                            nonlocal frame_idx, bytes_received, eof_sent, shutdown_ack
                            if event.kind == "message" and event.message:
                                reply = event.message
                                if reply.kind == MSG_EOF:
                                    print('[CLIENT] EOF handshake complete')
                                    shutdown_ack = True
                                    return
                                if reply.kind == MSG_ERROR:
                                    detail = reply.payload.decode(errors='ignore')
                                    stem = reply.name or 'frame'
                                    ctx = inflight.pop(Path(stem).stem, None)
                                    print(
                                        f"[CLIENT] SERVER ERROR for {stem}: {detail}"
                                    )
                                    if ctx:
                                        ctx.handle.on_consumed()
                                    return
                                stem = Path(reply.name or '').stem
                                ctx = inflight.pop(stem, None)
                                if ctx is None:
                                    print(f"[CLIENT] WARN: Received reply for unknown frame {reply.name}")
                                    return
                                bytes_received += len(reply.payload)
                                reply_name = reply.name or f"{stem}.decoded"
                                if not reply_name.endswith('.ply'):
                                    reply_name = f"{reply_name}.ply"
                                decoded_path = decoded_dir / reply_name
                                decoded_path.write_bytes(reply.payload)

                                pts_src = ctx.handle.load_source_points()
                                pts_dec = load_xyz_from_bytes(reply.payload)
                                metrics = compute_basic_metrics(pts_src, pts_dec, args.play_sample)
                                rtt = time.monotonic() - ctx.sent_at
                                throughput_mbps = (
                                    ctx.payload_size * 8 / max(rtt, 1e-6) / 1e6
                                )
                                print(
                                    f"[CLIENT] Frame {frame_idx:05d} metrics — "
                                    f"Δpts={metrics['diff']} centroid_norm={metrics['centroid_norm']:.3f} "
                                    f"bboxΔ=({metrics['bbox_delta'][0]:+.3f},{metrics['bbox_delta'][1]:+.3f},{metrics['bbox_delta'][2]:+.3f}) "
                                    f"Chamfer(mean/max)={metrics['chamfer_mean']}/{metrics['chamfer_max']} "
                                    f"RTT={rtt:.3f}s throughput={throughput_mbps:.2f}Mbps"
                                )
                                to_play.put((frame_idx, stem, pts_src, pts_dec))
                                ctx.handle.on_consumed()
                                frame_idx += 1
                                return
                            if event.kind == "error" and event.error:
                                raise event.error
                            if event.kind == "closed":
                                raise ConnectionClosed("server closed")

                        def drain_replies(block: bool, timeout: float | None = None) -> bool:
                            drained = False
                            if block:
                                try:
                                    event = reply_queue.get(timeout=timeout)
                                except queue.Empty:
                                    return False
                                handle_reply(event)
                                drained = True
                            while True:
                                try:
                                    event = reply_queue.get_nowait()
                                except queue.Empty:
                                    break
                                handle_reply(event)
                                drained = True
                            return drained

                        while drain_replies(block=False):
                            progress_made = True
                            if shutdown_ack:
                                break
                        if shutdown_ack:
                            break

                        if not eof_sent:
                            new_handles = frame_supplier.wait_for_new(timeout=0.2)
                            if new_handles:
                                pending.extend(new_handles)
                                progress_made = True

                        bag_done = bag_process.poll() is not None
                        saver_done = saver_proc is None or saver_proc.poll() is not None
                        if (
                            bag_done
                            and saver_done
                            and not pending
                            and not inflight
                            and not eof_sent
                        ):
                            eof_message = Message(kind=MSG_EOF, name='', payload=b'')
                            try:
                                protocol.send(sock, eof_message)
                            except socket.timeout:
                                print('[CLIENT] Timeout while sending EOF marker')
                                break
                            print('[CLIENT] Sent EOF marker to server')
                            eof_sent = True
                            progress_made = True

                        if shutdown_ack:
                            break

                        if inflight and (len(inflight) >= max_inflight or not pending):
                            progress_made = drain_replies(
                                block=True,
                                timeout=args.socket_timeout if args.socket_timeout > 0 else None,
                            ) or progress_made
                            if shutdown_ack:
                                break

                        if not pending and not inflight and eof_sent:
                            if shutdown_ack:
                                break
                            progress_made = drain_replies(
                                block=True,
                                timeout=args.socket_timeout if args.socket_timeout > 0 else None,
                            ) or progress_made
                            if shutdown_ack:
                                break

                        if not progress_made:
                            if inflight:
                                progress_made = drain_replies(
                                    block=True,
                                    timeout=args.socket_timeout if args.socket_timeout > 0 else None,
                                )
                                if shutdown_ack:
                                    break
                            elif not eof_sent:
                                new_handles = frame_supplier.wait_for_new(timeout=0.5)
                                if new_handles:
                                    pending.extend(new_handles)
                                    progress_made = True

                        if shutdown_ack:
                            break

                        if not progress_made and not pending and not inflight and eof_sent:
                            break
                except ConnectionClosed:
                    print('[CLIENT] Connection closed, stopping loop')
                except socket.timeout:
                    print('[CLIENT] Socket timeout encountered, shutting down connection')
                finally:
                    stop_event.set()
                    if pump.is_alive():
                        pump.join(timeout=1.0)
    finally:
        for ctx in inflight.values():
            with contextlib.suppress(Exception):
                ctx.handle.on_aborted()
        while pending:
            handle = pending.popleft()
            with contextlib.suppress(Exception):
                handle.on_aborted()
        to_play.put(None)
        if playback_thread.is_alive():
            playback_thread.join(timeout=1.0)
        _terminate_process(bag_process, 'ros2 bag')
        if saver_proc is not None:
            _terminate_process(saver_proc, 'bag_to_ply')
        elapsed = max(time.monotonic() - start_time, 1e-6)
        print('[CLIENT] ---- Transfer summary ----')
        print(f"  elapsed: {elapsed:.2f} s")
        print(f"  sent: {bytes_sent} bytes ({bytes_sent * 8 / elapsed / 1e6:.3f} Mbps)")
        print(f"  received: {bytes_received} bytes ({bytes_received * 8 / elapsed / 1e6:.3f} Mbps)")


if __name__ == '__main__':
    main()

# 변경 요약:
# - 공유 메모리 기반 캡처 백엔드를 추가해 디스크 스풀 없이 프레임을 공급할 수 있도록 했습니다.
# - 프레임 핸들 추상화로 파일/공유 메모리 경로를 통합 관리하고 전송 실패 시에도 자원을 정리합니다.
# - 인코더 산출물과 응답 처리 흐름을 보강해 임시 파일을 자동 삭제하고 기존 메트릭 파이프라인과 연계했습니다.
