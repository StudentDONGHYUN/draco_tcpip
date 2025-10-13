# Refactor and Audit Log
Combines audit findings with the refactor rollout timeline to document completed work, verification evidence, and remaining follow-up tasks.
_Last updated: 2025-03-15_

**Sections**
- [Summary](#summary)
- [Audit Entries](#audit-entries)
- [Refactor Timeline](#refactor-timeline)
- [Operational Guidance](#operational-guidance)
- [Follow-up Actions](#follow-up-actions)

## Summary
- Control-plane handshake (`MSG_EOF`, `MSG_ACK`, `MSG_HEARTBEAT`) is fully enforced across client and server with structured shutdown logs.
- Filesystem watcher, configuration helpers, and socket options were hardened to support diverse environments.
- Documentation, CLI, and automation artefacts now point to shared references for profiles, QoS, and encoder options.

## Audit Entries
| Status | Identifier | Location | Details |
|--------|------------|----------|---------|
| ✅ Fixed | PYTEST-0001 | `tests/perf/test_latency_gate.py` et al. | `ModuleNotFoundError: No module named 'tests.perf'` caused by ROS 2 workspace shadowing repository tests. Resolved by normalising `sys.path`, materialising the local `tests` package, and constraining discovery via `pytest.ini`. |
| ✅ Fixed | PYTEST-0002 | `tests/unit/test_protocol_header.py` et al. | After addressing PYTEST-0001, ROS 2 packages fell off `sys.path`. The repository-level `conftest.py` now appends `ros2_ws/src` ensuring nodes and utilities import correctly. |

Evidence: `pytest` succeeds with the adjusted bootstrap (see CI logs or local executions captured in the [Development Process](../development/Development_Process.md)).

## Refactor Timeline
| Phase | Highlights |
|-------|-----------|
| 1 | Unified protocol/PLY/metrics utilities with dedicated unit tests under `ros2_ws/src/draco_roundtrip/tests`. |
| 2 | Consolidated Draco encoder CLI parsing and logging via `draco_tools.core.encoder`. |
| 3 | Expanded layout/QoS helpers and adopted them across streaming, offline pipelines, and launch files. |
| 4 | Established CI flow (`colcon build`, `colcon test`, perf gates) with GitHub Actions. |
| 5 | Delivered SLAM integration launch, network emulation helpers, and log collection automation. |
| 6 | Finalised documentation updates (User Guide, configuration references, results template). |

## Operational Guidance
1. **Environment preparation**: Install ROS 2 dependencies, run `pip install -e .`, and configure IDE search paths to mirror runtime bootstrap.
2. **Streaming workflow**: Prefer the bringup launch or follow the [User Guide](../guides/User_Guide.md) for manual sequencing. Always enable binary protocol unless testing legacy compatibility.
3. **Log and artifact management**: Use `stream_collect_logs` to populate manifests and archive ROS logs. Follow the [Results Template](../reports/results_template.md) for run documentation.
4. **Network tuning**: Apply `stream_netem` profiles for reproducible conditions and restore baseline settings post-test.
5. **Telemetry compliance**: Validate JSON outputs against the [Protocol and Schema Reference](../reference/Protocol_and_Schema_Reference.md) before publishing results.

## Follow-up Actions
- [ ] Prototype QUIC/UDP-FEC transports and capture comparative telemetry.
- [ ] Integrate in-process Draco encode/decode to remove external binary dependency.
- [ ] Automate report generation that links telemetry artefacts to checklist updates in [Development Process](../development/Development_Process.md).
