from __future__ import annotations

from pathlib import Path

import pytest

from draco_roundtrip.tools import netem


def test_load_profiles_json(tmp_path: Path) -> None:
    config = tmp_path / "netem.json"
    config.write_text(
        """
        {"profiles": {"wifi": {"delay": "30ms", "jitter": "10ms", "loss": "0.1%"}}}
        """.strip(),
        encoding="utf-8",
    )

    profiles = netem.load_profiles(config)
    assert "wifi" in profiles
    commands = netem.build_tc_commands(profiles["wifi"], "lo")
    assert commands == [["tc", "qdisc", "replace", "dev", "lo", "root", "netem", "delay", "30ms", "10ms", "loss", "0.1%"]]


def test_clear_profile_builds_delete_command() -> None:
    profile = netem.NetemProfile(name="clear", params={"clear": True})
    commands = netem.build_tc_commands(profile, "eth0")
    assert commands == [["tc", "qdisc", "del", "dev", "eth0", "root"]]


def test_build_commands_requires_modifiers() -> None:
    profile = netem.NetemProfile(name="empty", params={})
    with pytest.raises(ValueError):
        netem.build_tc_commands(profile, "eth0")
