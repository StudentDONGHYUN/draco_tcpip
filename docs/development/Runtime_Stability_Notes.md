# Runtime Stability Notes
Hardening summary for the Python streaming stack to ensure graceful degradation when the server or control plane encounters faults.
_Last updated: 2025-03-15_

**Sections**
- [Client (`stream_client.py`)](#client-stream_clientpy)
- [Shared Memory](#shared-memory)
- [Server (`stream_server.py`)](#server-stream_serverpy)
- [Offline Pipeline](#offline-pipeline)
- [Testing](#testing)

## Client (`stream_client.py`)
- Tracks explicit lifecycle states **OK → DEGRADED → CLOSING**; transitions are logged and shutdown summaries export queue and latency metrics.
- `network_sender` wakes every 500 ms while waiting on the inflight condition so heartbeat/stop signals cannot deadlock the loop and it honours `HeartbeatWatch` timeouts.
- `reply_consumer` handles `CancelledError` gracefully by draining reordering buffers, clearing pending ACK slots, and emitting tail statistics.
- New `--spool-gc-window=N` flag bounds remembered spool entries when scanning filesystem transports and prunes processed files to control RSS.
- Shutdown prints structured JSON with queue depths, latency percentiles, pending counts, and session state; the same data surfaces in telemetry JSON through `session_overrides`.

## Shared Memory
- Segments are always unlinked if `sendall` fails, with an optional background janitor (disabled by default) that retries unlinking when eager cleanup is insufficient.

## Server (`stream_server.py`)
- Sends ACKs and heartbeats using a bounded exponential backoff helper. Failure marks the control path as down, drains queued frames, and logs degradation instead of dropping payloads silently.

## Offline Pipeline
- `bag_to_ply` saver stage is monitored by a reader thread that captures the last 1 KB of stdout; `--saver-timeout` (default 180 s) aborts stalled runs and prints diagnostics on abnormal exits.
- Early EOF events map to `stream_end` ensuring the pipeline terminates cleanly.

## Testing
- Unit tests cover spool watcher pruning behaviour and shared memory publisher cleanup when `sendall` raises.
