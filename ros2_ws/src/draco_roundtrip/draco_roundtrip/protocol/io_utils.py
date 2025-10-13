"""I/O helpers shared by transport components."""

from __future__ import annotations

import socket

__all__ = ["recv_exact"]


def recv_exact(sock: socket.socket, size: int) -> bytes:
    """Receive exactly ``size`` bytes or raise ``ConnectionError``.

    ``socket.recv`` is not guaranteed to return the requested amount; this helper keeps
    reading until the buffer is filled or EOF is encountered.
    """

    if size < 0:
        raise ValueError("size must be non-negative")
    remaining = size
    chunks: list[bytes] = []
    while remaining:
        chunk = sock.recv(remaining)
        if not chunk:
            raise ConnectionError("socket closed before recv_exact completed")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)

