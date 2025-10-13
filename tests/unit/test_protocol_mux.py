import socket

from draco_roundtrip.draco_roundtrip.net import protocol


def test_binary_protocol_multiplex_ordering():
    proto = protocol.resolve_protocol("binary")
    sender, receiver = socket.socketpair()
    try:
        messages = [
            protocol.Message(kind=protocol.MSG_DATA, name="frame", payload=b"abc", sequence=1),
            protocol.Message(kind=protocol.MSG_ACK, name="ack", payload=b"", sequence=1),
            protocol.Message(kind=protocol.MSG_HEARTBEAT, name="hb", payload=b""),
            protocol.Message(kind=protocol.MSG_EOF, name="final", payload=b""),
        ]
        for msg in messages:
            proto.send(sender, msg)
        received = [proto.recv(receiver) for _ in messages]
    finally:
        sender.close()
        receiver.close()
    kinds = [msg.kind for msg in received]
    assert kinds == [protocol.MSG_DATA, protocol.MSG_ACK, protocol.MSG_HEARTBEAT, protocol.MSG_EOF]
    assert received[0].payload == b"abc"
