<!-- Path: docs/guides/3d_slam_setup.md -->

# 3D LiDAR SLAM(HDL Graph SLAM) 통합 가이드

통합 bringup 런치(`slam_stream_bridge/launch/bringup.launch.py`)는 `draco_roundtrip` 스트리밍 결과를 SLAM 파이프라인으로 바로 전달합니다. 이 문서는 HDL Graph SLAM을 기준으로 필요한 파일과 명령, 그리고 관련 코드 위치를 정리합니다. 코드베이스 구성은 `../references/codebase_overview.md`에서 확인할 수 있습니다.

## 1. 의존성 설치
```bash
sudo apt update
sudo apt install ros-humble-hdl-graph-slam
```

## 2. 구성 파일 확인
- 파라미터 파일: `configs/hdl_graph_slam_stream.yaml` (세부 필드는 `../references/config_reference.md` 참고)
  - 입력 토픽: `/stream_pair/decoded`
  - 프레임 이름: `lidar_link` — 스트리밍 클라이언트 실행 시 `--play-frame-id` 옵션과 일치해야 합니다.
  - 다운샘플링 및 NDT 설정은 환경에 맞게 조정합니다.
- 통합 런치 내부 동작: `slam_stream_bridge/launch/bringup.launch.py`에서 `resolve_data_layout`/`resolve_qos_override`를 호출해 프로파일 기반 디렉터리와 QoS 설정을 적용합니다.【F:ros2_ws/src/slam_stream_bridge/slam_stream_bridge/launch/bringup.launch.py†L15-L83】

## 3. SLAM 실행
다음 명령을 실행하면 HDL Graph SLAM 노드가 스트리밍 파이프라인과 함께 시작됩니다.
```bash
source /opt/ros/humble/setup.bash
cd /path/to/draco_tcpip/ros2_ws
source install/setup.bash
ros2 launch slam_stream_bridge bringup.launch.py \
  bag:=/path/to/bag \
  topic:=/sensing/lidar/top/pointcloud \
  layout_profile:=client.profile.yaml \
  slam:=hdl
```
- `slam_params` 인자를 사용하면 임의의 파라미터 파일로 덮어쓸 수 있습니다.
- bringup 런치는 내부에서 `stream_server`/`stream_client` 노드를 실행해 `/stream_pair/decoded` 토픽을 퍼블리시합니다.【F:ros2_ws/src/slam_stream_bridge/slam_stream_bridge/launch/bringup.launch.py†L84-L128】

## 4. 포인트클라우드 공급 및 QoS
- `stream_client`는 bag 재생 시 QoS override 파일을 적용합니다. 기본 경로는 `configs/qos_override.yaml`이며, 프로파일(`client.profile.yaml`)에서도 `qos_override`를 지정할 수 있습니다.
- QoS/프로파일 항목은 `../references/layout_profiles.md`와 `../references/config_reference.md`에 정리되어 있습니다.
- bringup 런치에서 `qos_override` 인자를 제공하면 `resolve_qos_override`가 자동으로 해석해 클라이언트에 전달합니다.

## 5. 결과 정리
- 실험 종료 후 `stream_collect_logs` CLI로 결과를 정리하면 SLAM 로그(`ros_logs/`), 아티팩트(`artifacts/`)가 함께 보관됩니다.
- 디렉터리 구조와 manifest 형식은 `logging_guidelines.md`(동일 폴더)를 참고하세요.

### 관련 코드 살펴보기
- 런치 로직: `ros2_ws/src/slam_stream_bridge/slam_stream_bridge/launch/`
- 스트리밍 노드: `ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/`
- 레이아웃/QoS 헬퍼: `ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/config.py`
