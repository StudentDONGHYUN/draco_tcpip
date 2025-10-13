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

from draco_roundtrip.protocol import (
    HEADER_SIZE,
    HeaderType,
    SEQUENCE_NONE,
    pack_header,
    recv_exact,
    unpack_header,
)

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

MSG_DATA = "data"
MSG_ERROR = "error"
MSG_EOF = "eof"
MSG_ACK = "ack"
MSG_HEARTBEAT = "heartbeat"

_KIND_TO_TYPE = {
    MSG_DATA: HeaderType.DATA,
    MSG_ERROR: HeaderType.ERROR,
    MSG_EOF: HeaderType.HEARTBEAT,
    MSG_ACK: HeaderType.ACK,
    MSG_HEARTBEAT: HeaderType.HEARTBEAT,
}
_TYPE_TO_KIND = {
    HeaderType.DATA: MSG_DATA,
    HeaderType.ERROR: MSG_ERROR,
    HeaderType.ACK: MSG_ACK,
    HeaderType.HEARTBEAT: MSG_HEARTBEAT,
}

_RESERVED_EOF = 0x45  # ASCII 'E'


class ProtocolError(RuntimeError):
    """Raised when the TCP framing is malformed."""


class ConnectionClosed(RuntimeError):
    """Raised when the peer closes the connection unexpectedly."""


@dataclass(slots=True)
class Message:
    kind: str
    name: str
    payload: bytes
    sequence: int | None = None
    flags: int = 0
    reserved: int = 0
    version: int = 1

    def header_type(self) -> HeaderType:
        return _KIND_TO_TYPE.get(self.kind, HeaderType.DATA)

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
    name_bytes = message.name.encode("utf-8") if message.name else b""
    if len(name_bytes) > 0xFFFF:
        raise ProtocolError("message name too long for binary framing")
    payload_len = len(message.payload)
    sequence = message.sequence if message.sequence is not None else SEQUENCE_NONE
    reserved = message.reserved
    if message.kind == MSG_EOF and not reserved:
        reserved = _RESERVED_EOF
    header_bytes = pack_header(
        flags=message.flags,
        msg_type=message.header_type(),
        sequence=sequence,
        name_length=len(name_bytes),
        payload_length=payload_len,
        version=message.version,
        reserved=reserved,
    )
    sock.sendall(header_bytes)
    if name_bytes:
        sock.sendall(name_bytes)
    if payload_len:
        _send_all(sock, message.payload)


def _recv_binary(sock: socket.socket) -> Optional[Message]:
    try:
        header_bytes = recv_exact(sock, HEADER_SIZE)
    except ConnectionError:
        return None
    header = unpack_header(header_bytes)
    name = ""
    if header.name_length:
        name_bytes = recv_exact(sock, header.name_length)
        name = name_bytes.decode("utf-8")
    payload = recv_exact(sock, header.payload_length) if header.payload_length else b""
    msg_type = header.type
    try:
        kind = _TYPE_TO_KIND[msg_type]
    except KeyError:  # pragma: no cover
        kind = MSG_DATA
    if msg_type is HeaderType.HEARTBEAT and header.reserved == _RESERVED_EOF:
        kind = MSG_EOF
    sequence = header.sequence if header.sequence != SEQUENCE_NONE else None
    return Message(
        kind=kind,
        name=name,
        payload=payload,
        sequence=sequence,
        flags=header.flags,
        reserved=header.reserved,
        version=header.version,
    )


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
