"""Backwards-compatible re-exports for legacy imports."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .config import (
    DataLayout,
    ProfileConfig,
    ensure_directory,
    load_profile,
    resolve_data_layout,
    resolve_profile_path,
    resolve_qos_override,
)
from .executable import resolve_executable

if TYPE_CHECKING:  # pragma: no cover - imported for type checkers only
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
    "DataLayout",
    "ProfileConfig",
    "ensure_directory",
    "load_profile",
    "resolve_data_layout",
    "resolve_profile_path",
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


def __getattr__(name: str) -> Any:  # pragma: no cover - thin compatibility layer
    if name in {
        "compute_basic_metrics",
        "sample_indices",
    }:
        from draco_roundtrip.analysis.metrics import compute_basic_metrics, sample_indices

        globals().update(
            {
                "compute_basic_metrics": compute_basic_metrics,
                "sample_indices": sample_indices,
            }
        )
        return globals()[name]

    if name in {"load_points", "load_points_from_bytes", "_HAVE_O3D"}:
        from draco_roundtrip.io.ply_codec import (
            _HAVE_O3D,
            load_xyz as load_points,
            load_xyz_from_bytes as load_points_from_bytes,
        )

        globals().update(
            {
                "load_points": load_points,
                "load_points_from_bytes": load_points_from_bytes,
                "_HAVE_O3D": _HAVE_O3D,
            }
        )
        return globals()[name]

    if name in {
        "ConnectionClosed",
        "Message",
        "ProtocolError",
        "MSG_DATA",
        "MSG_EOF",
        "MSG_ERROR",
        "recv_message",
        "send_message",
    }:
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

        globals().update(
            {
                "ConnectionClosed": ConnectionClosed,
                "Message": Message,
                "ProtocolError": ProtocolError,
                "MSG_DATA": MSG_DATA,
                "MSG_EOF": MSG_EOF,
                "MSG_ERROR": MSG_ERROR,
                "recv_message": recv_message,
                "send_message": send_message,
            }
        )
        return globals()[name]

    raise AttributeError(name)
