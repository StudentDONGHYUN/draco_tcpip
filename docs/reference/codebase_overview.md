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
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/analysis/__init__.py` — 외부 소비자를 위한 분석 헬퍼를 제공합니다.
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/analysis/metrics.py` — 포인트 클라우드 비교용 메트릭 헬퍼.
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/analysis/pointcloud_metrics.py` — 라운드트립 품질 추적을 위한 포인트 클라우드 메트릭 유틸리티.
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/analysis/quality.py` — Draco 라운드트립 품질 분석을 위한 공유 헬퍼.

- **cli**
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/cli/__init__.py` — Draco roundtrip 패키지의 콘솔 엔트리포인트.
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/cli/monitor.py` — 모니터 도구용 CLI 래퍼.
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/cli/replay.py` — 리플레이 도구용 CLI 래퍼.
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/cli/stream_client.py` — 스트리밍 클라이언트용 CLI 래퍼.
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/cli/stream_server.py` — 스트리밍 서버용 CLI 래퍼.

- **data**
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/data/__init__.py` — draco_roundtrip에서 하위 프로세스 헬퍼를 호출할 때 사용하는 래퍼 엔트리포인트.
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/data/bag_to_ply.py` — 공유 bag recorder 유틸리티를 호출.

- **draco**
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/draco/__init__.py` — 모듈 주석 없음
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/draco/encoder.py` — 스트리밍과 배치 유틸리티에서 공유하는 Draco 인코더 헬퍼.

- **io**
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/io/__init__.py` — 모듈 주석 없음
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/io/bag_recorder.py` — ROS2 PointCloud2 → PLY 저장 노드(Open3D 우선, plyfile 폴백).
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/io/ply_codec.py` — PLY 및 포인트 클라우드 유틸리티 헬퍼.

- **net**
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/net/__init__.py` — 모듈 주석 없음
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/net/io.py` — 클라이언트와 서버가 공유하는 소켓 I/O 유틸리티.
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/net/protocol.py` — 클라이언트와 서버가 공유하는 TCP 프로토콜 헬퍼.

- **nodes**
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/__init__.py` — 모듈 주석 없음
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_client.py` — rosbag 프레임을 스트리밍하고 인코딩/전송하며 디코드 결과를 RViz로 재생.
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_server.py` — 제한된 파이프라인과 텔레메트리를 갖춘 비동기 Draco 스트리밍 서버.

- **protocol**
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/protocol/__init__.py` — 스트리밍 클라이언트/서버가 공유하는 프로토콜 헬퍼.
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/protocol/header.py` — 스트리밍 클라이언트와 서버가 공유하는 바이너리 프레이밍 헤더.

- **ros**
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/ros/__init__.py` — 모듈 주석 없음
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/ros/playback.py` — 포인트 클라우드를 퍼블리시하는 ROS 헬퍼 노드.

- **shared_memory**
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/shared_memory/__init__.py` — 제로카피 프레임 캡처를 위한 공유 메모리 전송 헬퍼.
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/shared_memory/channel.py` — 포인트 클라우드 프레임을 위한 TCP 조정 공유 메모리 채널.

- **tools**
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/tools/__init__.py` — 모듈 주석 없음
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/tools/log_collection.py` — 실행 아티팩트를 구조화된 결과 디렉터리에 수집하는 유틸리티.
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/tools/monitor.py` — PLY 페어를 재생하며 ROS로 퍼블리시하고 프레임별 차이 메트릭을 출력.
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/tools/netem.py` — configs/netem.profiles.yaml에 정의된 tc netem 프로파일을 적용하는 헬퍼.
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/tools/replay.py` — 원본/디코드 PLY 페어를 PointCloud2 토픽으로 재생해 RViz 비교를 지원.

- **utils**
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/__init__.py` — 레거시 임포트를 위한 하위 호환 재노출 모듈.
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/config.py` — QoS 오버라이드와 아티팩트 디렉터리를 위한 구성 헬퍼.
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/executable.py` — 필수 외부 실행 파일(draco_encoder/decoder)을 찾는 헬퍼.
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/metrics.py` — 새 패키지의 메트릭 헬퍼를 불러오는 하위 호환 래퍼.
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/ply_io.py` — 새 모듈의 PLY 헬퍼를 재노출하는 하위 호환 래퍼.
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/protocol.py` — 새 모듈의 프로토콜 헬퍼를 재사용하는 하위 호환 래퍼.
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/stream_protocol.py` — docs/contracts/control_plane_contract.md에 맞춘 제어 플레인 헬퍼.
- `ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py` — docs/specs/telemetry_schema.md와 일치하는 텔레메트리 빌더.

### draco_tools

- **analysis**
- `ros2_ws/src/draco_tools/draco_tools/analysis/__init__.py` — 모듈 주석 없음
- `ros2_ws/src/draco_tools/draco_tools/analysis/analyze_draco_quality.py` — PLY(original) vs DRC(Draco) 품질/성능 비교(멀티코어 + 진행바 강화판)
- `ros2_ws/src/draco_tools/draco_tools/analysis/quality.py` — Draco 라운드트립 품질 분석을 위한 공유 헬퍼.

- **cli**
- `ros2_ws/src/draco_tools/draco_tools/cli/__init__.py` — draco_tools 패키지의 콘솔 엔트리포인트.
- `ros2_ws/src/draco_tools/draco_tools/cli/encode_ply_to_draco.py` — 공유 핵심 헬퍼를 재사용하는 배치 인코더 CLI.

- **core**
- `ros2_ws/src/draco_tools/draco_tools/core/__init__.py` — Draco 도구 전반에서 공유하는 핵심 헬퍼.
- `ros2_ws/src/draco_tools/draco_tools/core/encoder.py` — 공유 Draco 인코더 헬퍼와 CLI 바인딩을 노출하는 호환 계층.

### slam_stream_bridge

- **launch**
- `ros2_ws/src/slam_stream_bridge/slam_stream_bridge/launch/bringup.launch.py` — 모듈 주석 없음
- `ros2_ws/src/slam_stream_bridge/slam_stream_bridge/launch/hdl_graph_slam_stream.launch.py` — 모듈 주석 없음
- `ros2_ws/src/slam_stream_bridge/slam_stream_bridge/launch/rtabmap_stream.launch.py` — 모듈 주석 없음
<!-- AUTODOC:MODULE_MAP:END -->
