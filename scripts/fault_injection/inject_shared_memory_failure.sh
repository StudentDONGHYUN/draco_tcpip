#!/usr/bin/env bash
set -euo pipefail

PYTHONPATH=${PYTHONPATH:-}:$(pwd)/ros2_ws/src \
    pytest tests/unit/test_stream_resources.py::test_shared_memory_publisher_unlinks_on_failure
