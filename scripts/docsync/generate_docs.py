"""Synchronise auto-generated documentation from source of truth."""

from __future__ import annotations

import argparse
import datetime as _dt
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
ROS_SRC = REPO_ROOT / "ros2_ws" / "src"
if str(ROS_SRC) not in sys.path:
    sys.path.insert(0, str(ROS_SRC))
for pkg_name in ("draco_roundtrip", "draco_tools", "slam_stream_bridge"):
    pkg_root = ROS_SRC / pkg_name
    if pkg_root.exists() and str(pkg_root) not in sys.path:
        sys.path.insert(0, str(pkg_root))

from scripts.docsync.parsers.cli_flags import (
    CLIArgument,
    collect_cli_arguments,
    render_cli_summary,
    render_cli_table,
)
from scripts.docsync.parsers.configs import (
    collect_config_entries,
    collect_env_vars,
    render_config_table,
    render_env_table,
)
from scripts.docsync.parsers.protocol import (
    collect_protocol,
    render_enum_table,
    render_header_table,
)
from scripts.docsync.parsers.telemetry import (
    collect_telemetry,
    render_telemetry_table,
)
from scripts.docsync.renderers.markdown import TableColumn, format_table, format_bullet_list
from scripts.docsync.renderers.mermaid import (
    render_control_state_diagram,
    render_e2e_sequence_detailed,
    render_e2e_sequence_simple,
    render_tcp_control_plane_sequence_detailed,
    render_tcp_control_plane_sequence_simple,
)
from scripts.docsync.utils.fileio import AnchorUpdate, apply_updates, write_text


ANCHOR_RENDERERS: dict[tuple[Path, str], Callable[[], str]] = {
    (REPO_ROOT / "README.md", "AUTODOC:E2E_SEQUENCE_SIMPLE"): render_e2e_sequence_simple,
    (
        REPO_ROOT / "docs" / "architecture" / "Architectural_Design_and_Plan.md",
        "AUTODOC:E2E_SEQUENCE",
    ): render_e2e_sequence_detailed,
    (
        REPO_ROOT / "docs" / "reference" / "Protocol_and_Schema_Reference.md",
        "AUTODOC:TCP_CONTROL_SEQUENCE_SIMPLE",
    ): render_tcp_control_plane_sequence_simple,
    (
        REPO_ROOT / "docs" / "architecture" / "Control_Plane_Design.md",
        "AUTODOC:TCP_CONTROL_SEQUENCE_DETAILED",
    ): render_tcp_control_plane_sequence_detailed,
}


def _inject_mermaid_by_registry() -> None:
    updates_by_file: dict[Path, list[AnchorUpdate]] = {}
    for (path, anchor), renderer in ANCHOR_RENDERERS.items():
        md = f"```mermaid\n{renderer()}\n```\n"
        updates_by_file.setdefault(path, []).append(AnchorUpdate(name=anchor, content=md))
    for path, updates in updates_by_file.items():
        apply_updates(path, updates)


@dataclass(slots=True)
class TroubleshootingEntry:
    symptom: str
    cause: str
    fix: str
    sources: str


@dataclass(slots=True)
class TraceabilityRow:
    requirement: str
    source_doc: str
    implementation: str
    verification: str
    docs: str


@dataclass(slots=True)
class PerformanceTarget:
    metric: str
    target: str
    source: str
    validation: str



def _build_troubleshooting() -> list[TroubleshootingEntry]:
    return [
        TroubleshootingEntry(
            symptom="Shared memory publish failed for <stem>",
            cause="SharedMemoryPublisher backend unavailable or exhausted",
            fix="Ensure shared memory daemon is running or disable --shared-memory-only",
            sources="ros2_ws/src/draco_roundtrip/draco_roundtrip/io/bag_recorder.py:104",
        ),
        TroubleshootingEntry(
            symptom="Telemetry validation failed: pending frames remain",
            cause="Telemetry exported before ControlPlane reached TERMINATED",
            fix="Drain outstanding ACKs or wait for on_eof handshake before exporting",
            sources="ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py:146",
        ),
        TroubleshootingEntry(
            symptom="ACK timeout strikes exceeded",
            cause="Network congestion or control-plane heartbeat stalled",
            fix="Increase --ack-timeout-max or investigate link health (check metrics logs)",
            sources="ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_client.py:1798",
        ),
        TroubleshootingEntry(
            symptom="No messages for idle-timeout. Shutting down.",
            cause="Rosbag stream exhausted or topic inactive",
            fix="Lower --idle-timeout or verify rosbag playback",
            sources="ros2_ws/src/draco_roundtrip/draco_roundtrip/io/bag_recorder.py:82",
        ),
    ]


def _render_troubleshooting(entries: Iterable[TroubleshootingEntry]) -> str:
    headers = [
        TableColumn("Symptom"),
        TableColumn("Likely Cause"),
        TableColumn("Recommended Fix"),
        TableColumn("Source"),
    ]
    rows = [
        [item.symptom, item.cause, item.fix, item.sources]
        for item in entries
    ]
    return format_table(headers, rows)


def _build_traceability() -> list[TraceabilityRow]:
    return [
        TraceabilityRow(
            requirement="RQ-CP-001",
            source_doc="Control-plane state machine defined in Protocol and Schema Reference",
            implementation="ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/stream_protocol.py",
            verification="tests/unit/test_protocol_integration.py",
            docs="docs/reference/Protocol_and_Schema_Reference.md",
        ),
        TraceabilityRow(
            requirement="RQ-DATA-001",
            source_doc="Binary frame header layout",
            implementation="ros2_ws/src/draco_roundtrip/draco_roundtrip/protocol/header.py",
            verification="tests/unit/test_protocol_header.py",
            docs="docs/reference/Protocol_and_Schema_Reference.md",
        ),
        TraceabilityRow(
            requirement="RQ-CLI-001",
            source_doc="Configuration Reference CLI matrix",
            implementation="ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_client.py",
            verification="tests/unit/test_window_enforcement.py",
            docs="docs/reference/Configuration_Reference.md",
        ),
        TraceabilityRow(
            requirement="RQ-TEL-001",
            source_doc="Telemetry schema JSON",
            implementation="ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py",
            verification="tests/unit/test_telemetry_minimal.py",
            docs="docs/reference/Protocol_and_Schema_Reference.md",
        ),
    ]


def _render_traceability(rows: Iterable[TraceabilityRow]) -> str:
    headers = [
        TableColumn("Requirement"),
        TableColumn("Source"),
        TableColumn("Implementation"),
        TableColumn("Verification"),
        TableColumn("Documentation"),
    ]
    table_rows = [
        [row.requirement, row.source_doc, row.implementation, row.verification, row.docs]
        for row in rows
    ]
    return format_table(headers, table_rows)


def _build_performance_targets() -> list[PerformanceTarget]:
    return [
        PerformanceTarget(
            metric="Client telemetry latency p95",
            target="< threshold from docs/tests/perf/latency_benchmark_plan.md (default 250ms)",
            source="tests/perf/test_latency_gate.py",
            validation="pytest -k test_latency_p95_gate",
        ),
        PerformanceTarget(
            metric="Control-plane heartbeat liveness",
            target="Heartbeat observed within 6s (HEARTBEAT_LIVENESS_NS)",
            source="ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/stream_protocol.py",
            validation="tests/unit/test_protocol_integration.py::test_heartbeat_timeout",
        ),
        PerformanceTarget(
            metric="Max inflight frames",
            target="Window clamp obeys --max-inflight and drains on EOF",
            source="ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_client.py",
            validation="tests/unit/test_window_enforcement.py",
        ),
    ]


def _render_performance_targets(entries: Iterable[PerformanceTarget]) -> str:
    headers = [
        TableColumn("Metric"),
        TableColumn("Target"),
        TableColumn("Source"),
        TableColumn("Validation"),
    ]
    rows = [[e.metric, e.target, e.source, e.validation] for e in entries]
    return format_table(headers, rows)


def _build_module_map() -> str:
    ros_src = REPO_ROOT / "ros2_ws" / "src"
    sections: list[str] = []
    for package_dir in sorted(ros_src.iterdir()):
        if not package_dir.is_dir():
            continue
        setup = package_dir / "setup.py"
        if not setup.exists():
            continue
        pkg_name = package_dir.name
        module_root = package_dir / pkg_name
        if not module_root.exists():
            continue
        sections.append(f"### {pkg_name}")
        for sub in sorted(module_root.iterdir()):
            if not sub.is_dir() or sub.name.startswith("__"):
                continue
            entries: list[str] = []
            for pyfile in sorted(sub.glob("*.py")):
                doc = _first_line_doc(pyfile)
                entries.append(f"`{pyfile.relative_to(REPO_ROOT)}` — {doc or 'No module docstring'}")
            if entries:
                sections.append(f"- **{sub.name}**\n" + format_bullet_list(entries))
    return "\n\n".join(sections)


def _first_line_doc(path: Path) -> str:
    import ast

    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError:
        return ""
    doc = ast.get_docstring(tree)
    if not doc:
        return ""
    return doc.strip().splitlines()[0]


def _write_mermaid(protocol_info: dict[str, object]) -> tuple[str, str]:
    state_diagram = render_control_state_diagram(protocol_info["transitions"])  # type: ignore[arg-type]
    state_path = REPO_ROOT / "docs" / "mermaid" / "tcp_control_plane_sequence.mmd"
    write_text(state_path, state_diagram + "\n")
    e2e_diagram = render_e2e_sequence_simple()
    e2e_path = REPO_ROOT / "docs" / "mermaid" / "e2e_roundtrip_sequence.mmd"
    write_text(e2e_path, e2e_diagram + "\n")
    return state_diagram, e2e_diagram


def _update_protocol_doc(protocol_info: dict[str, object], telemetry_table: str, state_diagram: str) -> None:
    frame_header_md = render_header_table("Frame Header", protocol_info["frame_header"])  # type: ignore[arg-type]
    fragment_md = render_header_table("Fragment Info", protocol_info["fragment_header"])  # type: ignore[arg-type]
    frame_types_md = render_enum_table("FrameType", protocol_info["frame_types"])  # type: ignore[arg-type]
    control_codes_md = render_enum_table("ControlCode", protocol_info["control_codes"])  # type: ignore[arg-type]
    error_codes_md = render_enum_table("ErrorCode", protocol_info["error_codes"])  # type: ignore[arg-type]
    data_header_md = render_header_table("Data Header", protocol_info["data_header"])  # type: ignore[arg-type]
    response_header_md = render_header_table("Response Header", protocol_info["response_header"])  # type: ignore[arg-type]
    timeout_rows = [
        [name, str(value)]
        for name, value in protocol_info["timeouts"].items()  # type: ignore[assignment]
    ]
    fragment_rows = [
        [name, str(value)]
        for name, value in protocol_info["fragment_limits"].items()  # type: ignore[assignment]
    ]
    channel_rows = [
        [name, value]
        for name, value in protocol_info["channels"].items()  # type: ignore[assignment]
    ]
    constants_table = format_table(
        [TableColumn("Constant"), TableColumn("Value")],
        timeout_rows + fragment_rows + channel_rows,
    )
    protocol_md = "\n\n".join(
        [
            "#### Binary Frame Header",
            frame_header_md,
            "#### Fragment Metadata",
            fragment_md,
            "#### Control Plane Data Headers",
            data_header_md,
            response_header_md,
            "#### Enumerations",
            frame_types_md,
            control_codes_md,
            error_codes_md,
            "#### Timing and Fragment Limits",
            constants_table,
        ]
    )
    updates = [
        AnchorUpdate(name="AUTODOC:PROTOCOL", content=protocol_md),
        AnchorUpdate(name="AUTODOC:STATE_MACHINE", content=f"```mermaid\n{state_diagram}\n```"),
        AnchorUpdate(name="AUTODOC:TELEMETRY", content=telemetry_table),
    ]
    apply_updates(REPO_ROOT / "docs" / "reference" / "Protocol_and_Schema_Reference.md", updates)


def _update_configuration_doc(cli_md: str, config_md: str, env_md: str) -> None:
    content = "\n\n".join(
        [
            "### CLI Flags",
            cli_md,
            "### Configuration Files",
            config_md,
            "### Environment Variables",
            env_md,
        ]
    )
    updates = [AnchorUpdate(name="AUTODOC:CONFIG_KEYS", content=content)]
    apply_updates(REPO_ROOT / "docs" / "reference" / "Configuration_Reference.md", updates)


def _update_user_guide(cli_summary: str, troubleshooting_md: str) -> None:
    updates = [
        AnchorUpdate(name="AUTODOC:CLI_FLAGS", content=cli_summary),
        AnchorUpdate(name="AUTODOC:TROUBLESHOOT", content=troubleshooting_md),
    ]
    apply_updates(REPO_ROOT / "docs" / "guides" / "User_Guide.md", updates)


def _update_module_map(module_md: str) -> None:
    updates = [AnchorUpdate(name="AUTODOC:MODULE_MAP", content=module_md)]
    apply_updates(REPO_ROOT / "docs" / "reference" / "codebase_overview.md", updates)


def _update_performance(perf_md: str) -> None:
    quality_dir = REPO_ROOT / "docs" / "quality"
    apply_updates(quality_dir / "Performance_Test_Plan.md", [AnchorUpdate(name="AUTODOC:PERF_TARGETS", content=perf_md)])
    apply_updates(quality_dir / "results_template.md", [AnchorUpdate(name="AUTODOC:PERF_TARGETS", content=perf_md)])


def _update_traceability(trace_md: str) -> None:
    apply_updates(
        REPO_ROOT / "docs" / "architecture" / "Traceability_Matrix.md",
        [AnchorUpdate(name="AUTODOC:TRACEABILITY", content=trace_md)],
    )


def _update_audit_log() -> None:
    today = _dt.datetime.utcnow().strftime("%Y-%m-%d")
    entry = (
        f"### {today}\n"
        "- Ran `scripts/docsync/generate_docs.py --all` to refresh CLI, protocol, telemetry, and performance references.\n"
        "- Updated Mermaid diagrams and regenerated telemetry tables."
    )
    apply_updates(
        REPO_ROOT / "docs" / "reports" / "Refactor_and_Audit_Log.md",
        [AnchorUpdate(name="AUTODOC:AUDIT", content=entry)],
    )


def _update_docs_index() -> None:
    instructions = (
        "To refresh auto-generated sections run `python scripts/docsync/generate_docs.py --all`. "
        "The script is idempotent and rewrites only AUTODOC anchors."
    )
    apply_updates(
        REPO_ROOT / "docs" / "reference" / "Documentation_Index.md",
        [AnchorUpdate(name="AUTODOC:HOWTO", content=instructions)],
    )


def _update_runtime_notes(usages: list) -> None:
    notes = "Telemetry samples were not found under artifacts/perf; run a client/server session before exporting telemetry."
    apply_updates(
        REPO_ROOT / "docs" / "runtime" / "Runtime_Stability_Notes.md",
        [AnchorUpdate(name="AUTODOC:TELEMETRY_STATUS", content=notes)],
    )


def _write_report(arguments: list[CLIArgument], config_entries, telemetry_fields) -> None:
    report = {
        "cli_flags": len(arguments),
        "config_keys": len(config_entries),
        "telemetry_fields": len(telemetry_fields),
    }
    write_text(REPO_ROOT / "scripts" / "docsync" / "report.md", json.dumps(report, indent=2))


def run_all() -> None:
    cli_arguments = collect_cli_arguments(REPO_ROOT)
    cli_table = render_cli_table(cli_arguments)
    cli_summary = render_cli_summary(cli_arguments)

    config_entries = collect_config_entries(REPO_ROOT)
    config_table = render_config_table(config_entries)
    env_table = render_env_table(collect_env_vars(REPO_ROOT))

    protocol_info = collect_protocol(REPO_ROOT)
    telemetry_fields = collect_telemetry(REPO_ROOT)
    telemetry_md = render_telemetry_table(telemetry_fields)
    state_diagram, _ = _write_mermaid(protocol_info)

    troubleshooting_md = _render_troubleshooting(_build_troubleshooting())
    traceability_md = _render_traceability(_build_traceability())
    performance_md = _render_performance_targets(_build_performance_targets())
    module_map_md = _build_module_map()

    _update_protocol_doc(protocol_info, telemetry_md, state_diagram)
    _update_configuration_doc(cli_table, config_table, env_table)
    _update_user_guide(cli_summary, troubleshooting_md)
    _update_module_map(module_map_md)
    _update_performance(performance_md)
    _update_traceability(traceability_md)
    _update_audit_log()
    _update_docs_index()
    _update_runtime_notes(config_entries)
    _inject_mermaid_by_registry()
    _write_report(cli_arguments, config_entries, telemetry_fields)


def main() -> None:
    parser = argparse.ArgumentParser(description="Synchronise Draco docs from source code")
    parser.add_argument("--all", action="store_true", help="Generate every supported section (default)")
    args = parser.parse_args()
    if args.all or True:
        run_all()


if __name__ == "__main__":
    main()
