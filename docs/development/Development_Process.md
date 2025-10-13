# Development Process
Outlines the continuous improvement workflow for Draco Roundtrip, combining review findings with actionable checklists for code quality, hybrid architecture, and refactoring milestones.
_Last updated: 2025-03-15_

**Sections**
- [Workflow Overview](#workflow-overview)
- [Definition of Done](#definition-of-done)
- [Execution Checklist](#execution-checklist)
- [Outstanding Work](#outstanding-work)
- [References](#references)

## Workflow Overview
- **Context**: Draco Roundtrip streams Draco-compressed LiDAR frames over TCP using shared utilities between ROS 2 nodes and CLI tools. The codebase layout is summarised in [Configuration Reference](../reference/Configuration_Reference.md).
- **Bootstrap**: Activate a Python 3.11 virtual environment, run `pip install -e .`, and ensure IDEs include the repository root before `ros2_ws/src` in `PYTHONPATH` to prevent module shadowing.
- **Type Checking**: Pyright strict mode is mandatory. `pytest.ini` limits discovery to the repository `tests/` package to avoid ROS package conflicts.
- **Testing Strategy**: Run `pytest`, targeted perf gates, and, when relevant, `colcon test` from `ros2_ws`. Record outcomes in the [Results Template](../reports/results_template.md).

## Definition of Done
### Code Improvement Stream
1. **Control-plane handshake**: `MSG_EOF` exchanged at shutdown, logs show `EOF sent`/`EOF received` with `pending=0` summary.
2. **Filesystem watcher**: Event-based watcher enabled when available; fallback polling prunes processed entries to avoid RSS growth.
3. **Configuration safety**: `utils/config.py` handles shallow installations without `IndexError` and keeps profile/QoS resolution consistent.
4. **Socket portability**: Server gracefully falls back when `SO_REUSEPORT` is unavailable.
5. **Decode hygiene**: Temporary decode artifacts removed unless `--keep-artifacts` is explicitly set.

### Hybrid Architecture Stream
1. **Bounded queues** across capture→encode→send→decode with explicit `maxsize` and pause/resume signalling.
2. **TX/RX separation** with worker pools propagating stop events on error.
3. **Adaptive window** toggled via `--adaptive-window`, `--window-ema-alpha`, and validated through latency gates.
4. **Binary protocol** default with distinct control/data addressing and MTU-safe fragmentation (`--tx-fragment-size`).
5. **Performance gate** enforced via `tests/perf/test_latency_gate.py` and CI scripts.

### Refactor Stream
1. **Utility consolidation**: Shared helpers (`protocol`, `executable`, `ply_io`, `metrics`) referenced consistently by nodes, tools, and CLIs.
2. **Encoder CLI harmonisation**: `draco_tools.core.encoder` acts as the single entry point for option parsing/log formatting.
3. **Config unification**: `resolve_data_layout` and QoS helpers reused by offline pipelines and launch files.
4. **Testing and CI**: Unit tests live in `ros2_ws/src/draco_roundtrip/tests/`, E2E scripts exercise at least one roundtrip, and CI runs build + test + perf gates.
5. **Documentation alignment**: Guides and references link to the unified configuration and protocol docs, with README/HOWTO kept in sync.

## Execution Checklist
1. **Plan the change** using the [Architectural Design and Plan](../architecture/Architectural_Design_and_Plan.md) and identify affected requirements in the [Traceability Matrix](../architecture/Traceability_Matrix.md).
2. **Update configuration docs** when introducing new flags or directories; keep the [Configuration Reference](../reference/Configuration_Reference.md) consistent with CLI defaults.
3. **Implement and lint**:
   ```bash
   ruff check .
   pyright
   pytest --maxfail=1 --disable-warnings
   ```
4. **Run performance gates** if transport, queueing, or telemetry paths change:
   ```bash
   pytest tests/perf/test_latency_gate.py
   ```
5. **Capture telemetry** and logs with `stream_collect_logs`, archiving manifests alongside artifacts for reproducibility.
6. **Document outcomes**: update relevant checklist sections here, record regression evidence in [Refactor and Audit Log](../reports/Refactor_and_Audit_Log.md), and populate the [Results Template](../reports/results_template.md).

## Outstanding Work
- [ ] Measure filesystem watcher performance on non-Linux platforms and adjust polling intervals if necessary.
- [ ] Prototype `--transport=quic|udp_fec` and capture perf deltas under loss scenarios.
- [ ] Extend regression suites to cover EOF/binary control paths end-to-end.
- [ ] Port streaming nodes to rclcpp + Asio and validate parity with Python implementation.
- [ ] Automate container-based deployment with low-latency kernel tuning and telemetry dashboards.

## References
- [Architectural Design and Plan](../architecture/Architectural_Design_and_Plan.md)
- [Traceability Matrix](../architecture/Traceability_Matrix.md)
- [Protocol and Schema Reference](../reference/Protocol_and_Schema_Reference.md)
- [User Guide](../guides/User_Guide.md)
