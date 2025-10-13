# Project Progress Report
Summarises short- and long-term initiatives for Draco Roundtrip along with current execution status and outstanding checklist items.
_Last updated: 2025-03-15_

**Sections**
- [Executive Summary](#executive-summary)
- [Short-Term Plan](#short-term-plan)
- [Long-Term Plan](#long-term-plan)
- [Status Table](#status-table)
- [Outstanding Checklist](#outstanding-checklist)

## Executive Summary
Async pipeline and hybrid control-plane objectives are largely stable. Binary protocol, telemetry, and adaptive window features are in production, but regression benchmarking, advanced transports, and in-process Draco remain open. Long-term items (QUIC/UDP-FEC, C++ port, telemetry-driven adaptation) are still in design review.

## Short-Term Plan
- Build rosbag regression benchmark harness and enforce the p95 latency gate automatically.
- Measure filesystem watcher performance on platforms without native event APIs and document remediation strategies.
- Expand integration tests and logging coverage for EOF and binary protocol flows.
- Finalise tuning flags for `--tx-fragment-size` and `--socket-buffer-autotune` with documented defaults.

## Long-Term Plan
- Introduce QUIC and UDP+FEC transport modes with standardised loss scenarios.
- Integrate Draco C++ API for in-process encode/decode paired with shared memory transport.
- Implement rclcpp + Asio pipeline with a Python compatibility layer.
- Automate deployment via containers, CI/CD, and telemetry dashboards.
- Complete telemetry-driven adaptive control loops for inflight window and bitrate adjustments.

## Status Table
| Workstream | State | Notes |
|------------|-------|-------|
| Async pipeline stabilisation | ✅ Complete | Bounded queues, EOF/ACK handshake, binary protocol live. |
| Regression benchmarking | ⏳ In Progress | Harness defined, automated enforcement pending. |
| Transport experiments | 🟡 Planned | QUIC/UDP-FEC profiles drafted but not prototyped. |
| C++ migration | 🟡 Planned | Architecture captured; implementation not started. |
| Telemetry automation | ⏳ In Progress | Schema enforced; dashboards pending. |

## Outstanding Checklist
- [ ] Rosbag regression benchmark and CI threshold enforcement.
- [ ] Cross-platform filesystem watcher performance study and tuning.
- [ ] Binary protocol end-to-end integration tests with comprehensive logging.
- [ ] QUIC/UDP+FEC transport prototypes and loss scenario catalogues.
- [ ] Draco C++ in-process encode/decode pathway and rclcpp parity validation.
- [ ] Container deployment pipeline with telemetry dashboard integration.
