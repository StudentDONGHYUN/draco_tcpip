"""Shared streaming session state machine utilities."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from threading import Lock
from typing import Dict, List, Tuple


class StreamState(str, Enum):
    """Lifecycle phases for the TCP streaming pipeline."""

    INIT = "INIT"
    HANDSHAKING = "HANDSHAKING"
    STREAMING = "STREAMING"
    DRAINING = "DRAINING"
    TERMINATED = "TERMINATED"
    FAILED = "FAILED"


class StateTransitionError(RuntimeError):
    """Raised on illegal state transitions."""


@dataclass(slots=True)
class StreamStateMachine:
    """Thread-safe helper to track high-level session state transitions."""

    role: str
    state: StreamState = StreamState.INIT
    reason: str | None = None
    history: List[dict[str, str | None]] = field(default_factory=list)

    _VALID_TRANSITIONS: Dict[StreamState, Tuple[StreamState, ...]] = field(
        init=False,
        repr=False,
        default_factory=lambda: {
            StreamState.INIT: (StreamState.HANDSHAKING, StreamState.FAILED),
            StreamState.HANDSHAKING: (
                StreamState.STREAMING,
                StreamState.DRAINING,
                StreamState.FAILED,
            ),
            StreamState.STREAMING: (StreamState.DRAINING, StreamState.FAILED),
            StreamState.DRAINING: (StreamState.TERMINATED, StreamState.FAILED),
            StreamState.TERMINATED: (),
            StreamState.FAILED: (),
        },
    )
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)

    def transition(self, target: StreamState, *, reason: str | None = None) -> StreamState:
        """Move to ``target`` when the transition is valid."""

        with self._lock:
            if target == StreamState.FAILED:
                return self._enter_failed_locked(reason)
            if self.state == StreamState.FAILED:
                return self.state
            if target == self.state:
                if reason and reason != self.reason:
                    self.reason = reason
                    self.history.append({"state": self.state.value, "reason": reason})
                return self.state
            allowed = self._VALID_TRANSITIONS[self.state]
            if target not in allowed:
                raise StateTransitionError(
                    f"{self.role} cannot transition {self.state.value} → {target.value}"
                )
            previous = self.state
            self.state = target
            self.reason = reason
            self.history.append(
                {"from": previous.value, "state": target.value, "reason": reason}
            )
            return self.state

    def fail(self, reason: str | None = None) -> StreamState:
        """Enter the FAILED state (idempotent)."""

        with self._lock:
            return self._enter_failed_locked(reason)

    def _enter_failed_locked(self, reason: str | None = None) -> StreamState:
        """Internal helper to record transition into FAILED while holding ``_lock``."""

        if self.state == StreamState.FAILED:
            if reason and reason != self.reason:
                self.reason = reason
                self.history.append({"state": self.state.value, "reason": reason})
            return self.state
        previous = self.state
        self.state = StreamState.FAILED
        self.reason = reason
        self.history.append(
            {"from": previous.value, "state": StreamState.FAILED.value, "reason": reason}
        )
        return self.state

    def snapshot(self) -> dict[str, object]:
        """Return a serialisable summary."""

        with self._lock:
            return {
                "role": self.role,
                "state": self.state.value,
                "reason": self.reason,
                "history": list(self.history),
            }

    def reset(self) -> None:
        """Return to INIT (used by tests)."""

        with self._lock:
            self.state = StreamState.INIT
            self.reason = None
            self.history.clear()
