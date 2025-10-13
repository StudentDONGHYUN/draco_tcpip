"""Shared fixtures for repository tests.

This module intentionally remains lightweight so that both the repository test
suite and the ROS package specific tests can import ``tests.conftest`` without
pulling in heavy dependencies."""

from __future__ import annotations

# The real fixtures live under ``tests/unit`` and ``tests/perf``.  They are
# imported explicitly by the respective suites.  We just keep this file so that
# third-party packages expecting ``tests.conftest`` can resolve it when the
# repository root is on ``sys.path``.
