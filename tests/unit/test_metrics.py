import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "ros2_ws" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import tests  # noqa: F401  # ensure bootstrap side effects
import pytest

np = pytest.importorskip("numpy")

from draco_roundtrip.draco_roundtrip.analysis import pointcloud_metrics


def test_compute_basic_metrics_cube():
    points = np.array(
        [
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
        ],
        dtype=np.float32,
    )
    metrics = pointcloud_metrics.compute(points, frame_id="frame-1", sample=0, bits_per_point=8.0)
    assert metrics["frame_id"] == "frame-1"
    assert metrics["point_count"] == 4
    assert np.allclose(metrics["bbox_min"], [0.0, 0.0, 0.0])
    assert np.allclose(metrics["bbox_max"], [1.0, 1.0, 1.0])
    assert np.isclose(metrics["scale_diag"], np.sqrt(3))
    assert metrics["bits_per_point"] == 8.0


def test_compute_sampling_reduces_points():
    points = np.stack([np.arange(1000, dtype=np.float32)] * 3, axis=1)
    metrics = pointcloud_metrics.compute(points, sample=10)
    assert metrics["point_count"] == 1000
    assert metrics["avg_nn_dist"] >= 0.0


def test_chamfer_est_zero_for_identical_sets():
    cloud = np.random.default_rng(1).random((100, 3), dtype=np.float32)
    distance = pointcloud_metrics.chamfer_est(cloud, cloud, sample=50)
    assert distance == 0.0
