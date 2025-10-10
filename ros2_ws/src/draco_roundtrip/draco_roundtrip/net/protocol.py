"""TCP protocol helpers shared by client/server.

The original implementation relied on a text meta-header (``"kind:name"``)
sent ahead of the payload.  While simple, that approach required several
``sendall``/``recv`` syscalls and UTF-8 encoding work on every frame.  To
support the network latency reduction roadmap we introduce a compact binary
framing format.  Both variants live side-by-side and can be selected via the
command-line flags exposed by ``stream_client`` and ``stream_server``.
"""

from __future__ import annotations

import socket
import struct
from dataclasses import dataclass
from typing import Callable, Dict, Optional

__all__ = [
    "Message",
    "ProtocolError",
    "ConnectionClosed",
    "MSG_DATA",
    "MSG_ERROR",
    "MSG_EOF",
    "MSG_ACK",
    "MSG_HEARTBEAT",
    "ProtocolHandler",
    "available_protocols",
    "resolve_protocol",
    "send_message",
    "recv_message",
]

_HEADER = struct.Struct("!I")
_SIZE = struct.Struct("!Q")
_SEPARATOR = ":"

_BINARY_HEADER = struct.Struct("!BBH")  # version, kind, name length
_BINARY_SIZE = struct.Struct("!Q")
_BINARY_VERSION = 1

_KIND_TO_CODE = {"data": 0, "error": 1, "eof": 2, "ack": 3, "heartbeat": 4}
_CODE_TO_KIND = {value: key for key, value in _KIND_TO_CODE.items()}

MSG_DATA = "data"
MSG_ERROR = "error"
MSG_EOF = "eof"
MSG_ACK = "ack"
MSG_HEARTBEAT = "heartbeat"


class ProtocolError(RuntimeError):
    """Raised when the TCP framing is malformed."""


class ConnectionClosed(RuntimeError):
    """Raised when the peer closes the connection unexpectedly."""


@dataclass(slots=True)
class Message:
    kind: str
    name: str
    payload: bytes

    def as_meta(self) -> str:
        return f"{self.kind}{_SEPARATOR}{self.name}" if self.name else self.kind

    @classmethod
    def from_meta(cls, meta: str, payload: bytes) -> "Message":
        if _SEPARATOR in meta:
            kind, name = meta.split(_SEPARATOR, 1)
        else:
            # NOTE: Legacy text framing omitted the kind for data messages, but
            # control frames (EOF/ERROR) can appear without a name.  Preserve the
            # behaviour where an unknown token is treated as the frame name for a
            # data message while ensuring well-known kinds round-trip correctly.
            if meta in {MSG_ERROR, MSG_EOF} and not payload:
                kind, name = meta, ""
            elif meta == MSG_DATA and not payload:
                kind, name = MSG_DATA, ""
            else:
                kind, name = MSG_DATA, meta
        return cls(kind=kind or MSG_DATA, name=name, payload=payload)


def _read_exact(sock: socket.socket, size: int) -> bytes:
    buf = bytearray()
    while len(buf) < size:
        chunk = sock.recv(size - len(buf))
        if not chunk:
            raise ConnectionClosed("socket closed while reading")
        buf.extend(chunk)
    return bytes(buf)


def _send_text(sock: socket.socket, message: Message) -> None:
    meta = message.as_meta().encode("utf-8")
    sock.sendall(_HEADER.pack(len(meta)))
    sock.sendall(meta)
    sock.sendall(_SIZE.pack(len(message.payload)))
    if message.payload:
        sock.sendall(message.payload)


def _send_all(sock: socket.socket, payload: bytes, *, chunk_size: int = 1400) -> None:
    """Transmit payload in MTU-friendly chunks to reduce large write spikes."""

    view = memoryview(payload)
    total = len(view)
    offset = 0
    while offset < total:
        end = offset + chunk_size
        sent = sock.send(view[offset:end])
        if sent <= 0:
            raise ConnectionClosed("socket closed while writing")
        offset += sent


def _recv_text(sock: socket.socket) -> Optional[Message]:
    header = sock.recv(_HEADER.size)
    if not header:
        return None
    if len(header) != _HEADER.size:
        raise ProtocolError("incomplete header")
    (name_len,) = _HEADER.unpack(header)
    if name_len <= 0:
        return None
    meta = _read_exact(sock, name_len).decode("utf-8")
    (payload_len,) = _SIZE.unpack(_read_exact(sock, _SIZE.size))
    payload = _read_exact(sock, payload_len) if payload_len else b""
    return Message.from_meta(meta, payload)


def _send_binary(sock: socket.socket, message: Message) -> None:
    kind_code = _KIND_TO_CODE.get(message.kind, _KIND_TO_CODE[MSG_DATA])
    name_bytes = message.name.encode("utf-8") if message.name else b""
    if len(name_bytes) > 0xFFFF:
        raise ProtocolError("message name too long for binary framing")
    header = _BINARY_HEADER.pack(_BINARY_VERSION, kind_code, len(name_bytes))
    sock.sendall(header)
    if name_bytes:
        sock.sendall(name_bytes)
    payload_len = len(message.payload)
    sock.sendall(_BINARY_SIZE.pack(payload_len))
    if payload_len:
        _send_all(sock, message.payload)


def _recv_binary(sock: socket.socket) -> Optional[Message]:
    header = sock.recv(_BINARY_HEADER.size)
    if not header:
        return None
    if len(header) != _BINARY_HEADER.size:
        raise ProtocolError("incomplete binary header")
    version, kind_code, name_len = _BINARY_HEADER.unpack(header)
    if version != _BINARY_VERSION:
        raise ProtocolError(f"unsupported binary protocol version {version}")
    if name_len:
        name_bytes = _read_exact(sock, name_len)
        name = name_bytes.decode("utf-8")
    else:
        name = ""
    (payload_len,) = _BINARY_SIZE.unpack(_read_exact(sock, _BINARY_SIZE.size))
    payload = _read_exact(sock, payload_len) if payload_len else b""
    try:
        kind = _CODE_TO_KIND[kind_code]
    except KeyError as exc:  # pragma: no cover - only triggered by wire corruption.
        raise ProtocolError(f"unknown message kind code {kind_code}") from exc
    return Message(kind=kind, name=name, payload=payload)


@dataclass(frozen=True)
class ProtocolHandler:
    """Runtime-selected framing helpers."""

    name: str
    send: Callable[[socket.socket, Message], None]
    recv: Callable[[socket.socket], Optional[Message]]
    description: str


_PROTOCOLS: Dict[str, ProtocolHandler] = {
    "text": ProtocolHandler(
        name="text",
        send=_send_text,
        recv=_recv_text,
        description="Length-prefixed UTF-8 meta header (backwards compatible)",
    ),
    "binary": ProtocolHandler(
        name="binary",
        send=_send_binary,
        recv=_recv_binary,
        description="Compact binary framing (reduced syscalls/encoding)",
    ),
}

_ALIASES: Dict[str, str] = {"legacy": "text"}


def available_protocols() -> Dict[str, str]:
    """Return protocol names mapped to descriptions for CLI help."""

    mapping = {name: handler.description for name, handler in _PROTOCOLS.items()}
    for alias, target in _ALIASES.items():
        handler = _PROTOCOLS[target]
        mapping[alias] = f"alias for {handler.name}: {handler.description}"
    return mapping


def resolve_protocol(name: str) -> ProtocolHandler:
    """Return the framing handler requested by the user."""

    try:
        canonical = _ALIASES.get(name, name)
        return _PROTOCOLS[canonical]
    except KeyError as exc:  # pragma: no cover - argument parsing validates.
        raise ValueError(f"unknown protocol '{name}'") from exc


def send_message(sock: socket.socket, message: Message) -> None:
    """Default send helper (text framing)."""

    _PROTOCOLS["text"].send(sock, message)


def recv_message(sock: socket.socket) -> Optional[Message]:
    """Default receive helper (text framing)."""

    return _PROTOCOLS["text"].recv(sock)
