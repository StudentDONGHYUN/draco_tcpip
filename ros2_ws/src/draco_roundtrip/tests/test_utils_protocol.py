"""Tests for the backwards-compatible protocol shims."""

import pytest

pytest.importorskip("numpy")

import socket

from draco_roundtrip.net import protocol as core_protocol
from draco_roundtrip.utils import protocol as shim_protocol


def test_protocol_exports_match_core():
    """Every symbol exposed by the shim should map to the core helper."""
    assert set(shim_protocol.__all__) == {
        "ConnectionClosed",
        "Message",
        "ProtocolError",
        "ProtocolHandler",
        "MSG_DATA",
        "MSG_EOF",
        "MSG_ERROR",
        "available_protocols",
        "send_message",
        "resolve_protocol",
        "recv_message",
    }

    for name in shim_protocol.__all__:
        shim_attr = getattr(shim_protocol, name)
        core_attr = getattr(core_protocol, name)
        assert (
            shim_attr is core_attr
        ), f"shim draco_roundtrip.utils.protocol.{name} must alias core implementation"


def test_binary_protocol_round_trip():
    handler = core_protocol.resolve_protocol("binary")
    lhs, rhs = socket.socketpair()
    try:
        message = core_protocol.Message(kind=core_protocol.MSG_DATA, name="frame_1", payload=b"payload")
        handler.send(lhs, message)
        received = handler.recv(rhs)
        assert received == message
    finally:
        lhs.close()
        rhs.close()
