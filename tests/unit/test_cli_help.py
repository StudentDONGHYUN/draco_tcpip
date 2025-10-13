import pytest

pytest.importorskip("numpy")

from draco_roundtrip.draco_roundtrip.nodes import stream_client, stream_server


def test_server_help_mentions_control_port_deprecation():
    parser = stream_server.build_arg_parser()
    help_text = parser.format_help()
    assert "[DEPRECATED]" in help_text
    assert "control-plane messages reuse the data port" in help_text


def test_client_help_mentions_control_port_deprecation():
    parser = stream_client.build_arg_parser()
    help_text = parser.format_help()
    assert "[DEPRECATED]" in help_text
    assert "control-plane messages share the data connection" in help_text
