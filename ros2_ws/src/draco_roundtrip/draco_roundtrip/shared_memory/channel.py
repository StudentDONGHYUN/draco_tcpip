"""TCP-coordinated shared memory channel for point cloud frames."""

from __future__ import annotations

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

    def __init__(self, host: str, port: int, *, connect_timeout: float = 5.0) -> None:
        self._host = host
        self._port = port
        self._connect_timeout = connect_timeout
        self._sock: Optional[socket.socket] = None
        self._lock = threading.Lock()

    def _ensure_connection(self) -> socket.socket:
        if self._sock is not None:
            return self._sock
        sock = socket.create_connection((self._host, self._port), timeout=self._connect_timeout)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._sock = sock
        return sock

    def publish(self, frame: str, points: np.ndarray) -> SharedMemoryDescriptor:
        """Publish a point cloud through shared memory and notify the listener."""

        if points.dtype != np.float32:
            points = np.asarray(points, dtype=np.float32)
        if not points.flags.c_contiguous:
            points = np.ascontiguousarray(points)
        size = int(points.nbytes)
        shape = tuple(int(v) for v in points.shape)
        if size == 0:
            shm_name = ""
        else:
            shm_name = f"draco_stream_{uuid.uuid4().hex}"
            segment = shared_memory.SharedMemory(name=shm_name, create=True, size=size)
            try:
                buffer = np.ndarray(shape, dtype=np.float32, buffer=segment.buf)
                buffer[...] = points
            finally:
                segment.close()
        descriptor = SharedMemoryDescriptor(
            frame=frame,
            shm=shm_name,
            size=size,
            shape=shape,
            dtype=str(np.float32),
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
        with self._lock:
            sock = self._ensure_connection()
            sock.sendall(payload)
        return descriptor

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

