import sys
from pathlib import Path


SRC_ROOT = Path(__file__).resolve().parents[2]
PKG_ROOT = SRC_ROOT / "draco_roundtrip"
for path in (SRC_ROOT, PKG_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
