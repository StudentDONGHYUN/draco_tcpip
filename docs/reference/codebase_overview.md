<!-- Path: docs/references/codebase_overview.md -->

# 코드베이스 개요

이 문서는 `draco_tcpip` 워크스페이스의 주요 패키지와 데이터 흐름을 빠르게 파악할 수 있도록 구성 요소를 요약합니다. 세부적인 사용 예시는 각 가이드 문서를, 파라미터와 프로파일 설명은 레퍼런스 문서를 참고하세요.

## ROS 2 워크스페이스 레이아웃

- `ros2_ws/src/draco_roundtrip/`: 스트리밍 클라이언트/서버 노드와 공용 유틸리티를 담고 있으며, TCP 프레임 프로토콜·Draco 래퍼·로그 수집 도구를 제공합니다.
- `ros2_ws/src/draco_tools/`: rosbag→PLY→Draco 변환과 품질 분석 배치 파이프라인을 포함합니다.
- `ros2_ws/src/slam_stream_bridge/`: 스트리밍 파이프라인과 SLAM 패키지를 묶는 런치 파일을 제공합니다.
- `configs/`: QoS, 네트워크 에뮬레이션, 데이터 레이아웃 프로파일 등 실행 시 필요한 기본 구성입니다.

## `draco_roundtrip` 패키지

### 노드(`draco_roundtrip/nodes`)
- `stream_client.py`: rosbag 또는 라이브 토픽에서 프레임을 읽어 Draco로 인코딩하고 TCP로 전송합니다. 인플라이트 윈도우, 공유 메모리, QoS 오버라이드를 지원합니다.【F:ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_client.py†L1-L222】
- `stream_server.py`: TCP로 수신한 Draco 프레임을 디코딩해 `/stream_pair/decoded` 토픽으로 퍼블리시합니다. 파이프라인 단계별 텔레메트리를 수집하고 파일 기반/zero-copy 아티팩트 생성을 지원합니다.【F:ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_server.py†L1-L160】

### 도구(`draco_roundtrip/tools`)
- `monitor.py`, `replay.py`: 실시간 품질 모니터링과 저장된 PLY 재생을 제공합니다.
- `netem.py`: `stream_netem` CLI로 네트워크 에뮬레이션 프로파일을 적용합니다.
- `log_collection.py`: `stream_collect_logs` CLI를 통해 실험 결과 디렉터리를 구성하고 메타데이터를 기록합니다.【F:ros2_ws/src/draco_roundtrip/setup.py†L18-L29】

### 공용 유틸리티
- `utils/config.py`: 레이아웃 프로파일과 QoS 오버라이드를 로드/검증하며, `slam_stream_bridge` 런치에서도 재사용됩니다.【F:ros2_ws/src/slam_stream_bridge/slam_stream_bridge/launch/bringup.launch.py†L15-L83】
- `utils/protocol.py`, `utils/stream_protocol.py`: TCP 프레이밍과 제어/데이터 채널 인코딩을 담당합니다.
- `draco/encoder.py`: Draco 바이너리 실행 파일 탐색과 옵션 구성을 담당하며, 배치 도구와 노드에서 동일한 인터페이스를 사용하도록 유지합니다.【F:ros2_ws/src/draco_tools/draco_tools/core/encoder.py†L1-L107】

## `draco_tools` 패키지

- `bag_to_ply.py`: rosbag에서 PLY 프레임을 추출합니다.
- `encode_ply_to_draco.py`: PLY를 Draco로 일괄 인코딩합니다.
- `offline_pipeline.py`: bag 재생 → PLY 추출 → Draco 인코딩 → 품질 지표 집계를 한 번에 수행하고 CSV 리포트를 생성합니다.【F:ros2_ws/src/draco_tools/draco_tools/offline_pipeline.py†L1-L120】
- `core/encoder.py`: 스트리밍 노드와 동일한 Draco 래퍼를 재사용하기 위한 호환 계층입니다.【F:ros2_ws/src/draco_tools/draco_tools/core/encoder.py†L1-L107】

## `slam_stream_bridge` 패키지

- `launch/bringup.launch.py`: 스트리밍 서버/클라이언트, 선택한 SLAM 파이프라인(`rtabmap` 또는 `hdl`)과 네트워크 에뮬레이션을 단일 런치로 실행합니다.【F:ros2_ws/src/slam_stream_bridge/slam_stream_bridge/launch/bringup.launch.py†L1-L128】
- `launch/rtabmap_stream.launch.py`, `launch/hdl_graph_slam_stream.launch.py`: 개별 SLAM 런치를 제공합니다.

## 데이터 흐름 요약

1. `stream_client`가 rosbag/라이브 토픽에서 포인트클라우드를 수신하고, `draco_roundtrip.draco.encoder`를 통해 Draco 바이너리를 호출하여 압축합니다.
2. 인코딩된 프레임은 `utils.protocol`의 바이너리 프레이밍을 사용해 TCP로 전송됩니다.
3. `stream_server`는 프레임을 수신하고 디코딩한 뒤 ROS 토픽과 파일 아티팩트로 내보냅니다.
4. 선택적으로 `stream_collect_logs`가 결과 디렉터리를 정리하고, `offline_pipeline`이 동일한 레이아웃을 사용해 배치 분석을 수행합니다.
5. `slam_stream_bridge` 런치는 동일한 레이아웃/ QoS 헬퍼를 사용해 SLAM 노드를 포함한 통합 bringup을 제공합니다.

## 콘솔 스크립트 엔트리포인트

| 패키지 | 엔트리포인트 | 모듈 | 설명 |
| --- | --- | --- | --- |
| `draco_roundtrip` | `stream_client`, `stream_server`, `stream_monitor`, `stream_replay`, `stream_netem`, `stream_collect_logs` | `nodes/` 및 `tools/` | 실시간 스트리밍, 모니터링, 네트워크 에뮬레이션, 로그 수집 CLI. |
| `draco_tools` | `bag_to_ply`, `encode_ply_to_draco`, `offline_pipeline` | 루트 모듈 | 배치 변환 및 오프라인 품질 분석 CLI. |

## 테스트 및 회귀

- `ros2_ws/src/draco_roundtrip/tests/`: 프로토콜, 파이프라인, 도구에 대한 단위 테스트와 엔드투엔드 셸 스크립트가 위치합니다.
- GitHub Actions CI는 `ros2_ws/src/draco_roundtrip/tests/e2e_roundtrip.sh`를 실행해 numpy 기반 스텁 인코더로 회귀를 검증합니다.

이 개요는 다른 문서를 읽을 때 공통 맥락을 제공하도록 작성되었습니다. 구체적인 절차는 `../guides/`에서, 개발 워크플로는 `../development/Development_Process.md`와 `../development/Performance_Test_Plan.md`에서, 보고서는 `../reports/` 하위 문서에서 확인하세요.

## Auto-Generated Module Map
<!-- AUTODOC:MODULE_MAP:BEGIN -->
### draco_roundtrip

- **analysis**
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/analysis/__init__.py` — Analysis helpers exposed for external consumers.
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/analysis/metrics.py` — Metric helpers for comparing point clouds.
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/analysis/pointcloud_metrics.py` — Point cloud metric utilities for round-trip quality tracking.
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/analysis/quality.py` — Shared helpers for Draco roundtrip quality analysis.

- **cli**
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/cli/__init__.py` — Console entry points for the Draco roundtrip package.
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/cli/monitor.py` — CLI wrapper for the monitor tool.
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/cli/replay.py` — CLI wrapper for the replay tool.
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/cli/stream_client.py` — CLI wrapper for the streaming client.
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/cli/stream_server.py` — CLI wrapper for the streaming server.

- **common**
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/common/state_machine.py` — Shared streaming session state machine utilities.
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/common/timers.py` — ACK 타임아웃 스케줄러 유틸리티.

- **data**
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/data/__init__.py` — Wrapper entry-points used by draco_roundtrip for subprocess helpers.
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/data/bag_to_ply.py` — Invoke the shared bag recorder utility.

- **draco**
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/draco/__init__.py` — No module docstring
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/draco/encoder.py` — Shared Draco encoder helpers for streaming and batch utilities.

- **io**
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/io/__init__.py` — No module docstring
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/io/bag_recorder.py` — ROS2 PointCloud2 -> PLY 저장 노드 (Open3D 우선 + plyfile 폴백)
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/io/ply_codec.py` — PLY and PointCloud utility helpers.

- **net**
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/net/__init__.py` — No module docstring
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/net/io.py` — Socket I/O utilities shared by client and server.
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/net/protocol.py` — TCP protocol helpers shared by client and server.

- **nodes**
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/__init__.py` — No module docstring
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_client.py` — Stream rosbag frames, encode/send to server, replay decoded results to RViz.
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_server.py` — Async Draco streaming server with bounded pipeline and telemetry.

- **protocol**
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/protocol/__init__.py` — Protocol helpers shared by streaming client/server.
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/protocol/header.py` — Binary framing header shared by the streaming client and server.

- **ros**
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/ros/__init__.py` — No module docstring
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/ros/playback.py` — ROS helper nodes for publishing point clouds.

- **shared_memory**
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/shared_memory/__init__.py` — Shared-memory transport helpers for zero-copy frame capture.
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/shared_memory/channel.py` — TCP-coordinated shared memory channel for point cloud frames.

- **tools**
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/tools/__init__.py` — No module docstring
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/tools/log_collection.py` — Utilities for collecting run artifacts into a structured results directory.
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/tools/monitor.py` — Replay PLY pairs and emit per-frame diff metrics while publishing to ROS.
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/tools/netem.py` — Helpers for applying tc netem profiles defined in configs/netem.profiles.yaml.
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/tools/replay.py` — Replay original & decoded PLY pairs as PointCloud2 topics for RViz comparison.

- **utils**
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/__init__.py` — Backwards-compatible re-exports for legacy imports.
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/config.py` — Configuration helpers for QoS overrides and artifact directories.
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/executable.py` — Helpers that locate required external executables (draco_encoder/decoder).
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/metrics.py` — Backwards-compatible shim importing metrics helpers from the new package.
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/ply_io.py` — Backwards-compatible shim importing PLY helpers from the new module.
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/protocol.py` — Backwards-compatible shim importing protocol helpers from the new module.
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/stream_protocol.py` — Control-plane helpers aligned with docs/contracts/control_plane_contract.md.
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py` — Telemetry builder aligned with docs/specs/telemetry_schema.md.

### draco_tools

- **analysis**
- `ros2_ws/src/draco_tools/draco_tools/analysis/__init__.py` — No module docstring
- `ros2_ws/src/draco_tools/draco_tools/analysis/analyze_draco_quality.py` — PLY(original) vs DRC(Draco) 품질/성능 비교 (멀티코어 + 진행바 강화판)
- `ros2_ws/src/draco_tools/draco_tools/analysis/quality.py` — Shared helpers for Draco roundtrip quality analysis.

- **cli**
- `ros2_ws/src/draco_tools/draco_tools/cli/__init__.py` — Console entry points for draco_tools.
- `ros2_ws/src/draco_tools/draco_tools/cli/encode_ply_to_draco.py` — Batch encoder CLI that reuses shared core helpers.

- **core**
- `ros2_ws/src/draco_tools/draco_tools/core/__init__.py` — Core helpers shared across Draco tooling.
- `ros2_ws/src/draco_tools/draco_tools/core/encoder.py` — Compatibility layer exposing shared Draco encoder helpers and CLI bindings.

### slam_stream_bridge

- **launch**
- `ros2_ws/src/slam_stream_bridge/slam_stream_bridge/launch/bringup.launch.py` — No module docstring
- `ros2_ws/src/slam_stream_bridge/slam_stream_bridge/launch/hdl_graph_slam_stream.launch.py` — No module docstring
- `ros2_ws/src/slam_stream_bridge/slam_stream_bridge/launch/rtabmap_stream.launch.py` — No module docstring
<!-- AUTODOC:MODULE_MAP:END -->
