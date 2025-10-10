from __future__ import annotations

import sys
from pathlib import Path


_SRC_ROOT = Path(__file__).resolve().parents[2]
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))

for package_dir in ("draco_roundtrip", "draco_tools"):
    candidate = _SRC_ROOT / package_dir
    if candidate.is_dir():
        path_str = str(candidate)
        if path_str not in sys.path:
            sys.path.insert(0, path_str)
