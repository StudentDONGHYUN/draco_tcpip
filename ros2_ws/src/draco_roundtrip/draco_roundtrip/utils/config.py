"""Configuration helpers (QoS, directories)."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

try:  # optional during build
    from ament_index_python.packages import get_package_share_directory
except Exception:  # pragma: no cover
    get_package_share_directory = None  # type: ignore

__all__ = ["resolve_qos_override", "ensure_directory"]


def resolve_qos_override(package: str = "draco_roundtrip") -> Optional[Path]:
    candidates: list[Path] = []
    if get_package_share_directory:
        try:
            share_dir = Path(get_package_share_directory(package))
            candidates.append(share_dir / "config" / "qos_override.yaml")
            candidates.append(share_dir / "configs" / "qos_override.yaml")
        except Exception:
            pass
    # development fallbacks (symlink install, editable build)
    here = Path(__file__).resolve()
    candidates.append(here.parents[2] / "configs" / "qos_override.yaml")
    candidates.append(here.parents[3] / "configs" / "qos_override.yaml")
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def ensure_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path
