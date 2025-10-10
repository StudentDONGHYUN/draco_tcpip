"""Shared-memory transport helpers for zero-copy frame capture."""

from .channel import (
    SharedMemoryDescriptor,
    SharedMemoryPublisher,
    SharedMemoryReceiver,
)

__all__ = [
    "SharedMemoryDescriptor",
    "SharedMemoryPublisher",
    "SharedMemoryReceiver",
]
