import asyncio
import pytest

pytest.importorskip("numpy")

from draco_roundtrip.common.state_machine import StreamState, StreamStateMachine, StateTransitionError
from draco_roundtrip.utils.stream_protocol import ControlPlane
from draco_roundtrip.nodes import stream_client


@pytest.mark.asyncio
async def test_fail_and_signal_sets_failure_and_wakes_condition() -> None:
    lifecycle = StreamStateMachine(role="client")
    stop_event = asyncio.Event()
    condition = asyncio.Condition()

    async def waiter() -> None:
        async with condition:
            await condition.wait()

    task = asyncio.create_task(waiter())
    await asyncio.sleep(0)
    await stream_client._fail_and_signal(  # type: ignore[attr-defined]
        lifecycle,
        stop_event,
        "unit-test failure",
        inflight_condition=condition,
    )
    assert lifecycle.state is StreamState.FAILED
    assert lifecycle.reason == "unit-test failure"
    assert stop_event.is_set()
    await asyncio.wait_for(task, timeout=1.0)


def test_stream_state_machine_transitions() -> None:
    lifecycle = StreamStateMachine(role="server")
    lifecycle.transition(StreamState.HANDSHAKING)
    lifecycle.transition(StreamState.STREAMING)
    lifecycle.transition(StreamState.DRAINING)
    lifecycle.transition(StreamState.TERMINATED)
    assert lifecycle.state is StreamState.TERMINATED
    lifecycle.reset()
    lifecycle.transition(StreamState.HANDSHAKING)
    lifecycle.fail("simulated failure")
    assert lifecycle.state is StreamState.FAILED
    with pytest.raises(StateTransitionError):
        lifecycle.transition(StreamState.STREAMING)


def test_control_plane_eof_idempotent() -> None:
    plane = ControlPlane(role="client")
    plane.on_connected()
    plane.on_first_data()
    plane.on_eof_sent()
    plane.on_eof_sent()  # idempotent
    plane.on_eof_received()
    plane.on_eof_received()
    assert plane.state in (StreamState.DRAINING, StreamState.TERMINATED)


def test_loopback_control_plane_termination() -> None:
    client_plane = ControlPlane(role="client")
    server_plane = ControlPlane(role="server")
    client_state = StreamStateMachine(role="client")
    server_state = StreamStateMachine(role="server")

    client_plane.on_connected()
    server_plane.on_connected()
    client_state.transition(StreamState.HANDSHAKING)
    server_state.transition(StreamState.HANDSHAKING)

    for seq in range(3):
        client_plane.on_frame_sent(seq)
        server_plane.on_first_data()
        client_state.transition(StreamState.STREAMING)
        server_state.transition(StreamState.STREAMING)
        client_plane.on_ack(seq)

    assert client_plane.pending == 0
    client_plane.on_eof_sent()
    server_plane.on_eof_received()
    server_state.transition(StreamState.DRAINING)
    client_plane.on_eof_received()
    client_state.transition(StreamState.DRAINING)
    client_plane.on_shutdown()
    server_plane.on_shutdown()
    assert client_plane.state in (StreamState.DRAINING, StreamState.TERMINATED, StreamState.FAILED)
    assert server_plane.state in (StreamState.DRAINING, StreamState.TERMINATED, StreamState.FAILED)
    if client_plane.state == StreamState.TERMINATED:
        client_state.transition(StreamState.TERMINATED)
    if server_plane.state == StreamState.TERMINATED:
        server_state.transition(StreamState.TERMINATED)
    assert client_state.state in {
        StreamState.DRAINING,
        StreamState.TERMINATED,
        StreamState.FAILED,
    }
    assert server_state.state in {
        StreamState.DRAINING,
        StreamState.TERMINATED,
        StreamState.FAILED,
    }
