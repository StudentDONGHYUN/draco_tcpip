"""Mermaid diagram generators for docs sync."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping


_LEGACY_DIR = Path(__file__).resolve().parents[1] / "legacy" / "diagrams"


def _read_legacy(name: str) -> str:
    path = _LEGACY_DIR / name
    return path.read_text(encoding="utf-8").strip()


def render_control_state_diagram(transitions: Mapping[object, tuple[object, ...]]) -> str:
    lines = ["stateDiagram-v2", "  [*] --> INIT"]
    lines.append("  INIT --> HANDSHAKING: on_connected()")
    lines.append("  HANDSHAKING --> STREAMING: on_first_data() / on_heartbeat()")
    lines.append("  STREAMING --> DRAINING: on_eof_sent() / on_eof_received()")
    lines.append("  DRAINING --> TERMINATED: on_ack() with no pending")
    lines.append("  STREAMING --> FAILED: on_error() / heartbeat timeout")
    lines.append("  DRAINING --> FAILED: on_error()")
    lines.append("  HANDSHAKING --> FAILED: on_error()")
    lines.append("  TERMINATED --> [*]")
    lines.append("  FAILED --> [*]")
    # Document allowed loops for retransmission/pending management
    lines.append("  STREAMING --> STREAMING: on_frame_sent() / ACK pending")
    lines.append("  DRAINING --> DRAINING: pending ACKs remain")
    return "\n".join(lines)


def render_e2e_sequence_simple() -> str:
    lines = [
        "sequenceDiagram",
        "  participant Sensor as LiDAR Sensor",
        "  participant Encoder as Draco Encoder",
        "  participant Sender as TCP Sender",
        "  participant Bridge as ROS 2 Bridge",
        "  Sensor->>Encoder: Capture frame",
        "  Encoder->>Sender: Compressed Draco payload",
        "  Sender-->>Bridge: TCP DATA stream",
        "  Bridge->>Bridge: Decode + build PointCloud2",
        "  Bridge-->>Sender: ACK / flow control",
    ]
    return "\n".join(lines)


def render_e2e_sequence_detailed() -> str:
    return _read_legacy("legacy_e2e_roundtrip_sequence.mmd")


def render_tcp_control_plane_sequence_simple() -> str:
    lines = [
        "sequenceDiagram",
        "  participant Sender as TCP Sender",
        "  participant Receiver as TCP Receiver",
        "  participant Control as Control Plane",
        "  Sender->>Receiver: DATA frame",
        "  Receiver-->>Sender: ACK (window update)",
        "  Control-->>Sender: Heartbeat timer",
        "  Sender-->>Control: EOF / Error signal",
        "  Control-->>Receiver: Close stream on EOF",
    ]
    return "\n".join(lines)


def render_tcp_control_plane_sequence_detailed() -> str:
    return _read_legacy("legacy_tcp_control_plane_sequence.mmd")
