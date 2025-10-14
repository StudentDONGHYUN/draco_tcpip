import pytest

pytest.importorskip("numpy")
pytest.importorskip("DracoPy")

import numpy as np

from draco_roundtrip.draco._draco_adapter import decode_points_np
from draco_roundtrip.draco.encoder import EncoderOptions, encode_points


def test_encode_points_roundtrip() -> None:
    rng = np.random.default_rng(42)
    points = rng.random((128, 3), dtype=np.float32)

    result = encode_points(points, EncoderOptions())

    assert isinstance(result.encoded_data, bytes)
    assert len(result.encoded_data) > 0
    assert result.duration >= 0.0

    decoded = decode_points_np(result.encoded_data)
    assert decoded.shape == points.shape
    assert np.allclose(decoded, points, atol=5e-3)
