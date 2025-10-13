Moved from templates/.

# Roundtrip Regression Log Template
Use this template after running end-to-end regression (`ros2_ws/src/draco_roundtrip/tests/e2e_roundtrip.sh`) to capture reproducibility metadata. Keep arguments, environment details, and metrics complete so future investigations can replay the run. Directory expectations follow the [User Guide](../guides/User_Guide.md) and [Configuration Reference](../reference/Configuration_Reference.md).

## 1. Environment Summary
- Execution time: <!-- 2025-03-15 14:32 KST -->
- Host/CI runner: <!-- local-devbox-01 -->
- ROS 2 distribution: <!-- humble -->
- Draco encoder/decoder path: <!-- /opt/draco/bin/draco_encoder -->
- Extra dependencies: <!-- numpy==1.26.4, plyfile==0.9 -->

## 2. Commands
```bash
$ ros2_ws/src/draco_roundtrip/tests/e2e_roundtrip.sh -vv
```
Add any additional `pytest` flags, environment variables, or launch arguments used in the session.

## 3. Results Summary
| Frame | Source points | Decoded points | Δ Points | Centroid distance (norm) | Chamfer distance (avg/max) | Notes |
|-------|---------------|----------------|----------|--------------------------|----------------------------|-------|
| frame_00000 | <!-- 4 --> | <!-- 4 --> | <!-- 0 --> | <!-- 0.000 --> | <!-- 0.000 / 0.000 --> | <!-- stub encoder --> |

## 4. Logs and Notes
- <!-- [CLIENT] Frame 00000 Δpts=0 centroid_norm=0.000 ... -->
- <!-- Test executed with stub encoder/decoder. Production regression pending. -->

Archive supporting logs under `logs/` within the run directory. When using `stream_collect_logs`, attach the manifest path and relevant artifacts/ROS logs. Cross-reference follow-up tasks in the [Development Process](../development/Development_Process.md) and [Refactor and Audit Log](../reports/Refactor_and_Audit_Log.md).
