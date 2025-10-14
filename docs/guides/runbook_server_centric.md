# Server-Centric Streaming Runbook

This guide explains how to operate the server-centric architecture that keeps
the Draco uplink intact while streaming autonomy outputs back to the robot.

## Prerequisites

* ROS 2 Galactic or later on both client and server hosts
* Draco encoder/decoder binaries discoverable in `$PATH` or supplied through the
  `encoder`/`decoder` ROS parameters
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

* `port` defaults to `5000`. When `downlink_port` is left at its default of `0`,
  the server computes `port + 1` for the control-plane link.
* `downlink_port` can be set explicitly (e.g., `downlink_port:=6001`) if a
  different control socket must be exposed.
* Run this command on the high-performance server that performs decoding and
  analytics.

### Client PC (robot)

```bash
ros2 launch draco_roundtrip client.launch.py \
  server_host:=192.168.3.16 \
  server_port:=5000 \
  bag_file:=/path/to/recording \
  topic_name:=/lidar/points
```

* `server_host` is required and must point to the server PC reachable over the
  network. The same address is reused for the downlink connection.
* `server_port` defaults to `5000`; the client automatically listens on
  `server_port + 1` for the downlink.
* `bag_file` should point to the rosbag2 directory or database file to replay.
* `topic_name` selects the `sensor_msgs/msg/PointCloud2` topic inside the bag.
* Additional launch arguments map directly to ROS 2 parameters: for example,
  `work_dir:=/mnt/tmp` or `telemetry_rate:=5.0`.

The nodes now rely entirely on ROS 2 parameters instead of custom CLI flags. To
override multiple settings at once, supply a YAML file via
`--ros-args --params-file path/to/custom.yaml` or stack launch overrides like
`ros2 launch ... telemetry_rate:=5.0 heartbeat_interval:=2.0`.

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
* **Legacy workflows:** launch the server with `legacy_downlink:=true` and keep
  the client pointed at the decoded directory; no other changes required.
* **Oversized paths:** ensure planners limit trajectories to ≤200 poses or the
  server will drop the update.
