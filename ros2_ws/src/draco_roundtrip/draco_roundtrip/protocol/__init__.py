"""Unified transport primitives for the Draco roundtrip pipeline."""

from .header import (
    FLAGS_FRAGMENTED,
    FLAGS_FRAGMENT_END,
    FLAGS_FRAGMENT_START,
    Header,
    HeaderType,
    MAGIC,
    SEQUENCE_NONE,
    SIZE as HEADER_SIZE,
    pack_header,
    unpack_header,
)
from .framing import (
    FragmentMetadata,
    METADATA_SIZE,
    iter_fragment_payloads,
    pack_metadata,
    unpack_metadata,
)
from .io_utils import recv_exact

__all__ = [
    "FLAGS_FRAGMENTED",
    "FLAGS_FRAGMENT_END",
    "FLAGS_FRAGMENT_START",
    "FragmentMetadata",
    "Header",
    "HeaderType",
    "HEADER_SIZE",
    "MAGIC",
    "METADATA_SIZE",
    "SEQUENCE_NONE",
    "iter_fragment_payloads",
    "pack_header",
    "pack_metadata",
    "recv_exact",
    "unpack_header",
    "unpack_metadata",
]

