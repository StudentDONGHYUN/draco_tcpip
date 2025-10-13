"""Test package bootstrap helpers.

This module ensures that both the repository root (for local helper modules
such as ``tests.perf``) and the ROS 2 workspace source tree are available on
``sys.path`` during test collection.

Historically we inserted the ROS 2 workspace path at index 0 which caused
Python to resolve ``tests`` to the ROS package ``ros2_ws/src/draco_roundtrip/tests``
instead of the top-level test helpers shipped with this repository.  That
resulted in ``ModuleNotFoundError`` during collection because our helper
packages such as ``tests.perf`` and ``tests.unit`` live alongside this file.

By prioritising the repository root we keep the helpers importable while still
exposing the ROS workspace for runtime modules.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SRC = ROOT / "ros2_ws" / "src"
if str(SRC) not in sys.path:
    try:
        root_index = sys.path.index(str(ROOT))
    except ValueError:
        # ``ROOT`` may have been removed or re-ordered by external tooling.
        # Fall back to keeping the ROS workspace near the front so that the
        # working tree wins over any installed packages.
        insertion_index = 0
    else:
        insertion_index = root_index + 1
    sys.path.insert(insertion_index, str(SRC))
