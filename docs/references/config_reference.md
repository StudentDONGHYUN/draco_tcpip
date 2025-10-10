# 설정 파일 참조

`configs/` 디렉터리에 있는 프로파일과 파라미터 파일을 한 곳에서 정리했습니다. 모든 항목은 `draco_roundtrip.utils.config`가 사용하는 검색 규칙(패키지 `share/`, 현재 작업 디렉터리, `DRACO_CONFIG_ROOT` 환경 변수)과 호환됩니다.【F:ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/config.py†L1-L140】 런치 파일(`slam_stream_bridge/launch/bringup.launch.py`)과 CLI가 동일한 헬퍼를 사용하므로, 경로만 맞으면 어디서든 동일하게 불러올 수 있습니다.【F:ros2_ws/src/slam_stream_bridge/slam_stream_bridge/launch/bringup.launch.py†L15-L83】

## 데이터 배치 및 QoS 프로파일

| 파일 | 주요 키 | 설명 |
| --- | --- | --- |
| `client.profile.yaml` | `data_root`, `directories.*`, `qos_override`, `rosbag.topic` | rosbag → 스트리밍 클라이언트 실험에서 사용할 기본 디렉터리 구조와 QoS 파일을 정의합니다. `resolve_data_layout()` 호출 시 `ply_stream`, `client_work`, `decoded_from_server`, `results`, `ros_logs` 경로가 채워집니다. |
| `server.profile.yaml` | `data_root`, `directories.*` | 디코더 서버 측 임시 디렉터리와 공용 결과 폴더를 제공합니다. `stream_server` 실행 시 `--layout-profile server.profile.yaml`로 지정하면 동일한 규칙을 적용할 수 있습니다. |
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
- bringup 런치 역시 위 인자를 내부적으로 구성해 서버/클라이언트 모두 동일한 레이아웃을 사용합니다.【F:ros2_ws/src/slam_stream_bridge/slam_stream_bridge/launch/bringup.launch.py†L34-L76】
- 디렉터리 구조와 결과 정리는 `../guides/logging_guidelines.md`에서 시각적으로 설명합니다.

## 인코더/디코더 기본 옵션
- `draco.json`: `draco_tools.core.encoder.resolve_encoder_options()`가 불러오는 참조 설정입니다. `compression_level`, `quantization_bits`, `speed`를 명시해 CLI와 스트리밍 클라이언트가 동일한 품질/성능 기준을 공유합니다.【F:ros2_ws/src/draco_tools/draco_tools/core/encoder.py†L43-L107】
- `draco_roundtrip/draco/encoder.py`는 환경 변수와 PATH 기반으로 실행 파일을 찾고, 위 설정을 기반으로 Draco 바이너리를 호출합니다.【F:ros2_ws/src/draco_roundtrip/draco_roundtrip/draco/encoder.py†L1-L160】

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
- `ros_topics.yaml`: 스트리밍과 모니터링에서 사용되는 토픽 명칭을 문서화합니다. 런치 파일이나 시각화 스크립트를 작성할 때 참조하면 혼선을 줄일 수 있습니다.
- `stream_client`/`stream_server`가 퍼블리시하는 기본 토픽은 `../references/codebase_overview.md`의 데이터 흐름 섹션에 정리되어 있습니다.

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
- `netem.profiles.yaml`: `stream_netem` CLI가 읽는 네트워크 조건 프리셋을 담습니다. JSON 호환 YAML 형식이라 PyYAML 없이도 파싱됩니다.

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
```

## 연관 문서
- 디렉터리 규칙 및 manifest 예시: `../guides/logging_guidelines.md`
- 레이아웃 프로파일 구조: `../references/layout_profiles.md`
- 네트워크 지연 개선 로드맵: `../plans/network_latency_reduction_plan.md`
- 코드 구조 개요: `../references/codebase_overview.md`

필요한 값을 수정할 때에는 스트리밍 노드와 배치 파이프라인이 동일한 설정을 참조하는지 확인하세요. 변경 사항을 `../templates/results_template.md`에 기록하면 회귀 분석 시 추적이 용이합니다.
