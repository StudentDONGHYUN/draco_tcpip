"""Configuration helpers for QoS overrides and artifact directories."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, MutableMapping, Optional, Sequence

try:  # optional during build/runtime
    from ament_index_python.packages import get_package_share_directory
except Exception:  # pragma: no cover - ROS 2 not available during tests
    get_package_share_directory = None  # type: ignore

try:  # optional dependency, not required for JSON profiles
    import yaml  # type: ignore
except Exception:  # pragma: no cover - PyYAML not installed
    yaml = None

__all__ = [
    "DataLayout",
    "ProfileConfig",
    "ensure_directory",
    "load_profile",
    "resolve_data_layout",
    "resolve_profile_path",
    "resolve_qos_override",
]

DEFAULT_DATA_SUBDIRS: Mapping[str, str] = {
    "ply_stream": "ply_stream",
    "client_work": "client_tmp",
    "decoded_from_server": "decoded_from_server",
    "ply_raw": "ply_raw",
    "draco_out": "draco_out",
    "decoded_tmp": "tmp_decoded_ply",
    "results": "results",
    "server_work": "server_tmp",
}


@dataclass(frozen=True)
class ProfileConfig:
    """Loaded profile metadata used to resolve directories and QoS files."""

    path: Optional[Path]
    data: Mapping[str, Any]

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    @property
    def data_root(self) -> Optional[Path]:
        value = self.data.get("data_root")
        if not value:
            return None
        path = Path(str(value)).expanduser()
        if path.is_absolute() or self.path is None:
            return path
        return (self.path.parent / path).resolve()

    def directory_override(self, key: str) -> Optional[str]:
        directories = self.data.get("directories")
        if isinstance(directories, Mapping):
            value = directories.get(key)
            if isinstance(value, (str, os.PathLike)):
                return str(value)
        return None

    @property
    def qos_override(self) -> Optional[str]:
        value = self.data.get("qos_override")
        if isinstance(value, (str, os.PathLike)):
            return str(value)
        return None


@dataclass(frozen=True)
class DataLayout:
    """Resolved directories for a given execution context."""

    root: Path
    directories: Mapping[str, Path]
    profile: ProfileConfig

    def __getitem__(self, key: str) -> Path:
        return self.directories[key]

    def as_dict(self) -> Mapping[str, Path]:
        return dict(self.directories)


def ensure_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _iter_packages(package: str | Sequence[str] | None) -> Iterable[str]:
    if package is None:
        return []
    if isinstance(package, str):
        return [package]
    return list(package)


def _candidate_config_roots(
    package: str | Sequence[str] | None,
    profile: ProfileConfig | None,
) -> list[Path]:
    roots: list[Path] = []
    env_root = os.environ.get("DRACO_CONFIG_ROOT")
    if env_root:
        roots.append(Path(env_root).expanduser())

    if profile and profile.path:
        roots.append(profile.path.parent)

    if get_package_share_directory:
        for pkg in _iter_packages(package):
            try:
                share_dir = Path(get_package_share_directory(pkg))
            except Exception:  # pragma: no cover - package not installed
                continue
            roots.extend(
                [
                    share_dir / "configs",
                    share_dir / "config",
                    share_dir,
                ]
            )

    here = Path(__file__).resolve()
    roots.extend(
        [
            here.parents[2] / "configs",
            here.parents[3] / "configs",
            here.parents[5] / "configs",
            Path.cwd() / "configs",
        ]
    )

    seen: set[Path] = set()
    unique_roots: list[Path] = []
    for candidate in roots:
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique_roots.append(resolved)
    return unique_roots


def resolve_profile_path(
    profile: str | os.PathLike[str] | Path | None,
    *,
    package: str | Sequence[str] | None = ("draco_roundtrip", "draco_tools"),
) -> Optional[Path]:
    if profile is None:
        return None

    profile_path = Path(profile).expanduser()
    if profile_path.is_absolute():
        return profile_path if profile_path.exists() else None

    if profile_path.suffix:
        candidate_names = [profile_path.name]
    else:
        stem = profile_path.name
        candidate_names = [
            f"{stem}.profile.yaml",
            f"{stem}.profile.json",
            f"{stem}.yaml",
            f"{stem}.yml",
            f"{stem}.json",
        ]

    for root in _candidate_config_roots(package, None):
        for name in candidate_names:
            candidate = root / name
            if candidate.exists():
                return candidate
    return None


def _parse_profile_file(path: Path) -> Mapping[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        return json.loads(text)
    if yaml is None:
        raise RuntimeError(
            f"Cannot load YAML profile {path} without PyYAML installed."
        )
    return yaml.safe_load(text)


def load_profile(
    profile: str | os.PathLike[str] | Path | Mapping[str, Any] | None,
    *,
    package: str | Sequence[str] | None = ("draco_roundtrip", "draco_tools"),
) -> ProfileConfig:
    if profile is None:
        return ProfileConfig(path=None, data={})
    if isinstance(profile, Mapping):
        return ProfileConfig(path=None, data=dict(profile))

    path = resolve_profile_path(profile, package=package)
    if path is None:
        raise FileNotFoundError(f"Could not locate profile: {profile}")
    data = _parse_profile_file(path)
    if not isinstance(data, MutableMapping):
        raise ValueError(f"Profile {path} must contain a mapping at the top level")
    return ProfileConfig(path=path, data=dict(data))


def _default_data_root(profile: ProfileConfig | None) -> Path:
    if profile and profile.path:
        parent = profile.path.parent
        candidate = (parent / "data").resolve()
        if candidate.exists():
            return candidate
        candidate = (parent.parent / "data").resolve()
        if candidate.exists():
            return candidate
    here = Path(__file__).resolve()
    cwd_candidate = (Path.cwd() / "data").resolve()
    package_candidates = [
        (here.parents[5] / "data").resolve(),
        (here.parents[4] / "data").resolve(),
    ]

    if cwd_candidate.exists():
        return cwd_candidate

    try:
        cwd_candidate.mkdir(parents=True, exist_ok=True)
        return cwd_candidate
    except OSError:
        pass

    for candidate in package_candidates:
        if candidate.exists():
            return candidate

    return package_candidates[0]


def _resolve_data_root(
    *,
    base: str | os.PathLike[str] | Path | None,
    profile: ProfileConfig,
) -> Path:
    if base:
        return Path(base).expanduser().resolve()
    if profile.data_root:
        return profile.data_root
    env_root = os.environ.get("DRACO_DATA_ROOT")
    if env_root:
        return Path(env_root).expanduser().resolve()
    return _default_data_root(profile)


def _resolve_directory_value(
    key: str,
    *,
    root: Path,
    override: str | os.PathLike[str] | Path | None,
    profile: ProfileConfig,
) -> Path:
    value: Optional[str | os.PathLike[str] | Path] = None
    if override:
        value = override
    else:
        value = profile.directory_override(key)
        if value is None:
            value = DEFAULT_DATA_SUBDIRS.get(key, key)

    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        path = (root / path).resolve()
    return path


def resolve_data_layout(
    layout_keys: Mapping[str, str],
    *,
    profile: str | os.PathLike[str] | Path | Mapping[str, Any] | None = None,
    overrides: Mapping[str, str | os.PathLike[str] | Path | None] | None = None,
    base: str | os.PathLike[str] | Path | None = None,
    ensure: bool = False,
    package: str | Sequence[str] | None = ("draco_roundtrip", "draco_tools"),
) -> DataLayout:
    profile_config = load_profile(profile, package=package)
    root = _resolve_data_root(base=base, profile=profile_config)

    resolved: dict[str, Path] = {}
    for alias, key in layout_keys.items():
        override = None
        if overrides and alias in overrides:
            override = overrides[alias]
        path = _resolve_directory_value(key, root=root, override=override, profile=profile_config)
        if ensure:
            ensure_directory(path)
        resolved[alias] = path

    return DataLayout(root=root, directories=resolved, profile=profile_config)


def _resolve_config_path(
    value: str | os.PathLike[str] | Path,
    *,
    profile: ProfileConfig | None,
    package: str | Sequence[str] | None,
) -> Optional[Path]:
    candidate = Path(value).expanduser()
    if candidate.is_absolute():
        return candidate if candidate.exists() else None

    search_roots = _candidate_config_roots(package, profile)
    for root in search_roots:
        path = root / candidate
        if path.exists():
            return path
    cwd_candidate = (Path.cwd() / candidate).resolve()
    if cwd_candidate.exists():
        return cwd_candidate
    if profile and profile.path:
        relative = (profile.path.parent / candidate).resolve()
        if relative.exists():
            return relative
    return None


def resolve_qos_override(
    explicit: str | os.PathLike[str] | Path | None = None,
    *,
    profile: ProfileConfig | None = None,
    package: str | Sequence[str] | None = ("draco_roundtrip", "draco_tools"),
) -> Optional[Path]:
    if explicit:
        path = _resolve_config_path(explicit, profile=profile, package=package)
        if path is not None:
            return path
    if profile and profile.qos_override:
        path = _resolve_config_path(profile.qos_override, profile=profile, package=package)
        if path is not None:
            return path

    for root in _candidate_config_roots(package, profile):
        candidate = root / "qos_override.yaml"
        if candidate.exists():
            return candidate
    return None
