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

이 개요는 다른 문서를 읽을 때 공통 맥락을 제공하도록 작성되었습니다. 구체적인 절차는 `../guides/`, 체크리스트는 `../checklists/`, 계획/보고서는 각각의 하위 폴더에서 확인하세요.
