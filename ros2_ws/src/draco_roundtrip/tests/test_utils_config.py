"""Tests for draco_roundtrip.utils.config helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from draco_roundtrip.utils.config import (
    resolve_data_layout,
    resolve_profile_path,
    resolve_qos_override,
)


def test_resolve_data_layout_with_env_root(tmp_path, monkeypatch):
    data_root = tmp_path / "artifacts"
    monkeypatch.setenv("DRACO_DATA_ROOT", str(data_root))

    layout = resolve_data_layout(
        {
            "ply": "ply_stream",
            "work": "client_work",
        },
        ensure=False,
    )

    assert layout.root == data_root.resolve()
    assert layout["ply"] == data_root / "ply_stream"
    assert layout["work"] == data_root / "client_tmp"


def test_resolve_data_layout_with_profile_overrides(tmp_path, monkeypatch):
    config_root = tmp_path / "configs"
    config_root.mkdir()

    profile_path = config_root / "client.profile.json"
    profile_path.write_text(
        json.dumps(
            {
                "data_root": "../data_root",
                "directories": {
                    "ply_stream": "spool",
                    "client_work": "/abs/work",
                },
                "qos_override": "qos/custom.yaml",
            }
        ),
        encoding="utf-8",
    )

    qos_path = config_root / "qos" / "custom.yaml"
    qos_path.parent.mkdir()
    qos_path.write_text("profiles: []\n", encoding="utf-8")

    monkeypatch.setenv("DRACO_CONFIG_ROOT", str(config_root))

    layout = resolve_data_layout(
        {
            "ply_dir": "ply_stream",
            "work_dir": "client_work",
        },
        profile="client",
        ensure=True,
    )

    expected_root = (profile_path.parent / "../data_root").resolve()
    assert layout.root == expected_root
    assert layout["ply_dir"] == expected_root / "spool"
    assert layout["work_dir"] == Path("/abs/work")

    qos_resolved = resolve_qos_override(profile=layout.profile)
    assert qos_resolved == qos_path.resolve()


def test_resolve_profile_path_absolute(tmp_path):
    profile_path = tmp_path / "custom.json"
    profile_path.write_text("{}", encoding="utf-8")

    assert resolve_profile_path(profile_path) == profile_path


def test_resolve_qos_override_explicit(tmp_path, monkeypatch):
    config_root = tmp_path / "configs"
    config_root.mkdir()
    qos_path = config_root / "qos_override.yaml"
    qos_path.write_text("{}", encoding="utf-8")

    monkeypatch.setenv("DRACO_CONFIG_ROOT", str(config_root))

    resolved = resolve_qos_override()
    assert resolved == qos_path

    explicit = resolve_qos_override(qos_path)
    assert explicit == qos_path
