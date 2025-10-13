import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / 'ros2_ws' / 'src'
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import tests
import socket
import threading
import time

import pytest

from draco_roundtrip.draco_roundtrip.net.io import recv_exact


def test_recv_exact_reads_all_bytes():
    server, client = socket.socketpair()
    try:
        def _producer() -> None:
            client.sendall(b"ab")
            time.sleep(0.05)
            client.sendall(b"cd")
            client.close()

        threading.Thread(target=_producer, daemon=True).start()
        data = recv_exact(server, 4)
        assert data == b"abcd"
    finally:
        server.close()


def test_recv_exact_raises_on_eof():
    server, client = socket.socketpair()
    try:
        client.close()
        with pytest.raises(ConnectionError):
            recv_exact(server, 1)
    finally:
        server.close()
