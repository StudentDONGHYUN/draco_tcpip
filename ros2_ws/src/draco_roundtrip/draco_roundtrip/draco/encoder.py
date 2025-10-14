"""In-memory Draco encoder utilities built on top of :mod:`DracoPy`."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Sequence

import numpy as np

from ._draco_adapter import encode_points_np

__all__ = ["EncoderOptions", "EncodeResult", "encode_points"]


@dataclass(slots=True)
class EncoderOptions:
    """Configuration options for Draco encoding.

    Parameters mirror the previously supported CLI flags so existing
    configuration files remain valid.  ``generic_quantization_bits`` and
    ``extra_args`` do not have direct equivalents in :mod:`DracoPy`; the values
    are accepted for backwards compatibility but ignored.
    """

    compress_level: int = 8
    position_quantization_bits: int = 12
    generic_quantization_bits: int = 10
    extra_args: Sequence[str] = ()


@dataclass(slots=True)
class EncodeResult:
    """Result of encoding a single frame."""

    encoded_data: bytes
    duration: float


def _normalise_points(points: np.ndarray) -> np.ndarray:
    arr = np.asarray(points, dtype=np.float32)
    if arr.ndim != 2 or arr.shape[1] < 3:
        raise ValueError(
            f"Expected points with shape (N, 3+) but received {arr.shape!r}"
        )
    if arr.shape[1] > 3:
        arr = arr[:, :3]
    if arr.dtype != np.float32 or not arr.flags.c_contiguous:
        arr = np.ascontiguousarray(arr, dtype=np.float32)
    return arr


def encode_points(points: np.ndarray, options: EncoderOptions) -> EncodeResult:
    """Encode ``points`` using DracoPy and return timing metadata."""

    arr = _normalise_points(points)
    start = time.perf_counter()
    payload = encode_points_np(
        arr,
        compression_level=options.compress_level,
        quantization_bits=options.position_quantization_bits,
    )
    duration = time.perf_counter() - start
    return EncodeResult(encoded_data=payload, duration=duration)

