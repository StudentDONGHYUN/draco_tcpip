# 서버 중심 스트리밍 실행 가이드

이 가이드는 Draco 업링크를 유지하면서 자율주행 출력을 로봇에 다시 스트리밍하는 서버 중심 아키텍처의 작동 방법을 설명합니다.

## 사전 요구사항

* 클라이언트와 서버 호스트 모두에 ROS 2 Galactic 이상 설치
* Draco 인코더/디코더 바이너리가 `$PATH`에서 찾을 수 있거나 `encoder`/`decoder` ROS 파라미터를 통해 제공됨
* 업링크 및 다운링크 포트를 위한 클라이언트와 서버 간 네트워크 연결성

## 파이프라인 실행

재설계된 양방향 워크플로우는 분산 배포를 가정합니다. 업링크와 다운링크 흐름이 동기화를 유지할 수 있도록 서버와 클라이언트를 각각의 머신에서 실행하세요.

### 서버 PC (업링크/다운링크 허브)

```bash
source /opt/ros/humble/setup.bash
cd /home/kkit/newdisk/draco_tcpip/ros2_ws
source install/setup.bash
ros2 launch draco_roundtrip server.launch.py [port:=5000]
```

* `port`의 기본값은 `5000`입니다. `downlink_port`가 기본값 `0`으로 설정된 경우, 서버는 제어 평면 링크에 대해 `port + 1`을 사용합니다.
* 다른 제어 소켓을 노출해야 하는 경우 `downlink_port`를 명시적으로 설정할 수 있습니다(예: `downlink_port:=6001`).
* 이 명령은 디코딩과 분석을 수행하는 고성능 서버에서 실행하세요.

### 클라이언트 PC (로봇)

```bash
source /opt/ros/humble/setup.bash
cd /home/kkit/newdisk/draco_tcpip/ros2_ws
source install/setup.bash
ros2 launch draco_roundtrip client.launch.py \
  server_host:=192.168.3.16 \
  server_port:=5000 \
  bag_file:=/home/kkit/newdisk/draco_tcpip/ros2_ws/data/bags/rosbag2_2024_09_24-14_28_57 \
  topic_name:=/sensing/lidar/top/pointcloud \
  prefix:=client_test
```

* `server_host`는 필수이며 네트워크를 통해 접근 가능한 서버 PC를 가리켜야 합니다. 
  동일한 주소가 다운링크 연결에도 재사용됩니다.
* `server_port`의 기본값은 `5000`입니다. 클라이언트는 다운링크를 위해 자동으로 
  `server_port + 1`에서 수신 대기합니다.
* `bag_file`은 재생할 rosbag2 디렉터리나 데이터베이스 파일을 가리켜야 합니다.
* `topic_name`은 bag 내의 `sensor_msgs/msg/PointCloud2` 토픽을 선택합니다.
* 추가 실행 인자는 ROS 2 파라미터에 직접 매핑됩니다. 예: `work_dir:=/mnt/tmp` 또는 
  `telemetry_rate:=5.0`

이제 노드들은 사용자 정의 CLI 플래그 대신 ROS 2 파라미터에 전적으로 의존합니다. 
여러 설정을 한 번에 덮어쓰려면 `--ros-args --params-file path/to/custom.yaml`로 YAML 파일을 
제공하거나 `ros2 launch ... telemetry_rate:=5.0 heartbeat_interval:=2.0`와 같이 
실행 인자를 쌓아서 사용하세요.

하트비트 메시지는 다운링크를 활성 상태로 유지합니다. 위성통신 링크를 위해 하트비트 간격을 
늘리려면 다음과 같이 환경변수를 설정하세요:

```bash
export ROS_ARGUMENTS='--ros-args --params-file path/to/custom.yaml'
```

또는 클라이언트 파라미터를 조정하는 오버라이드 YAML로 실행하세요.

## 텔레메트리

클라이언트는 기본적으로 각 `cmd_vel` 메시지의 미리보기를 로그로 남깁니다. `ClientBridge` 
후크를 수정하거나 모터 컨트롤러 노드에 연결하여 사용자 정의 실행 콜백을 제공할 수 있습니다.

## 문제 해결

* **다운링크 패킷 없음:** 클라이언트가 하트비트를 보내고 있는지 확인하세요. 서버는 
  활동이 없는 상태로 하트비트 간격의 2배가 지나면 전송을 중단합니다.
* **레거시 워크플로우:** 서버를 `legacy_downlink:=true`로 실행하고 클라이언트가 디코딩된 
  디렉터리를 가리키도록 유지하세요. 다른 변경은 필요 없습니다.
* **과대 크기 경로:** 플래너가 궤적을 200개 이하의 포즈로 제한하도록 하세요. 그렇지 않으면 
  서버가 업데이트를 삭제합니다.
