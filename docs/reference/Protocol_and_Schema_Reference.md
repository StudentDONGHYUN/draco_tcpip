# Protocol and Schema Reference
Defines the control-plane messages, state machine, and telemetry schema that govern Draco Roundtrip streaming sessions.
_Last updated: 2025-03-15_

**Sections**
- [Control-Plane Messages](#control-plane-messages)
- [Session State Machine](#session-state-machine)
- [Timing and Fragmentation Rules](#timing-and-fragmentation-rules)
- [Telemetry Schema](#telemetry-schema)
- [Validation Checklist](#validation-checklist)

## Control-Plane Messages
| Code (hex) | Symbol | Purpose | Payload |
|------------|--------|---------|---------|
| `0x01` | `ACK` | Confirms the receiver accepted a data frame. | 8-byte unsigned sequence (big-endian). |
| `0x02` | `HEARTBEAT` | Indicates the sender is alive during idle periods. | Optional 8-byte monotonic timestamp. |
| `0x03` | `EOF` | Signals the sender finished transmitting all frames. | None. |
| `0x04` | `ERROR` | Reports abnormal termination. | 1-byte error code + UTF-8 message. |

### Error Codes
| Code | Identifier | Description |
|------|------------|-------------|
| `0` | `NONE` | Reserved. |
| `1` | `PROTOCOL_VIOLATION` | Invalid headers or state transition. |
| `2` | `TIMEOUT` | ACK/HEARTBEAT exceeded timeout budget. |
| `3` | `INTERNAL_ERROR` | Encoder/decoder failures. |
| `4` | `SHUTDOWN` | Operator-initiated graceful stop. |

## Session State Machine
States progress `INIT → HANDSHAKING → STREAMING → DRAINING → TERMINATED`, with `FAILED` reachable from any state when errors occur.

1. `INIT` → `HANDSHAKING`: TCP link established; first heartbeat or frame must follow within 1 s.
2. `HANDSHAKING` → `STREAMING`: First data frame or ACK received.
3. `STREAMING` → `DRAINING`: Sender issues `EOF` and waits for remaining ACKs.
4. `DRAINING` → `TERMINATED`: All frames acknowledged, queues empty (`pending=0`).
5. Any state → `FAILED`: Error message, timeout, or internal failure.

During shutdown both sides emit structured logs summarising pending queues, RTT, and latency percentiles. Sessions entering `FAILED` should stop sending further data or control messages.

## Timing and Fragmentation Rules
- `ACK_TIMEOUT_S = 0.5`: Initial ACK deadline before RTT EMA adjusts.
- `HEARTBEAT_INTERVAL_S = 2.0`: Send heartbeat if no data frames within the interval.
- `HEARTBEAT_LIVENESS_S = 6.0`: Missing heartbeats beyond this threshold triggers `ERROR` with code `TIMEOUT`.
- `CONTROL_POLL_INTERVAL_S = 0.05`: Polling cadence for control sockets.
- Fragmentation: When `--tx-fragment-size` > 0, split payloads into 256–1400 B chunks with a `more_fragments` flag. Receivers assemble fragments before acknowledging.

## Telemetry Schema
Telemetry JSON must include the following fields (schema version `1.0.0`):

| Field | Type | Notes |
|-------|------|-------|
| `schema_version` | string | Always `1.0.0`. |
| `schema_doc` | string | Should reference this document path. |
| `session.id` | string | Unique session identifier. |
| `session.role` | string | `"client"` or `"server"`. |
| `session.transport` | string | Mirrors `--transport` flag. |
| `session.protocol` | string | `legacy` or `binary`. |
| `session.fragment_size` | integer | Value of `--tx-fragment-size`. |
| `session.socket_buffer_autotune` | boolean | Mirrors CLI flag. |
| `session.started_at_ns` / `session.ended_at_ns` | integer | Monotonic timestamps (nanoseconds). |
| `session.state` | string | `TERMINATED` or `FAILED`. |
| `session.error_code` / `session.error_message` | mixed | Required when `state = FAILED`; codes align with table above. |
| `metrics.latency_ms` | object | Contains `p50`, `p95`, `p99`, and optional histogram. |
| `metrics.rtt_ms` | object | Same fields as latency. |
| `metrics.ack_latency_ms` | object | Server processing delay before ACK. |
| `metrics.throughput_mbps` | object | `avg` and `peak`. |
| `metrics.queues` | object | `capture_max`, `encode_max`, `decode_max`, and current `pending`. |
| `metrics.frames` | object | `sent`, `acked`, `dropped`, `skipped`. |

Telemetry writers must validate against `docs/specs/telemetry_schema.json` before persisting files. Invalid telemetry should abort with `ERROR` code `INTERNAL_ERROR`.

## Validation Checklist
- [ ] Binary protocol headers conform to message table above.
- [ ] Heartbeat and ACK timers honour timeout constants and CLI overrides in the [Configuration Reference](../reference/Configuration_Reference.md).
- [ ] Telemetry JSON contains required fields and passes schema validation.
- [ ] Shutdown logs record `pending` counts and p50/p95/p99 metrics prior to closing sockets.
- [ ] Fragmentation obeys 256–1400 B bounds when enabled.
