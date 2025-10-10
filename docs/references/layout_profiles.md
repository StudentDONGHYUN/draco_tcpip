# 레이아웃 프로필과 데이터 디렉터리 가이드

`draco_roundtrip.utils.config` 모듈은 스트리밍 도구와 배치 파이프라인이 작업 디렉터리를 찾는 방식을 일원화합니다.【F:ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/config.py†L1-L140】 이 문서는 기본 규칙과 사용자 정의 방법을 정리합니다. 전체 코드 구조는 `../references/codebase_overview.md`를 참고하세요.

## 기본 레이아웃
추가 설정이 없을 때 헬퍼는 다음 우선순위로 데이터 루트 경로를 결정합니다.
1. CLI 인자 `--data-root`
2. 활성 레이아웃 프로필에 정의된 `data_root`
3. 환경 변수 `DRACO_DATA_ROOT`
4. 패키지 또는 현재 작업 디렉터리 기준으로 가장 가까운 `data/` 디렉터리(필요 시 생성)

선택된 데이터 루트 아래에는 필요에 따라 다음 하위 디렉터리가 생성됩니다.

| 키 | 기본 하위 디렉터리 |
| --- | --- |
| `ply_stream` | `ply_stream/` |
| `client_work` | `client_tmp/` |
| `decoded_from_server` | `decoded_from_server/` |
| `ply_raw` | `ply_raw/` |
| `draco_out` | `draco_out/` |
| `decoded_tmp` | `tmp_decoded_ply/` |
| `results` | `results/` |
| `server_work` | `server_tmp/` |
| `ros_logs` | `logs/ros/` |

- `stream_client`는 `ply_stream`, `client_work`, `decoded_from_server` 키를 사용합니다.
- `offline_pipeline`은 `ply_raw`, `draco_out`, `decoded_tmp`, `results`를 활용합니다.【F:ros2_ws/src/draco_tools/draco_tools/offline_pipeline.py†L1-L120】
- `ros_logs` 별칭은 실험 로그 수집(`stream_collect_logs`) 시 ROS 2 로그 스냅샷을 보관하는 위치입니다.【F:ros2_ws/src/draco_roundtrip/setup.py†L18-L29】

## 레이아웃 프로필
프로필은 `configs/` 경로 아래 JSON 또는 YAML 형식으로 작성합니다. 헬퍼는 다음 위치를 순서대로 검색합니다.
1. 절대 경로로 지정된 `--layout-profile`
2. 환경 변수 `DRACO_CONFIG_ROOT`에 등록된 디렉터리
3. 설치된 패키지의 공유 디렉터리(`<pkg>/configs/`)
4. 저장소 로컬 `configs/` 디렉터리

최소 JSON 프로필 예시:
```json
{
  "data_root": "../experiment_data",
  "directories": {
    "ply_stream": "stream_cache",
    "client_work": "/var/tmp/draco_client"
  },
  "qos_override": "qos/custom_client.yaml"
}
```
- `data_root`는 절대 경로나 프로필 파일 기준 상대 경로를 모두 허용합니다.
- `directories`에 정의된 항목은 데이터 루트 기준 상대 경로나 절대 경로를 사용할 수 있습니다.
- `qos_override`는 프로필 파일 또는 구성 검색 경로를 기준으로 한 QoS 오버라이드 파일을 가리킵니다.

YAML 프로필도 동일한 필드 이름을 사용하며, `.yaml` 또는 `.yml` 파일을 읽으려면 런타임에 `PyYAML`이 설치되어 있어야 합니다.

## QoS 오버라이드 해석
`resolve_qos_override()`는 명시적인 경로와 `ProfileConfig` 객체를 모두 지원합니다. 우선순위는 다음과 같습니다.
1. CLI에서 전달된 `--qos-override`
2. 활성 레이아웃 프로필에 정의된 `qos_override`
3. 구성 검색 경로에서 처음 발견한 `qos_override.yaml`

bringup 런치(`slam_stream_bridge/launch/bringup.launch.py`)는 위 규칙을 그대로 따라 클라이언트 인자를 생성합니다.【F:ros2_ws/src/slam_stream_bridge/slam_stream_bridge/launch/bringup.launch.py†L15-L83】

## 연관 문서
- 설정 파일 전체 목록: `config_reference.md` (동일 폴더)
- 로그/결과 디렉터리 활용: `../guides/logging_guidelines.md`
- 네트워크 지연 개선 로드맵: `../plans/network_latency_reduction_plan.md`
- 실험 보고 템플릿: `../templates/results_template.md`

프로필을 수정한 뒤에는 `stream_client --layout-profile <file>` 또는 bringup 런치를 실행해 경로가 올바르게 생성되는지 확인하세요. 문제가 있다면 `draco_roundtrip.utils.config`가 출력하는 로그를 참고하면 경로 결정 과정을 추적할 수 있습니다.
