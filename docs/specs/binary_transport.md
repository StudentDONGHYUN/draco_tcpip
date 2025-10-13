# Draco Binary Transport Header

The TCP transport used by `stream_client` and `stream_server` now shares a single
binary framing format. Every message on the wire starts with the fixed header
below:

| Field           | Type  | Description |
|-----------------|-------|-------------|
| MAGIC           | 4s    | Always `DRTC` |
| version         | u8    | Currently `1`; mismatches are rejected |
| flags           | u8    | Bitfield (see below) |
| type            | u8    | `1=DATA`, `2=ACK`, `3=ERROR`, `4=HEARTBEAT` |
| reserved        | u8    | Reserved for future use (`0x45` denotes EOF) |
| sequence        | u32   | Frame sequence (use `0xFFFFFFFF` when absent) |
| name_length     | u16   | UTF-8 name length |
| payload_length  | u32   | Payload byte length |

The payload that follows is always the application data. DATA messages contain
pure Draco bytes, ACK/ERROR frames use small UTF-8 JSON payloads, and
HEARTBEAT messages may use an empty payload. EOF is encoded as a HEARTBEAT
message with `reserved=0x45` and an empty body.

## Flags

- `0x01` – `FLAGS_FRAGMENTED`: Payload contains a fragment metadata header.
- `0x02` – `FLAGS_FRAGMENT_START`: First fragment of the sequence.
- `0x04` – `FLAGS_FRAGMENT_END`: Final fragment of the sequence.

When fragmentation is active, the payload starts with a 12-byte metadata block
(`!III`) carrying `total_length`, `offset`, and `chunk_length`. The remainder of
the payload is the raw Draco fragment. Receivers accumulate fragments per
sequence and hand a byte-for-byte buffer to the decoder only after the final
fragment arrives.

## Control Payloads

- **ACK** – `{"seq": <int>}` (empty payload allowed for compatibility).
- **ERROR** – `{"seq": <int>, "msg": "human-readable detail", "code": "INTERNAL_ERROR"}`
  The `code` field is optional; the client defaults to `INTERNAL_ERROR`.
- **HEARTBEAT** – empty payload.

Legacy peers that respond with plaintext errors are still accepted: the client
logs a single warning and continues processing.

## Fragmentation Semantics

`--tx-fragment-size=0` disables fragmentation. When the value is positive, the
client emits fragments whose `payload_length` does not exceed the configured
budget. ACKs are emitted only after the full frame is reconstructed, ensuring
one control acknowledgement per logical frame.

EOF handshakes still use the control channel. When both sides drain their
queues, they emit an EOF message followed by `shutdown(SHUT_WR)` to close the
TCP stream gracefully.

