# Server-Centric Streaming Runbook

This guide explains how to operate the server-centric architecture that keeps
the Draco uplink intact while streaming autonomy outputs back to the robot.

## Prerequisites

* ROS 2 Galactic or later on both client and server hosts
* Draco encoder/decoder binaries discoverable in `$PATH` or via
  `--encoder/--decoder`
* Network reachability between the client and server for the uplink and
  downlink ports

## Launching the pipeline

The refactored, bidirectional workflow assumes a distributed deployment. Launch
the server and client on their respective machines so the uplink and downlink
flows stay synchronized.

### Server PC (uplink/downlink hub)

```bash
ros2 launch draco_roundtrip server.launch.py [port:=5000]
```

* `port` defaults to `5000`. The downlink port is automatically derived as
  `port + 1`.
* Run this command on the high-performance server that performs decoding and
  analytics.

### Client PC (robot)

```bash
ros2 launch draco_roundtrip client.launch.py \
  server_ip:=192.168.3.16 \
  server_port:=5000 \
  bag_file:=/path/to/recording \
  topic_name:=/lidar/points
```

* `server_ip` is required and must point to the server PC reachable over the
  network. The same address is reused for the downlink connection.
* `server_port` defaults to `5000`; the client automatically listens on
  `server_port + 1` for the downlink.
* `bag_file` should point to the rosbag2 directory or database file to replay.
* `topic_name` selects the `sensor_msgs/msg/PointCloud2` topic inside the bag.

Additional command-line options for `stream_client` and `stream_server` can be
passed via `ROS_ARGUMENTS` when necessary (e.g., enabling `--downlink-json`).
Both nodes inherit the package defaults for heartbeat timing, telemetry topics,
and QoS handling.

Heartbeat messages keep the downlink alive. Increase the heartbeat interval for
satcom links by exporting

```bash
export ROS_ARGUMENTS='--ros-args --params-file path/to/custom.yaml'
```

or by launching with an override YAML that tweaks the client parameters.

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
