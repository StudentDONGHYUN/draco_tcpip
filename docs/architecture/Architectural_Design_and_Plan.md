# Architectural Design and Latency Plan
This document consolidates the async streaming pipeline architecture, the hybrid control-plane evolution, and the network latency reduction roadmap for Draco Roundtrip.
_Last updated: 2025-03-15_

**Sections**
- [Architecture Objectives](#architecture-objectives)
- [End-to-End Pipeline Design](#end-to-end-pipeline-design)
- [Control Plane and Bounded Queues](#control-plane-and-bounded-queues)
- [Latency Reduction Strategy](#latency-reduction-strategy)
- [Implementation Roadmap and Definition of Done](#implementation-roadmap-and-definition-of-done)
- [Observability and Telemetry](#observability-and-telemetry)

## Architecture Objectives
- Minimise end-to-end latency by overlapping capture, encode, transport, decode, and publish stages across asynchronous workers.
- Guarantee deterministic shutdown through explicit `MSG_EOF`, `MSG_ACK`, and heartbeat exchanges even on lossy links.
- Keep all queues bounded (`maxsize` per stage, finite in-flight window) to avoid unbounded memory usage.
- Maintain compatibility with Python ROS 2 nodes today while preparing an rclcpp/Boost.Asio migration path.

## End-to-End Pipeline Design
```
[Capture Thread] --bounded--> [Encode Worker Pool] --bounded--> [TX Loop]
      │                                                         │
      │<--backpressure------------------------------------------│
      ▼                                                         ▼
[Network Transport] <== control/data ==> [RX Pump] --bounded--> [Decode Pool] --bounded--> [Publish Thread]
```
- **Capture Stage**: Subscribes to ROS 2 topics or filesystem spoolers, enqueues frame handles (metadata + payload pointer) into a bounded queue (default 4, configurable up to 16). When the queue is full the capture loop either drops the oldest frame or pauses until space frees.
- **Encode Stage**: Thread pool or `asyncio.to_thread` workers call the Draco encoder wrapper, tagging each result with sequence ID, timestamps, and encode duration. Failures emit structured `ERROR` messages.
- **Transport Stage**: The TX loop uses non-blocking sockets, records send time per sequence, and respects the `max_inflight` window. Payloads use the binary framing header (kind `0x10`, Draco content) and optional fragmentation controlled by `--tx-fragment-size`.
- **RX Pump and Decode Stage**: A dedicated reader processes control and data channels, updating the in-flight table on ACKs and forwarding decoded payloads to a bounded decode queue. A reorder buffer keyed by `next_seq` preserves publish order.
- **Publish Stage**: Publishes decoded point clouds to ROS topics and writes optional artifacts based on layout profiles defined in the [Configuration Reference](../reference/Configuration_Reference.md).
- **Shared Memory**: Optional zero-copy capture paths clean up shared memory segments if transport fails, keeping resource usage bounded.

## Control Plane and Bounded Queues
- **Message Codes** (`0x01` ACK, `0x02` HEARTBEAT, `0x03` EOF, `0x04` ERROR) follow the contract in the [Protocol and Schema Reference](../reference/Protocol_and_Schema_Reference.md).
- **State Machine**: `INIT → HANDSHAKING → STREAMING → DRAINING → TERMINATED` with a `FAILED` escape hatch. EOF transitions require `pending=0` before declaring termination.
- **Heartbeat Policy**: Heartbeats every 2 s, liveness timeout at 6 s. Missed heartbeats trigger `ERROR` with code `TIMEOUT` and force queue drains.
- **Window Control**: Adaptive window controller observes RTT EMA and clamps between `--ack-timeout-min` and `--ack-timeout-max`. Bounded queues (`asyncio.Queue(maxsize=n)`) exist at every boundary with explicit pause/resume signals.
- **Fragmentation**: When `--tx-fragment-size` > 0 the TX loop emits MTU-safe fragments (256–1400 B) with `more_fragments` flags; receivers stitch fragments before ACKing.

## Latency Reduction Strategy
1. **Pipeline parallelism**: Implement capture/encode/send overlap with asynchronous queues and backpressure, ensuring Draco encoding does not block capture.
2. **Zero-copy paths**: Prefer loaned messages or shared memory to avoid filesystem spool overhead, with automatic cleanup if transmissions fail.
3. **Binary protocol**: Default to `--protocol=binary` to minimise header size and system calls. Control/data channels share a socket but maintain independent addressing.
4. **Transport tuning**: Enable optional socket buffer autotuning and fragmentation. Future phases include QUIC/UDP-FEC transport experiments guarded by `--transport`.
5. **C++ migration**: Port critical nodes to rclcpp + Boost.Asio to remove the Python GIL bottleneck while keeping CLI compatibility through a thin shim layer.
6. **Benchmarks**: Validate improvements with the rosbag-based benchmark described in the [Performance Test Plan](../development/Performance_Test_Plan.md).

## Implementation Roadmap and Definition of Done
| Phase | Focus | Definition of Done |
|-------|-------|--------------------|
| 0 – Stability | EOF/ACK/Heartbeat handshake, bounded queues, deterministic shutdown summary | Logs show `EOF sent/received`, telemetry reports `pending=0`, bounded queue instrumentation merged. |
| 1 – Performance | Adaptive window, binary protocol, MTU-safe fragmentation, network autotuning | `--adaptive-window`, `--tx-fragment-size`, and `--socket-buffer-autotune` flags wired; latency benchmark passes with p95 < 250 ms. |
| 2 – Transport Experiments | QUIC/UDP-FEC prototypes, priority queues, zero-copy improvements | Experimental transports gated behind `--transport`, shared memory cleanup validated. |
| 3 – Future Enhancements | rclcpp/Asio port, in-process Draco integration, Python compatibility layer | C++ nodes achieve feature parity, Python tools interact through unified protocol adapters. |

Outstanding actions include QUIC/UDP-FEC evaluation, adaptive bitrate controllers, and automated deployment of low-latency kernel tuning. Track individual tasks in the [Development Process](../development/Development_Process.md).

## Sequence Diagrams
The diagrams below reflect the current hybrid pipeline with bounded queues, ACK-based flow control, and the control/data channel split.

See also [Async Pipeline Design](../designs/async_pipeline_design.md), [Control Plane Contract](../contracts/control_plane_contract.md), and [Codebase Overview](../references/codebase_overview.md).

```mermaid
sequenceDiagram
    title Draco TCP/IP Roundtrip — End-to-End Data Flow
    participant U as User/CLI
    participant BAG as ros2 bag play (proc)
    participant CLI as StreamClient (stream_client.py)
    participant ENC as Draco Encoder (proc)
    participant SRV as StreamServer (stream_server.py)
    participant DEC as Draco Decoder (proc)
    participant ROS as ROS 2 Topic (/stream_pair/decoded)

    %% Data channel uses binary framing; control channel carries ACK/HEARTBEAT/EOF (see control_plane_contract.md)
    %% Queues are bounded; TX path honors max_inflight (see async_pipeline_design.md)

    U->>SRV: Start server (listen)
    U->>CLI: Start client

    BAG-->>CLI: Publish PointCloud2 (capture)
    Note right of CLI: Capture queue (bounded)

    CLI->>ENC: Encode PLY → Draco (.drc)
    Note right of ENC: External process call

    ENC-->>CLI: Encoded bytes
    CLI->>SRV: Send framed DATA over TCP (binary protocol)
    Note right of CLI: Network queue (bounded)\nTX loop with max_inflight

    SRV-->>CLI: ACK(seq) on control channel
    Note right of CLI: in_flight -= 1

    SRV->>DEC: Decode Draco → PLY
    Note right of DEC: External process call

    DEC-->>SRV: Decoded cloud (PLY/PCD)
    SRV-->>ROS: Publish decoded cloud

    SRV-->>CLI: (optional) Metrics/summary for frame

    %% Graceful end
    CLI-->>SRV: EOF (control channel)
    SRV-->>CLI: EOF (after pending=0)
    SRV-xROS: Close session
    CLI-xBAG: Stop capture; close session
```

```mermaid
sequenceDiagram
    title Draco TCP/IP Roundtrip — TCP Control Plane
    participant CLI as StreamClient
    participant SRV as StreamServer

    %% Control plane kinds: ACK(0x01), HEARTBEAT(0x02), EOF(0x03), ERROR(0x04)
    %% Data vs Control channel separation per contract

    rect rgb(245,245,245)
      CLI->>SRV: TCP connect (data)
      CLI-->>SRV: (optional) TCP connect (control)
    end

    par Streaming
      CLI->>SRV: DATA Frame (seq=1)  %% data channel
      SRV-->>CLI: ACK(seq=1)         %% control channel
      Note right of CLI: in_flight ≤ max_inflight\nACK frees one slot

      CLI->>SRV: DATA Frame (seq=2)
      SRV-->>CLI: ACK(seq=2)
      CLI->>SRV: DATA Frame (seq=3)
      SRV-->>CLI: ACK(seq=3)
    and Heartbeat
      loop idle
        SRV-->>CLI: HEARTBEAT
      end
    end

    opt Error path
      CLI->>SRV: DATA Frame (seq=4)
      SRV-->>CLI: ERROR{code=TIMEOUT,msg="ACK overdue"}
      CLI-xSRV: Close sockets; state=FAILED
    end

    opt Graceful shutdown
      CLI-->>SRV: EOF
      SRV-->>CLI: EOF (after pending=0)
      CLI-xSRV: Close sockets; state=TERMINATED
    end
```

## Observability and Telemetry
- Record timestamps on enqueue/dequeue for each stage to derive stage latency histograms.
- Maintain RTT, ACK latency, throughput, and queue depth metrics per session. Persist results to `artifacts/perf/*.json` with the schema documented in the [Protocol and Schema Reference](../reference/Protocol_and_Schema_Reference.md).
- During shutdown, log structured JSON summarising `pending`, `acks_pending`, p50/p95/p99 latency, transmitted bytes, and dropped frames.
- Feed telemetry outputs into regression gates and dashboards; failing validation should transition the session to `FAILED` with the correct `ERROR` code.
