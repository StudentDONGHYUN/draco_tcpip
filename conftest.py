from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOCAL_TESTS = ROOT / "tests" / "__init__.py"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if LOCAL_TESTS.exists():
    spec = importlib.util.spec_from_file_location("tests", LOCAL_TESTS)
    if spec and spec.loader:
        module = importlib.util.module_from_spec(spec)
        module.__path__ = [str(LOCAL_TESTS.parent)]
        sys.modules.setdefault("tests", module)
        spec.loader.exec_module(module)

SRC = ROOT / "ros2_ws" / "src"
if str(SRC) not in sys.path:
    sys.path.append(str(SRC))
