# Layout Profiles and Data Directories

`draco_roundtrip.utils.config` centralizes the way streaming tools and batch
pipelines resolve their working directories. This document summarises the
conventions and how to customise them.

## Default layout

Without any extra configuration the helpers derive a data root from the
following precedence order:

1. `--data-root` CLI argument.
2. `data_root` defined in the active layout profile.
3. `DRACO_DATA_ROOT` environment variable.
4. Nearest `data/` directory relative to the package or the current working
   tree (created on demand).

Under the resolved data root the following sub-directories are created as
needed:

| Key                   | Default sub-directory |
| --------------------- | --------------------- |
| `ply_stream`          | `ply_stream/`         |
| `client_work`         | `client_tmp/`         |
| `decoded_from_server` | `decoded_from_server/`|
| `ply_raw`             | `ply_raw/`            |
| `draco_out`           | `draco_out/`          |
| `decoded_tmp`         | `tmp_decoded_ply/`    |
| `results`             | `results/`            |
| `server_work`         | `server_tmp/`         |
| `ros_logs`            | `logs/ros/`           |

`stream_client` consumes the `ply_stream`, `client_work`, and
`decoded_from_server` keys, while `offline_pipeline` uses `ply_raw`,
`draco_out`, `decoded_tmp`, and `results`. The `ros_logs` alias is reserved for
실험 로그 수집(`stream_collect_logs`) 시 ROS 2 로그 스냅샷을 보관하는 위치를 가리킵니다.

## Layout profiles

Profiles live under `configs/` and can be authored in JSON or YAML. The helper
searches the following locations in order:

1. `--layout-profile` path if it is absolute.
2. Directories specified by `DRACO_CONFIG_ROOT`.
3. Installed package shares (`<pkg>/configs/`).
4. Repository-local `configs/` directories.

A minimal JSON profile looks like this:

```json
{
  "data_root": "../experiment_data",
  "directories": {
    "ply_stream": "stream_cache",
    "client_work": "/var/tmp/draco_client"
  },
  "qos_override": "qos/custom_client.yaml"
}
```

* `data_root` may be absolute or relative to the profile file.
* Each entry under `directories` can be absolute or relative to the resolved
  data root.
* `qos_override` points to a QoS override file relative to the profile or the
  configuration search paths.

A YAML profile uses the same field names; `PyYAML` must be available at runtime
for `.yaml` or `.yml` files.

## QoS override resolution

`resolve_qos_override()` now accepts both explicit overrides and a
`ProfileConfig`. When provided, the helper prefers:

1. `--qos-override` if supplied on the command line.
2. `qos_override` from the active layout profile.
3. The first `qos_override.yaml` found within the configuration search paths.

This keeps ROS 2 QoS defaults, stream directories, and batch artefacts aligned
across command line tools, ROS nodes, and shell scripts.
