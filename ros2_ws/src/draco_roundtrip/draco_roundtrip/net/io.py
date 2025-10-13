"""Socket I/O utilities shared by client and server."""

from __future__ import annotations

import socket


def recv_exact(sock: socket.socket, size: int) -> bytes:
    """Read exactly ``size`` bytes or raise ``ConnectionError``."""

    if size < 0:
        raise ValueError("size must be non-negative")
    buf = bytearray()
    remaining = size
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise ConnectionError("socket closed before recv_exact completed")
        buf.extend(chunk)
        remaining -= len(chunk)
    return bytes(buf)
