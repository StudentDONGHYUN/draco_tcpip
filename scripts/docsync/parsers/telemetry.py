"""Telemetry schema extraction and producer mapping."""

from __future__ import annotations

import importlib
import sys
import inspect
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List

from scripts.docsync.renderers.markdown import TableColumn, format_table


@dataclass(slots=True)
class TelemetryField:
    path: str
    type_info: str
    producer: str
    when: str
    notes: str


def _flatten_schema(node: Dict[str, Any], prefix: str, *, required: Iterable[str]) -> List[tuple[str, Dict[str, Any]]]:
    entries: list[tuple[str, Dict[str, Any]]] = []
    node_type = node.get("type")
    if node_type == "object":
        props = node.get("properties", {})
        req = node.get("required", [])
        for name, child in props.items():
            path = f"{prefix}.{name}" if prefix else name
            entries.extend(_flatten_schema(child, path, required=req))
    else:
        meta = dict(node)
        meta["required"] = prefix.split(".")[-1] in required if prefix and isinstance(required, Iterable) else False
        entries.append((prefix, meta))
    return entries


def _type_info(meta: Dict[str, Any]) -> str:
    type_name = meta.get("type", "?")
    extras: list[str] = []
    if "enum" in meta:
        extras.append("enum=" + ",".join(map(str, meta["enum"])))
    if "minimum" in meta:
        extras.append(f"min={meta['minimum']}")
    if "maximum" in meta:
        extras.append(f"max={meta['maximum']}")
    if meta.get("required"):
        extras.append("required")
    return f"{type_name}{' (' + '; '.join(extras) + ')' if extras else ''}"


def collect_telemetry(repo_root: Path) -> list[TelemetryField]:
    schema_path = repo_root / "docs" / "reference" / "telemetry_schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    flattened = _flatten_schema(schema, "", required=schema.get("required", []))

    if "draco_roundtrip" not in sys.modules:
        importlib.import_module("draco_roundtrip")
    telemetry_mod = importlib.import_module("draco_roundtrip.utils.telemetry")
    telemetry_cls = getattr(telemetry_mod, "Telemetry")
    producers: dict[str, str] = {}
    when_notes: dict[str, tuple[str, str]] = {}

    source_map: dict[str, str] = {}
    for name in ["build", "_session_block", "_normalize_metrics", "validate"]:
        func = getattr(telemetry_cls, name)
        file_path = Path(inspect.getsourcefile(func))
        line = inspect.getsourcelines(func)[1]
        try:
            rel = file_path.relative_to(repo_root)
        except ValueError:
            rel = file_path
        source_map[name] = f"{rel}:{line} ({telemetry_cls.__name__}.{name})"

    producers.update(
        {
            "schema_version": source_map["build"],
            "schema_doc": source_map["build"],
            "session.id": source_map["_session_block"],
            "session.role": source_map["_session_block"],
            "session.transport": source_map["_session_block"],
            "session.protocol": source_map["_session_block"],
            "session.fragment_size": source_map["_session_block"],
            "session.socket_buffer_autotune": source_map["_session_block"],
            "session.started_at_ns": source_map["_session_block"],
            "session.ended_at_ns": source_map["_session_block"],
            "session.state": source_map["_session_block"],
            "session.error_code": source_map["_session_block"],
            "session.error_message": source_map["_session_block"],
            "metrics.latency_ms.p50": source_map["_normalize_metrics"],
            "metrics.latency_ms.p95": source_map["_normalize_metrics"],
            "metrics.latency_ms.p99": source_map["_normalize_metrics"],
            "metrics.rtt_ms.p50": source_map["_normalize_metrics"],
            "metrics.rtt_ms.p95": source_map["_normalize_metrics"],
            "metrics.rtt_ms.p99": source_map["_normalize_metrics"],
            "metrics.ack_latency_ms.p50": source_map["_normalize_metrics"],
            "metrics.ack_latency_ms.p95": source_map["_normalize_metrics"],
            "metrics.ack_latency_ms.p99": source_map["_normalize_metrics"],
            "metrics.throughput_mbps.avg": source_map["_normalize_metrics"],
            "metrics.throughput_mbps.peak": source_map["_normalize_metrics"],
            "metrics.queues.capture_max": source_map["_normalize_metrics"],
            "metrics.queues.encode_max": source_map["_normalize_metrics"],
            "metrics.queues.decode_max": source_map["_normalize_metrics"],
            "metrics.queues.pending": source_map["_normalize_metrics"],
            "metrics.frames.sent": source_map["_normalize_metrics"],
            "metrics.frames.acked": source_map["_normalize_metrics"],
            "metrics.frames.dropped": source_map["_normalize_metrics"],
            "metrics.frames.skipped": source_map["_normalize_metrics"],
        }
    )

    when_notes.update(
        {
            "schema_version": ("Telemetry export", "Constant from Telemetry.SCHEMA_VERSION"),
            "schema_doc": ("Telemetry export", "Anchors schema doc path"),
            "session.id": ("Session creation", "Derived from role/time/pid"),
            "session.role": ("Session creation", "CLI role passed to Telemetry"),
            "session.transport": ("Session creation", "Transport argument"),
            "session.protocol": ("Session creation", "Framing protocol name"),
            "session.fragment_size": ("Session creation", "Tx fragment configuration"),
            "session.socket_buffer_autotune": ("Session creation", "Reflects CLI socket buffer flag"),
            "session.started_at_ns": ("on_connected", "ControlPlane timestamp"),
            "session.ended_at_ns": ("on_shutdown", "ControlPlane completion timestamp"),
            "session.state": ("export", "ControlPlane.state value"),
            "session.error_code": ("Failure export", "Filled when state == FAILED"),
            "session.error_message": ("Failure export", "Optional failure context"),
            "metrics.latency_ms.p50": ("Metrics normalization", "Percentiles computed from PipelineStats"),
            "metrics.latency_ms.p95": ("Metrics normalization", ""),
            "metrics.latency_ms.p99": ("Metrics normalization", ""),
            "metrics.rtt_ms.p50": ("Metrics normalization", ""),
            "metrics.rtt_ms.p95": ("Metrics normalization", ""),
            "metrics.rtt_ms.p99": ("Metrics normalization", ""),
            "metrics.ack_latency_ms.p50": ("Metrics normalization", ""),
            "metrics.ack_latency_ms.p95": ("Metrics normalization", ""),
            "metrics.ack_latency_ms.p99": ("Metrics normalization", ""),
            "metrics.throughput_mbps.avg": ("Metrics normalization", "Aggregated from total bytes/elapsed"),
            "metrics.throughput_mbps.peak": ("Metrics normalization", "Same as avg in current exporter"),
            "metrics.queues.capture_max": ("Metrics normalization", "Max capture queue depth"),
            "metrics.queues.encode_max": ("Metrics normalization", "Max encode queue depth"),
            "metrics.queues.decode_max": ("Metrics normalization", "Max decode queue depth"),
            "metrics.queues.pending": ("Metrics normalization", "Pending frames at export (0 when terminated)"),
            "metrics.frames.sent": ("Metrics normalization", "Total frames sent"),
            "metrics.frames.acked": ("Metrics normalization", "Frames acknowledged"),
            "metrics.frames.dropped": ("Metrics normalization", "Frames dropped"),
            "metrics.frames.skipped": ("Metrics normalization", "Frames skipped due to quality filters"),
        }
    )

    results: list[TelemetryField] = []
    for path, meta in flattened:
        producer = producers.get(path, "")
        when, note = when_notes.get(path, ("", ""))
        results.append(
            TelemetryField(
                path=path,
                type_info=_type_info(meta),
                producer=producer,
                when=when,
                notes=note,
            )
        )
    return results


def render_telemetry_table(fields: list[TelemetryField]) -> str:
    headers = [
        TableColumn("Field"),
        TableColumn("Type / Constraints"),
        TableColumn("Produced By"),
        TableColumn("When"),
        TableColumn("Notes"),
    ]
    rows = [
        [field.path, field.type_info, field.producer, field.when, field.notes]
        for field in sorted(fields, key=lambda item: item.path)
    ]
    return format_table(headers, rows)
