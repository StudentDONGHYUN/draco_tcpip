"""TCP-coordinated shared memory channel for point cloud frames."""

from __future__ import annotations

import contextlib
import json
import queue
import socket
import threading
import time
import uuid
from dataclasses import dataclass
from multiprocessing import shared_memory
from typing import List, Optional, Tuple

import numpy as np

__all__ = [
    "SharedMemoryDescriptor",
    "SharedMemoryPublisher",
    "SharedMemoryReceiver",
]


@dataclass(slots=True)
class SharedMemoryDescriptor:
    """Metadata describing a frame stored in shared memory."""

    frame: str
    shm: str
    size: int
    shape: Tuple[int, ...]
    dtype: str
    timestamp: float


class SharedMemoryPublisher:
    """Send numpy arrays over a TCP side channel using shared memory."""

    def __init__(
        self,
        host: str,
        port: int,
        *,
        connect_timeout: float = 5.0,
        enable_janitor: bool = False,
        janitor_interval: float = 5.0,
    ) -> None:
        self._host = host
        self._port = port
        self._connect_timeout = connect_timeout
        self._sock: Optional[socket.socket] = None
        self._lock = threading.Lock()
        self._janitor_enabled = enable_janitor
        self._janitor_interval = max(0.1, janitor_interval)
        self._dangling: "queue.Queue[str]" = queue.Queue()
        self._janitor_stop: threading.Event | None = threading.Event() if enable_janitor else None
        self._janitor_thread: threading.Thread | None = None
        if enable_janitor:
            self._janitor_thread = threading.Thread(
                target=self._janitor_loop,
                name="SharedMemoryJanitor",
                daemon=True,
            )
            self._janitor_thread.start()

    def _ensure_connection(self) -> socket.socket:
        if self._sock is not None:
            return self._sock
        sock = socket.create_connection((self._host, self._port), timeout=self._connect_timeout)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._sock = sock
        return sock

    @staticmethod
    def _try_unlink(name: str) -> bool:
        if not name:
            return True
        try:
            shm = shared_memory.SharedMemory(name=name)
        except FileNotFoundError:
            return True
        except Exception:
            return False
        try:
            shm.unlink()
            return True
        except FileNotFoundError:
            return True
        except Exception:
            return False
        finally:
            with contextlib.suppress(Exception):
                shm.close()

    def _schedule_unlink(self, name: str) -> None:
        if not name:
            return
        if self._try_unlink(name):
            return
        if self._janitor_enabled and self._janitor_stop is not None:
            self._dangling.put_nowait(name)

    def _janitor_loop(self) -> None:  # pragma: no cover - background maintenance
        assert self._janitor_stop is not None
        while not self._janitor_stop.is_set():
            try:
                name = self._dangling.get(timeout=self._janitor_interval)
            except queue.Empty:
                continue
            if not name:
                continue
            self._try_unlink(name)

    def publish(self, frame: str, points: np.ndarray) -> SharedMemoryDescriptor:
        """Publish a point cloud through shared memory and notify the listener."""

        if points.dtype != np.float32:
            points = np.asarray(points, dtype=np.float32)
        if not points.flags.c_contiguous:
            points = np.ascontiguousarray(points)
        size = int(points.nbytes)
        shape = tuple(int(v) for v in points.shape)
        cleanup_name: str | None = None
        segment: shared_memory.SharedMemory | None = None
        if size == 0:
            shm_name = ""
        else:
            shm_name = f"draco_stream_{uuid.uuid4().hex}"
            segment = shared_memory.SharedMemory(name=shm_name, create=True, size=size)
            cleanup_name = shm_name
            buffer = np.ndarray(shape, dtype=np.float32, buffer=segment.buf)
            buffer[...] = points
        descriptor = SharedMemoryDescriptor(
            frame=frame,
            shm=shm_name,
            size=size,
            shape=shape,
            dtype=np.dtype(np.float32).name,
            timestamp=time.time(),
        )
        payload = json.dumps(
            {
                "frame": descriptor.frame,
                "shm": descriptor.shm,
                "size": descriptor.size,
                "shape": descriptor.shape,
                "dtype": descriptor.dtype,
                "timestamp": descriptor.timestamp,
            },
            separators=(",", ":"),
        ).encode("utf-8") + b"\n"
        try:
            with self._lock:
                sock = self._ensure_connection()
                sock.sendall(payload)
            cleanup_name = None
            return descriptor
        finally:
            if segment is not None:
                with contextlib.suppress(Exception):
                    segment.close()
            if cleanup_name:
                self._schedule_unlink(cleanup_name)

    def close(self) -> None:
        with self._lock:
            if self._sock is not None:
                try:
                    self._sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                try:
                    self._sock.close()
                except OSError:
                    pass
                self._sock = None
        if self._janitor_enabled and self._janitor_stop is not None:
            self._janitor_stop.set()
            self._dangling.put_nowait("")
            if self._janitor_thread is not None:
                self._janitor_thread.join(timeout=1.0)


class SharedMemoryReceiver:
    """Accept shared-memory frame notifications and expose them via a queue."""

    def __init__(self, host: str = "127.0.0.1", port: int = 0) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((host, port))
        self.host, self.port = self._sock.getsockname()
        self._sock.listen(1)
        self._queue: "queue.Queue[SharedMemoryDescriptor]" = queue.Queue()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="SharedMemoryReceiver", daemon=True)

    def _run(self) -> None:  # pragma: no cover - networking/thread timing dependent
        conn: Optional[socket.socket] = None
        buffer = bytearray()
        try:
            conn, _ = self._sock.accept()
            conn.settimeout(0.5)
            while not self._stop.is_set():
                try:
                    chunk = conn.recv(65536)
                except socket.timeout:
                    continue
                if not chunk:
                    break
                buffer.extend(chunk)
                while True:
                    newline = buffer.find(b"\n")
                    if newline == -1:
                        break
                    line = bytes(buffer[:newline])
                    del buffer[:newline + 1]
                    if not line:
                        continue
                    try:
                        meta = json.loads(line.decode("utf-8"))
                    except json.JSONDecodeError:
                        continue
                    shape = tuple(int(v) for v in meta.get("shape", ()))
                    descriptor = SharedMemoryDescriptor(
                        frame=str(meta.get("frame", "")),
                        shm=str(meta.get("shm", "")),
                        size=int(meta.get("size", 0)),
                        shape=shape,
                        dtype=str(meta.get("dtype", "float32")),
                        timestamp=float(meta.get("timestamp", time.time())),
                    )
                    self._queue.put(descriptor)
        finally:
            if conn is not None:
                try:
                    conn.close()
                except OSError:
                    pass
            try:
                self._sock.close()
            except OSError:
                pass

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        try:
            with socket.create_connection((self.host, self.port), timeout=0.2):
                pass
        except OSError:
            pass
        self._thread.join(timeout=1.0)

    def get_batch(self, timeout: float) -> List[SharedMemoryDescriptor]:
        frames: List[SharedMemoryDescriptor] = []
        try:
            first = self._queue.get(timeout=timeout)
        except queue.Empty:
            return frames
        frames.append(first)
        while True:
            try:
                frames.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return frames

