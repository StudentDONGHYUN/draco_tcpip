"""Backwards-compatible re-exports for legacy imports."""

from .config import ensure_directory, resolve_qos_override
from .executable import resolve_executable

from draco_roundtrip.analysis.metrics import compute_basic_metrics, sample_indices
from draco_roundtrip.io.ply_codec import (
    _HAVE_O3D,
    load_xyz as load_points,
    load_xyz_from_bytes as load_points_from_bytes,
)
from draco_roundtrip.net.protocol import (
    ConnectionClosed,
    Message,
    ProtocolError,
    MSG_DATA,
    MSG_EOF,
    MSG_ERROR,
    recv_message,
    send_message,
)

__all__ = [
    "ensure_directory",
    "resolve_qos_override",
    "resolve_executable",
    "compute_basic_metrics",
    "sample_indices",
    "load_points",
    "load_points_from_bytes",
    "ConnectionClosed",
    "ProtocolError",
    "Message",
    "MSG_DATA",
    "MSG_EOF",
    "MSG_ERROR",
    "send_message",
    "recv_message",
    "_HAVE_O3D",
]
