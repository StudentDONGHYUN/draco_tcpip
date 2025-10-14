import math
import random

import pytest

from draco_roundtrip.net.control_plane import (
    PATH_POSE_LIMIT,
    PathPayload,
    PathPose,
    PosePayload,
    TwistPayload,
    build_path_message,
    build_pose_message,
    build_twist_message,
    decode_path_payload,
    decode_pose_payload,
    decode_twist_payload,
)


def random_pose_payload(seed: int) -> PosePayload:
    rng = random.Random(seed)
    return PosePayload(
        stamp_ns=rng.randrange(1_000_000, 9_000_000),
        frame_id="map",
        x=rng.uniform(-10, 10),
        y=rng.uniform(-10, 10),
        z=rng.uniform(-2, 2),
        qx=rng.uniform(-1, 1),
        qy=rng.uniform(-1, 1),
        qz=rng.uniform(-1, 1),
        qw=rng.uniform(-1, 1),
    )


def random_twist_payload(seed: int) -> TwistPayload:
    rng = random.Random(seed)
    return TwistPayload(
        stamp_ns=rng.randrange(1_000_000, 9_000_000),
        vx=rng.uniform(-1, 1),
        vy=rng.uniform(-1, 1),
        vz=rng.uniform(-1, 1),
        wx=rng.uniform(-2, 2),
        wy=rng.uniform(-2, 2),
        wz=rng.uniform(-2, 2),
    )


def test_pose_roundtrip() -> None:
    payload = random_pose_payload(123)
    msg = build_pose_message(payload)
    decoded = decode_pose_payload(msg.payload)
    assert decoded == payload


def test_twist_roundtrip() -> None:
    payload = random_twist_payload(456)
    msg = build_twist_message(payload)
    decoded = decode_twist_payload(msg.payload)
    assert decoded.stamp_ns == payload.stamp_ns
    for attr in ("vx", "vy", "vz", "wx", "wy", "wz"):
        assert math.isclose(getattr(decoded, attr), getattr(payload, attr), rel_tol=1e-6)


def test_path_roundtrip_length_guard() -> None:
    poses = [
        PathPose(x=float(i), y=float(i) * 0.5, z=0.0, qx=0.0, qy=0.0, qz=0.0, qw=1.0)
        for i in range(8)
    ]
    payload = PathPayload(stamp_ns=42, frame_id="map", poses=poses)
    msg = build_path_message(payload)
    decoded = decode_path_payload(msg.payload)
    assert decoded.stamp_ns == 42
    assert decoded.frame_id == "map"
    assert len(decoded.poses) == len(poses)
    assert all(math.isclose(p.x, d.x) for p, d in zip(poses, decoded.poses))


def test_path_limit_enforced() -> None:
    poses = [
        PathPose(x=0.0, y=0.0, z=0.0, qx=0.0, qy=0.0, qz=0.0, qw=1.0)
        for _ in range(PATH_POSE_LIMIT + 1)
    ]
    with pytest.raises(ValueError):
        PathPayload(stamp_ns=1, frame_id="map", poses=poses)
