"""Thin compatibility wrapper around the :mod:`DracoPy` API.

This module centralises the imports of :mod:`DracoPy` so we can gracefully
surface missing dependency errors from a single place.  The exposed helpers
operate on NumPy arrays to provide a consistent interface for the rest of the
codebase.
"""

from __future__ import annotations

from typing import Any

import numpy as np

try:  # pragma: no cover - exercised indirectly in tests
    from DracoPy import decode as _draco_decode
    from DracoPy import encode as _draco_encode
except Exception as exc:  # pragma: no cover - import side effects only
    raise ImportError("DracoPy is required for in-memory Draco codecs") from exc

__all__ = ["encode_points_np", "decode_points_np"]


def _ensure_xyz(points: np.ndarray) -> np.ndarray:
    """Validate and normalise an array of XYZ points."""

    arr = np.asarray(points, dtype=np.float32)
    if arr.ndim != 2 or arr.shape[1] < 3:
        raise ValueError(
            f"Expected points with shape (N, 3+) but received {arr.shape!r}"
        )
    if arr.dtype != np.float32 or not arr.flags.c_contiguous:
        arr = np.ascontiguousarray(arr[:, :3], dtype=np.float32)
    else:
        arr = arr[:, :3]
    return arr


def encode_points_np(
    points: np.ndarray,
    *,
    compression_level: int = 8,
    quantization_bits: int = 12,
    **kwargs: Any,
) -> bytes:
    """Encode XYZ points to Draco bytes using :mod:`DracoPy`.

    Parameters
    ----------
    points:
        Input array of shape ``(N, 3+)``.  Only the first three columns are
        consumed and they must represent XYZ coordinates in metres.
    compression_level:
        Draco compression speed/ratio trade-off level.  The valid range is
        [0, 10]; values outside the range are clamped.
    quantization_bits:
        Number of quantisation bits applied to positions.  DracoPy currently
        exposes a single knob for positional quantisation so we map any caller
        provided values to this parameter.
    kwargs:
        Ignored keyword arguments for forward compatibility.  They are
        accepted to match the legacy CLI options surface.
    """

    arr = _ensure_xyz(points)
    level = max(0, min(int(compression_level), 10))
    qbits = max(1, min(int(quantization_bits), 30))
    return _draco_encode(arr, compression_level=level, quantization_bits=qbits)


def decode_points_np(data: bytes) -> np.ndarray:
    """Decode Draco bytes produced by :func:`encode_points_np`."""

    if not data:
        raise ValueError("Cannot decode empty Draco payload")
    decoded_obj = _draco_decode(data)
    # decoded_obj.points 로 실제 포인트 배열에 접근
    arr = np.asarray(decoded_obj.points, dtype=np.float32)
    if arr.ndim != 2 or arr.shape[1] < 3:
        raise ValueError(
            f"Decoded Draco payload produced invalid shape {arr.shape!r}"
        )
    if arr.shape[1] > 3:
        arr = arr[:, :3]
    return np.ascontiguousarray(arr, dtype=np.float32)

