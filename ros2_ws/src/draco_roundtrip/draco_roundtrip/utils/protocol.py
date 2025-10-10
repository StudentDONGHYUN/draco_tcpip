"""Backwards-compatible shim importing protocol helpers from the new module."""

from draco_roundtrip.net.protocol import (  # noqa: F401
    ConnectionClosed,
    Message,
    MSG_DATA,
    MSG_EOF,
    MSG_ERROR,
    ProtocolError,
    recv_message,
    send_message,
)

__all__ = [
    "ConnectionClosed",
    "Message",
    "ProtocolError",
    "MSG_DATA",
    "MSG_EOF",
    "MSG_ERROR",
    "send_message",
    "recv_message",
]
