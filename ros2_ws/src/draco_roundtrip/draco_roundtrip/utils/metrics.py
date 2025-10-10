"""Backwards-compatible shim importing metrics helpers from the new package."""

from draco_roundtrip.analysis.metrics import (  # noqa: F401
    _HAVE_SCIPY,
    compute_basic_metrics,
    sample_indices,
)

__all__ = ["_HAVE_SCIPY", "compute_basic_metrics", "sample_indices"]
