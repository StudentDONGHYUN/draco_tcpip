from __future__ import annotations

import importlib.abc
import importlib.machinery
import importlib.util
import sys
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parent
TESTS_ROOT = ROOT / "tests"


def _iter_candidate_paths(parts: Iterable[str]) -> tuple[Path, Path | None]:
    base = TESTS_ROOT.joinpath(*parts)
    package_init = base / "__init__.py"
    module_file = base.with_suffix(".py")
    return package_init, module_file


class _TestsPackageFinder(importlib.abc.MetaPathFinder):
    """Meta path finder that resolves the in-repo ``tests`` package."""

    def find_spec(self, fullname: str, path: object | None, target: object | None = None):
        if fullname == "tests":
            init_path, _ = _iter_candidate_paths(())
            if init_path.exists():
                loader = importlib.machinery.SourceFileLoader(fullname, str(init_path))
                return importlib.util.spec_from_file_location(
                    fullname,
                    str(init_path),
                    loader=loader,
                    submodule_search_locations=[str(init_path.parent)],
                )
            return None
        if not fullname.startswith("tests."):
            return None
        parts = fullname.split(".")[1:]
        init_path, module_path = _iter_candidate_paths(parts)
        if init_path.exists():
            loader = importlib.machinery.SourceFileLoader(fullname, str(init_path))
            return importlib.util.spec_from_file_location(
                fullname,
                str(init_path),
                loader=loader,
                submodule_search_locations=[str(init_path.parent)],
            )
        if module_path.exists():
            loader = importlib.machinery.SourceFileLoader(fullname, str(module_path))
            return importlib.util.spec_from_file_location(fullname, str(module_path), loader=loader)
        return None


# Ensure the finder has priority over the default filesystem importer so the
# package resolves even when pytest alters ``sys.path`` during collection.
_finder = _TestsPackageFinder()
if not any(isinstance(finder, _TestsPackageFinder) for finder in sys.meta_path):
    sys.meta_path.insert(0, _finder)

SRC = ROOT / "ros2_ws" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
