import json

import pytest

pytest.importorskip("numpy")

from draco_roundtrip.net.control_plane import (
    PathPayload,
    PathPose,
    PosePayload,
    TwistPayload,
    build_path_message,
    build_pose_message,
    build_twist_message,
)
from draco_roundtrip.net.protocol import MSG_PATH, MSG_POSE, MSG_TWIST
from draco_roundtrip.nodes.stream_client import _decode_downlink_message


@pytest.mark.parametrize("protocol", ["binary", "json"])
def test_decode_downlink_message_pose(protocol: str) -> None:
    payload = PosePayload(
        stamp_ns=123,
        frame_id="map",
        x=1.0,
        y=2.0,
        z=3.0,
        qx=0.0,
        qy=0.0,
        qz=0.0,
        qw=1.0,
    )
    message = build_pose_message(payload)
    if protocol == "json":
        body = json.dumps(
            {
                "type": MSG_POSE,
                "stamp_ns": payload.stamp_ns,
                "frame_id": payload.frame_id,
                "position": {"x": payload.x, "y": payload.y, "z": payload.z},
                "orientation": {
                    "x": payload.qx,
                    "y": payload.qy,
                    "z": payload.qz,
                    "w": payload.qw,
                },
            }
        ).encode("utf-8")
        message.payload = body
    kind, msg = _decode_downlink_message(message, protocol)
    assert kind == MSG_POSE
    assert msg.header.frame_id == "map"
    assert msg.pose.position.x == pytest.approx(1.0)


def test_decode_downlink_message_path_binary() -> None:
    payload = PathPayload(
        stamp_ns=456,
        frame_id="odom",
        poses=[
            PathPose(x=0.0, y=0.0, z=0.0, qx=0.0, qy=0.0, qz=0.0, qw=1.0),
            PathPose(x=1.0, y=0.0, z=0.0, qx=0.0, qy=0.0, qz=0.0, qw=1.0),
        ],
    )
    message = build_path_message(payload)
    kind, msg = _decode_downlink_message(message, "binary")
    assert kind == MSG_PATH
    assert len(msg.poses) == 2
    assert msg.poses[1].pose.position.x == pytest.approx(1.0)


def test_decode_downlink_message_twist_json() -> None:
    payload = TwistPayload(
        stamp_ns=789,
        vx=0.1,
        vy=0.0,
        vz=0.0,
        wx=0.0,
        wy=0.0,
        wz=0.5,
    )
    message = build_twist_message(payload)
    body = json.dumps(
        {
            "type": MSG_TWIST,
            "stamp_ns": payload.stamp_ns,
            "linear": {"x": payload.vx, "y": payload.vy, "z": payload.vz},
            "angular": {"x": payload.wx, "y": payload.wy, "z": payload.wz},
        }
    ).encode("utf-8")
    message.payload = body
    kind, msg = _decode_downlink_message(message, "json")
    assert kind == MSG_TWIST
    assert msg.angular.z == pytest.approx(0.5)
