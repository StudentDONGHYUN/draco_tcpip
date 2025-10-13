# Configuration Reference
Centralises execution profiles, directory layouts, and CLI defaults used by Draco Roundtrip nodes, tools, and launch files.
_Last updated: 2025-03-15_

**Sections**
- [Configuration Discovery Rules](#configuration-discovery-rules)
- [Layout Profiles and Directories](#layout-profiles-and-directories)
- [CLI Flag Matrix](#cli-flag-matrix)
- [Usage Examples](#usage-examples)
- [Related Documents](#related-documents)

## Configuration Discovery Rules
`draco_roundtrip.utils.config` loads profiles and QoS overrides using the following precedence:
1. Explicit CLI argument (`--layout-profile`, `--qos-override`).
2. Paths relative to the active profile file.
3. Directories listed in `DRACO_CONFIG_ROOT`.
4. Installed package share directories (`<pkg>/configs/`).
5. Repository `configs/` directory or the nearest `data/` root.

Helper functions ensure directories exist (`ensure_directory`) and normalise paths even when the package is installed in a shallow site-packages layout. Launch files in `slam_stream_bridge` reuse the same helpers so ROS 2 nodes and CLI tools resolve profiles identically.

## Layout Profiles and Directories
Layout profiles define a canonical experiment filesystem. Keys map to subdirectories under the resolved `data_root`.

| Key | Default Subdirectory | Typical Usage |
|-----|----------------------|---------------|
| `ply_stream` | `ply_stream/` | Streaming client PLY cache. |
| `client_work` | `client_tmp/` | Temporary Draco encoder workspace. |
| `decoded_from_server` | `decoded_from_server/` | Server responses written by the client. |
| `ply_raw` | `ply_raw/` | Offline pipeline raw PLY output. |
| `draco_out` | `draco_out/` | Batch Draco archives. |
| `decoded_tmp` | `tmp_decoded_ply/` | Scratch area for decode jobs. |
| `results` | `results/` | Experiment manifests and metrics. |
| `server_work` | `server_tmp/` | Server-side temporary files. |
| `ros_logs` | `logs/ros/` | ROS 2 log snapshots collected post-run. |

Profile authoring tips:
- JSON and YAML profiles share the same schema. Relative paths are resolved against the profile location.
- `data_root` falls back to `DRACO_DATA_ROOT` or the nearest `data/` directory when not provided.
- QoS overrides follow the same search rules via `resolve_qos_override`.

## CLI Flag Matrix
| Flag | Client Default | Server Default | Description | Primary Reference |
|------|----------------|----------------|-------------|-------------------|
| `--transport {tcp,quic,udp_fec}` | `tcp` | `tcp` | Selects the transport backend. Only `tcp` is active today; other values raise `NotImplementedError`. | [Architectural Design and Plan](../architecture/Architectural_Design_and_Plan.md) |
| `--protocol {legacy,binary}` | `binary` | `binary` | Chooses framing format; `binary` uses MTU-safe headers and bounded queues per the control-plane contract. | [Protocol and Schema Reference](../reference/Protocol_and_Schema_Reference.md) |
| `--tx-fragment-size` | `0` (disabled) | `0` | MTU-safe fragmentation size in bytes. Valid range 256–1400. | [Protocol and Schema Reference](../reference/Protocol_and_Schema_Reference.md) |
| `--ack-timeout` | `0.5` s | n/a | Initial ACK timeout before RTT EMA converges. | [Protocol and Schema Reference](../reference/Protocol_and_Schema_Reference.md) |
| `--ack-timeout-min` | `0.5` s | n/a | Lower bound for adaptive ACK timeout. | [Protocol and Schema Reference](../reference/Protocol_and_Schema_Reference.md) |
| `--ack-timeout-max` | `2.0` s | n/a | Upper bound for adaptive ACK timeout. | [Protocol and Schema Reference](../reference/Protocol_and_Schema_Reference.md) |
| `--ack-timeout-strikes` | `3` | n/a | Consecutive timeout strikes before declaring failure. | [Protocol and Schema Reference](../reference/Protocol_and_Schema_Reference.md) |
| `--socket-buffer-autotune` | `False` | `False` | Requests kernel buffer autotuning (`SO_RCVBUF`/`SO_SNDBUF` = 0). | [Architectural Design and Plan](../architecture/Architectural_Design_and_Plan.md) |
| `--metrics-out` | `artifacts/perf/client_latest.json` | `artifacts/perf/server_latest.json` | Path for telemetry JSON output that must satisfy the schema. | [Protocol and Schema Reference](../reference/Protocol_and_Schema_Reference.md) |

When introducing new flags, update this matrix and align CLI defaults, help text, and regression docs before merging code changes.

## Usage Examples
Configure a client run with explicit layout profile and QoS override:
```bash
ros2 run draco_roundtrip stream_client \
  --bag data/bags/sample.bag \
  --topic /sensing/lidar/top/pointcloud \
  --prefix sample \
  --layout-profile client.profile.yaml \
  --data-root ./data \
  --qos-override configs/qos_override.yaml
```
Bringup launch wraps the same helpers, so providing `layout_profile:=client.profile.yaml` and `qos_override:=configs/qos_override.yaml` forwards the resolved paths to both client and server nodes.

## Related Documents
- [Protocol and Schema Reference](../reference/Protocol_and_Schema_Reference.md)
- [Architectural Design and Plan](../architecture/Architectural_Design_and_Plan.md)
- [Development Process](../development/Development_Process.md)
- [User Guide](../guides/User_Guide.md)
