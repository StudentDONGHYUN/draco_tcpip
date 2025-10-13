import logging

import pytest

from draco_roundtrip.draco_roundtrip.net import protocol


class FakeSocket:
    def __init__(self, payloads: list[bytes]) -> None:
        self._payloads = [bytearray(p) for p in payloads]
        self.shutdown_called = False
        self.closed = False

    def recv(self, size: int) -> bytes:
        if not self._payloads:
            return b""
        chunk = self._payloads[0][:size]
        del self._payloads[0][: len(chunk)]
        if not self._payloads[0]:
            self._payloads.pop(0)
        return bytes(chunk)

    def shutdown(self, how: int) -> None:  # pragma: no cover - behaviour simple
        self.shutdown_called = True

    def close(self) -> None:  # pragma: no cover - behaviour simple
        self.closed = True


def test_recv_text_name_limit(monkeypatch, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING)
    monkeypatch.setattr(protocol, "_text_limit_drops", 0)
    name_len = protocol.MAX_TEXT_NAME_LEN + 1
    sock = FakeSocket([protocol._HEADER.pack(name_len)])
    with pytest.raises(protocol.ConnectionClosed):
        protocol._recv_text(sock)
    assert sock.shutdown_called and sock.closed
    assert any("meta length" in record.message for record in caplog.records)


def test_recv_text_payload_limit(monkeypatch, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING)
    monkeypatch.setattr(protocol, "_text_limit_drops", 0)
    name = b"data:foo"
    payload_len = protocol.MAX_TEXT_PAYLOAD_LEN + 1
    sock = FakeSocket(
        [
            protocol._HEADER.pack(len(name)),
            name,
            protocol._SIZE.pack(payload_len),
        ]
    )
    with pytest.raises(protocol.ConnectionClosed):
        protocol._recv_text(sock)
    assert sock.shutdown_called and sock.closed
    assert any("payload length" in record.message for record in caplog.records)


def test_recv_text_accepts_within_limits(monkeypatch) -> None:
    monkeypatch.setattr(protocol, "MAX_TEXT_NAME_LEN", 8)
    monkeypatch.setattr(protocol, "MAX_TEXT_PAYLOAD_LEN", 16)
    monkeypatch.setattr(protocol, "_text_limit_drops", 0)
    name = b"data:pcd"
    payload = b"ok"
    sock = FakeSocket(
        [
            protocol._HEADER.pack(len(name)),
            name,
            protocol._SIZE.pack(len(payload)),
            payload,
        ]
    )
    message = protocol._recv_text(sock)
    assert message.kind == protocol.MSG_DATA
    assert message.name == "pcd"
    assert message.payload == payload
