# Draco Roundtrip User Guide
Draco Roundtrip streams LiDAR point clouds over TCP with deterministic control-plane handshakes and shared configuration helpers. This guide sequences setup, streaming, monitoring, and log collection workflows for operators and developers.
_Last updated: 2025-03-15_

**Sections**
- [Environment Setup](#environment-setup)
- [Streaming Operations](#streaming-operations)
- [Monitoring and Validation](#monitoring-and-validation)
- [Log Collection and Post-Run Tasks](#log-collection-and-post-run-tasks)
- [Troubleshooting and Quick Commands](#troubleshooting-and-quick-commands)

## Environment Setup
1. Install ROS 2 Humble and source the environment before building:
   ```bash
   source /opt/ros/humble/setup.bash
   ```
2. Clone the repository and build the workspace with dependencies:
   ```bash
   cd /path/to/draco_tcpip/ros2_ws
   rosdep install --from-paths src --rosdistro humble --ignore-src -y
   colcon build --symlink-install
   source install/setup.bash
   ```
3. Install the Python packages in editable mode from the repository root to share utilities between ROS 2 nodes and CLI tools:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -e .
   ```
4. Configure IDE/type checking paths so `tests` and `ros2_ws/src` resolve identically to runtime bootstrap order (see [Development Process](../development/Development_Process.md)).

### SLAM integration quickstart
Use the integrated bringup launch to feed the streaming output directly into HDL Graph SLAM:
```bash
source /opt/ros/humble/setup.bash
cd /path/to/draco_tcpip/ros2_ws
source install/setup.bash
ros2 launch slam_stream_bridge bringup.launch.py \
  bag:=/data/bags/sample.bag \
  topic:=/sensing/lidar/top/pointcloud \
  layout_profile:=client.profile.yaml \
  slam:=hdl
```
The launch file wires `stream_server`/`stream_client` to `/stream_pair/decoded` and reuses the QoS/profile helpers documented in the [Configuration Reference](../reference/Configuration_Reference.md). Override `slam_params` to supply a custom HDL Graph SLAM parameter file when required.

## Streaming Operations
1. **Start the server** with deterministic cleanup and telemetry:
   ```bash
   ros2 run draco_roundtrip stream_server --port 5000
   ```
   - Supports `--protocol` (`legacy` or `binary`), `--resp-format`, `--metrics-out`, and `--socket-buffer-autotune`; see [Configuration Reference](../reference/Configuration_Reference.md) for defaults.
   - Logs and telemetry follow the control-plane contract and schema from [Protocol and Schema Reference](../reference/Protocol_and_Schema_Reference.md).

2. **Optionally apply network emulation** before the client joins:
   ```bash
   # dry-run profile preview
   ros2 run draco_roundtrip stream_netem wifi_dense --iface lo --dry-run
   # apply profile (requires sudo)
   sudo ros2 run draco_roundtrip stream_netem wifi_dense --iface eno1 --clear
   ```

3. **Launch the client** from another terminal:
   ```bash
   ros2 run draco_roundtrip stream_client \
       --bag /path/to/bag \
       --topic /sensing/lidar/top/pointcloud \
       --prefix demo_run \
       --layout-profile client.profile.yaml \
       --data-root ./data \
       --quality-thresholds '{"centroid_l2": 0.05}'
   ```
   - Handshakes: `MSG_ACK`, `MSG_HEARTBEAT`, and `MSG_EOF` manage bounded queues and session shutdown; RTT windows adapt via `--ack-timeout*` flags.
   - Directory/QoS resolution, profile search order, and CLI defaults are defined in [Configuration Reference](../reference/Configuration_Reference.md).
   - Quality JSONL metrics are emitted to `quality_report_dir/<prefix>_quality.jsonl`. Toggle Draco artifact retention with `--keep-artifacts` on the server and `--no-save-decoded` on the client.

4. **3D SLAM streaming**: When the bringup launch is not used, manually start HDL Graph SLAM and subscribe to `/stream_pair/decoded`. Ensure `--play-frame-id` on the client matches the SLAM frame (default `lidar_link`).

## Monitoring and Validation
- Live monitoring:
  ```bash
  ros2 run draco_roundtrip stream_monitor \
      --source /stream_pair/source \
      --decoded /stream_pair/decoded
  ```
- Replay stored PLY pairs for offline analysis:
  ```bash
  ros2 run draco_roundtrip stream_replay \
      --original data/ply \
      --decoded data/decoded
  ```
- Performance guardrails:
  - `pytest tests/perf/test_latency_gate.py` enforces the p95 latency target configured in the [Performance Test Plan](../development/Performance_Test_Plan.md).
  - `scripts/netem_profile.sh <profile>` activates predefined latency/loss patterns and should be reset with `scripts/netem_profile.sh clear` after experiments.
- Observability: Structured logs include session state, queue depth, and latency percentiles. Telemetry JSON must validate against the schema in [Protocol and Schema Reference](../reference/Protocol_and_Schema_Reference.md).

## Log Collection and Post-Run Tasks
Automate result collation with `stream_collect_logs`:
```bash
ros2 run draco_roundtrip stream_collect_logs run_20240315 \
  --layout-profile client.profile.yaml \
  --data-root ./data \
  --metadata bag=sample.bag --metadata slam=rtabmap \
  --ros-log ~/.ros/log/latest \
  --attach data/ply_stream/sample_0001.ply \
  --notes "Baseline roundtrip with wifi_dense profile"
```
This populates `data/results/<run_id>/` with `artifacts/`, `metrics/`, `ros_logs/`, and `manifest.json`. The manifest captures the run ID, profile, QoS override, metadata key-values, and EOF handshake status. When automation is unavailable, mirror the same directory layout manually and document the run with the [Results Template](../reports/results_template.md).

After SLAM experiments, archive ROS logs and SLAM outputs under `ros_logs/` and `artifacts/` so the manifest references remain valid.

## Troubleshooting and Quick Commands
- Validate environment assumptions:
  ```bash
  ruff check .
  pyright
  pytest --maxfail=1 --disable-warnings
  ```
- Networking issues:
  - If ACK timeouts spike, review `--ack-timeout`, `--ack-timeout-min`, and `--ack-timeout-max` settings.
  - Use `--socket-buffer-autotune` on both endpoints when high-latency links cause buffer pressure.
- Filesystem transport:
  - Configure `--spool-gc-window` to bound remembered spool entries when using filesystem-based capture.
  - Ensure layout profiles enumerate `ply_stream`, `client_work`, and `decoded_from_server` directories; see [Configuration Reference](../reference/Configuration_Reference.md).
- For full recovery steps or audit expectations, consult the [Development Process](../development/Development_Process.md) and [Refactor and Audit Log](../reports/Refactor_and_Audit_Log.md).
