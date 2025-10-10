# Draco Roundtrip Utility Usage Reference

`draco_roundtrip.utils` exposes the compatibility surface that higher level nodes,
CLI shims, and developer tooling must consume. This document records where each
shared helper is referenced so future refactors can audit import paths quickly.

## Canonical Consumers

| Utility module | Key symbols | Primary consumers | Notes |
| --- | --- | --- | --- |
| `draco_roundtrip.utils.protocol` | `Message`, `send_message`, `recv_message`, `ConnectionClosed` | `nodes/stream_client.py`, `nodes/stream_server.py` | Both the streaming client and server rely on the shim so the TCP framing layer stays in sync with protocol updates. |
| `draco_roundtrip.utils.ply_io` | `collect_matching_pairs`, `load_points`, `load_points_from_bytes` | `nodes/stream_client.py`, `tools/monitor.py`, `tools/replay.py` | Streaming importers alias the helpers to legacy names (`load_xyz*`) to keep existing code readable while ensuring consistent I/O behaviour. |
| `draco_roundtrip.utils.metrics` | `compute_basic_metrics`, `sample_indices` | `nodes/stream_client.py`, `tools/monitor.py` | Metrics printed in live streams and offline monitoring resolve through the shim so SciPy optional-dependency guards are centralised. |
| `draco_roundtrip.utils.executable` | `resolve_executable` | `nodes/stream_server.py` | Decoder resolution honours environment overrides and common fallbacks; additional CLI wrappers should prefer this helper. |

When introducing new consumers, import from the shim modules above rather than
directly from `draco_roundtrip.net`, `draco_roundtrip.io`, or
`draco_roundtrip.analysis`. Doing so allows the shims to absorb future
organisation changes without touching every caller.
