"""Mermaid diagram generators for docs sync."""

from __future__ import annotations

from typing import Mapping


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


def render_e2e_sequence() -> str:
    lines = [
        "sequenceDiagram",
        "  participant Capture as Capture Thread",
        "  participant Encode as Draco Encoder",
        "  participant Tx as TCP Sender",
        "  participant Rx as TCP Receiver",
        "  participant Decode as Draco Decoder",
        "  participant Publish as ROS Publisher",
        "  Capture->>Encode: FrameHandle + metadata",
        "  Encode->>Tx: DATA[FrameHeader+DataHeader+Draco payload]",
        "  Tx-->>Rx: TCP stream (DATA frames)",
        "  Rx->>Decode: Draco payload (fragment reassembly)",
        "  Decode->>Publish: PointCloud2 + metrics",
        "  Publish-->>Tx: compose_response_payload()",
        "  Tx-->>Rx: CONTROL ACK/EOF/Error (ControlPlane)",
        "  Rx-->>Tx: HEARTBEAT / ACK for flow control",
        "  Tx->>Capture: backpressure via max_inflight",
    ]
    return "\n".join(lines)
