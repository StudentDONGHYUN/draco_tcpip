"""TCP protocol helpers shared by client and server."""

from __future__ import annotations

import contextlib
import logging
import socket
import struct
from dataclasses import dataclass
from typing import Callable, Dict, Optional

from .io import recv_exact
from ..protocol.header import (
    FLAG_FRAGMENTED,
    FLAG_MORE_FRAGMENTS,
    FrameHeader,
    FrameType,
    FragmentInfo,
    FRAGMENT_INFO_SIZE,
    HEADER_PREFIX_SIZE,
    HEADER_SIZE,
    LEGACY_HEADER_SIZE,
    HeaderError,
    LEGACY_MAGIC,
    LEGACY_VERSION,
    MAGIC,
    VERSION,
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

MAX_TEXT_NAME_LEN = 4096
MAX_TEXT_PAYLOAD_LEN = 100 * 1024 * 1024

_HEADER = struct.Struct("!I")
_SIZE = struct.Struct("!Q")
_SEPARATOR = ":"

MSG_DATA = "data"
MSG_ERROR = "error"
MSG_EOF = "eof"
MSG_ACK = "ack"
MSG_HEARTBEAT = "heartbeat"

_FRAME_TYPE_BY_KIND = {
    MSG_DATA: FrameType.DATA,
    MSG_ERROR: FrameType.ERROR,
    MSG_EOF: FrameType.EOF,
    MSG_ACK: FrameType.ACK,
    MSG_HEARTBEAT: FrameType.HEARTBEAT,
}

_KIND_BY_FRAME_TYPE = {value: key for key, value in _FRAME_TYPE_BY_KIND.items()}

logger = logging.getLogger(__name__)
_text_limit_drops = 0


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
    fragmented: bool = False
    fragment_index: int | None = None
    fragments_total: int | None = None
    frame_payload_len: int | None = None
    flags: int | None = None
    timestamp_ns: int | None = None
    content_type: int | None = None
    header_version: int = VERSION

    def as_meta(self) -> str:
        return f"{self.kind}{_SEPARATOR}{self.name}" if self.name else self.kind

    @classmethod
    def from_meta(cls, meta: str, payload: bytes) -> "Message":
        if _SEPARATOR in meta:
            kind, name = meta.split(_SEPARATOR, 1)
        else:
            if meta in {MSG_ERROR, MSG_EOF} and not payload:
                kind, name = meta, ""
            elif meta == MSG_DATA and not payload:
                kind, name = MSG_DATA, ""
            else:
                kind, name = MSG_DATA, meta
        return cls(kind=kind or MSG_DATA, name=name, payload=payload)


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


def _close_socket(sock: socket.socket) -> None:
    with contextlib.suppress(OSError):
        sock.shutdown(socket.SHUT_RDWR)
    with contextlib.suppress(OSError):
        sock.close()


def _recv_text(sock: socket.socket) -> Optional[Message]:
    global _text_limit_drops
    header = sock.recv(_HEADER.size)
    if not header:
        return None
    if len(header) != _HEADER.size:
        raise ProtocolError("incomplete header")
    (name_len,) = _HEADER.unpack(header)
    if name_len <= 0:
        return None
    if name_len > MAX_TEXT_NAME_LEN:
        _text_limit_drops += 1
        logger.warning(
            "[PROTO] text meta length %d exceeds limit %d; closing connection",
            name_len,
            MAX_TEXT_NAME_LEN,
        )
        _close_socket(sock)
        raise ConnectionClosed("text meta length exceeded limit")
    meta = recv_exact(sock, name_len).decode("utf-8")
    (payload_len,) = _SIZE.unpack(recv_exact(sock, _SIZE.size))
    if payload_len > MAX_TEXT_PAYLOAD_LEN:
        _text_limit_drops += 1
        logger.warning(
            "[PROTO] text payload length %d exceeds limit %d; closing connection",
            payload_len,
            MAX_TEXT_PAYLOAD_LEN,
        )
        _close_socket(sock)
        raise ConnectionClosed("text payload length exceeded limit")
    payload = recv_exact(sock, payload_len) if payload_len else b""
    return Message.from_meta(meta, payload)


def _build_fragment_info(message: Message) -> tuple[FragmentInfo | None, bool]:
    if not message.fragmented and not message.fragments_total:
        return None, False
    total = message.fragments_total if message.fragments_total else 1
    index = message.fragment_index if message.fragment_index is not None else 0
    frame_len = (
        message.frame_payload_len
        if message.frame_payload_len is not None
        else len(message.payload)
    )
    fragment = FragmentInfo(index=index, total=total, frame_payload_len=frame_len)
    more = index < total - 1 or bool(message.fragmented and message.fragments_total is None)
    return fragment, more


def _send_binary(sock: socket.socket, message: Message) -> None:
    frame_type = _FRAME_TYPE_BY_KIND.get(message.kind, FrameType.DATA)
    name_bytes = message.name.encode("utf-8") if message.name else b""
    if len(name_bytes) > 0xFFFF:
        raise ProtocolError("message name too long for binary framing")
    sequence = message.sequence if message.sequence is not None else 0
    fragment, more = _build_fragment_info(message)
    flags = int(frame_type) & 0x0F
    if fragment is not None:
        flags |= FLAG_FRAGMENTED
    if more:
        flags |= FLAG_MORE_FRAGMENTS
    header = FrameHeader(
        frame_type=frame_type,
        sequence=sequence,
        name_len=len(name_bytes),
        payload_len=len(message.payload),
        timestamp_ns=message.timestamp_ns or 0,
        content_type=message.content_type or 0,
        flags=flags,
        version=message.header_version or VERSION,
        fragment=fragment,
    )
    sock.sendall(header.to_bytes())
    if name_bytes:
        sock.sendall(name_bytes)
    if message.payload:
        _send_all(sock, message.payload)


def _recv_binary(sock: socket.socket, *, allow_legacy: bool = False) -> Optional[Message]:
    first = sock.recv(HEADER_PREFIX_SIZE)
    if not first:
        return None
    header_buf = bytearray(first)
    while len(header_buf) < HEADER_PREFIX_SIZE:
        chunk = sock.recv(HEADER_PREFIX_SIZE - len(header_buf))
        if not chunk:
            raise ConnectionClosed("socket closed while reading header")
        header_buf.extend(chunk)
    magic = bytes(header_buf[:4])
    version = header_buf[4]
    flags = header_buf[5]
    if magic == MAGIC and version == VERSION:
        header_len = HEADER_SIZE
    elif allow_legacy and magic == LEGACY_MAGIC and version == LEGACY_VERSION:
        header_len = LEGACY_HEADER_SIZE
    else:
        raise ProtocolError(f"unsupported header magic/version {magic!r}/{version}")
    if flags & FLAG_FRAGMENTED:
        header_len += FRAGMENT_INFO_SIZE
    while len(header_buf) < header_len:
        chunk = sock.recv(header_len - len(header_buf))
        if not chunk:
            raise ConnectionClosed("socket closed while reading header")
        header_buf.extend(chunk)
    try:
        frame_header = FrameHeader.from_bytes(bytes(header_buf), allow_legacy=allow_legacy)
    except HeaderError as exc:
        raise ProtocolError(str(exc)) from exc
    name_bytes = recv_exact(sock, frame_header.name_len) if frame_header.name_len else b""
    name = name_bytes.decode("utf-8") if name_bytes else ""
    payload = recv_exact(sock, frame_header.payload_len) if frame_header.payload_len else b""
    kind = _KIND_BY_FRAME_TYPE.get(frame_header.frame_type, MSG_DATA)
    message = Message(kind=kind, name=name, payload=payload)
    message.sequence = frame_header.sequence
    message.fragmented = frame_header.is_fragmented
    message.flags = frame_header.flags
    message.timestamp_ns = frame_header.timestamp_ns
    message.content_type = frame_header.content_type
    message.header_version = frame_header.version
    if frame_header.fragment is not None:
        message.fragment_index = frame_header.fragment.index
        message.fragments_total = frame_header.fragment.total
        message.frame_payload_len = frame_header.fragment.frame_payload_len
        if not message.fragmented and frame_header.fragment.total > 1:
            message.fragmented = True
    if frame_header.flags & FLAG_MORE_FRAGMENTS:
        message.fragmented = True
    return message


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
        description="Compact Draco binary framing (shared header)",
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
