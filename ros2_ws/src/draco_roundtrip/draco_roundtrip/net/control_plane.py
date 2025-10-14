"""Binary control-plane payloads for downlink telemetry."""

from __future__ import annotations

import json
import struct
import time
from dataclasses import dataclass
from typing import List

from .protocol import MSG_PATH, MSG_POSE, MSG_TWIST, Message

__all__ = [
    "PosePayload",
    "TwistPayload",
    "PathPayload",
    "PATH_POSE_LIMIT",
    "encode_pose_payload",
    "encode_twist_payload",
    "encode_path_payload",
    "decode_pose_payload",
    "decode_twist_payload",
    "decode_path_payload",
    "build_pose_message",
    "build_twist_message",
    "build_path_message",
    "message_to_json",
]


PATH_POSE_LIMIT = 200
_FRAME_ID_SIZE = 64
_POSE_STRUCT = struct.Struct("!Q64sddddddd")
_TWIST_STRUCT = struct.Struct("!Qffffff")
_PATH_HEADER_STRUCT = struct.Struct("!Q64sH")
_PATH_POSE_STRUCT = struct.Struct("!ddddddd")


@dataclass(slots=True)
class PosePayload:
    stamp_ns: int
    frame_id: str
    x: float
    y: float
    z: float
    qx: float
    qy: float
    qz: float
    qw: float


@dataclass(slots=True)
class TwistPayload:
    stamp_ns: int
    vx: float
    vy: float
    vz: float
    wx: float
    wy: float
    wz: float


@dataclass(slots=True)
class PathPose:
    x: float
    y: float
    z: float
    qx: float
    qy: float
    qz: float
    qw: float


@dataclass(slots=True)
class PathPayload:
    stamp_ns: int
    frame_id: str
    poses: List[PathPose]

    def __post_init__(self) -> None:
        if len(self.poses) > PATH_POSE_LIMIT:
            raise ValueError(f"path pose count {len(self.poses)} exceeds limit {PATH_POSE_LIMIT}")


def _encode_frame_id(frame_id: str) -> bytes:
    encoded = frame_id.encode("utf-8")[:_FRAME_ID_SIZE]
    return encoded.ljust(_FRAME_ID_SIZE, b"\x00")


def encode_pose_payload(payload: PosePayload) -> bytes:
    return _POSE_STRUCT.pack(
        payload.stamp_ns,
        _encode_frame_id(payload.frame_id),
        payload.x,
        payload.y,
        payload.z,
        payload.qx,
        payload.qy,
        payload.qz,
        payload.qw,
    )


def encode_twist_payload(payload: TwistPayload) -> bytes:
    return _TWIST_STRUCT.pack(
        payload.stamp_ns,
        payload.vx,
        payload.vy,
        payload.vz,
        payload.wx,
        payload.wy,
        payload.wz,
    )


def encode_path_payload(payload: PathPayload) -> bytes:
    header = _PATH_HEADER_STRUCT.pack(
        payload.stamp_ns,
        _encode_frame_id(payload.frame_id),
        len(payload.poses),
    )
    buf = bytearray(header)
    for pose in payload.poses:
        buf.extend(
            _PATH_POSE_STRUCT.pack(
                pose.x,
                pose.y,
                pose.z,
                pose.qx,
                pose.qy,
                pose.qz,
                pose.qw,
            )
        )
    return bytes(buf)


def _decode_frame_id(frame_id_bytes: bytes) -> str:
    return frame_id_bytes.split(b"\x00", 1)[0].decode("utf-8", errors="ignore")


def decode_pose_payload(data: bytes) -> PosePayload:
    if len(data) != _POSE_STRUCT.size:
        raise ValueError(f"pose payload size {len(data)} != {_POSE_STRUCT.size}")
    (
        stamp_ns,
        frame_id_bytes,
        x,
        y,
        z,
        qx,
        qy,
        qz,
        qw,
    ) = _POSE_STRUCT.unpack(data)
    return PosePayload(
        stamp_ns=stamp_ns,
        frame_id=_decode_frame_id(frame_id_bytes),
        x=x,
        y=y,
        z=z,
        qx=qx,
        qy=qy,
        qz=qz,
        qw=qw,
    )


def decode_twist_payload(data: bytes) -> TwistPayload:
    if len(data) != _TWIST_STRUCT.size:
        raise ValueError(f"twist payload size {len(data)} != {_TWIST_STRUCT.size}")
    (
        stamp_ns,
        vx,
        vy,
        vz,
        wx,
        wy,
        wz,
    ) = _TWIST_STRUCT.unpack(data)
    return TwistPayload(
        stamp_ns=stamp_ns,
        vx=vx,
        vy=vy,
        vz=vz,
        wx=wx,
        wy=wy,
        wz=wz,
    )


def decode_path_payload(data: bytes) -> PathPayload:
    if len(data) < _PATH_HEADER_STRUCT.size:
        raise ValueError("path payload too small")
    stamp_ns, frame_id_bytes, count = _PATH_HEADER_STRUCT.unpack_from(data)
    if count > PATH_POSE_LIMIT:
        raise ValueError(f"path pose count {count} exceeds limit {PATH_POSE_LIMIT}")
    expected = _PATH_HEADER_STRUCT.size + count * _PATH_POSE_STRUCT.size
    if len(data) != expected:
        raise ValueError(f"path payload size {len(data)} != {expected}")
    poses: List[PathPose] = []
    offset = _PATH_HEADER_STRUCT.size
    for _ in range(count):
        (x, y, z, qx, qy, qz, qw) = _PATH_POSE_STRUCT.unpack_from(data, offset)
        offset += _PATH_POSE_STRUCT.size
        poses.append(PathPose(x=x, y=y, z=z, qx=qx, qy=qy, qz=qz, qw=qw))
    return PathPayload(
        stamp_ns=stamp_ns,
        frame_id=_decode_frame_id(frame_id_bytes),
        poses=poses,
    )


def build_pose_message(payload: PosePayload) -> Message:
    return Message(kind=MSG_POSE, name="pose", payload=encode_pose_payload(payload))


def build_twist_message(payload: TwistPayload) -> Message:
    return Message(kind=MSG_TWIST, name="twist", payload=encode_twist_payload(payload))


def build_path_message(payload: PathPayload) -> Message:
    return Message(kind=MSG_PATH, name="path", payload=encode_path_payload(payload))


def message_to_json(message: Message) -> bytes:
    now_ns = int(time.time() * 1e9)
    if message.kind == MSG_POSE:
        pose = decode_pose_payload(message.payload)
        data = {
            "type": MSG_POSE,
            "stamp_ns": pose.stamp_ns,
            "frame_id": pose.frame_id,
            "position": {
                "x": pose.x,
                "y": pose.y,
                "z": pose.z,
            },
            "orientation": {
                "x": pose.qx,
                "y": pose.qy,
                "z": pose.qz,
                "w": pose.qw,
            },
            "relay_stamp_ns": now_ns,
        }
    elif message.kind == MSG_TWIST:
        twist = decode_twist_payload(message.payload)
        data = {
            "type": MSG_TWIST,
            "stamp_ns": twist.stamp_ns,
            "linear": {"x": twist.vx, "y": twist.vy, "z": twist.vz},
            "angular": {"x": twist.wx, "y": twist.wy, "z": twist.wz},
            "relay_stamp_ns": now_ns,
        }
    elif message.kind == MSG_PATH:
        path = decode_path_payload(message.payload)
        data = {
            "type": MSG_PATH,
            "stamp_ns": path.stamp_ns,
            "frame_id": path.frame_id,
            "poses": [
                {
                    "position": {"x": p.x, "y": p.y, "z": p.z},
                    "orientation": {"x": p.qx, "y": p.qy, "z": p.qz, "w": p.qw},
                }
                for p in path.poses
            ],
            "relay_stamp_ns": now_ns,
        }
    else:
        raise ValueError(f"unsupported message kind {message.kind}")
    return json.dumps(data, separators=(",", ":")).encode("utf-8")

