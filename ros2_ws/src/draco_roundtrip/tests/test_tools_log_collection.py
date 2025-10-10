from __future__ import annotations

import json
from pathlib import Path

from draco_roundtrip.tools.log_collection import RUN_SUBDIRS, _parse_metadata, _write_notes, initialize_run
from draco_roundtrip.utils.config import DataLayout, ProfileConfig


def _make_layout(tmp_path: Path) -> DataLayout:
    root = tmp_path
    profile = ProfileConfig(path=None, data={})
    directories = {"results": root / "results"}
    return DataLayout(root=root, directories=directories, profile=profile)


def test_initialize_run_creates_manifest(tmp_path: Path) -> None:
    layout = _make_layout(tmp_path)
    metadata = {"bag": "test.bag"}
    dummy_log = tmp_path / "ros_log"
    dummy_log.mkdir()
    (dummy_log / "events.txt").write_text("log", encoding="utf-8")

    run_root = initialize_run(
        layout,
        "run_001",
        metadata=metadata,
        ros_logs=[dummy_log],
        attachments=[],
    )

    manifest = json.loads((run_root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["metadata"] == metadata
    assert (run_root / RUN_SUBDIRS["ros_logs"] / dummy_log.name / "events.txt").exists()


def test_parse_metadata_requires_key_value() -> None:
    parsed = _parse_metadata(["bag=test.bag", "netem=wifi"])
    assert parsed == {"bag": "test.bag", "netem": "wifi"}


def test_write_notes_appends(tmp_path: Path) -> None:
    layout = _make_layout(tmp_path)
    run_root = initialize_run(layout, "run_notes", metadata={}, ros_logs=[], attachments=[])
    _write_notes(run_root, "first line")
    _write_notes(run_root, "second line")
    notes_path = run_root / RUN_SUBDIRS["notes"] / "README.txt"
    content = notes_path.read_text(encoding="utf-8")
    assert "first line" in content and "second line" in content
