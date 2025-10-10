"""Backwards-compatible shim importing PLY helpers from the new module."""

from draco_roundtrip.io.ply_codec import (  # noqa: F401
    _HAVE_O3D,
    collect_matching_pairs,
    ensure_suffix,
    load_xyz as load_points,
    load_xyz_from_bytes as load_points_from_bytes,
)

__all__ = [
    "_HAVE_O3D",
    "load_points",
    "load_points_from_bytes",
    "ensure_suffix",
    "collect_matching_pairs",
]
