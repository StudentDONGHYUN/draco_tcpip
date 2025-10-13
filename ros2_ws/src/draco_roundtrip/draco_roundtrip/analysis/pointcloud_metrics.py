"""Point cloud metric utilities for round-trip quality tracking."""

from __future__ import annotations

from typing import Sequence

import numpy as np

try:  # Optional dependency used for efficient nearest-neighbour queries.
    from scipy.spatial import cKDTree  # type: ignore

    _HAVE_SCIPY = True
except Exception:  # pragma: no cover - SciPy is optional in CI environments.
    cKDTree = None  # type: ignore[assignment]
    _HAVE_SCIPY = False

__all__ = ["compute", "chamfer_est", "_HAVE_SCIPY"]


def _ensure_array(points: Sequence[Sequence[float]] | np.ndarray) -> np.ndarray:
    arr = np.asarray(points, dtype=np.float32)
    if arr.ndim != 2 or arr.shape[1] != 3:
        raise ValueError("points must be an array-like of shape (N, 3)")
    return arr


def _subsample(points: np.ndarray, sample: int | None) -> np.ndarray:
    if sample is None or sample <= 0 or len(points) <= sample:
        return points
    step = max(len(points) // sample, 1)
    if step <= 1:
        return points
    return points[::step][:sample]


def _nearest_distances(
    points: np.ndarray, query: np.ndarray, *, skip_self: bool = False
) -> np.ndarray:
    if len(points) == 0 or len(query) == 0:
        return np.empty(0, dtype=np.float32)
    if _HAVE_SCIPY:
        tree = cKDTree(points)
        k = 2 if skip_self and len(points) > 1 else 1
        distances, _ = tree.query(query, k=k)
        if k == 1:
            return np.atleast_1d(np.asarray(distances, dtype=np.float32))
        if distances.ndim == 1:
            return np.asarray(distances[1:], dtype=np.float32)
        return np.asarray(distances[:, 1], dtype=np.float32)
    diffs = query[:, None, :] - points[None, :, :]
    norms = np.linalg.norm(diffs, axis=2)
    if skip_self:
        norms.sort(axis=1)
        if norms.shape[1] <= 1:
            return np.zeros(len(query), dtype=np.float32)
        return norms[:, 1].astype(np.float32, copy=False)
    return np.min(norms, axis=1).astype(np.float32, copy=False)


def _avg_nn_distance(points: np.ndarray, sample: int | None) -> float:
    if len(points) <= 1:
        return 0.0
    sampled = _subsample(points, sample)
    dists = _nearest_distances(points, sampled, skip_self=True)
    if dists.size == 0:
        return 0.0
    return float(np.mean(dists))


def compute(
    points: Sequence[Sequence[float]] | np.ndarray,
    *,
    sample: int | None = None,
    frame_id: str | None = None,
    bits_per_point: float | None = None,
    decode_ms: float | None = None,
    encode_ms: float | None = None,
    extra_notes: str = "",
    extra_impl: str = "draco_roundtrip-v1",
) -> dict[str, object]:
    """Compute summary metrics for a point cloud.

    Parameters
    ----------
    points:
        Array-like container of XYZ points.
    sample:
        Optional cap on the number of points used for statistics that do not
        require the full cloud (e.g. nearest-neighbour distances).
    frame_id:
        Identifier of the originating frame for inclusion in the JSON payload.
    bits_per_point:
        If provided, record the compression density in the metrics payload.
    decode_ms / encode_ms:
        Pipeline timing fields propagated from the encoder/decoder stages.
    extra_notes / extra_impl:
        Metadata added to the ``extra`` object in the JSON output.
    """

    xyz = _ensure_array(points)
    point_count = int(xyz.shape[0])
    if point_count == 0:
        bbox_min = np.zeros(3, dtype=np.float32)
        bbox_max = np.zeros(3, dtype=np.float32)
        centroid = np.zeros(3, dtype=np.float32)
        scale_diag = 0.0
    else:
        bbox_min = np.min(xyz, axis=0)
        bbox_max = np.max(xyz, axis=0)
        centroid = np.mean(xyz, axis=0)
        scale_diag = float(np.linalg.norm(bbox_max - bbox_min))

    avg_nn = _avg_nn_distance(xyz, sample)

    return {
        "frame_id": frame_id if frame_id is not None else "",
        "point_count": point_count,
        "bbox_min": bbox_min.astype(float).tolist(),
        "bbox_max": bbox_max.astype(float).tolist(),
        "centroid": centroid.astype(float).tolist(),
        "scale_diag": scale_diag,
        "avg_nn_dist": avg_nn,
        "bits_per_point": float(bits_per_point) if bits_per_point is not None else 0.0,
        "decode_ms": float(decode_ms) if decode_ms is not None else 0.0,
        "encode_ms": float(encode_ms) if encode_ms is not None else None,
        "extra": {"impl": extra_impl, "notes": extra_notes},
    }


def chamfer_est(
    points_a: Sequence[Sequence[float]] | np.ndarray,
    points_b: Sequence[Sequence[float]] | np.ndarray,
    *,
    sample: int | None = None,
) -> float:
    """Estimate the (symmetric) Chamfer distance between two clouds."""

    a = _ensure_array(points_a)
    b = _ensure_array(points_b)
    if a.size == 0 and b.size == 0:
        return 0.0
    sample_a = _subsample(a, sample)
    sample_b = _subsample(b, sample)
    if sample_a.size == 0 or sample_b.size == 0:
        return 0.0
    d_ab = _nearest_distances(b, sample_a)
    d_ba = _nearest_distances(a, sample_b)
    arrays = [arr for arr in (d_ab, d_ba) if arr.size]
    if not arrays:
        return 0.0
    combined = np.concatenate(arrays)
    return float(np.mean(combined))
