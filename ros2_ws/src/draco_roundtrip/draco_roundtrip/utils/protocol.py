"""Backwards-compatible shim importing protocol helpers from the new module."""

from draco_roundtrip.net.protocol import (  # noqa: F401
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
    recv_message,
    resolve_protocol,
    send_message,
)

__all__ = [
    "ConnectionClosed",
    "Message",
    "ProtocolError",
    "ProtocolHandler",
    "MSG_DATA",
    "MSG_EOF",
    "MSG_ERROR",
    "MSG_ACK",
    "MSG_HEARTBEAT",
    "available_protocols",
    "send_message",
    "resolve_protocol",
    "recv_message",
]
