"""Binary framing header shared by the streaming client and server."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import IntEnum
from typing import Tuple

MAGIC = b"DRTC"
VERSION = 1
HEADER_FORMAT = "!4sBBIHI"
HEADER_STRUCT = struct.Struct(HEADER_FORMAT)
HEADER_SIZE = HEADER_STRUCT.size

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
    flags: int
    sequence: int
    name_len: int
    payload_len: int
    fragment: FragmentInfo | None = None

    @property
    def is_fragmented(self) -> bool:
        return bool(self.flags & FLAG_FRAGMENTED)

    @property
    def has_more_fragments(self) -> bool:
        return bool(self.flags & FLAG_MORE_FRAGMENTS)


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


def pack_frame_header(
    *,
    frame_type: FrameType,
    sequence: int,
    name_len: int,
    payload_len: int,
    fragment: FragmentInfo | None = None,
    more_fragments: bool = False,
) -> bytes:
    """Serialize a frame header using the shared SSOT format."""

    if name_len < 0 or name_len > 0xFFFF:
        raise HeaderError("name length must fit into uint16")
    if payload_len < 0 or payload_len > 0xFFFFFFFF:
        raise HeaderError("payload length must fit into uint32")
    fragmented = fragment is not None
    if fragmented:
        fragment.validate()
        if more_fragments and fragment.total == 1:
            raise HeaderError("more_fragments flag set for single-fragment frame")
        if more_fragments and fragment.index == fragment.total - 1:
            raise HeaderError("more_fragments flag set on final fragment")
    flags = _compose_flags(frame_type, fragmented=fragmented, more=more_fragments)
    header = HEADER_STRUCT.pack(MAGIC, VERSION, flags, sequence, name_len, payload_len)
    if fragment is not None:
        header += FRAGMENT_INFO_STRUCT.pack(
            fragment.index,
            fragment.total,
            fragment.frame_payload_len,
        )
    return header


def unpack_frame_header(raw: bytes) -> FrameHeader:
    """Parse a frame header ensuring the magic/version match expectations."""

    if len(raw) < HEADER_SIZE:
        raise HeaderError("payload shorter than frame header")
    magic, version, flags, sequence, name_len, payload_len = HEADER_STRUCT.unpack_from(raw)
    if magic != MAGIC:
        raise HeaderError(f"bad magic {magic!r}")
    if version != VERSION:
        raise HeaderError(f"unsupported version {version}")
    frame_type, fragmented, more = _parse_flags(flags)
    fragment: FragmentInfo | None = None
    if fragmented:
        if len(raw) < HEADER_SIZE + FRAGMENT_INFO_SIZE:
            raise HeaderError("missing fragment metadata")
        index, total, frame_payload_len = FRAGMENT_INFO_STRUCT.unpack_from(
            raw, HEADER_SIZE
        )
        fragment = FragmentInfo(index=index, total=total, frame_payload_len=frame_payload_len)
        fragment.validate()
    return FrameHeader(
        frame_type=frame_type,
        flags=flags,
        sequence=sequence,
        name_len=name_len,
        payload_len=payload_len,
        fragment=fragment,
    )
