"""Telemetry builder aligned with docs/specs/telemetry_schema.md."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Mapping

from draco_roundtrip.utils.stream_protocol import ControlPlane, ControlState

__all__ = ["Telemetry", "percentiles_block"]

_PERCENTILE_KEYS = ("p50", "p95", "p99")


def percentiles_block(values: Mapping[str, float] | None, *, scale: float = 1.0) -> Dict[str, float]:
    """Normalize percentile mappings with optional scaling.

    Missing keys default to ``0.0`` to satisfy telemetry schema requirements.
    """

    values = values or {}
    return {key: float(values.get(key, 0.0) * scale) for key in _PERCENTILE_KEYS}


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
        return Path(__file__).resolve().parents[5]

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

    def _session_block(
        self,
        control_plane: ControlPlane,
        overrides: Mapping[str, Any] | None = None,
    ) -> Dict[str, Any]:
        started_ns = control_plane.started_at_ns or time.monotonic_ns()
        ended_ns = control_plane.ended_at_ns or time.monotonic_ns()
        session: Dict[str, Any] = {
            "id": self.session_id,
            "role": self.role,
            "transport": self.transport,
            "protocol": self.protocol,
            "fragment_size": self.fragment_size,
            "socket_buffer_autotune": self.socket_buffer_autotune,
            "started_at_ns": int(started_ns),
            "ended_at_ns": int(ended_ns),
            "state": control_plane.state.value,
        }
        if overrides:
            session.update(overrides)
        if control_plane.state == ControlState.FAILED:
            session["error_code"] = int(control_plane.error_code)
            if control_plane.error_message:
                session["error_message"] = control_plane.error_message
        return session

    @staticmethod
    def _normalize_metrics(metrics: Mapping[str, Any]) -> Dict[str, Any]:
        if not isinstance(metrics, Mapping):
            raise ValueError("metrics payload must be a mapping")
        normalized: Dict[str, Any] = {}
        for section in ("latency_ms", "rtt_ms", "ack_latency_ms"):
            block = metrics.get(section)
            if not isinstance(block, Mapping):
                raise ValueError(f"metrics.{section} must be a mapping")
            normalized[section] = percentiles_block(block)
        throughput = metrics.get("throughput_mbps")
        if not isinstance(throughput, Mapping):
            raise ValueError("metrics.throughput_mbps must be a mapping")
        normalized["throughput_mbps"] = {
            "avg": float(throughput.get("avg", 0.0)),
            "peak": float(throughput.get("peak", 0.0)),
        }
        queues = metrics.get("queues")
        if not isinstance(queues, Mapping):
            raise ValueError("metrics.queues must be a mapping")
        pending = int(queues.get("pending", 0))
        if pending != 0:
            raise ValueError("metrics.queues.pending must be 0 at export time")
        normalized["queues"] = {
            "capture_max": int(queues.get("capture_max", 0)),
            "encode_max": int(queues.get("encode_max", 0)),
            "decode_max": int(queues.get("decode_max", 0)),
            "pending": pending,
        }
        frames = metrics.get("frames")
        if not isinstance(frames, Mapping):
            raise ValueError("metrics.frames must be a mapping")
        normalized["frames"] = {
            "sent": int(frames.get("sent", 0)),
            "acked": int(frames.get("acked", 0)),
            "dropped": int(frames.get("dropped", 0)),
            "skipped": int(frames.get("skipped", 0)),
        }
        return normalized

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
            for key in _PERCENTILE_KEYS:
                self._ensure(key in stats, f"{section}.{key} missing")
        queues = metrics.get("queues", {})
        self._ensure(isinstance(queues, dict), "queues missing")
        for key in ("capture_max", "encode_max", "decode_max", "pending"):
            self._ensure(key in queues, f"queues.{key} missing")
        frames = metrics.get("frames", {})
        self._ensure(isinstance(frames, dict), "frames missing")
        for key in ("sent", "acked", "dropped", "skipped"):
            self._ensure(key in frames, f"frames.{key} missing")

    def build(
        self,
        *,
        control_plane: ControlPlane,
        metrics: Mapping[str, Any],
        session_overrides: Mapping[str, Any] | None = None,
    ) -> Dict[str, Any]:
        if control_plane.pending != 0:
            raise ValueError("control plane must have pending=0 before telemetry export")
        payload: Dict[str, Any] = {
            "schema_version": self.SCHEMA_VERSION,
            "schema_doc": self.SCHEMA_DOC,
            "session": self._session_block(control_plane, overrides=session_overrides),
            "metrics": self._normalize_metrics(metrics),
        }
        if payload["session"].get("state") == ControlState.FAILED.value:
            payload["session"].setdefault("error_code", int(control_plane.error_code))
            if control_plane.error_message:
                payload["session"].setdefault("error_message", control_plane.error_message)
        self.validate(payload)
        return payload
