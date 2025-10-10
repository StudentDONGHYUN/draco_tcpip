# 3D LiDAR SLAM (HDL Graph SLAM) Integration

이 문서는 `/stream_pair/decoded` 포인트클라우드를 이용해 3D 맵을 생성하는 방법을 정리한 것입니다. 아래 단계는 ROS 2 Humble + `hdl_graph_slam` 패키지를 기준으로 설명합니다.

## 1. 의존성 설치

```bash
sudo apt update
sudo apt install ros-humble-hdl-graph-slam
```

## 2. 구성 파일 확인

- 파라미터 파일: `configs/hdl_graph_slam_stream.yaml` (세부 설명은 `docs/config_reference.md` 참고)
  - 입력 토픽은 `/stream_pair/decoded`
  - 프레임 이름: `lidar_link` (스트리밍 클라이언트 실행시 `--play-frame-id` 옵션과 맞춰야 합니다.)
  - 다운샘플링이나 NDT 설정은 환경에 따라 조절 가능합니다.

## 3. SLAM 실행

터미널에서 다음 명령을 실행하면 HDL Graph SLAM 노드가 시작됩니다.

```bash
source /opt/ros/humble/setup.bash
cd /path/to/draco_tcpip/ros2_ws
source install/setup.bash  # `colcon build --symlink-install` 이후 한 번만 필요
ros2 launch slam_stream_bridge hdl_graph_slam_stream.launch.py
```

만약 다른 파라미터 파일을 사용하고 싶다면 `params_file` 인자를 덮어쓰면 됩니다.

```bash
ros2 launch slam_stream_bridge hdl_graph_slam_stream.launch.py \
  params_file:=/path/to/custom.yaml
```

## 4. 포인트클라우드 공급

`draco_roundtrip` 패키지의 스트리밍 서버/클라이언트를 사용하면 `/stream_pair/decoded` 토픽으로 복원된 포인트클라우드를 퍼블리시합니다. rosbag 테스트 시 QoS를 `BEST_EFFORT`로 맞춰 주세요 (`configs/qos_override.yaml`).

실행 순서 예시:

1. 스트리밍 서버 실행 `ros2 run draco_roundtrip stream_server`
2. 스트리밍 클라이언트 실행 `ros2 run draco_roundtrip stream_client --bag <rosbag_dir> --topic <cloud_topic>` (또는 라이브 토픽 사용)
3. SLAM Launch 실행 (위 명령)

통합 bringup을 사용해 스트리밍과 SLAM을 한 번에 띄울 수도 있습니다.

```bash
ros2 launch slam_stream_bridge bringup.launch.py \
  bag:=/data/bags/sample.bag \
  topic:=/sensing/lidar/top/pointcloud \
  slam:=hdl \
  netem_profile:=wifi_dense
```
- bringup 런치는 `stream_server`, `stream_client`, 선택된 SLAM 노드, 그리고 필요 시 `stream_netem`을 순차적으로 호출합니다.
- `netem_profile`은 dry-run 모드가 기본이므로, 실제로 `tc`를 적용하려면 `netem_dry_run:=false`와 관리자 권한이 필요합니다.

## 5. RViz 확인

- Fixed Frame: `map`
- PointCloud2 디스플레이로 `/hdl_graph_slam/map_points` (혹은 `/map`) 등을 확인하면 누적된 맵을 볼 수 있습니다.
- TF 트리에서 `map -> lidar_link` 변환이 생성됩니다.

## 6. 맵 저장

HDL Graph SLAM은 `/hdl_graph_slam/save_map` 서비스를 제공합니다.

```bash
ros2 service call /hdl_graph_slam/save_map hdl_graph_slam/srv/SaveMap "{filename: '/tmp/stream_map.pcd'}"
```

필요하면 Occupancy Grid 형태로 변환하거나 후처리(Downsample, Crop 등)를 Open3D/PCL에서 수행할 수 있습니다.

## 7. 팁

- 포인트 수가 많아 SLAM이 느리면 `configs/hdl_graph_slam_stream.yaml`의 `voxel_leaf_size` 값을 키우거나 `ros2 run draco_roundtrip stream_client` 실행 시 `--play-sample` 값을 낮춰 입력 포인트를 줄이세요.
- IMU/ODOM 등의 센서가 있을 경우 파라미터 파일에서 해당 토픽을 지정하면 정합 성능이 좋아집니다.

## 8. RTAB-Map 기반 LiDAR SLAM

HDL Graph SLAM 대신 RTAB-Map을 사용해도 `/stream_pair/decoded` 토픽을 그대로 활용해 3D 맵을 생성할 수 있습니다. RTAB-Map은 loop closure 및 그래프 최적화 기능이 풍부해 장시간 주행 시 재방문 감지에 강점이 있습니다.

### 1) 의존성 설치

```bash
sudo apt update
sudo apt install ros-humble-rtabmap-ros ros-humble-rtabmap-launch ros-humble-rtabmap-slam ros-humble-rtabmap-odom
```

### 2) 구성 파일 확인

- 파라미터 파일: `configs/rtabmap_stream.yaml`
  - `rtabmap` 노드와 `icp_odometry` 노드의 공통 프레임은 `lidar_link`
  - 입력 포인트클라우드 토픽은 런치 파일에서 기본 `/stream_pair/decoded`로 remap 됩니다.
- 필요 시 `Grid/CellSize`, `Icp/VoxelSize` 등을 조정해 다운샘플링 강도를 변경합니다.

### 3) SLAM 실행

```bash
source /opt/ros/humble/setup.bash
cd /path/to/draco_tcpip/ros2_ws
source install/setup.bash
ros2 launch slam_stream_bridge rtabmap_stream.launch.py
```

주요 런치 인자:

- `cloud_topic`: 기본 `/stream_pair/decoded`. 다른 토픽을 사용하려면 `cloud_topic:=/my/point_cloud` 형태로 지정합니다.
- `params_file`: 필요 시 RTAB-Map 파라미터 YAML 파일 경로를 덮어씁니다.
- `use_sim_time`: 시뮬레이션/rosbag 재생 시 `true`로 설정합니다.

### 4) 포인트클라우드 공급 및 결과 확인

- 기존과 동일하게 스트리밍 서버/클라이언트 또는 rosbag 재생으로 `/stream_pair/decoded`를 퍼블리시합니다.
- RTAB-Map 노드는 `/map` TF와 누적 점군 `/rtabmap/map_data` 등을 퍼블리시합니다. RViz에서 Fixed Frame을 `map`으로 설정하고 `/rtabmap/map_data` 또는 `/rtabmap/cloud_map`을 시각화하세요.

### 5) 맵 저장

데이터베이스(`~/.ros/rtabmap.db`)에는 그래프와 포인트맵이 저장됩니다. 필요하면 다음 서비스를 호출해 누적 점군을 PCD로 덤프할 수 있습니다.

```bash
ros2 service call /rtabmap/save_map rtabmap_msgs/srv/SaveMap "{output: '/tmp/rtabmap_stream_map.pcd', binary: true, cloud: true, ground: true, obstacles: true}"
```

서비스 호출 전 `ros2 service list | grep save_map`으로 서비스가 준비되었는지 확인하세요.
