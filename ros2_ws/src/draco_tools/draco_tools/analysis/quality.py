"""Shared helpers for Draco roundtrip quality analysis."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import numpy as np

from draco_roundtrip.analysis.metrics import compute_basic_metrics, sample_indices
from draco_roundtrip.io.ply_codec import load_xyz

try:  # optional dependency
    from scipy.spatial import cKDTree  # type: ignore
    _HAVE_SCIPY = True
except Exception:  # pragma: no cover
    _HAVE_SCIPY = False

__all__ = [
    "load_pair",
    "summarize_pair",
]


def _directional_distances(src_pts: np.ndarray, dec_pts: np.ndarray, sample: int) -> Tuple[np.ndarray, np.ndarray]:
    if src_pts.size == 0 or dec_pts.size == 0:
        return np.asarray([], dtype=np.float32), np.asarray([], dtype=np.float32)

    sample_count = sample if sample > 0 else min(len(src_pts), len(dec_pts))
    idx_src = sample_indices(len(src_pts), sample_count)
    idx_dec = sample_indices(len(dec_pts), sample_count)
    pts_src = src_pts[idx_src]
    pts_dec = dec_pts[idx_dec]

    if _HAVE_SCIPY and pts_src.size and pts_dec.size:
        kd_dec = cKDTree(pts_dec)
        kd_src = cKDTree(pts_src)
        d_src = kd_dec.query(pts_src, k=1)[0]
        d_dec = kd_src.query(pts_dec, k=1)[0]
        return d_src.astype(np.float32), d_dec.astype(np.float32)

    # Fallback: align the shorter array and compute direct deltas
    m = min(len(pts_src), len(pts_dec))
    if m == 0:
        return np.asarray([], dtype=np.float32), np.asarray([], dtype=np.float32)
    diffs = pts_dec[:m] - pts_src[:m]
    dists = np.linalg.norm(diffs, axis=1).astype(np.float32)
    return dists, dists


def load_pair(src_path: Path, dec_path: Path) -> Tuple[np.ndarray, np.ndarray]:
    """Load source/decoded PLY points, relying on shared loaders."""
    return load_xyz(src_path), load_xyz(dec_path)


def summarize_pair(
    stem: str,
    src_pts: np.ndarray,
    dec_pts: np.ndarray,
    sample: int,
    thresholds: Iterable[float],
) -> Dict[str, object]:
    metrics = compute_basic_metrics(src_pts, dec_pts, sample)

    d_src, d_dec = _directional_distances(src_pts, dec_pts, sample)
    mean_src = float(np.mean(d_src)) if d_src.size else math.nan
    mean_dec = float(np.mean(d_dec)) if d_dec.size else math.nan
    max_src = float(np.max(d_src)) if d_src.size else math.nan
    max_dec = float(np.max(d_dec)) if d_dec.size else math.nan
    hausdorff = max(v for v in (max_src, max_dec) if math.isfinite(v)) if any(
        math.isfinite(v) for v in (max_src, max_dec)
    ) else math.nan

    chamfer_mean = metrics["chamfer_mean"]
    chamfer_mean_val = float(chamfer_mean) if isinstance(chamfer_mean, str) and chamfer_mean not in ("n/a", "") else (
        chamfer_mean if isinstance(chamfer_mean, (int, float)) else math.nan
    )

    summary: Dict[str, object] = {
        "name": stem,
        "n_src": metrics["n_src"],
        "n_dec": metrics["n_dec"],
        "diff": metrics["diff"],
        "centroid_delta": metrics["centroid_delta"].tolist() if isinstance(metrics["centroid_delta"], np.ndarray) else metrics["centroid_delta"],
        "centroid_norm": metrics["centroid_norm"],
        "bbox_delta": metrics["bbox_delta"].tolist() if isinstance(metrics["bbox_delta"], np.ndarray) else metrics["bbox_delta"],
        "mean_src_to_dec": mean_src,
        "mean_dec_to_src": mean_dec,
        "chamfer_mean": chamfer_mean,
        "chamfer_max": metrics["chamfer_max"],
        "chamfer_med": math.nan,
        "chamfer_rms": math.nan,
        "hausdorff": hausdorff,
        "status": "ok",
    }

    for thr in thresholds:
        passed = math.isfinite(mean_src) and math.isfinite(mean_dec) and mean_src <= thr and mean_dec <= thr
        summary[f"pass_{thr}m"] = 1.0 if passed else 0.0

    return summary
