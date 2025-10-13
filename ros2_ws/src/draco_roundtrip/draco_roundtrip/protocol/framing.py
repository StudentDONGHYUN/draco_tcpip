"""Fragmentation helpers built on top of the unified transport header."""

from __future__ import annotations

import dataclasses
import struct
from typing import Iterable, Iterator

from .header import (
    FLAGS_FRAGMENTED,
    FLAGS_FRAGMENT_END,
    FLAGS_FRAGMENT_START,
)

__all__ = [
    "FragmentMetadata",
    "METADATA_SIZE",
    "pack_metadata",
    "unpack_metadata",
    "iter_fragment_payloads",
]

_METADATA_STRUCT = struct.Struct("!III")  # total_len, offset, chunk_len
METADATA_SIZE = _METADATA_STRUCT.size


@dataclasses.dataclass(slots=True)
class FragmentMetadata:
    total_length: int
    offset: int
    chunk_length: int

    def flags_for_position(self, *, is_first: bool, is_last: bool) -> int:
        flags = FLAGS_FRAGMENTED
        if is_first:
            flags |= FLAGS_FRAGMENT_START
        if is_last:
            flags |= FLAGS_FRAGMENT_END
        return flags


def pack_metadata(meta: FragmentMetadata) -> bytes:
    if meta.total_length < 0 or meta.offset < 0 or meta.chunk_length < 0:
        raise ValueError("fragment metadata fields must be non-negative")
    return _METADATA_STRUCT.pack(meta.total_length, meta.offset, meta.chunk_length)


def unpack_metadata(buffer: bytes) -> FragmentMetadata:
    if len(buffer) < _METADATA_STRUCT.size:
        raise ValueError("fragment payload shorter than metadata header")
    total_len, offset, chunk_len = _METADATA_STRUCT.unpack_from(buffer)
    return FragmentMetadata(total_length=total_len, offset=offset, chunk_length=chunk_len)


def iter_fragment_payloads(
    payload: bytes,
    *,
    fragment_size: int,
) -> Iterator[tuple[int, bytes, FragmentMetadata]]:
    """Yield ``(flags, chunk, metadata)`` tuples for fragmented payloads."""

    if fragment_size <= 0:
        raise ValueError("fragment_size must be positive")
    if fragment_size <= METADATA_SIZE:
        raise ValueError("fragment_size too small for metadata header")
    total = len(payload)
    offset = 0
    chunk_budget = fragment_size - METADATA_SIZE
    index = 0
    while offset < total:
        end = min(offset + chunk_budget, total)
        chunk = payload[offset:end]
        is_first = index == 0
        is_last = end >= total
        meta = FragmentMetadata(total_length=total, offset=offset, chunk_length=len(chunk))
        yield meta.flags_for_position(is_first=is_first, is_last=is_last), chunk, meta
        offset = end
        index += 1

