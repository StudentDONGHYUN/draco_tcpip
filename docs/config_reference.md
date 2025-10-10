# 설정 파일 참조

`configs/` 디렉터리에 있는 프로파일과 파라미터 파일을 한 곳에서 정리했습니다. 모든 항목은 `draco_roundtrip.utils.config`가 검색하는 경로 규칙(패키지 `share/`, 현재 작업 디렉터리, `DRACO_CONFIG_ROOT` 환경 변수)과 호환되며, ROS 2 런치 및 CLI에서 같은 이름으로 참조할 수 있습니다.

## 데이터 배치 및 QoS 프로파일

| 파일 | 주요 키 | 설명 |
| --- | --- | --- |
| `client.profile.yaml` | `data_root`, `directories.*`, `qos_override`, `rosbag.topic` | rosbag → 스트리밍 클라이언트 실험에서 사용할 기본 디렉터리 구조와 QoS 파일을 정의합니다. `resolve_data_layout()` 호출 시 `ply_stream`, `client_work`, `decoded_from_server`, `results`, `ros_logs` 경로가 채워집니다. |
| `server.profile.yaml` | `data_root`, `directories.*` | 디코더 서버 측 임시 디렉터리와 공용 결과 폴더를 제공합니다. `stream_server` 런치 또는 CLI에서 `--layout-profile server.profile.yaml`로 재사용할 수 있습니다. |
| `qos_override.yaml` | ROS QoS 정책 | rosbag 재생 시 적용할 QoS 덮어쓰기를 정의합니다. 프로파일에서 `qos_override` 키로 참조하거나 `--qos-override` CLI 인자로 전달합니다. |

### 사용 예시

```bash
# 클라이언트 실행 시 프로파일과 데이터 루트를 명시적으로 지정
ros2 run draco_roundtrip stream_client \
  --bag data/bags/sample.bag \
  --topic /sensing/lidar/top/pointcloud \
  --prefix sample \
  --layout-profile client.profile.yaml \
  --data-root ./data
```

## 인코더/디코더 기본 옵션

- `draco.json`: `draco_tools.core.encoder.resolve_encoder_options()`가 불러오는 참조 설정입니다. `compression_level`, `quantization_bits`, `speed`를 명시해 CLI와 스트리밍 클라이언트가 동일한 품질/성능 기준을 공유합니다.

```json
{
  "encoder": {
    "compression_level": 7,
    "quantization_bits": {
      "position": 14,
      "normal": 10,
      "color": 10
    },
    "speed": {
      "encoding": 5,
      "decoding": 5
    },
    "keep_attributes": ["POSITION", "NORMAL", "COLOR"]
  }
}
```

## ROS 토픽 매핑

- `ros_topics.yaml`: 스트리밍과 모니터링에서 사용되는 토픽 명칭을 문서화합니다. 런치 파일이나 시각화 스크립트를 작성할 때 참조하여 혼선을 줄입니다.

```json
{
  "stream": {
    "source_pointcloud": "/stream_pair/source",
    "decoded_pointcloud": "/stream_pair/decoded",
    "metrics": "/stream_pair/metrics"
  },
  "monitor": {
    "rviz_frame": "lidar_link",
    "playback_topic": "/stream_pair/replay"
  }
}
```

## 네트워크 에뮬레이션 프로파일

- `netem.profiles.yaml`: `stream_netem` CLI가 읽는 네트워크 조건 프리셋을 담습니다. JSON 호환 YAML 형식으로 작성되어 PyYAML 없이도 파싱됩니다.

| 프로파일 | 의미 |
| --- | --- |
| `loopback` | shaping 없이 현재 링크 상태를 유지합니다. |
| `wifi_dense` | 혼잡한 Wi-Fi 환경을 모사합니다 (`delay=45ms`, `loss=0.5%`, `rate=35mbit`). |
| `lte_nominal` | 표준 LTE 업링크 조건을 가정합니다. |
| `satellite_demo` | 고지연 위성 통신 상황을 재현합니다. |
| `clear` | 기존 `tc qdisc` 구성을 제거합니다. |

실행 예시:

```bash
# 루프백 인터페이스에 Wi-Fi 혼잡 프로파일 적용 (명령만 출력)
ros2 run draco_roundtrip stream_netem wifi_dense --iface lo --dry-run

# 실제 적용 후 SLAM 브릿지 런치
sudo ros2 run draco_roundtrip stream_netem wifi_dense --iface eno1 --clear
ros2 launch slam_stream_bridge bringup.launch.py \
  bag:=data/bags/sample.bag topic:=/sensing/lidar/top/pointcloud
```

## SLAM 및 스트리밍 런치 설정

| 파일 | 용도 |
| --- | --- |
| `rtabmap_stream.yaml` | `slam_stream_bridge/launch/rtabmap_stream.launch.py`와 `bringup.launch.py`에서 사용되는 RTAB-Map 매개변수. |
| `hdl_graph_slam_stream.yaml` | HDL Graph SLAM 노드 파라미터. |

`bringup.launch.py`를 이용하면 스트리밍 서버/클라이언트와 선택한 SLAM 파이프라인을 한 번에 띄울 수 있으며, `slam_params:=<경로>` 인자로 다른 파라미터 파일을 적용할 수 있습니다.

## 실험 결과 수집

- `stream_collect_logs` CLI는 `client.profile.yaml`이 정의한 `results`/`ros_logs` 위치를 기준으로 실험 산출물을 정리합니다. 자세한 구조는 `docs/logging_guidelines.md`를 참고하세요.
