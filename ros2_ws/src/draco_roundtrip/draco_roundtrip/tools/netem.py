"""Helpers for applying tc netem profiles defined in configs/netem.profiles.yaml."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

try:  # Optional dependency, keep graceful fallback for tests/CI
    import yaml  # type: ignore
except Exception:  # pragma: no cover - PyYAML not available
    yaml = None

from draco_roundtrip.utils.config import resolve_profile_path


@dataclass(frozen=True)
class NetemProfile:
    """Container describing a tc netem profile."""

    name: str
    params: Mapping[str, object]

    @property
    def description(self) -> str:
        value = self.params.get("description")
        return str(value) if value is not None else ""

    @property
    def is_clear(self) -> bool:
        return bool(self.params.get("clear", False))


def _load_mapping(path: Path) -> Mapping[str, object]:
    text = path.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        if yaml is None:
            raise
        data = yaml.safe_load(text)
    if not isinstance(data, Mapping):
        raise ValueError(f"Netem profile file must contain a mapping: {path}")
    return data


def load_profiles(path: Path | None = None) -> dict[str, NetemProfile]:
    """Load named tc netem profiles from the configs directory."""

    if path is None:
        resolved = resolve_profile_path("netem.profiles.yaml")
        if resolved is None:
            resolved = Path(__file__).resolve().parents[5] / "configs" / "netem.profiles.yaml"
        path = resolved
    data = _load_mapping(path)
    profiles_obj = data.get("profiles", data)
    if not isinstance(profiles_obj, Mapping):
        raise ValueError("Top-level 'profiles' key must map profile names to parameters")
    profiles: dict[str, NetemProfile] = {}
    for name, params in profiles_obj.items():
        if not isinstance(params, Mapping):
            raise ValueError(f"Profile '{name}' must map to a dictionary")
        profiles[name] = NetemProfile(name=name, params=dict(params))
    return profiles


def build_tc_commands(profile: NetemProfile, iface: str) -> list[list[str]]:
    """Create tc command lines implementing the provided profile."""

    if profile.is_clear:
        return [["tc", "qdisc", "del", "dev", iface, "root"]]

    if "commands" in profile.params:
        commands_param = profile.params["commands"]
        if not isinstance(commands_param, Iterable):
            raise ValueError("Profile 'commands' must be an iterable of command strings")
        commands: list[list[str]] = []
        for entry in commands_param:
            if not isinstance(entry, str):
                raise ValueError("Custom command entries must be strings")
            commands.append(entry.split())
        return commands

    args: list[str] = ["tc", "qdisc", "replace", "dev", iface, "root", "netem"]

    def _maybe_append(key: str, *extra: str) -> None:
        value = profile.params.get(key)
        if value in (None, ""):
            return
        args.extend([key.replace("_", "-"), str(value)])
        for item in extra:
            args.append(item)

    delay = profile.params.get("delay")
    if delay not in (None, ""):
        args.extend(["delay", str(delay)])
        jitter = profile.params.get("jitter")
        if jitter not in (None, ""):
            args.append(str(jitter))
        distribution = profile.params.get("distribution")
        if distribution not in (None, ""):
            args.extend(["distribution", str(distribution)])

    for key in ("loss", "duplicate", "corrupt", "reorder", "rate"):
        _maybe_append(key)

    if len(args) == 7:  # No modifiers were provided
        raise ValueError(f"Profile '{profile.name}' does not define any netem modifiers")

    return [args]


def format_commands(commands: Iterable[list[str]]) -> list[str]:
    return [" ".join(cmd) for cmd in commands]


def apply_profile(profile: NetemProfile, iface: str, *, dry_run: bool = False) -> list[subprocess.CompletedProcess[str]]:
    commands = build_tc_commands(profile, iface)
    completed: list[subprocess.CompletedProcess[str]] = []
    for cmd in commands:
        if dry_run:
            print("[NETEM] DRY-RUN:", " ".join(cmd))
            completed.append(
                subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")
            )
            continue
        result = subprocess.run(cmd, check=False, capture_output=True, text=True)
        completed.append(result)
        if result.returncode != 0:
            raise RuntimeError(
                f"Command failed ({result.returncode}): {' '.join(cmd)}\n"\
                f"STDOUT: {result.stdout}\nSTDERR: {result.stderr}"
            )
    return completed


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Apply tc netem profiles from configs/netem.profiles.yaml")
    parser.add_argument("profile", nargs="?", help="Name of the profile to apply or 'list' to inspect available profiles")
    parser.add_argument("--iface", default="lo", help="Network interface to configure (default: loopback)")
    parser.add_argument("--config", default=None, help="Override path to netem profiles file")
    parser.add_argument("--dry-run", action="store_true", help="Print commands without executing them")
    parser.add_argument("--clear", action="store_true", help="Remove existing netem qdisc before applying the selected profile")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    profiles = load_profiles(Path(args.config)) if args.config else load_profiles()
    if args.profile in (None, "list"):
        print("Available netem profiles:")
        for name in sorted(profiles):
            profile = profiles[name]
            description = profile.description or "(no description)"
            summary = ", ".join(format_commands(build_tc_commands(profile, args.iface)))
            print(f"  - {name}: {description}\n    {summary}")
        return 0

    if args.profile not in profiles:
        print(f"Unknown profile '{args.profile}'. Use 'list' to inspect options.", file=sys.stderr)
        return 2

    profile = profiles[args.profile]

    if args.clear and not profile.is_clear:
        clear_profile = NetemProfile(name="clear", params={"clear": True})
        apply_profile(clear_profile, args.iface, dry_run=args.dry_run)

    try:
        apply_profile(profile, args.iface, dry_run=args.dry_run)
    except Exception as exc:  # pragma: no cover - exercised via CLI
        print(f"Failed to apply profile '{profile.name}': {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    sys.exit(main())
