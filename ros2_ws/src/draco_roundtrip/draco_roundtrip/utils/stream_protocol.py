"""Control-plane helpers aligned with docs/contracts/control_plane_contract.md.

본 모듈은 바이너리 헤더, 제어 메시지 코드, 상태 머신 및 프래그먼트 유틸리티를
제공해 클라이언트/서버 구현이 SSOT 규격을 일관되게 준수하도록 돕는다.
"""

from __future__ import annotations

import enum
import struct
import time
from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Mapping

__all__ = [
    "ControlCode",
    "ErrorCode",
    "ControlState",
    "ControlPlane",
    "ControlPlaneError",
    "DATA_CHANNEL",
    "CONTROL_CHANNEL",
    "FrameHeader",
    "FrameFragment",
    "ACK_TIMEOUT_NS",
    "CONTROL_POLL_INTERVAL",
    "HEARTBEAT_INTERVAL_NS",
    "HEARTBEAT_LIVENESS_NS",
    "MIN_FRAGMENT_SIZE",
    "MAX_FRAGMENT_SIZE",
    "ACK_PAYLOAD_STRUCT",
    "FRAME_HEADER_SIZE",
    "pack_frame_header",
    "unpack_frame_header",
    "iter_fragments",
    "validate_fragment_size",
    "FrameAddress",
    "encode_frame_address",
    "decode_frame_address",
]

# 제어 평면 상수 (docs/contracts/control_plane_contract.md 참고)
FRAME_VERSION = 1
FLAG_CONTROL = 0x01
FLAG_MORE_FRAGMENTS = 0x02
_HEADER_STRUCT = struct.Struct("!BBHQ")  # version, flags, control_code, sequence
_NO_SEQUENCE = 0xFFFFFFFFFFFFFFFF
FRAME_HEADER_SIZE = _HEADER_STRUCT.size

ACK_TIMEOUT_NS = int(0.5 * 1_000_000_000)  # 500ms
HEARTBEAT_INTERVAL_NS = int(2.0 * 1_000_000_000)  # 2s
HEARTBEAT_LIVENESS_NS = int(6.0 * 1_000_000_000)  # 6s
CONTROL_POLL_INTERVAL = 0.05

MIN_FRAGMENT_SIZE = 256
MAX_FRAGMENT_SIZE = 1400

# ACK 페이로드는 8바이트 시퀀스를 big-endian으로 담는다.
ACK_PAYLOAD_STRUCT = struct.Struct("!Q")


class ControlCode(enum.IntEnum):
    """제어 메시지 코드 (SSOT 참조)."""

    ACK = 0x01
    HEARTBEAT = 0x02
    EOF = 0x03
    ERROR = 0x04


class ErrorCode(enum.IntEnum):
    """오류 코드 정의 (docs/contracts/control_plane_contract.md)."""

    NONE = 0
    PROTOCOL_VIOLATION = 1
    TIMEOUT = 2
    INTERNAL_ERROR = 3
    SHUTDOWN = 4


class ControlState(enum.Enum):
    """제어 평면 상태 머신 단계."""

    INIT = "INIT"
    HANDSHAKING = "HANDSHAKING"
    STREAMING = "STREAMING"
    DRAINING = "DRAINING"
    TERMINATED = "TERMINATED"
    FAILED = "FAILED"


@dataclass(slots=True, frozen=True)
class FrameHeader:
    """docs/contracts/control_plane_contract.md에서 정의한 프레임 헤더 표현."""

    version: int
    is_control: bool
    more_fragments: bool
    control_code: ControlCode | None
    sequence: int | None


@dataclass(slots=True)
class FrameFragment:
    """docs/contracts/control_plane_contract.md에 명시된 프래그먼트 구조."""

    sequence: int | None
    payload: bytes
    control_code: ControlCode | None = None
    more_fragments: bool = False

    def header(self) -> FrameHeader:
        return FrameHeader(
            version=FRAME_VERSION,
            is_control=self.control_code is not None,
            more_fragments=self.more_fragments,
            control_code=self.control_code,
            sequence=self.sequence,
        )


def pack_frame_header(header: FrameHeader) -> bytes:
    """docs/contracts/control_plane_contract.md 명세에 따라 헤더를 직렬화한다."""

    flags = 0
    control_code_value = 0
    if header.is_control:
        flags |= FLAG_CONTROL
        if header.control_code is None:
            raise ValueError("control frames must have a control code")
        control_code_value = int(header.control_code)
    if header.more_fragments:
        flags |= FLAG_MORE_FRAGMENTS
    sequence = header.sequence if header.sequence is not None else _NO_SEQUENCE
    return _HEADER_STRUCT.pack(
        header.version,
        flags,
        control_code_value,
        sequence,
    )


def unpack_frame_header(payload: bytes) -> FrameHeader:
    """docs/contracts/control_plane_contract.md 규격의 헤더를 역직렬화한다."""

    if len(payload) < _HEADER_STRUCT.size:
        raise ValueError("payload shorter than frame header")
    version, flags, control_code_value, sequence = _HEADER_STRUCT.unpack_from(payload)
    if version != FRAME_VERSION:
        raise ValueError(f"unsupported frame version {version}")
    is_control = bool(flags & FLAG_CONTROL)
    more_fragments = bool(flags & FLAG_MORE_FRAGMENTS)
    control_code: ControlCode | None = None
    if is_control:
        try:
            control_code = ControlCode(control_code_value)
        except ValueError as exc:
            raise ValueError(f"unknown control code {control_code_value}") from exc
    sequence_value = None if sequence == _NO_SEQUENCE else int(sequence)
    return FrameHeader(
        version=version,
        is_control=is_control,
        more_fragments=more_fragments,
        control_code=control_code,
        sequence=sequence_value,
    )


def iter_fragments(
    payload: bytes,
    *,
    sequence: int,
    fragment_size: int,
) -> Iterator[FrameFragment]:
    """docs/contracts/control_plane_contract.md에 정의된 MTU 안전 조각을 생성한다."""

    if fragment_size <= 0:
        yield FrameFragment(sequence=sequence, payload=payload, more_fragments=False)
        return
    fragment_size = validate_fragment_size(fragment_size)
    if fragment_size <= _HEADER_STRUCT.size:
        raise ValueError("fragment size too small for frame header")
    chunk_payload = fragment_size - _HEADER_STRUCT.size
    total = len(payload)
    offset = 0
    while offset < total:
        end = min(offset + chunk_payload, total)
        chunk = payload[offset:end]
        offset = end
        more = offset < total
        yield FrameFragment(
            sequence=sequence,
            payload=chunk,
            more_fragments=more,
        )


def validate_fragment_size(value: int) -> int:
    """docs/contracts/control_plane_contract.md의 프래그먼트 범위를 강제한다."""

    if value == 0:
        return 0
    if value < MIN_FRAGMENT_SIZE or value > MAX_FRAGMENT_SIZE:
        raise ValueError(
            f"fragment size {value} outside supported range "
            f"[{MIN_FRAGMENT_SIZE}, {MAX_FRAGMENT_SIZE}]"
        )
    return value


class ControlPlaneError(RuntimeError):
    """docs/contracts/control_plane_contract.md 상태 머신 위반 시 발생."""


class ControlPlane:
    """docs/contracts/control_plane_contract.md에 정의된 상태 머신."""

    _VALID_TRANSITIONS: Mapping[ControlState, tuple[ControlState, ...]] = {
        ControlState.INIT: (ControlState.HANDSHAKING,),
        ControlState.HANDSHAKING: (ControlState.STREAMING, ControlState.FAILED),
        ControlState.STREAMING: (ControlState.DRAINING, ControlState.FAILED),
        ControlState.DRAINING: (ControlState.TERMINATED, ControlState.FAILED),
        ControlState.TERMINATED: (),
        ControlState.FAILED: (),
    }

    def __init__(self, *, role: str) -> None:
        self.role = role
        self.state = ControlState.INIT
        self.started_at_ns: int | None = None
        self.ended_at_ns: int | None = None
        self._pending_deadlines: Dict[int, int] = {}
        self._last_heartbeat_ns: int | None = None
        self.error_code: ErrorCode = ErrorCode.NONE
        self.error_message: str | None = None

    # 상태 전이 -----------------------------------------------------------------
    def on_connected(self, now_ns: int | None = None) -> None:
        self._transition(ControlState.HANDSHAKING)
        timestamp = now_ns if now_ns is not None else time.monotonic_ns()
        self.started_at_ns = timestamp
        self._last_heartbeat_ns = timestamp

    def on_first_data(self) -> None:
        if self.state not in (ControlState.HANDSHAKING, ControlState.STREAMING):
            raise ControlPlaneError(f"cannot enter STREAMING from {self.state}")
        self._transition(ControlState.STREAMING)

    def on_frame_sent(self, sequence: int, *, now_ns: int | None = None) -> None:
        if self.state not in (ControlState.STREAMING, ControlState.DRAINING):
            self.on_first_data()
        deadline = (now_ns if now_ns is not None else time.monotonic_ns()) + ACK_TIMEOUT_NS
        self._pending_deadlines[sequence] = deadline

    def on_ack(self, sequence: int) -> None:
        try:
            del self._pending_deadlines[sequence]
        except KeyError:
            raise ControlPlaneError(f"ack for unknown sequence {sequence}") from None
        if self.state == ControlState.DRAINING and not self._pending_deadlines:
            self._transition(ControlState.TERMINATED)

    def on_eof_sent(self) -> None:
        if self.state not in (ControlState.STREAMING, ControlState.DRAINING):
            raise ControlPlaneError(f"cannot send EOF while in {self.state}")
        self._transition(ControlState.DRAINING)

    def on_eof_received(self) -> None:
        if self.state in (ControlState.INIT, ControlState.HANDSHAKING):
            raise ControlPlaneError("EOF received before streaming began")
        if self.state == ControlState.STREAMING:
            self._transition(ControlState.DRAINING)
        if self.state == ControlState.DRAINING and not self._pending_deadlines:
            self._transition(ControlState.TERMINATED)

    def on_error(self, code: ErrorCode, message: str | None = None) -> None:
        self.error_code = code
        self.error_message = message
        self._transition(ControlState.FAILED)

    def on_shutdown(self) -> None:
        if self.state not in (ControlState.TERMINATED, ControlState.FAILED):
            self._transition(ControlState.FAILED)
        self.ended_at_ns = time.monotonic_ns()

    # 하트비트/타임아웃 ---------------------------------------------------------
    def on_heartbeat(self, *, now_ns: int | None = None) -> None:
        timestamp = now_ns if now_ns is not None else time.monotonic_ns()
        self._last_heartbeat_ns = timestamp
        if self.state == ControlState.HANDSHAKING:
            self._transition(ControlState.STREAMING)

    def expired_sequences(self, *, now_ns: int | None = None) -> List[int]:
        if not self._pending_deadlines:
            return []
        current = now_ns if now_ns is not None else time.monotonic_ns()
        expired = [seq for seq, deadline in self._pending_deadlines.items() if current >= deadline]
        for seq in expired:
            del self._pending_deadlines[seq]
        return expired

    def heartbeat_timed_out(self, *, now_ns: int | None = None) -> bool:
        if self._last_heartbeat_ns is None:
            return False
        current = now_ns if now_ns is not None else time.monotonic_ns()
        return current - self._last_heartbeat_ns >= HEARTBEAT_LIVENESS_NS

    # 속성/도우미 ----------------------------------------------------------------
    @property
    def pending(self) -> int:
        return len(self._pending_deadlines)

    def _transition(self, target: ControlState) -> None:
        if target == self.state:
            return
        allowed = self._VALID_TRANSITIONS[self.state]
        if target not in allowed:
            raise ControlPlaneError(f"illegal transition {self.state} → {target}")
        self.state = target
        if target in (ControlState.TERMINATED, ControlState.FAILED):
            self.ended_at_ns = time.monotonic_ns()


# ------------------------------------------------------------------------------
# 레거시 주소 유틸리티 (기존 코드와 호환용)
# ------------------------------------------------------------------------------
_DATA_DELIM = "|"
_CHANNEL_DELIM = "/"
DATA_CHANNEL = "data"
CONTROL_CHANNEL = "control"


@dataclass(slots=True, frozen=True)
class FrameAddress:
    """SSOT 레거시 주소 규칙(`docs/contracts/control_plane_contract.md`) 구현."""

    channel: str
    sequence: int | None
    name: str

    @property
    def is_control(self) -> bool:
        return self.channel != DATA_CHANNEL


def encode_frame_address(
    sequence: int | None,
    name: str,
    *,
    channel: str = DATA_CHANNEL,
) -> str:
    """채널/시퀀스를 docs/contracts/control_plane_contract.md 규칙으로 인코딩."""

    base = name or ""
    token = base
    if sequence is not None:
        token = f"{sequence}{_DATA_DELIM}{base}" if base else f"{sequence}{_DATA_DELIM}"
    channel = channel or DATA_CHANNEL
    if not token:
        return channel
    return f"{channel}{_CHANNEL_DELIM}{token}" if channel else token


def decode_frame_address(raw: str | None) -> FrameAddress:
    """docs/contracts/control_plane_contract.md 규칙으로 주소 메타데이터를 복원."""

    if not raw:
        return FrameAddress(channel=DATA_CHANNEL, sequence=None, name="")
    channel = DATA_CHANNEL
    token = raw
    if _CHANNEL_DELIM in raw:
        channel, token = raw.split(_CHANNEL_DELIM, 1)
        channel = channel or DATA_CHANNEL
    sequence: int | None = None
    name = token
    if _DATA_DELIM in token:
        prefix, suffix = token.split(_DATA_DELIM, 1)
        try:
            sequence = int(prefix)
            name = suffix
        except ValueError:
            sequence = None
            name = token
    return FrameAddress(channel=channel or DATA_CHANNEL, sequence=sequence, name=name)
