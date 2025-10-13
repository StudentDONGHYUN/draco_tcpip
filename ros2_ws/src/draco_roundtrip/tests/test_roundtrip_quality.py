import json
from pathlib import Path

import numpy as np
import pytest

from draco_roundtrip.analysis import pointcloud_metrics
from draco_roundtrip.io.ply_codec import save_xyz
from draco_roundtrip.utils.ply_io import load_points_from_bytes
from draco_roundtrip.utils import stream_protocol


def _quality_from_metrics(orig_metrics, decoded_metrics, orig_points, decoded_points):
    def _rel_delta(a: float, b: float) -> float:
        if b == 0.0:
            return 0.0 if a == 0.0 else float("inf")
        return abs(a - b) / abs(b)

    return {
        "point_count_abs": abs(decoded_metrics["point_count"] - orig_metrics["point_count"]),
        "centroid_l2": float(
            np.linalg.norm(
                np.asarray(decoded_metrics["centroid"], dtype=float)
                - np.asarray(orig_metrics["centroid"], dtype=float)
            )
        ),
        "scale_diag_rel": _rel_delta(decoded_metrics["scale_diag"], orig_metrics["scale_diag"]),
        "avg_nn_rel": _rel_delta(decoded_metrics["avg_nn_dist"], orig_metrics["avg_nn_dist"]),
        "chamfer_est": pointcloud_metrics.chamfer_est(orig_points, decoded_points, sample=None),
    }


def test_roundtrip_quality_pipeline(tmp_path: Path):
    orig_points = np.array(
        [
            [0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [1.0, 0.0, 0.0],
            [1.0, 1.0, 0.0],
        ],
        dtype=np.float32,
    )
    decoded_path = tmp_path / "decoded.ply"
    save_xyz(decoded_path, orig_points)
    decoded_bytes = decoded_path.read_bytes()

    request_header, request_payload = stream_protocol.compose_request_payload(
        sequence=1,
        draco_bytes=b"fake-draco",
        timestamp_ns=42,
    )
    parsed_header, draco_payload = stream_protocol.parse_request_payload(request_payload)
    assert draco_payload == b"fake-draco"
    assert parsed_header.sequence == request_header.sequence

    server_metrics = pointcloud_metrics.compute(
        orig_points,
        sample=0,
        frame_id="frame-001",
        bits_per_point=len(draco_payload) * 8 / orig_points.shape[0],
        decode_ms=3.5,
    )
    server_metrics["extra"]["resp_format"] = "ply"
    server_metrics.setdefault("encode_ms", None)
    metrics_json = json.dumps(server_metrics).encode("utf-8")

    _, response_payload = stream_protocol.compose_response_payload(
        sequence=request_header.sequence,
        timestamp_ns=request_header.timestamp_ns,
        decoded_payload=decoded_bytes,
        metrics_json=metrics_json,
        decode_ms=server_metrics["decode_ms"],
    )
    response_header, decoded_payload, metrics_payload = stream_protocol.parse_response_payload(response_payload)
    assert response_header.decoded_len == len(decoded_bytes)
    metrics_back = json.loads(metrics_payload)
    assert metrics_back["point_count"] == orig_points.shape[0]

    decoded_points = load_points_from_bytes(decoded_payload)
    client_metrics = pointcloud_metrics.compute(decoded_points, sample=0)
    orig_metrics = pointcloud_metrics.compute(orig_points, sample=0)
    quality = _quality_from_metrics(orig_metrics, client_metrics, orig_points, decoded_points)

    assert all(value == pytest.approx(0.0) for value in quality.values())
    thresholds = {"centroid_l2": 1e-6, "scale_diag_rel": 1e-6, "avg_nn_rel": 1e-6}
    assert all(quality[key] <= limit for key, limit in thresholds.items())
