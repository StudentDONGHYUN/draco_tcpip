import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "ros2_ws" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import tests  # noqa: F401

pytest.importorskip("numpy")

_roundtrip_module = importlib.import_module("draco_roundtrip.tests.test_roundtrip_quality")


def test_roundtrip_quality_pipeline(tmp_path):
    _roundtrip_module.test_roundtrip_quality_pipeline(tmp_path)
