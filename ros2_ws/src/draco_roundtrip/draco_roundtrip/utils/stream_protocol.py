"""Helpers for embedding sequencing/control metadata inside protocol names."""
from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "FrameAddress",
    "CONTROL_CHANNEL",
    "DATA_CHANNEL",
    "encode_frame_address",
    "decode_frame_address",
]

_DATA_DELIM = "|"
_CHANNEL_DELIM = "/"
DATA_CHANNEL = "data"
CONTROL_CHANNEL = "control"


@dataclass(frozen=True)
class FrameAddress:
    """Decoded addressing metadata carried in ``Message.name``."""

    channel: str
    sequence: int | None
    name: str

    @property
    def is_control(self) -> bool:
        return self.channel != DATA_CHANNEL


def encode_frame_address(
    sequence: int | None,
    name: str,
    *,
    channel: str = DATA_CHANNEL,
) -> str:
    """Pack channel/sequence metadata into the wire name field."""

    base = name or ""
    token = base
    if sequence is not None:
        token = f"{sequence}{_DATA_DELIM}{base}" if base else f"{sequence}{_DATA_DELIM}"
    channel = channel or DATA_CHANNEL
    if not token:
        return channel
    return f"{channel}{_CHANNEL_DELIM}{token}" if channel else token


def decode_frame_address(raw: str | None) -> FrameAddress:
    """Extract channel/sequence metadata from a wire name."""

    if not raw:
        return FrameAddress(channel=DATA_CHANNEL, sequence=None, name="")
    channel = DATA_CHANNEL
    token = raw
    if _CHANNEL_DELIM in raw:
        channel, token = raw.split(_CHANNEL_DELIM, 1)
        channel = channel or DATA_CHANNEL
    sequence: int | None = None
    name = token
    if _DATA_DELIM in token:
        prefix, suffix = token.split(_DATA_DELIM, 1)
        try:
            sequence = int(prefix)
            name = suffix
        except ValueError:
            # Fall back to legacy semantics where the delimiter was part of the name.
            sequence = None
            name = token
    return FrameAddress(channel=channel or DATA_CHANNEL, sequence=sequence, name=name)
