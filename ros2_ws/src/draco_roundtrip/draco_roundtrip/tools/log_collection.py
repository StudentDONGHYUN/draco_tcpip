"""Utilities for collecting run artifacts into a structured results directory."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping

from draco_roundtrip.utils.config import DataLayout, ensure_directory, resolve_data_layout

RUN_SUBDIRS: Mapping[str, str] = {
    "artifacts": "artifacts",
    "metrics": "metrics",
    "ros_logs": "ros_logs",
    "notes": "notes",
}


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _copy_into(target: Path, source: Path) -> None:
    if not source.exists():
        return
    if source.is_dir():
        destination = target / source.name
        shutil.copytree(source, destination, dirs_exist_ok=True)
    else:
        ensure_directory(target)
        shutil.copy2(source, target / source.name)


def initialize_run(
    layout: DataLayout,
    run_id: str,
    *,
    metadata: Mapping[str, object],
    ros_logs: Iterable[Path] | None = None,
    attachments: Iterable[Path] | None = None,
) -> Path:
    """Prepare a results directory tree and persist the manifest."""

    run_root = ensure_directory(layout["results"] / run_id)
    directories = {}
    for key, folder in RUN_SUBDIRS.items():
        directories[key] = ensure_directory(run_root / folder)

    manifest = {
        "run_id": run_id,
        "timestamp": _timestamp(),
        "layout_root": str(layout.root),
        "profile": {
            "path": str(layout.profile.path) if layout.profile.path else None,
            "data": layout.profile.data,
        },
        "metadata": dict(metadata),
        "directories": {name: str(path) for name, path in directories.items()},
    }

    manifest_path = run_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    for source in ros_logs or []:
        _copy_into(directories["ros_logs"], source)
    for source in attachments or []:
        _copy_into(directories["artifacts"], source)

    return run_root


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Structure ROS roundtrip experiment outputs")
    parser.add_argument("run_id", help="Identifier for the experiment run (used as directory name)")
    parser.add_argument("--layout-profile", default=None, help="Layout profile used to resolve directories")
    parser.add_argument("--data-root", default=None, help="Override base data root")
    parser.add_argument("--metadata", action="append", default=[], help="Key=Value metadata to record in the manifest")
    parser.add_argument("--ros-log", action="append", default=[], help="Path(s) to ROS log directories to archive")
    parser.add_argument("--attach", action="append", default=[], help="Additional files or directories to copy into artifacts/")
    parser.add_argument("--notes", default=None, help="Free-form note written into notes/README.txt")
    return parser


def _parse_metadata(pairs: Iterable[str]) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for item in pairs:
        if "=" not in item:
            raise ValueError(f"Metadata entry must be in key=value format: {item}")
        key, value = item.split("=", 1)
        metadata[key.strip()] = value.strip()
    return metadata


def _write_notes(run_root: Path, note_text: str | None) -> None:
    if not note_text:
        return
    notes_dir = ensure_directory(run_root / RUN_SUBDIRS["notes"])
    notes_path = notes_dir / "README.txt"
    if notes_path.exists():
        existing = notes_path.read_text(encoding="utf-8")
        note_text = existing + os.linesep + note_text
    notes_path.write_text(note_text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    metadata = _parse_metadata(args.metadata)
    layout = resolve_data_layout({"results": "results"}, profile=args.layout_profile, base=args.data_root, ensure=True)

    ros_logs = [Path(p).expanduser().resolve() for p in args.ros_log]
    attachments = [Path(p).expanduser().resolve() for p in args.attach]

    run_root = initialize_run(
        layout,
        args.run_id,
        metadata=metadata,
        ros_logs=ros_logs,
        attachments=attachments,
    )
    _write_notes(run_root, args.notes)

    print(f"[LOG-COLLECT] Stored run manifest at {run_root / 'manifest.json'}")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    sys.exit(main())
