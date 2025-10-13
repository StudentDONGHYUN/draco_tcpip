"""Telemetry builder aligned with docs/specs/telemetry_schema.md."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict

from draco_roundtrip.utils.stream_protocol import ControlPlane, ControlState

__all__ = ["Telemetry"]


class Telemetry:
    """세션 텔레메트리 JSON을 생성하고 스키마 위반을 검증한다."""

    SCHEMA_VERSION = "1.0.0"
    SCHEMA_DOC = "docs/specs/telemetry_schema.md"
    _schema_cache: Dict[str, Any] | None = None

    def __init__(
        self,
        *,
        role: str,
        transport: str,
        protocol: str,
        fragment_size: int,
        socket_buffer_autotune: bool,
    ) -> None:
        self.role = role
        self.transport = transport
        self.protocol = protocol
        self.fragment_size = fragment_size
        self.socket_buffer_autotune = socket_buffer_autotune
        self.session_id = f"{role}-{int(time.time())}-{os.getpid()}"

    @classmethod
    def _repo_root(cls) -> Path:
        return Path(__file__).resolve().parents[3]

    @classmethod
    def schema_path(cls) -> Path:
        return cls._repo_root() / "docs" / "specs" / "telemetry_schema.json"

    @classmethod
    def load_schema(cls) -> Dict[str, Any]:
        if cls._schema_cache is None:
            data = json.loads(cls.schema_path().read_text(encoding="utf-8"))
            cls._schema_cache = data
        return cls._schema_cache

    @staticmethod
    def _ensure(condition: bool, message: str) -> None:
        if not condition:
            raise ValueError(f"Telemetry validation failed: {message}")

    def validate(self, payload: Dict[str, Any]) -> None:
        self._ensure(payload.get("schema_version") == self.SCHEMA_VERSION, "schema_version mismatch")
        self._ensure(payload.get("schema_doc") == self.SCHEMA_DOC, "schema_doc mismatch")
        session = payload.get("session")
        self._ensure(isinstance(session, dict), "session missing")
        for key in (
            "id",
            "role",
            "transport",
            "protocol",
            "fragment_size",
            "started_at_ns",
            "ended_at_ns",
            "state",
        ):
            self._ensure(key in session, f"session.{key} missing")
        metrics = payload.get("metrics")
        self._ensure(isinstance(metrics, dict), "metrics missing")
        for section in ("latency_ms", "rtt_ms", "ack_latency_ms"):
            stats = metrics.get(section)
            self._ensure(isinstance(stats, dict), f"{section} missing")
            for key in ("p50", "p95", "p99"):
                self._ensure(key in stats, f"{section}.{key} missing")
        queues = metrics.get("queues", {})
        self._ensure(isinstance(queues, dict), "queues missing")
        for key in ("capture_max", "encode_max", "decode_max", "pending"):
            self._ensure(key in queues, f"queues.{key} missing")
        frames = metrics.get("frames", {})
        self._ensure(isinstance(frames, dict), "frames missing")
        for key in ("sent", "acked", "dropped", "skipped"):
            self._ensure(key in frames, f"frames.{key} missing")

    @staticmethod
    def _percentile_block(values: Dict[str, float]) -> Dict[str, float]:
        return {key: float(values.get(key, 0.0)) for key in ("p50", "p95", "p99")}

    def build(
        self,
        *,
        control_plane: ControlPlane,
        elapsed: float,
        frames_processed: int,
        bytes_sent: int,
        bytes_received: int,
        latency_percentiles: Dict[str, float],
        rtt_percentiles: Dict[str, float],
        ack_percentiles: Dict[str, float],
        pending_inflight: int,
        dropped: int,
        skipped: int,
        capture_max: int,
        encode_max: int,
        decode_max: int,
        throughput_avg_mbps: float,
        throughput_peak_mbps: float,
    ) -> Dict[str, Any]:
        if pending_inflight != 0 or control_plane.pending != 0:
            raise ValueError("control plane pending queues must be empty before exporting telemetry")
        started_ns = control_plane.started_at_ns or time.monotonic_ns()
        ended_ns = control_plane.ended_at_ns or time.monotonic_ns()
        payload: Dict[str, Any] = {
            "schema_version": self.SCHEMA_VERSION,
            "schema_doc": self.SCHEMA_DOC,
            "session": {
                "id": self.session_id,
                "role": self.role,
                "transport": self.transport,
                "protocol": self.protocol,
                "fragment_size": self.fragment_size,
                "socket_buffer_autotune": self.socket_buffer_autotune,
                "started_at_ns": int(started_ns),
                "ended_at_ns": int(ended_ns),
                "state": control_plane.state.value,
            },
            "metrics": {
                "latency_ms": self._percentile_block(latency_percentiles),
                "rtt_ms": self._percentile_block(rtt_percentiles),
                "ack_latency_ms": self._percentile_block(ack_percentiles),
                "throughput_mbps": {
                    "avg": float(throughput_avg_mbps),
                    "peak": float(throughput_peak_mbps),
                },
                "queues": {
                    "capture_max": int(capture_max),
                    "encode_max": int(encode_max),
                    "decode_max": int(decode_max),
                    "pending": 0,
                },
                "frames": {
                    "sent": int(frames_processed),
                    "acked": int(frames_processed),
                    "dropped": int(dropped),
                    "skipped": int(skipped),
                },
            },
        }
        if control_plane.state == ControlState.FAILED:
            payload["session"]["error_code"] = int(control_plane.error_code)
            if control_plane.error_message:
                payload["session"]["error_message"] = control_plane.error_message
        self.validate(payload)
        return payload
