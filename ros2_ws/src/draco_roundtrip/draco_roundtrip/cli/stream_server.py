"""CLI wrapper for the streaming server."""

from __future__ import annotations

from draco_roundtrip.nodes.stream_server import main as node_main


def main() -> None:
    node_main()
