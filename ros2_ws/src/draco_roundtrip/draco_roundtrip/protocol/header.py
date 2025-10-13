"""Binary transport header shared by stream client/server."""

from __future__ import annotations

import dataclasses
import enum
import struct
from typing import Final

__all__ = [
    "MAGIC",
    "Header",
    "HeaderType",
    "SEQUENCE_NONE",
    "FLAGS_FRAGMENTED",
    "FLAGS_FRAGMENT_START",
    "FLAGS_FRAGMENT_END",
    "SIZE",
    "pack_header",
    "unpack_header",
]

MAGIC: Final[bytes] = b"DRTC"
_FMT: Final[str] = "!4sBBBBIHI"
SIZE: Final[int] = struct.calcsize(_FMT)
_VERSION: Final[int] = 1
SEQUENCE_NONE: Final[int] = 0xFFFFFFFF


class HeaderType(enum.IntEnum):
    DATA = 1
    ACK = 2
    ERROR = 3
    HEARTBEAT = 4


FLAGS_FRAGMENTED: Final[int] = 0x01
FLAGS_FRAGMENT_START: Final[int] = 0x02
FLAGS_FRAGMENT_END: Final[int] = 0x04


@dataclasses.dataclass(slots=True)
class Header:
    version: int
    flags: int
    type: HeaderType
    reserved: int
    sequence: int
    name_length: int
    payload_length: int

    def is_fragmented(self) -> bool:
        return bool(self.flags & FLAGS_FRAGMENTED)

    def is_fragment_start(self) -> bool:
        return bool(self.flags & FLAGS_FRAGMENT_START)

    def is_fragment_end(self) -> bool:
        return bool(self.flags & FLAGS_FRAGMENT_END)


def pack_header(
    *,
    flags: int,
    msg_type: HeaderType,
    sequence: int,
    name_length: int,
    payload_length: int,
    version: int = _VERSION,
    reserved: int = 0,
) -> bytes:
    if not (0 <= name_length <= 0xFFFF):
        raise ValueError("name_length must fit in uint16")
    if not (0 <= payload_length <= 0xFFFFFFFF):
        raise ValueError("payload_length must fit in uint32")
    return struct.pack(
        _FMT,
        MAGIC,
        version & 0xFF,
        flags & 0xFF,
        int(msg_type) & 0xFF,
        reserved & 0xFF,
        sequence & 0xFFFFFFFF,
        name_length & 0xFFFF,
        payload_length & 0xFFFFFFFF,
    )


def unpack_header(payload: bytes) -> Header:
    if len(payload) < SIZE:
        raise ValueError("payload shorter than transport header")
    magic, version, flags, msg_type, reserved, sequence, name_len, payload_len = struct.unpack(
        _FMT, payload[:SIZE]
    )
    if magic != MAGIC:
        raise ValueError("invalid transport magic")
    try:
        header_type = HeaderType(msg_type)
    except ValueError as exc:  # pragma: no cover - indicates wire corruption
        raise ValueError(f"unknown header type {msg_type}") from exc
    return Header(
        version=version,
        flags=flags,
        type=header_type,
        reserved=reserved,
        sequence=sequence,
        name_length=name_len,
        payload_length=payload_len,
    )

