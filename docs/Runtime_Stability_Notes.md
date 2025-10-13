# Runtime Stability Notes

This release hardens the Python streaming stack to degrade gracefully when the
server or control plane misbehaves.

## Client (`stream_client.py`)

* The client now tracks an explicit session lifecycle with the states
  **OK → DEGRADED → CLOSING**.  Transitions are logged and the shutdown summary
  exports the final state and reason alongside latency metrics.
* `network_sender` adds a 500 ms wake-up on the inflight condition wait so that
  heartbeat or stop signals break deadlocks.  The sender honours the shared
  `HeartbeatWatch` timeout and refuses to send EOF when the session is already
  degraded.
* `reply_consumer` cancels cleanly: on `CancelledError` it drains reordered
  results, clears pending ACK slots, and reports tail statistics.
* A new command-line flag `--spool-gc-window=N` bounds the remembered spool
  entries when scanning the filesystem transport.  Processed files are pruned
  from the `_known` set to avoid long-run RSS growth.
* Shutdown prints a structured JSON line that includes queue depths, latency
  percentiles, pending counts, and the session state.  The same information is
  exposed through the telemetry JSON via `session_overrides`.

## Shared Memory (`shared_memory/channel.py`)

* Shared memory segments are always unlinked if `sendall` fails.  An optional
  background janitor (disabled by default) retries unlinking should the eager
  cleanup fail.

## Server (`stream_server.py`)

* ACKs and heartbeats are sent through a bounded exponential backoff helper.
  When retries fail the server marks the control path as down, drains queued
  frames, and logs the degradation rather than dropping payloads silently.

## Offline Pipeline (`offline_pipeline.py`)

* The saver stage (`bag_to_ply`) is monitored by a reader thread that captures
  the last 1 KB of stdout.  A new `--saver-timeout` option (default 180 s)
  aborts stalled runs and the diagnostic tail is printed for abnormal exits.
* Early EOF is treated as `stream_end`, ensuring the pipeline terminates with a
  clear status instead of hanging indefinitely.

## Testing

* Unit tests cover the spool watcher’s pruning behaviour and the shared memory
  publisher’s unlink guarantees when `sendall` raises.
