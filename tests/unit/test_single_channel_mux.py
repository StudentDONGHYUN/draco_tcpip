import argparse
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("numpy")

from draco_roundtrip.draco_roundtrip.nodes import stream_server
from draco_roundtrip.draco_roundtrip.nodes.stream_server import ControlState


class DummyConn:
    def __init__(self) -> None:
        self.closed = False

    def __enter__(self):  # pragma: no cover - context protocol
        return self

    def __exit__(self, exc_type, exc, tb):  # pragma: no cover - context protocol
        self.close()
        return False

    def close(self) -> None:
        self.closed = True

    def settimeout(self, _value: float) -> None:  # pragma: no cover - simple stub
        return

    def setsockopt(self, *_args, **_kwargs) -> None:  # pragma: no cover - simple stub
        return

    def shutdown(self, _how: int) -> None:  # pragma: no cover - simple stub
        return


class DummyServer:
    def __enter__(self):  # pragma: no cover - context protocol
        return self

    def __exit__(self, exc_type, exc, tb):  # pragma: no cover - context protocol
        return False

    def accept(self):
        return DummyConn(), ("127.0.0.1", 5000)

    def close(self) -> None:  # pragma: no cover - context cleanup
        return


class StubControlPlane:
    state = ControlState.TERMINATED
    pending = 0
    error_message = ""

    def __init__(self) -> None:
        self.lifecycle = SimpleNamespace(
            state=SimpleNamespace(value="terminated"),
            reason="test",
        )

    def on_shutdown(self) -> None:  # pragma: no cover - interface compatibility
        return


@pytest.mark.asyncio
async def test_run_server_single_channel(monkeypatch, tmp_path, caplog):
    created = []

    def fake_create_server(address, reuse_port=True):
        created.append(address)
        return DummyServer()

    async def fake_handle_connection(conn, addr, args, decoder, work_dir, stats, totals):
        plane = StubControlPlane()
        plane.lifecycle.reason = "test-complete"
        return plane

    monkeypatch.setattr(stream_server.socket, "create_server", fake_create_server)
    monkeypatch.setattr(stream_server, "handle_connection", fake_handle_connection)
    monkeypatch.setattr(stream_server, "_export_server_telemetry", lambda *a, **k: None)
    monkeypatch.setattr(stream_server, "resolve_executable", lambda *a, **k: Path(tmp_path / "decoder"))
    monkeypatch.setattr(stream_server, "ensure_directory", lambda path: Path(path))

    args = argparse.Namespace(
        host="127.0.0.1",
        port=6000,
        control_port=6001,
        decoder=str(tmp_path / "decoder"),
        work_dir=str(tmp_path),
        decode_timeout=1.0,
        tcp_nodelay=False,
        socket_buffer_kb=0,
        socket_timeout=0.1,
        max_inflight=1,
        decode_workers=1,
        queue_size=0,
        heartbeat_interval=0.0,
        protocol="binary",
        legacy_mode=False,
        keep_artifacts=False,
        zero_copy_reply=False,
        resp_format="ply",
        metrics_out=None,
    )

    caplog.set_level(logging.WARNING)
    await stream_server.run_server(args)
    assert created == [(args.host, args.port)]
    assert args.control_port == 0
    assert any("control-port is deprecated" in record.message for record in caplog.records)
