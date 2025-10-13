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
    "ResponseHeader",
    "ACK_TIMEOUT_NS",
    "CONTROL_POLL_INTERVAL",
    "HEARTBEAT_INTERVAL_NS",
    "HEARTBEAT_LIVENESS_NS",
    "MIN_FRAGMENT_SIZE",
    "MAX_FRAGMENT_SIZE",
    "ACK_PAYLOAD_STRUCT",
    "DATA_KIND_DRACO",
    "CONTENT_TYPE_DRACO",
    "RESPONSE_KIND_DECODED_AND_METRICS",
    "iter_fragments",
    "validate_fragment_size",
    "FrameAddress",
    "encode_frame_address",
    "decode_frame_address",
    "pack_response_header",
    "unpack_response_header",
    "parse_legacy_request_payload",
    "compose_response_payload",
    "parse_response_payload",
    "LEGACY_DATA_HEADER_SIZE",
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

DATA_KIND_DRACO = 0x10
CONTENT_TYPE_DRACO = 0x01

RESPONSE_KIND_DECODED_AND_METRICS = 0x21

_LEGACY_DATA_HEADER_STRUCT = struct.Struct("!BIQIB")
LEGACY_DATA_HEADER_SIZE = _LEGACY_DATA_HEADER_STRUCT.size
_RESPONSE_HEADER_STRUCT = struct.Struct("!BIQI IH".replace(" ", ""))


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
    """Fragment chunk metadata used by the binary data plane."""

    sequence: int
    payload: bytes
    index: int = 0
    total: int = 1
    frame_payload_len: int | None = None

    @property
    def more_fragments(self) -> bool:
        return self.index < self.total - 1


@dataclass(slots=True, frozen=True)
class ResponseHeader:
    """Binary response header containing decoded payload and metrics layout."""

    kind: int
    sequence: int
    timestamp_ns: int
    decoded_len: int
    metrics_len: int
    decode_ms: int


def iter_fragments(
    payload: bytes,
    *,
    sequence: int,
    fragment_size: int,
) -> Iterator[FrameFragment]:
    """Generate payload chunks honouring the configured fragment size."""

    total_len = len(payload)
    if fragment_size <= 0 or total_len <= fragment_size:
        yield FrameFragment(
            sequence=sequence,
            payload=payload,
            index=0,
            total=1,
            frame_payload_len=total_len,
        )
        return
    fragment_size = validate_fragment_size(fragment_size)
    if total_len == 0:
        yield FrameFragment(sequence=sequence, payload=b"", index=0, total=1, frame_payload_len=0)
        return
    total_fragments = max(1, (total_len + fragment_size - 1) // fragment_size)
    offset = 0
    index = 0
    while offset < total_len:
        end = min(offset + fragment_size, total_len)
        chunk = payload[offset:end]
        yield FrameFragment(
            sequence=sequence,
            payload=chunk,
            index=index,
            total=total_fragments,
            frame_payload_len=total_len,
        )
        offset = end
        index += 1


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
        # Track pending ACK deadlines as ``sequence -> (deadline_ns, timeout_ns)`` so we
        # can reschedule late ACKs without dropping state.  This lets the client remain
        # responsive to delayed control messages instead of marking the frame as lost
        # immediately after the first timeout.
        self._pending_deadlines: Dict[int, tuple[int, int]] = {}
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

    def on_frame_sent(
        self,
        sequence: int,
        *,
        now_ns: int | None = None,
        ack_timeout_ns: int | None = None,
    ) -> None:
        if self.state not in (ControlState.STREAMING, ControlState.DRAINING):
            self.on_first_data()
        timeout = ack_timeout_ns if ack_timeout_ns is not None else ACK_TIMEOUT_NS
        timestamp = now_ns if now_ns is not None else time.monotonic_ns()
        self._pending_deadlines[sequence] = (timestamp + timeout, timeout)

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
        expired: list[int] = []
        for sequence, (deadline, timeout) in list(self._pending_deadlines.items()):
            if current >= deadline:
                expired.append(sequence)
                # Re-arm the deadline so we continue tracking late ACKs without
                # dropping the sequence from the pending map.  This avoids
                # ``ControlPlaneError`` on late acknowledgements while still
                # surfacing repeated timeouts to the caller.
                self._pending_deadlines[sequence] = (current + timeout, timeout)
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


def pack_response_header(header: ResponseHeader) -> bytes:
    if header.kind != RESPONSE_KIND_DECODED_AND_METRICS:
        raise ValueError(f"unsupported response kind {header.kind:#x}")
    return _RESPONSE_HEADER_STRUCT.pack(
        header.kind,
        header.sequence & 0xFFFFFFFF,
        header.timestamp_ns & 0xFFFFFFFFFFFFFFFF,
        header.decoded_len & 0xFFFFFFFF,
        header.metrics_len & 0xFFFFFFFF,
        header.decode_ms & 0xFFFF,
    )


def unpack_response_header(buffer: bytes) -> tuple[ResponseHeader, bytes]:
    if len(buffer) < _RESPONSE_HEADER_STRUCT.size:
        raise ValueError("buffer too small for response header")
    parts = _RESPONSE_HEADER_STRUCT.unpack_from(buffer)
    header = ResponseHeader(
        kind=parts[0],
        sequence=parts[1],
        timestamp_ns=parts[2],
        decoded_len=parts[3],
        metrics_len=parts[4],
        decode_ms=parts[5],
    )
    payload = buffer[_RESPONSE_HEADER_STRUCT.size :]
    if len(payload) < header.decoded_len + header.metrics_len:
        raise ValueError("payload truncated for declared decoded/metrics lengths")
    return header, payload


def parse_legacy_request_payload(buffer: bytes) -> tuple[int, int, int, bytes]:
    """Decode the legacy (v1) in-band request header into metadata.

    Returns ``(sequence, timestamp_ns, content_type, payload)`` and validates the
    declared payload length so callers can safely fall back to the unified v2
    frame header without double allocation.
    """

    if len(buffer) < LEGACY_DATA_HEADER_SIZE:
        raise ValueError("buffer too small for legacy data header")
    kind, sequence, ts_ns, payload_len, content_type = _LEGACY_DATA_HEADER_STRUCT.unpack_from(buffer)
    if kind != DATA_KIND_DRACO:
        raise ValueError(f"unexpected legacy data kind {kind:#x}")
    payload = buffer[
        LEGACY_DATA_HEADER_SIZE : LEGACY_DATA_HEADER_SIZE + payload_len
    ]
    if len(payload) != payload_len:
        raise ValueError("legacy payload truncated for declared length")
    return sequence, ts_ns, content_type, payload


def compose_response_payload(
    sequence: int,
    timestamp_ns: int,
    decoded_payload: bytes,
    metrics_json: bytes,
    *,
    decode_ms: float,
) -> tuple[ResponseHeader, bytes]:
    header = ResponseHeader(
        kind=RESPONSE_KIND_DECODED_AND_METRICS,
        sequence=sequence,
        timestamp_ns=timestamp_ns,
        decoded_len=len(decoded_payload),
        metrics_len=len(metrics_json),
        decode_ms=int(round(max(decode_ms, 0.0))),
    )
    packed = pack_response_header(header) + decoded_payload + metrics_json
    return header, packed


def parse_response_payload(buffer: bytes) -> tuple[ResponseHeader, bytes, bytes]:
    header, payload = unpack_response_header(buffer)
    if header.kind != RESPONSE_KIND_DECODED_AND_METRICS:
        raise ValueError(f"unexpected response kind {header.kind:#x}")
    decoded_end = header.decoded_len
    decoded = payload[:decoded_end]
    metrics = payload[decoded_end : decoded_end + header.metrics_len]
    if len(decoded) != header.decoded_len or len(metrics) != header.metrics_len:
        raise ValueError("response payload segments truncated")
    return header, decoded, metrics
