"""Binary framing header shared by the streaming client and server."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import IntEnum
from typing import Tuple

MAGIC = b"DRC0"
LEGACY_MAGIC = b"DRTC"
VERSION = 2
LEGACY_VERSION = 1

# Version 2 header layout extends the legacy format with timestamp and
# content-type metadata so higher layers no longer need to prepend a separate
# payload header.  Both layouts share the same prefix to simplify detection.
HEADER_FORMAT_V2 = "!4sBBIHIQH"
HEADER_STRUCT_V2 = struct.Struct(HEADER_FORMAT_V2)
HEADER_SIZE = HEADER_STRUCT_V2.size

HEADER_PREFIX_FORMAT = "!4sBB"
HEADER_PREFIX_STRUCT = struct.Struct(HEADER_PREFIX_FORMAT)
HEADER_PREFIX_SIZE = HEADER_PREFIX_STRUCT.size

LEGACY_HEADER_FORMAT = "!4sBBIHI"
LEGACY_HEADER_STRUCT = struct.Struct(LEGACY_HEADER_FORMAT)
LEGACY_HEADER_SIZE = LEGACY_HEADER_STRUCT.size

FRAGMENT_INFO_FORMAT = "!HHI"
FRAGMENT_INFO_STRUCT = struct.Struct(FRAGMENT_INFO_FORMAT)
FRAGMENT_INFO_SIZE = FRAGMENT_INFO_STRUCT.size

TYPE_MASK = 0x0F
FLAG_FRAGMENTED = 0x10
FLAG_MORE_FRAGMENTS = 0x20
DATA_FLAGS = 0


class FrameType(IntEnum):
    """Enumerate frame kinds multiplexed over the TCP stream."""

    DATA = 0
    ACK = 1
    ERROR = 2
    HEARTBEAT = 3
    EOF = 4
    CONTROL = 5


@dataclass(slots=True)
class FragmentInfo:
    """Metadata describing a fragmented payload chunk."""

    index: int
    total: int
    frame_payload_len: int

    def validate(self) -> None:
        if self.total <= 0:
            raise ValueError("fragment total must be positive")
        if not (0 <= self.index < self.total):
            raise ValueError("fragment index out of range")
        if self.frame_payload_len < 0:
            raise ValueError("frame payload length must be non-negative")


@dataclass(slots=True)
class FrameHeader:
    """Parsed header fields for a TCP frame."""

    frame_type: FrameType
    sequence: int
    name_len: int
    payload_len: int
    timestamp_ns: int
    content_type: int
    flags: int
    version: int = VERSION
    fragment: FragmentInfo | None = None

    @property
    def is_fragmented(self) -> bool:
        return bool(self.flags & FLAG_FRAGMENTED)

    @property
    def has_more_fragments(self) -> bool:
        return bool(self.flags & FLAG_MORE_FRAGMENTS)

    def to_bytes(self) -> bytes:
        """Serialize this header using the negotiated version."""

        if self.name_len < 0 or self.name_len > 0xFFFF:
            raise HeaderError("name length must fit into uint16")
        if self.payload_len < 0 or self.payload_len > 0xFFFFFFFF:
            raise HeaderError("payload length must fit into uint32")
        if self.timestamp_ns < 0:
            raise HeaderError("timestamp must be non-negative")
        if self.content_type < 0 or self.content_type > 0xFFFF:
            raise HeaderError("content type must fit into uint16")
        fragmented = self.fragment is not None
        more = bool(self.flags & FLAG_MORE_FRAGMENTS)
        flags = _compose_flags(self.frame_type, fragmented=fragmented, more=more)
        self.flags = flags
        if fragmented:
            self.fragment.validate()
        version = self.version or VERSION
        if version == VERSION:
            header = HEADER_STRUCT_V2.pack(
                MAGIC,
                VERSION,
                flags,
                self.sequence & 0xFFFFFFFF,
                self.name_len & 0xFFFF,
                self.payload_len & 0xFFFFFFFF,
                self.timestamp_ns & 0xFFFFFFFFFFFFFFFF,
                self.content_type & 0xFFFF,
            )
        elif version == LEGACY_VERSION:
            header = LEGACY_HEADER_STRUCT.pack(
                LEGACY_MAGIC,
                LEGACY_VERSION,
                flags,
                self.sequence & 0xFFFFFFFF,
                self.name_len & 0xFFFF,
                self.payload_len & 0xFFFFFFFF,
            )
        else:  # pragma: no cover - defensive guard for forward ports
            raise HeaderError(f"unsupported header version {version}")
        if fragmented and self.fragment is not None:
            header += FRAGMENT_INFO_STRUCT.pack(
                self.fragment.index & 0xFFFF,
                self.fragment.total & 0xFFFF,
                self.fragment.frame_payload_len & 0xFFFFFFFF,
            )
        return header

    @classmethod
    def from_bytes(cls, raw: bytes, *, allow_legacy: bool = False) -> "FrameHeader":
        """Parse a frame header ensuring the magic/version match expectations."""

        if len(raw) < HEADER_PREFIX_SIZE:
            raise HeaderError("payload shorter than header prefix")
        magic, version, flags = HEADER_PREFIX_STRUCT.unpack_from(raw)
        if magic == MAGIC and version == VERSION:
            if len(raw) < HEADER_SIZE:
                raise HeaderError("payload shorter than frame header")
            (
                _,
                _,
                _,
                sequence,
                name_len,
                payload_len,
                timestamp_ns,
                content_type,
            ) = HEADER_STRUCT_V2.unpack_from(raw)
        elif allow_legacy and magic == LEGACY_MAGIC and version == LEGACY_VERSION:
            if len(raw) < LEGACY_HEADER_SIZE:
                raise HeaderError("payload shorter than legacy frame header")
            (
                _,
                _,
                _,
                sequence,
                name_len,
                payload_len,
            ) = LEGACY_HEADER_STRUCT.unpack_from(raw)
            timestamp_ns = 0
            content_type = 0
        else:
            raise HeaderError(f"unsupported header magic/version {magic!r}/{version}")
        frame_type, fragmented, more = _parse_flags(flags)
        fragment: FragmentInfo | None = None
        if fragmented:
            required = LEGACY_HEADER_SIZE + FRAGMENT_INFO_SIZE
            if version == VERSION:
                required = HEADER_SIZE + FRAGMENT_INFO_SIZE
            if len(raw) < required:
                raise HeaderError("missing fragment metadata")
            index, total, frame_payload_len = FRAGMENT_INFO_STRUCT.unpack_from(
                raw,
                LEGACY_HEADER_SIZE if version == LEGACY_VERSION else HEADER_SIZE,
            )
            fragment = FragmentInfo(
                index=index,
                total=total,
                frame_payload_len=frame_payload_len,
            )
            fragment.validate()
        return cls(
            frame_type=frame_type,
            sequence=sequence,
            name_len=name_len,
            payload_len=payload_len,
            timestamp_ns=timestamp_ns,
            content_type=content_type,
            flags=flags,
            version=version,
            fragment=fragment,
        )


class HeaderError(ValueError):
    """Raised when the binary header fails validation."""


def _compose_flags(frame_type: FrameType, *, fragmented: bool, more: bool) -> int:
    flags = int(frame_type) & TYPE_MASK
    if fragmented:
        flags |= FLAG_FRAGMENTED
    if more:
        flags |= FLAG_MORE_FRAGMENTS
    return flags


def _parse_flags(flags: int) -> Tuple[FrameType, bool, bool]:
    try:
        frame_type = FrameType(flags & TYPE_MASK)
    except ValueError as exc:  # pragma: no cover - wire corruption
        raise HeaderError(f"unknown frame type code {flags & TYPE_MASK}") from exc
    fragmented = bool(flags & FLAG_FRAGMENTED)
    more = bool(flags & FLAG_MORE_FRAGMENTS)
    return frame_type, fragmented, more
