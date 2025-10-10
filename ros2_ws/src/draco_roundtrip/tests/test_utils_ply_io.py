"""Tests for the backwards-compatible PLY helpers."""

from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

from draco_roundtrip.io import ply_codec
from draco_roundtrip.utils import ply_io


_CORE_NAME_MAP = {
    "load_points": "load_xyz",
    "load_points_from_bytes": "load_xyz_from_bytes",
}


def test_ply_io_exports_align_with_core():
    expected = {
        "_HAVE_O3D",
        "collect_matching_pairs",
        "ensure_suffix",
        "load_points",
        "load_points_from_bytes",
    }
    assert set(ply_io.__all__) == expected

    for name in expected:
        core_name = _CORE_NAME_MAP.get(name, name)
        assert getattr(ply_io, name) is getattr(
            ply_codec, core_name
        ), f"shim alias {name} must reference draco_roundtrip.io.ply_codec.{core_name}"


def test_ensure_suffix_appends_missing_extension():
    assert ply_io.ensure_suffix("cloud", ".ply") == "cloud.ply"
    assert ply_io.ensure_suffix("cloud.ply", ".ply") == "cloud.ply"


def test_collect_matching_pairs_filters_by_prefix(tmp_path: Path):
    orig = tmp_path / "orig"
    dec = tmp_path / "dec"
    orig.mkdir()
    dec.mkdir()

    (orig / "scene_frame_001.ply").write_text("orig1")
    (orig / "scene_frame_002.ply").write_text("orig2")
    (dec / "scene_frame_001.dec.ply").write_text("dec1")
    (dec / "scene_frame_003.dec.ply").write_text("dec3")

    pairs = ply_io.collect_matching_pairs(
        orig, dec, prefix="scene", orig_suffix=".ply", dec_suffix=".dec.ply"
    )
    assert pairs == [
        (
            orig / "scene_frame_001.ply",
            dec / "scene_frame_001.dec.ply",
            "scene_frame_001",
        )
    ]


def test_load_points_from_bytes_round_trip(tmp_path: Path):
    # create a minimal binary ply file via the core helper and ensure the shim loads it
    pts = np.array([[0.0, 0.0, 0.0], [1.0, 2.0, 3.0]], dtype=np.float32)
    path = tmp_path / "cloud.ply"
    ply_codec.save_xyz(path, pts)

    data = path.read_bytes()
    loaded = ply_io.load_points_from_bytes(data)
    np.testing.assert_allclose(loaded, pts, rtol=1e-6, atol=1e-6)

    loaded_from_path = ply_io.load_points(path)
    np.testing.assert_allclose(loaded_from_path, pts, rtol=1e-6, atol=1e-6)
