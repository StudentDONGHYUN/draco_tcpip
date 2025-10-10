"""Tests for the backwards-compatible metrics utilities."""

import pytest

np = pytest.importorskip("numpy")

from draco_roundtrip.analysis import metrics as core_metrics
from draco_roundtrip.utils import metrics as shim_metrics


def test_metrics_exports_match_core_module():
    assert tuple(shim_metrics.__all__) == ("_HAVE_SCIPY", "compute_basic_metrics", "sample_indices")
    for name in shim_metrics.__all__:
        assert getattr(shim_metrics, name) is getattr(
            core_metrics, name
        ), f"shim draco_roundtrip.utils.metrics.{name} must reference the core implementation"


def test_sample_indices_downsamples_evenly():
    idx = shim_metrics.sample_indices(length=10, sample=3)
    assert idx.tolist() == [0, 3, 6]


def test_compute_basic_metrics_fallback(monkeypatch):
    # Force the fallback implementation by disabling SciPy for the duration of the test.
    monkeypatch.setattr(core_metrics, "_HAVE_SCIPY", False, raising=False)
    monkeypatch.setattr(shim_metrics, "_HAVE_SCIPY", False, raising=False)

    src = np.array([[0.0, 0.0, 0.0], [1.0, 1.0, 1.0]], dtype=np.float32)
    dec = np.array([[0.0, 0.0, 0.0], [1.0, 2.0, 3.0]], dtype=np.float32)

    metrics = shim_metrics.compute_basic_metrics(src, dec, sample=2)
    assert metrics["n_src"] == 2
    assert metrics["n_dec"] == 2
    assert metrics["diff"] == 0
    np.testing.assert_allclose(metrics["centroid_delta"], np.array([0.0, 0.5, 1.0], dtype=np.float32))
    assert isinstance(metrics["centroid_norm"], float)
    np.testing.assert_allclose(metrics["bbox_delta"], np.array([0.0, 1.0, 2.0], dtype=np.float32))
    # With SciPy disabled, the fallback should compute per-point distances
    assert metrics["chamfer_mean"] == "1.225"
    assert metrics["chamfer_max"] == "2.236"
