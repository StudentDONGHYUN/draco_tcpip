# Performance Test Plan
Defines the rosbag-based regression benchmark that enforces the Draco Roundtrip p95 latency target.
_Last updated: 2025-03-15_

**Sections**
- [Benchmark Configuration](#benchmark-configuration)
- [Execution Procedure](#execution-procedure)
- [Outputs](#outputs)
- [Maintenance Guidelines](#maintenance-guidelines)

## Benchmark Configuration
| Field | Value |
|-------|-------|
| Benchmark | `rosbag regression gate` |
| Dataset | `sample_bag/pointcloud_latency.bag` |
| Threshold (p95) | 250 ms |
| Sample Count | 1 200 frames |

## Execution Procedure
1. Replay the bag:
   ```bash
   ros2 bag play sample_bag/pointcloud_latency.bag
   ```
2. Start the server with the binary protocol and bounded queues.
3. Launch the client against the same bag, ensuring telemetry and layout settings follow the [Configuration Reference](../reference/Configuration_Reference.md).
4. Collect latency metrics by running:
   ```bash
   pytest tests/perf/test_latency_gate.py
   ```
5. The test harness computes p50/p95/p99, RTT, and ACK latency from capture-to-ACK timestamps. Fail the run if p95 ≥ 250 ms.

## Outputs
- `artifacts/perf/latest_latency.json`: Telemetry JSON conforming to the schema in the [Protocol and Schema Reference](../reference/Protocol_and_Schema_Reference.md).
- `artifacts/perf/summary.txt`: Text summary with percentile comparisons against thresholds.

## Maintenance Guidelines
- Maintain at least 1 000 frames per dataset to ensure statistically meaningful percentiles.
- Update dataset paths or thresholds in this plan and in CI scripts simultaneously (`scripts/ci/run_perf_gate.sh`).
- Revalidate the benchmark when transport flags (`--transport`, `--tx-fragment-size`, `--socket-buffer-autotune`) change.
