# Control Plane Contract

The control-plane extends the existing TCP framing (`net.protocol`) with three
new message kinds that deliver autonomy metadata from the server to the client.
Framing (magic/version/length/kind/seq) is unchanged; new kinds are only added
to the `kind` string:

| Kind      | Purpose                | Payload encoding                              |
|-----------|------------------------|-----------------------------------------------|
| `pose`    | Robot pose estimate    | Binary struct (default) or JSON               |
| `path`    | Planned trajectory     | Binary struct with bounded array or JSON      |
| `twist`   | Velocity command       | Binary struct or JSON                         |

Binary payloads use network byte order and fixed sizes to enable zero-copy
parsing. Strings are padded with `\0` and truncated at 64 bytes. JSON payloads
mirror the same fields and are emitted when the server node sets the
`downlink_protocol` parameter to `json` or toggles the boolean
`downlink_json` parameter.

## Structures

All timestamps use unsigned nanoseconds since the UNIX epoch.

### Pose (`pose`)

```
struct PosePayload {
    uint64 stamp_ns;
    char frame_id[64];
    double x, y, z;
    double qx, qy, qz, qw;
};
```

### Twist (`twist`)

```
struct TwistPayload {
    uint64 stamp_ns;
    float vx, vy, vz;
    float wx, wy, wz;
};
```

### Path (`path`)

```
struct PathPayload {
    uint64 stamp_ns;
    char frame_id[64];
    uint16 count;  // 0 <= count <= 200
    Pose poses[count];
};

struct Pose {
    double x, y, z;
    double qx, qy, qz, qw;
};
```

The path pose count is capped at 200 (~33 kiB payload) to bound bandwidth.

## Timing and liveness

* Downlink rate is throttled to the `downlink_rate` parameter (default 10 Hz).
* Clients send heartbeats (`heartbeat` kind with empty payload) every
  `heartbeat_interval` seconds (default 1 s). The server suppresses downlink if
  no heartbeat is observed within twice this interval.
* Legacy PLY replies remain behind the `legacy_downlink` parameter. When legacy
  mode is disabled the server ACKs uploads with `ack` messages.

## Error handling

* Binary payload size or `count` violations raise `ValueError` and result in the
  message being dropped.
* JSON decoding errors are logged and skipped.
* Heartbeat loss suspends downlink but does not abort the uplink session; once
  heartbeats resume the latest autonomy bundle is sent.
