import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / 'ros2_ws' / 'src'
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import tests
import socket

from draco_roundtrip.draco_roundtrip.net.protocol import Message, resolve_protocol
from draco_roundtrip.draco_roundtrip.utils.stream_protocol import (
    DATA_CHANNEL,
    CONTROL_CHANNEL,
    iter_fragments,
    encode_frame_address,
)


def test_binary_roundtrip_payload_intact():
    proto = resolve_protocol("binary")
    client, server = socket.socketpair()
    try:
        payload = b"draco-payload"
        message = Message(
            kind="data",
            name=encode_frame_address(5, "frame", channel=DATA_CHANNEL),
            payload=payload,
            sequence=5,
        )
        proto.send(client, message)
        received = proto.recv(server)
        assert received is not None
        assert received.kind == "data"
        assert received.payload == payload
        assert received.sequence == 5
    finally:
        client.close()
        server.close()


def test_fragment_roundtrip_over_socket():
    proto = resolve_protocol("binary")
    client, server = socket.socketpair()
    try:
        payload = (b"0123456789abcdefghijklmnopqrstuvwxyz" * 10)
        fragments = list(iter_fragments(payload, sequence=9, fragment_size=512))
        for fragment in fragments:
            message = Message(
                kind="data",
                name=encode_frame_address(fragment.sequence, "frame", channel=DATA_CHANNEL),
                payload=fragment.payload,
                sequence=fragment.sequence,
                fragmented=True,
                fragment_index=fragment.index,
                fragments_total=fragment.total,
                frame_payload_len=fragment.frame_payload_len,
            )
            proto.send(client, message)
        assembled = [b"" for _ in range(len(fragments))]
        for _ in fragments:
            received = proto.recv(server)
            assert received is not None
            assert received.sequence == 9
            if received.fragmented:
                assembled[received.fragment_index or 0] = received.payload
        assert b"".join(assembled) == payload
    finally:
        client.close()
        server.close()


def test_interleaved_control_and_data_messages():
    proto = resolve_protocol("binary")
    client, server = socket.socketpair()
    try:
        messages = [
            Message(
                kind="heartbeat",
                name=encode_frame_address(None, "hb", channel=CONTROL_CHANNEL),
                payload=b"",
            ),
            Message(
                kind="data",
                name=encode_frame_address(1, "frame", channel=DATA_CHANNEL),
                payload=b"xyz",
                sequence=1,
            ),
            Message(
                kind="ack",
                name=encode_frame_address(1, "frame", channel=CONTROL_CHANNEL),
                payload=b"",
                sequence=1,
            ),
        ]
        for message in messages:
            proto.send(client, message)
        received = [proto.recv(server) for _ in messages]
        kinds = [msg.kind for msg in received if msg is not None]
        assert kinds == ["heartbeat", "data", "ack"]
        assert received[1].payload == b"xyz"
        assert received[2].sequence == 1
    finally:
        client.close()
        server.close()
