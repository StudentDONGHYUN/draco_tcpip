# Server-Centric Streaming Runbook

This guide explains how to operate the server-centric architecture that keeps
the Draco uplink intact while streaming autonomy outputs back to the robot.

## Prerequisites

* ROS 2 Galactic or later on both client and server hosts
* Draco encoder/decoder binaries discoverable in `$PATH` or via
  `--encoder/--decoder`
* Network reachability between the client and server for the uplink and
  downlink ports

## Server

Launch the streaming server, which decodes Draco frames, publishes
`PointCloud2`, and emits control-plane telemetry. Binary downlink is enabled by
default.

```bash
ros2 run draco_roundtrip stream_server \
  --host 0.0.0.0 \
  --port 5000 \
  --downlink-port 6000 \
  --downlink-rate 10 \
  --points-topic /server/points \
  --pose-topic /server_pose \
  --path-topic /planned_path \
  --twist-topic /cmd_vel
```

The server publishes stub pose/path/twist messages if no SLAM/planner inputs
are available. Use `--legacy-downlink` to re-enable the original PLY response
flow (a deprecation warning is logged).

Switch to JSON telemetry when debugging:

```bash
ros2 run draco_roundtrip stream_server --downlink-json
```

## Client

Run the client to stream PLY frames, encode them to Draco, and consume the
downlink telemetry. The client publishes `/server_pose`, `/planned_path`, and
`/cmd_vel` into its ROS graph (prefixed via `--topic-prefix` when required).

```bash
ros2 run draco_roundtrip stream_client \
  --bag my_recording.db3 \
  --topic /lidar/points \
  --prefix robot1 \
  --ply-dir data/ply_stream \
  --server-host 192.168.1.100 \
  --server-port 5000 \
  --downlink-host 192.168.1.100 \
  --downlink-port 6000 \
  --topic-prefix robot1
```

Heartbeat messages keep the downlink alive. Increase the heartbeat interval for
satcom links:

```bash
ros2 run draco_roundtrip stream_client ... --heartbeat-interval 2.5
```

## Telemetry

The client logs a preview of each `cmd_vel` message by default. Supply a custom
execution callback by editing the `ClientBridge` hook or wiring it into a motor
controller node.

## Troubleshooting

* **No downlink packets:** verify that the client is sending heartbeats. The
  server stops transmitting after 2× the heartbeat interval with no activity.
* **Legacy workflows:** pass `--legacy-downlink` to the server and keep the
  client pointed at the decoded directory; no other changes required.
* **Oversized paths:** ensure planners limit trajectories to ≤200 poses or the
  server will drop the update.
