"""Protocol metadata extraction."""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Iterable

from scripts.docsync.renderers.markdown import TableColumn, format_table


@dataclass(slots=True)
class HeaderField:
    name: str
    fmt: str
    size: int
    description: str


@dataclass(slots=True)
class EnumEntry:
    name: str
    value: int
    description: str


def _load_module(path: Path, module_name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module {module_name} from {path}")
    module = importlib.util.module_from_spec(spec)
    import sys

    sys.modules[module_name] = module
    spec.loader.exec_module(module)  # type: ignore[misc]
    return module


def collect_protocol(repo_root: Path) -> dict[str, Any]:
    base = repo_root / "ros2_ws" / "src" / "draco_roundtrip" / "draco_roundtrip"
    header_mod = _load_module(base / "protocol" / "header.py", "docsync.protocol_header")
    stream_mod = _load_module(base / "utils" / "stream_protocol.py", "docsync.stream_protocol")

    header_struct = getattr(header_mod, "HEADER_STRUCT")
    fields = [
        HeaderField("magic", "4s", 4, "Constant ASCII magic b'DRTC'"),
        HeaderField("version", "B", 1, f"Protocol version (expected {getattr(header_mod, 'VERSION', '?')})"),
        HeaderField("flags", "B", 1, "Lower 4 bits = FrameType, upper bits = fragmentation flags"),
        HeaderField("sequence", "I", 4, "Monotonic frame sequence number"),
        HeaderField("name_len", "H", 2, "Length of logical name/path metadata"),
        HeaderField("payload_len", "I", 4, "Length of payload bytes"),
    ]
    fragment_struct = getattr(header_mod, "FRAGMENT_INFO_STRUCT")
    fragment_fields = [
        HeaderField("index", "H", 2, "Zero-based fragment index"),
        HeaderField("total", "H", 2, "Total number of fragments"),
        HeaderField("frame_payload_len", "I", 4, "Length of the reassembled payload"),
    ]

    frame_types = [
        EnumEntry(name=item.name, value=int(item.value), description=item.__doc__ or "")
        for item in getattr(header_mod, "FrameType")
    ]

    control_codes = [
        EnumEntry(name=item.name, value=int(item.value), description=item.__doc__ or "")
        for item in getattr(stream_mod, "ControlCode")
    ]
    error_codes = [
        EnumEntry(name=item.name, value=int(item.value), description=item.__doc__ or "")
        for item in getattr(stream_mod, "ErrorCode")
    ]

    data_header_fields = [
        HeaderField("kind", "B", 1, "Payload kind (DATA_KIND_DRACO)"),
        HeaderField("sequence", "I", 4, "Frame sequence number"),
        HeaderField("timestamp_ns", "Q", 8, "Capture timestamp in nanoseconds"),
        HeaderField("payload_len", "I", 4, "Compressed Draco payload size"),
        HeaderField("content_type", "B", 1, "Content type hint (CONTENT_TYPE_DRACO)"),
    ]
    response_header_fields = [
        HeaderField("kind", "B", 1, "Response kind (RESPONSE_KIND_DECODED_AND_METRICS)"),
        HeaderField("sequence", "I", 4, "Frame sequence number"),
        HeaderField("timestamp_ns", "Q", 8, "Echoed capture timestamp"),
        HeaderField("decoded_len", "I", 4, "Length of decoded payload"),
        HeaderField("metrics_len", "I", 4, "Length of JSON metrics payload"),
        HeaderField("decode_ms", "H", 2, "Decode latency in milliseconds"),
    ]

    control_plane = getattr(stream_mod, "ControlPlane")
    transitions = getattr(control_plane, "_VALID_TRANSITIONS")

    timeouts = {
        "ACK_TIMEOUT_NS": getattr(stream_mod, "ACK_TIMEOUT_NS"),
        "HEARTBEAT_INTERVAL_NS": getattr(stream_mod, "HEARTBEAT_INTERVAL_NS"),
        "HEARTBEAT_LIVENESS_NS": getattr(stream_mod, "HEARTBEAT_LIVENESS_NS"),
        "CONTROL_POLL_INTERVAL": getattr(stream_mod, "CONTROL_POLL_INTERVAL"),
    }
    fragment_limits = {
        "MIN_FRAGMENT_SIZE": getattr(stream_mod, "MIN_FRAGMENT_SIZE"),
        "MAX_FRAGMENT_SIZE": getattr(stream_mod, "MAX_FRAGMENT_SIZE"),
    }

    control_channels = {
        "DATA_CHANNEL": getattr(stream_mod, "DATA_CHANNEL"),
        "CONTROL_CHANNEL": getattr(stream_mod, "CONTROL_CHANNEL"),
    }

    return {
        "frame_header": (header_struct.size, fields),
        "fragment_header": (fragment_struct.size, fragment_fields),
        "frame_types": frame_types,
        "control_codes": control_codes,
        "error_codes": error_codes,
        "data_header": (getattr(stream_mod, "_DATA_HEADER_STRUCT").size, data_header_fields),
        "response_header": (getattr(stream_mod, "_RESPONSE_HEADER_STRUCT").size, response_header_fields),
        "timeouts": timeouts,
        "fragment_limits": fragment_limits,
        "channels": control_channels,
        "transitions": transitions,
    }


def render_header_table(name: str, header: tuple[int, Iterable[HeaderField]]) -> str:
    size, fields = header
    headers = [
        TableColumn(f"{name} Field"),
        TableColumn("Format"),
        TableColumn("Bytes"),
        TableColumn("Description"),
    ]
    rows = [
        [field.name, field.fmt, str(field.size), field.description] for field in fields
    ]
    rows.append(["Total", "", str(size), ""])
    return format_table(headers, rows)


def render_enum_table(title: str, entries: Iterable[EnumEntry]) -> str:
    headers = [
        TableColumn(title),
        TableColumn("Value"),
        TableColumn("Description"),
    ]
    rows = [[entry.name, str(entry.value), entry.description] for entry in entries]
    return format_table(headers, rows)
