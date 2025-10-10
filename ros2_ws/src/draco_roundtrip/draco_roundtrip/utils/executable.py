"""Helpers that locate required external executables (draco_encoder/decoder)."""

from __future__ import annotations

import os
from pathlib import Path
from shutil import which
from typing import Optional

__all__ = ["resolve_executable"]


def _candidate_from_hint(name: str, hint: Optional[str]) -> Optional[Path]:
    if not hint:
        return None
    hint_path = Path(hint).expanduser().resolve()
    if hint_path.is_file() and os.access(hint_path, os.X_OK):
        return hint_path
    candidate = hint_path / name
    if candidate.exists() and os.access(candidate, os.X_OK):
        return candidate
    return None


def resolve_executable(name: str, hint: Optional[str] = None, env_var: Optional[str] = None) -> Path:
    """Resolve an executable by checking hint, env var, PATH, and common fallbacks."""

    path = _candidate_from_hint(name, hint)
    if path:
        return path

    if env_var:
        env_val = os.environ.get(env_var)
        path = _candidate_from_hint(name, env_val) if env_val else None
        if path:
            return path

    found = which(name)
    if found:
        path = Path(found).resolve()
        if os.access(path, os.X_OK):
            return path

    home = Path.home()
    fallbacks = [
        home / "draco" / "build" / "bin" / name,
        home / "draco" / "build" / name,
    ]
    for candidate in fallbacks:
        if candidate.exists() and os.access(candidate, os.X_OK):
            return candidate.resolve()

    raise FileNotFoundError(f"Unable to locate required executable: {name}")

# 변경 요약:
# - 힌트 및 검색 경로에서 실행 권한이 있는지 확인해 잘못된 파일 선택을 방지했습니다.
