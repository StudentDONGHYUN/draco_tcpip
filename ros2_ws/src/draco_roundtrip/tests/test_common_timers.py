"""Tests for the ACK deadline scheduler helpers."""

from __future__ import annotations

import asyncio

from draco_roundtrip.common.timers import AckDeadlineHeap


def test_ack_deadline_heap_push_cancel_pop_due() -> None:
    heap = AckDeadlineHeap()
    assert heap.pop_due(0.0) == []
    assert heap.push(1, 1.0) is True
    assert heap.push(2, 0.5) is True
    assert heap.push(3, 5.0) is False
    assert heap.pop_due(0.4) == []
    assert heap.pop_due(0.6) == [2]
    assert heap.next_deadline() == 1.0
    assert heap.push(1, 1.5) is True
    assert heap.pop_due(1.6) == [1]
    assert heap.cancel(99) is False
    assert heap.push(4, 3.0) is True
    assert heap.cancel(4) is True
    assert heap.pop_due(3.5) == []


def test_ack_deadline_scheduler_orders_timeouts() -> None:
    heap = AckDeadlineHeap()
    order: list[int] = []

    async def scenario() -> None:
        async def advance(now: float) -> None:
            order.extend(heap.pop_due(now))
            await asyncio.sleep(0)

        heap.push(10, 0.4)
        heap.push(11, 0.2)
        await advance(0.1)
        await advance(0.21)
        heap.push(12, 0.6)
        await advance(0.41)
        await advance(0.7)

    asyncio.run(scenario())
    assert order == [11, 10, 12]
