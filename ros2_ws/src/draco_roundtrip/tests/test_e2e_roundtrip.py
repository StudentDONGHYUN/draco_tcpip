"""End-to-end regression covering a minimal Draco roundtrip."""

from __future__ import annotations

import os
import stat
import textwrap
from pathlib import Path

import pytest

from draco_tools.core.encoder import EncoderOptions, encode_frame
from draco_roundtrip.nodes.stream_server import decode_drc

np = pytest.importorskip("numpy")

from draco_roundtrip.utils.metrics import compute_basic_metrics
from draco_roundtrip.utils.ply_io import load_points, load_points_from_bytes


def _write_stub(name: str, path: Path) -> None:
    """Emit a tiny shim that mirrors draco_encoder/decoder behaviour."""

    script = textwrap.dedent(
        """
        #!/usr/bin/env python3
        import argparse
        import shutil
        import sys

        def main() -> int:
            parser = argparse.ArgumentParser()
            parser.add_argument("-i", dest="input")
            parser.add_argument("-o", dest="output")
            parser.add_argument("-cl", dest="cl", nargs="?")
            parser.add_argument("-qp", dest="qp", nargs="?")
            parser.add_argument("-qg", dest="qg", nargs="?")
            args, _ = parser.parse_known_args()
            shutil.copyfile(args.input, args.output)
            return 0

        if __name__ == "__main__":
            sys.exit(main())
        """
    ).strip()
    path.write_text(script)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


@pytest.mark.parametrize("sample", [0, 8])
def test_stubbed_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sample: int) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    encoder_path = bin_dir / "draco_encoder"
    decoder_path = bin_dir / "draco_decoder"
    _write_stub("encoder", encoder_path)
    _write_stub("decoder", decoder_path)

    monkeypatch.setenv("DRACO_ENCODER", str(encoder_path))
    monkeypatch.setenv("DRACO_DECODER", str(decoder_path))
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ.get('PATH', '')}")

    pts = np.array(
        [
            [0.0, 0.0, 0.0],
            [1.0, 0.5, 0.2],
            [2.0, 0.1, 0.4],
            [3.0, 0.4, 0.8],
        ],
        dtype=np.float32,
    )
    ply_lines = [
        "ply",
        "format ascii 1.0",
        f"element vertex {len(pts)}",
        "property float x",
        "property float y",
        "property float z",
        "end_header",
    ]
    ply_lines.extend("{0:.6f} {1:.6f} {2:.6f}".format(*row) for row in pts)

    ply_path = tmp_path / "frame_00000.ply"
    ply_path.write_text("\n".join(ply_lines))

    encoded_dir = tmp_path / "encoded"
    result = encode_frame(
        ply_path,
        encoded_dir,
        EncoderOptions(),
        encoder_hint=None,
        skip_existing=False,
    )
    assert not result.skipped
    assert result.output.exists()

    drc_bytes = result.output.read_bytes()
    decoded_bytes = decode_drc(decoder_path, drc_bytes, tmp_path / "decoded", "frame_00000")

    orig_pts = load_points(ply_path)
    dec_pts = load_points_from_bytes(decoded_bytes)

    assert orig_pts.shape == dec_pts.shape == pts.shape

    metrics = compute_basic_metrics(orig_pts, dec_pts, sample)
    assert metrics["diff"] == 0
    assert pytest.approx(metrics["centroid_norm"], abs=1e-6) == 0.0
    assert metrics["chamfer_mean"] in ("0.000", "n/a")
    assert metrics["chamfer_max"] in ("0.000", "n/a")

