# 구성 참조
Draco Roundtrip 노드·도구·런치 파일에서 사용하는 실행 프로파일, 디렉터리 구조, CLI 기본값을 한곳에 정리합니다.
_마지막 업데이트: 2025-03-15_

**목차**
- [구성 검색 규칙](#구성-검색-규칙)
- [레이아웃 프로파일과 디렉터리](#레이아웃-프로파일과-디렉터리)
- [CLI 플래그 매트릭스](#cli-플래그-매트릭스)
- [사용 예시](#사용-예시)
- [관련 문서](#관련-문서)

## 구성 검색 규칙
`draco_roundtrip.utils.config`는 다음 우선순위로 프로파일과 QoS 오버라이드를 로드합니다.
1. 명시적 CLI 인자(`--layout-profile`, `--qos-override`).
2. 활성 프로파일 파일 기준의 상대 경로.
3. `DRACO_CONFIG_ROOT`에 나열된 디렉터리.
4. 설치된 패키지의 share 디렉터리(`/<pkg>/configs/`).
5. 저장소 `configs/` 디렉터리 또는 가장 가까운 `data/` 루트.

헬퍼 함수는 디렉터리 존재 여부를 확인하고(`ensure_directory`), 패키지가 얕은 site-packages에 설치되었더라도 경로를 정규화합니다. `slam_stream_bridge` 런치 파일도 동일한 헬퍼를 사용해 ROS 2 노드와 CLI 도구가 같은 방식으로 프로파일을 해석합니다.

## 레이아웃 프로파일과 디렉터리
레이아웃 프로파일은 표준 실험 파일 시스템을 정의하며, 키는 결정된 `data_root` 아래의 하위 디렉터리에 매핑됩니다.

| 키 | 기본 하위 디렉터리 | 용도 |
|-----|----------------------|---------------|
| `ply_stream` | `ply_stream/` | 스트리밍 클라이언트 PLY 캐시 |
| `client_work` | `client_tmp/` | Draco 인코더 임시 작업 공간 |
| `decoded_from_server` | `decoded_from_server/` | 클라이언트가 저장하는 서버 응답 |
| `ply_raw` | `ply_raw/` | 오프라인 파이프라인 원본 PLY 출력 |
| `draco_out` | `draco_out/` | 일괄 Draco 아카이브 |
| `decoded_tmp` | `tmp_decoded_ply/` | 디코드 작업용 임시 영역 |
| `results` | `results/` | 실험 매니페스트 및 메트릭 |
| `server_work` | `server_tmp/` | 서버 측 임시 파일 |
| `ros_logs` | `logs/ros/` | 실행 후 수집한 ROS 2 로그 스냅샷 |

프로파일 작성 팁:
- JSON과 YAML 프로파일은 동일한 스키마를 사용하며, 상대 경로는 프로파일 위치를 기준으로 해석됩니다.
- `data_root`가 지정되지 않으면 `DRACO_DATA_ROOT` 또는 가장 가까운 `data/` 디렉터리를 사용합니다.
- QoS 오버라이드는 `resolve_qos_override`를 통해 동일한 검색 규칙을 따릅니다.

## CLI 플래그 매트릭스
| Flag | Client Default | Server Default | 설명 | Primary Reference |
|------|----------------|----------------|-------------|-------------------|
| `--transport {tcp,quic,udp_fec}` | `tcp` | `tcp` | 전송 백엔드를 선택합니다. 현재는 `tcp`만 활성화되어 있으며 다른 값은 `NotImplementedError`를 발생시킵니다. | [아키텍처 설계 및 지연 시간 계획](../architecture/Architectural_Design_and_Plan.md) |
| `--protocol {legacy,binary}` | `binary` | `binary` | 프레이밍 형식을 선택합니다. `binary`는 제어 플레인 계약에 따라 MTU 안전 헤더와 제한 큐를 사용합니다. | [프로토콜 및 스키마 참조](../reference/Protocol_and_Schema_Reference.md) |
| `--tx-fragment-size` | `0` (비활성) | `0` | MTU 안전 조각 크기(바이트). 허용 범위 256–1400. | [프로토콜 및 스키마 참조](../reference/Protocol_and_Schema_Reference.md) |
| `--ack-timeout` | `0.5` s | n/a | RTT EMA가 수렴하기 전 기본 ACK 타임아웃. | [프로토콜 및 스키마 참조](../reference/Protocol_and_Schema_Reference.md) |
| `--ack-timeout-min` | `0.5` s | n/a | 적응형 ACK 타임아웃 하한. | [프로토콜 및 스키마 참조](../reference/Protocol_and_Schema_Reference.md) |
| `--ack-timeout-max` | `2.0` s | n/a | 적응형 ACK 타임아웃 상한. | [프로토콜 및 스키마 참조](../reference/Protocol_and_Schema_Reference.md) |
| `--ack-timeout-strikes` | `3` | n/a | 실패로 간주하기 전 허용하는 연속 타임아웃 횟수. | [프로토콜 및 스키마 참조](../reference/Protocol_and_Schema_Reference.md) |
| `--socket-buffer-autotune` | `False` | `False` | 커널 버퍼 자동 튜닝(`SO_RCVBUF`/`SO_SNDBUF`=0)을 요청합니다. | [아키텍처 설계 및 지연 시간 계획](../architecture/Architectural_Design_and_Plan.md) |
| `--metrics-out` | `artifacts/perf/client_latest.json` | `artifacts/perf/server_latest.json` | 스키마를 준수해야 하는 텔레메트리 JSON 출력 경로. | [프로토콜 및 스키마 참조](../reference/Protocol_and_Schema_Reference.md) |

새 플래그를 도입할 때는 이 매트릭스를 갱신하고 CLI 기본값, 도움말, 회귀 문서를 코드 변경과 함께 맞춰야 합니다.

## 사용 예시
명시적인 레이아웃 프로파일과 QoS 오버라이드로 클라이언트를 설정합니다.
```bash
ros2 run draco_roundtrip stream_client \
  --bag data/bags/sample.bag \
  --topic /sensing/lidar/top/pointcloud \
  --prefix sample \
  --layout-profile client.profile.yaml \
  --data-root ./data \
  --qos-override configs/qos_override.yaml
```
bringup 런치는 동일한 헬퍼를 사용하므로 `layout_profile:=client.profile.yaml`, `qos_override:=configs/qos_override.yaml`을 전달하면 해석된 경로가 클라이언트와 서버 노드에 동일하게 적용됩니다.

## 관련 문서
- [프로토콜 및 스키마 참조](../reference/Protocol_and_Schema_Reference.md)
- [아키텍처 설계 및 지연 시간 계획](../architecture/Architectural_Design_and_Plan.md)
- [개발 프로세스](../development/Development_Process.md)
- [사용자 가이드](../guides/User_Guide.md)

## 자동 생성 구성 매트릭스
<!-- AUTODOC:CONFIG_KEYS:BEGIN -->
### CLI 플래그

| 명령 | 플래그 | 유형 | 기본값 | 필수 여부 | 설명 | 소스 |
| - | - | - | - | - | - | - |
| encode_ply_to_draco | --in | str | ./ply_raw | no | 입력 PLY 디렉터리 (기본: ./ply_raw) | ros2_ws/src/draco_tools/draco_tools/cli/encode_ply_to_draco.py:26 |
| encode_ply_to_draco | --log-csv | str |  | no | 프레임별 인코드 시간 로그 CSV | ros2_ws/src/draco_tools/draco_tools/cli/encode_ply_to_draco.py:39 |
| encode_ply_to_draco | --name | str |  | no | 대상 접두어(prefix). 지정 시 '<name>_*.ply'만 인코딩 | ros2_ws/src/draco_tools/draco_tools/cli/encode_ply_to_draco.py:28 |
| encode_ply_to_draco | --out | str | ./draco_out | no | 출력 DRC 디렉터리 (기본: ./draco_out) | ros2_ws/src/draco_tools/draco_tools/cli/encode_ply_to_draco.py:27 |
| encode_ply_to_draco | --workers | int | os.cpu_count() or 4 | no | 병렬 작업 수 | ros2_ws/src/draco_tools/draco_tools/cli/encode_ply_to_draco.py:29 |
| offline_pipeline | --bag | str |  | no | rosbag 디렉터리(메타/DB3 포함). 비우면 재생 안 함 | ros2_ws/src/draco_tools/draco_tools/offline_pipeline.py:176 |
| offline_pipeline | --bag-args | str | [] | no | ros2 bag play 추가 인자 | ros2_ws/src/draco_tools/draco_tools/offline_pipeline.py:180 |
| offline_pipeline | --bag-loop | bool | False | no |  | ros2_ws/src/draco_tools/draco_tools/offline_pipeline.py:178 |
| offline_pipeline | --bag-rate | float | 1.0 | no |  | ros2_ws/src/draco_tools/draco_tools/offline_pipeline.py:177 |
| offline_pipeline | --bag-remap | str |  | no | ros2 bag play의 remap 규칙 문자열 | ros2_ws/src/draco_tools/draco_tools/offline_pipeline.py:179 |
| offline_pipeline | --bag-warmup-sec | float | 0.0 | no |  | ros2_ws/src/draco_tools/draco_tools/offline_pipeline.py:181 |
| offline_pipeline | --best-effort | bool | False | no |  | ros2_ws/src/draco_tools/draco_tools/offline_pipeline.py:192 |
| offline_pipeline | --cl | int | DEFAULT_CL | no |  | ros2_ws/src/draco_tools/draco_tools/offline_pipeline.py:199 |
| offline_pipeline | --data-root | str |  | no | 생성된 아티팩트 기본 디렉터리(프로파일/데이터 루트를 덮어씀) | ros2_ws/src/draco_tools/draco_tools/offline_pipeline.py:188 |
| offline_pipeline | --decoded-dir | str |  | no | 임시 디코드 디렉터리 덮어쓰기 | ros2_ws/src/draco_tools/draco_tools/offline_pipeline.py:211 |
| offline_pipeline | --decoder | str | draco_decoder | no |  | ros2_ws/src/draco_tools/draco_tools/offline_pipeline.py:204 |
| offline_pipeline | --drc-dir | str |  | no | Draco 출력 디렉터리 덮어쓰기 | ros2_ws/src/draco_tools/draco_tools/offline_pipeline.py:209 |
| offline_pipeline | --encoder-extra | str | [] | no | draco_encoder에 넘길 추가 인자 문자열 (예: '--speed 10') | ros2_ws/src/draco_tools/draco_tools/offline_pipeline.py:233 |
| offline_pipeline | --fast-preset | bool | False | no | 30FPS 목표용 빠른 설정 적용 | ros2_ws/src/draco_tools/draco_tools/offline_pipeline.py:235 |
| offline_pipeline | --force-tqdm | bool | False | no | QA 단계(analyze_draco_quality.py)에서 tqdm 강제 표시 | ros2_ws/src/draco_tools/draco_tools/offline_pipeline.py:239 |
| offline_pipeline | --jobs | int | 1 | no |  | ros2_ws/src/draco_tools/draco_tools/offline_pipeline.py:202 |
| offline_pipeline | --keep-decoded | bool | False | no | QA 단계에서 디코드 PLY를 삭제하지 않음 | ros2_ws/src/draco_tools/draco_tools/offline_pipeline.py:223 |
| offline_pipeline | --layout-profile | str |  | no | 디렉터리 해석에 사용할 레이아웃 프로파일 이름 또는 경로 | ros2_ws/src/draco_tools/draco_tools/offline_pipeline.py:186 |
| offline_pipeline | --max-frames | int | 0 | no | 0=무제한 (bag 끝날 때까지) | ros2_ws/src/draco_tools/draco_tools/offline_pipeline.py:190 |
| offline_pipeline | --no-qa | bool | False | no | 품질 분석 단계 생략 | ros2_ws/src/draco_tools/draco_tools/offline_pipeline.py:236 |
| offline_pipeline | --ply-dir | str |  | no | 원본 PLY 출력 디렉터리 덮어쓰기 | ros2_ws/src/draco_tools/draco_tools/offline_pipeline.py:207 |
| offline_pipeline | --prefix | str |  | yes |  | ros2_ws/src/draco_tools/draco_tools/offline_pipeline.py:185 |
| offline_pipeline | --qg | int | DEFAULT_QG | no |  | ros2_ws/src/draco_tools/draco_tools/offline_pipeline.py:201 |
| offline_pipeline | --qp | int | DEFAULT_QP | no |  | ros2_ws/src/draco_tools/draco_tools/offline_pipeline.py:200 |
| offline_pipeline | --results-dir | str |  | no | 결과 집계 디렉터리 덮어쓰기 | ros2_ws/src/draco_tools/draco_tools/offline_pipeline.py:213 |
| offline_pipeline | --reuse-drc | bool | False | no | 기존 DRC를 재사용(재인코딩 생략) | ros2_ws/src/draco_tools/draco_tools/offline_pipeline.py:224 |
| offline_pipeline | --rmw-impl | str |  | no | 하위 프로세스에 전달할 RMW_IMPLEMENTATION 덮어쓰기 | ros2_ws/src/draco_tools/draco_tools/offline_pipeline.py:218 |
| offline_pipeline | --ros-domain-id | int |  | no | 하위 프로세스에 전달할 ROS_DOMAIN_ID 덮어쓰기 | ros2_ws/src/draco_tools/draco_tools/offline_pipeline.py:216 |
| offline_pipeline | --ros-localhost-only | str |  | no | 하위 프로세스에 전달할 ROS_LOCALHOST_ONLY 값 Choices: 0, 1 | ros2_ws/src/draco_tools/draco_tools/offline_pipeline.py:220 |
| offline_pipeline | --saver-timeout | float | 180.0 | no | bag_to_ply 단계의 전체 타임아웃(초). 0은 비활성 | ros2_ws/src/draco_tools/draco_tools/offline_pipeline.py:227 |
| offline_pipeline | --saver-voxel-size | float | 0.0 | no | bag_to_ply 복셀 다운샘플 크기(m) | ros2_ws/src/draco_tools/draco_tools/offline_pipeline.py:225 |
| offline_pipeline | --thresholds | float | [0.01, 0.03, 0.05] | no |  | ros2_ws/src/draco_tools/draco_tools/offline_pipeline.py:203 |
| offline_pipeline | --topic | str |  | yes |  | ros2_ws/src/draco_tools/draco_tools/offline_pipeline.py:184 |
| stream_client | --ack-timeout | float | 0.5 | no | 적응 조정 이전의 기본 ACK 타임아웃(초, 최소값) | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_client.py:1807 |
| stream_client | --ack-timeout-max | float | 2.0 | no | 적응형 ACK 타임아웃 상한(초) | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_client.py:1819 |
| stream_client | --ack-timeout-min | float | 0.5 | no | 적응형 ACK 타임아웃 하한(초) | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_client.py:1813 |
| stream_client | --ack-timeout-strikes | int | 3 | no | 세션 실패 전 허용할 연속 ACK 타임아웃 횟수 | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_client.py:1825 |
| stream_client | --adaptive-window | bool | False | no | RTT/처리량 기반 TX 윈도 적응 기능 활성화 | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_client.py:1801 |
| stream_client | --bag | str |  | yes |  | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_client.py:1728 |
| stream_client | --best-effort | bool | False | no |  | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_client.py:1752 |
| stream_client | --capture-queue | int | 4 | no | 백프레셔를 적용하기 전 허용되는 최대 캡처 큐 깊이 | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_client.py:1831 |
| stream_client | --capture-transport | str | shared-memory | no | 캡처 백엔드 선택: 파일 시스템 스풀(레거시) 또는 공유 메모리 제로카피 (선택지: filesystem, shared-memory) | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_client.py:1844 |
| stream_client | --control-port | int | 0 | no | 전용 제어 플레인 연결을 위한 TCP 포트(0은 비활성) | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_client.py:1765 |
| stream_client | --data-root | str |  | no | 생성된 아티팩트 기본 디렉터리(프로파일/데이터 루트를 덮어씀) | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_client.py:1733 |
| stream_client | --decoded-dir | str |  | no | 서버에서 받은 디코드 프레임 저장 디렉터리 덮어쓰기 | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_client.py:1755 |
| stream_client | --encode-workers | int | 2 | no | 비동기 파이프라인 인코더 워커 수 | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_client.py:1833 |
| stream_client | --heartbeat-timeout | float | 10.0 | no | 해당 시간(초) 동안 ACK/하트비트가 없으면 세션 실패 | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_client.py:1805 |
| stream_client | --idle-timeout | float | 10.0 | no |  | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_client.py:1750 |
| stream_client | --initial-inflight | int |  | no | 적응 제어가 조정하기 전 초기 TX 윈도(기본은 최대) | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_client.py:1799 |
| stream_client | --layout-profile | str |  | no | 레이아웃 프로파일 이름 또는 경로(configs/*.profile.{yaml,json}) | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_client.py:1731 |
| stream_client | --max-frames | int | 0 | no |  | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_client.py:1751 |
| stream_client | --max-inflight, --max-pending | int | 4 | no | ACK/디코드 응답을 기다리는 최대 동시 프레임 수 | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_client.py:1797 |
| stream_client | --metrics-out, --telemetry-out | str | artifacts/perf/client_latest.json | no | 텔레메트리 JSON 출력 경로 (스키마 준수). | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_client.py:1848 |
| stream_client | --metrics-sample | int | 50000 | no | 클라이언트 메트릭 계산에 사용할 최대 포인트 수(0은 전체 사용) | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_client.py:1771 |
| stream_client | --no-save-decoded | bool | False | no | 서버에서 받은 디코드 응답을 디스크에 저장하지 않음 | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_client.py:1761 |
| stream_client | --play-frame-id | str | lidar_link | no |  | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_client.py:1767 |
| stream_client | --play-hz | float | 10.0 | no |  | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_client.py:1769 |
| stream_client | --play-sample | int | 50000 | no |  | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_client.py:1770 |
| stream_client | --play-topic-prefix | str | stream_pair | no |  | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_client.py:1768 |
| stream_client | --ply-dir | str |  | no | 캡처한 PLY 스풀 디렉터리 덮어쓰기 | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_client.py:1735 |
| stream_client | --prefix | str |  | yes |  | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_client.py:1730 |
| stream_client | --print-metrics | bool | False | no | 재생 중 프레임별 지연/정확도 메트릭을 표준 출력으로 송출 | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_client.py:1855 |
| stream_client | --protocol | str | binary | no | 사용할 프레이밍 프로토콜(기본: %(default)s). `protocol_help`에서 제공하는 설명과 함께 선택지를 나열 | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_client.py:1780 |
| stream_client | --qos-override | str |  | no | QoS 프로파일 파일 덮어쓰기(기본은 레이아웃 프로파일 또는 패키지 설정) | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_client.py:1775 |
| stream_client | --quality-report-dir | str | artifacts/quality | no | 프레임별 품질 JSONL 보고서를 저장할 디렉터리 | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_client.py:1759 |
| stream_client | --quality-thresholds | str | {} | no | 품질 메트릭 허용 최대 편차를 정의하는 JSON 객체(비어 있으면 정보용) | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_client.py:1757 |
| stream_client | --resp-format | str | ply | no | 서버가 반환하는 디코드 페이로드 형식(기본: %(default)s) 선택지: ply, pcd | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_client.py:1773 |
| stream_client | --server-host | str | 127.0.0.1 | no |  | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_client.py:1763 |
| stream_client | --server-port | int | 5000 | no |  | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_client.py:1764 |
| stream_client | --socket-buffer-autotune | bool | False | no | 커널 소켓 버퍼 자동 튜닝을 요청한다 (SO_SNDBUF/SO_RCVBUF=0). | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_client.py:1839 |
| stream_client | --socket-buffer-kb | int | 0 | no | 고속 링크 포화를 위해 소켓 송수신 버퍼 크기(KiB) 조정 | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_client.py:1837 |
| stream_client | --socket-timeout | float | 15.0 | no | 소켓 연산 타임아웃(초). 0은 보호 기능 비활성 | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_client.py:1777 |
| stream_client | --spool-gc-window | int | 0 | no | 파일 시스템 스풀 스캔 시 기억할 최대 항목 수(0은 무제한) | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_client.py:1737 |
| stream_client | --tcp-nodelay | bool | False | no | 대화형 재생 지연을 줄이기 위해 Nagle 집계를 비활성 | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_client.py:1835 |
| stream_client | --topic | str |  | yes |  | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_client.py:1729 |
| stream_client | --transport | str | tcp | no | Transport layer for data plane. tcp만 구현되어 있으며 quic/udp_fec는 예약 상태입니다. Choices: tcp, quic, udp_fec | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_client.py:1785 |
| stream_client | --tx-fragment-size | int | 0 | no | Binary 프로토콜에서 payload를 MTU 안전 조각으로 분할한다 (0은 비활성). | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_client.py:1791 |
| stream_client | --window-ema-alpha | float | 0.2 | no | 적응형 윈도 텔레메트리 EMA 평활 계수(0–1) | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_client.py:1803 |
| stream_client | --work-dir | str |  | no | 인코더 임시 데이터 디렉터리 덮어쓰기 | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_client.py:1753 |
| stream_collect_logs | --attach | str | [] | no | artifacts/에 추가로 복사할 파일 또는 디렉터리 | ros2_ws/src/draco_roundtrip/draco_roundtrip/tools/log_collection.py:84 |
| stream_collect_logs | --data-root | str |  | no | 데이터 루트를 덮어쓰기 | ros2_ws/src/draco_roundtrip/draco_roundtrip/tools/log_collection.py:81 |
| stream_collect_logs | --layout-profile | str |  | no | 디렉터리를 해석할 때 사용할 레이아웃 프로파일 | ros2_ws/src/draco_roundtrip/draco_roundtrip/tools/log_collection.py:80 |
| stream_collect_logs | --metadata | str | [] | no | 매니페스트에 기록할 키=값 메타데이터 | ros2_ws/src/draco_roundtrip/draco_roundtrip/tools/log_collection.py:82 |
| stream_collect_logs | --notes | str |  | no | notes/README.txt에 기록할 자유 형식 노트 | ros2_ws/src/draco_roundtrip/draco_roundtrip/tools/log_collection.py:85 |
| stream_collect_logs | --ros-log | str | [] | no | 보관할 ROS 로그 디렉터리 경로 | ros2_ws/src/draco_roundtrip/draco_roundtrip/tools/log_collection.py:83 |
| stream_collect_logs | run_id | str |  | no | 실험 실행 식별자(디렉터리 이름으로 사용) | ros2_ws/src/draco_roundtrip/draco_roundtrip/tools/log_collection.py:79 |
| stream_monitor | --decoded-dir | str | data/tmp_decoded_ply | no |  | ros2_ws/src/draco_roundtrip/draco_roundtrip/tools/monitor.py:47 |
| stream_monitor | --decoded-suffix | str | .decoded.ply | no |  | ros2_ws/src/draco_roundtrip/draco_roundtrip/tools/monitor.py:50 |
| stream_monitor | --frame-id | str | lidar_link | no |  | ros2_ws/src/draco_roundtrip/draco_roundtrip/tools/monitor.py:52 |
| stream_monitor | --hz | float | 10.0 | no |  | ros2_ws/src/draco_roundtrip/draco_roundtrip/tools/monitor.py:51 |
| stream_monitor | --limit | int | 0 | no |  | ros2_ws/src/draco_roundtrip/draco_roundtrip/tools/monitor.py:54 |
| stream_monitor | --loop | bool | False | no |  | ros2_ws/src/draco_roundtrip/draco_roundtrip/tools/monitor.py:55 |
| stream_monitor | --orig-dir | str | data/ply_raw | no |  | ros2_ws/src/draco_roundtrip/draco_roundtrip/tools/monitor.py:46 |
| stream_monitor | --orig-suffix | str | .ply | no |  | ros2_ws/src/draco_roundtrip/draco_roundtrip/tools/monitor.py:49 |
| stream_monitor | --prefix | str | sample2 | no |  | ros2_ws/src/draco_roundtrip/draco_roundtrip/tools/monitor.py:48 |
| stream_monitor | --sample | int | 50000 | no |  | ros2_ws/src/draco_roundtrip/draco_roundtrip/tools/monitor.py:56 |
| stream_monitor | --topic-prefix | str | sample2_pair | no |  | ros2_ws/src/draco_roundtrip/draco_roundtrip/tools/monitor.py:53 |
| stream_netem | --clear | bool | False | no | 선택한 프로파일을 적용하기 전에 기존 netem qdisc 제거 | ros2_ws/src/draco_roundtrip/draco_roundtrip/tools/netem.py:147 |
| stream_netem | --config | str |  | no | netem 프로파일 파일 경로 덮어쓰기 | ros2_ws/src/draco_roundtrip/draco_roundtrip/tools/netem.py:145 |
| stream_netem | --dry-run | bool | False | no | 명령을 실행하지 않고 출력만 표시 | ros2_ws/src/draco_roundtrip/draco_roundtrip/tools/netem.py:146 |
| stream_netem | --iface | str | lo | no | 설정할 네트워크 인터페이스(기본: loopback) | ros2_ws/src/draco_roundtrip/draco_roundtrip/tools/netem.py:144 |
| stream_netem | profile | str |  | no | 적용할 프로파일 이름 또는 `list`로 목록 조회 | ros2_ws/src/draco_roundtrip/draco_roundtrip/tools/netem.py:143 |
| stream_replay | --decoded-dir | str | data/tmp_decoded_ply | no | 디코드 PLY 디렉토리 | ros2_ws/src/draco_roundtrip/draco_roundtrip/tools/replay.py:77 |
| stream_replay | --decoded-suffix | str | .decoded.ply | no | 디코드 파일 접미사 | ros2_ws/src/draco_roundtrip/draco_roundtrip/tools/replay.py:80 |
| stream_replay | --frame-id | str | map | no | 헤더 frame_id | ros2_ws/src/draco_roundtrip/draco_roundtrip/tools/replay.py:82 |
| stream_replay | --hz | float | 5.0 | no | 재생 속도(Hz) | ros2_ws/src/draco_roundtrip/draco_roundtrip/tools/replay.py:83 |
| stream_replay | --limit | int | 0 | no | 0=전체, 양수=앞에서 N개만 | ros2_ws/src/draco_roundtrip/draco_roundtrip/tools/replay.py:85 |
| stream_replay | --loop | bool | False | no | 끝나면 처음부터 반복 | ros2_ws/src/draco_roundtrip/draco_roundtrip/tools/replay.py:84 |
| stream_replay | --orig-dir | str | data/ply_raw | no | 원본 PLY 디렉토리 | ros2_ws/src/draco_roundtrip/draco_roundtrip/tools/replay.py:76 |
| stream_replay | --orig-suffix | str | .ply | no | 원본 파일 접미사 | ros2_ws/src/draco_roundtrip/draco_roundtrip/tools/replay.py:79 |
| stream_replay | --prefix | str | sample2 | no | 파일 접두어 | ros2_ws/src/draco_roundtrip/draco_roundtrip/tools/replay.py:78 |
| stream_replay | --topic-prefix | str | compare | no | 퍼블리시 토픽 접두어 | ros2_ws/src/draco_roundtrip/draco_roundtrip/tools/replay.py:81 |
| stream_server | --control-port | int | 0 | no | 제어 플레인 메시지용 TCP 포트(0은 비활성) | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_server.py:316 |
| stream_server | --decode-timeout | float | 30.0 | no | 외부 도구가 이 타임아웃(초)을 초과하면 디코딩을 실패 처리 | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_server.py:320 |
| stream_server | --decode-workers | int | 2 | no | 비동기 파이프라인에서 동시에 실행되는 디코드 워커 수 | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_server.py:330 |
| stream_server | --decoder | str |  | no | 사용할 draco_decoder 경로 | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_server.py:318 |
| stream_server | --heartbeat-interval | float | 2.0 | no | 제어 플레인 하트비트 전송 간격(초). 0은 keepalive 비활성 | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_server.py:342 |
| stream_server | --host | str | 0.0.0.0 | no |  | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_server.py:314 |
| stream_server | --keep-artifacts | bool | False | no | .drc/.ply 디코드 아티팩트를 디버깅용으로 유지(기본은 정리) | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_server.py:332 |
| stream_server | --legacy-mode | bool | False | no | 문제 해결을 위해 동기식 레거시 루프로 폴백 | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_server.py:340 |
| stream_server | --max-inflight | int | 2 | no | 클라이언트에 백프레셔를 걸기 전 동시에 디코드할 수 있는 최대 프레임 수 | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_server.py:328 |
| stream_server | --metrics-sample | int | 50000 | no | 품질 메트릭 계산 시 사용할 최대 포인트 수(0은 샘플링 비활성) | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_server.py:336 |
| stream_server | --port | int | 5000 | no |  | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_server.py:315 |
| stream_server | --protocol | str | binary | no | 클라이언트가 사용할 프레이밍 프로토콜(기본: %(default)s). `protocol_help`에서 제공하는 설명과 함께 선택지를 나열 | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_server.py:345 |
| stream_server | --resp-format | str | ply | no | 클라이언트에 반환할 디코드 페이로드 형식(기본: %(default)s) 선택지: ply, pcd | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_server.py:334 |
| stream_server | --socket-buffer-kb | int | 0 | no | 고처리량 링크를 위해 소켓 송수신 버퍼 크기(KiB) 조정 | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_server.py:324 |
| stream_server | --socket-timeout | float | 30.0 | no | 소켓 연산 타임아웃(초). 0은 보호 기능 비활성 | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_server.py:326 |
| stream_server | --tcp-nodelay | bool | False | no | 지연을 줄이기 위해 수락된 소켓에서 Nagle 집계를 비활성 | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_server.py:322 |
| stream_server | --work-dir | str | data/server_tmp | no |  | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_server.py:319 |
| stream_server | --zero-copy-reply | bool | False | no | 응답 전송 시 복사 오버헤드를 줄이기 위해 디코드된 PLY 페이로드를 메모리 매핑 | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_server.py:338 |

### 구성 파일

| 키 | 기본값/값 | 소스 | 컨텍스트 |
| - | - | - | - |
| data_root | ./data | configs/client.profile.yaml | profile |
| description | 루프백 TCP 서버에서 로컬 rosbag 재생 | configs/client.profile.yaml | profile |
| directories.client_work | client_tmp | configs/client.profile.yaml | profile |
| directories.decoded_from_server | decoded_from_server | configs/client.profile.yaml | profile |
| directories.ply_stream | ply_stream | configs/client.profile.yaml | profile |
| directories.results | results | configs/client.profile.yaml | profile |
| directories.ros_logs | logs/ros | configs/client.profile.yaml | profile |
| name | default-client | configs/client.profile.yaml | profile |
| qos_override | qos_override.yaml | configs/client.profile.yaml | profile |
| rosbag.topic | /sensing/lidar/top/pointcloud | configs/client.profile.yaml | profile |
| encoder.compression_level | 7 | configs/draco.json | profile |
| encoder.keep_attributes[0] | POSITION | configs/draco.json | profile |
| encoder.keep_attributes[1] | NORMAL | configs/draco.json | profile |
| encoder.keep_attributes[2] | COLOR | configs/draco.json | profile |
| encoder.quantization_bits.color | 10 | configs/draco.json | profile |
| encoder.quantization_bits.normal | 10 | configs/draco.json | profile |
| encoder.quantization_bits.position | 14 | configs/draco.json | profile |
| encoder.speed.decoding | 5 | configs/draco.json | profile |
| encoder.speed.encoding | 5 | configs/draco.json | profile |
| notes | draco_tools.core.encoder.resolve_encoder_options 기본값과 동일하게 구성 | configs/draco.json | profile |
| base_frame_id | lidar_link | configs/hdl_graph_slam_stream.yaml | profile |
| downsample_method | VoxelGrid | configs/hdl_graph_slam_stream.yaml | profile |
| imu_topic |  | configs/hdl_graph_slam_stream.yaml | profile |
| keyframe_delta_angle | 0.2 | configs/hdl_graph_slam_stream.yaml | profile |
| keyframe_delta_time | 1.0 | configs/hdl_graph_slam_stream.yaml | profile |
| keyframe_delta_trans | 0.5 | configs/hdl_graph_slam_stream.yaml | profile |
| loop_angle_threshold | 0.2 | configs/hdl_graph_slam_stream.yaml | profile |
| loop_detection_period | 2.0 | configs/hdl_graph_slam_stream.yaml | profile |
| loop_distance_threshold | 5.0 | configs/hdl_graph_slam_stream.yaml | profile |
| loop_gravity_align | False | configs/hdl_graph_slam_stream.yaml | profile |
| loop_search_num_targets | 50 | configs/hdl_graph_slam_stream.yaml | profile |
| map_cloud_path | map_stream.pcd | configs/hdl_graph_slam_stream.yaml | profile |
| map_frame_id | map | configs/hdl_graph_slam_stream.yaml | profile |
| map_publish_period | 1.0 | configs/hdl_graph_slam_stream.yaml | profile |
| odom_frame_id | odom | configs/hdl_graph_slam_stream.yaml | profile |
| odom_topic |  | configs/hdl_graph_slam_stream.yaml | profile |
| points_topic | /stream_pair/decoded | configs/hdl_graph_slam_stream.yaml | profile |
| publish_tf | True | configs/hdl_graph_slam_stream.yaml | profile |
| registration.large_voxel_radius | 0.8 | configs/hdl_graph_slam_stream.yaml | profile |
| registration.large_voxel_resolution | 0.8 | configs/hdl_graph_slam_stream.yaml | profile |
| registration.ndt_num_threads | 2 | configs/hdl_graph_slam_stream.yaml | profile |
| registration.ndt_resolution | 1.0 | configs/hdl_graph_slam_stream.yaml | profile |
| registration.ndt_step_size | 0.1 | configs/hdl_graph_slam_stream.yaml | profile |
| registration.small_voxel_radius | 0.2 | configs/hdl_graph_slam_stream.yaml | profile |
| registration.small_voxel_resolution | 0.2 | configs/hdl_graph_slam_stream.yaml | profile |
| registration.type | NDTOMP | configs/hdl_graph_slam_stream.yaml | profile |
| use_reflectance | False | configs/hdl_graph_slam_stream.yaml | profile |
| voxel_leaf_size | 0.2 | configs/hdl_graph_slam_stream.yaml | profile |
| profiles.clear.clear | True | configs/netem.profiles.yaml | profile |
| profiles.clear.description | 기존 qdisc 항목 제거 | configs/netem.profiles.yaml | profile |
| profiles.loopback.description | 트래픽 셰이핑 없음. 순수 처리량 벤치마크에 사용 | configs/netem.profiles.yaml | profile |
| profiles.lte_nominal.delay | 60ms | configs/netem.profiles.yaml | profile |
| profiles.lte_nominal.description | 표준 LTE 업링크 조건 | configs/netem.profiles.yaml | profile |
| profiles.lte_nominal.jitter | 20ms | configs/netem.profiles.yaml | profile |
| profiles.lte_nominal.loss | 0.2% | configs/netem.profiles.yaml | profile |
| profiles.lte_nominal.rate | 18mbit | configs/netem.profiles.yaml | profile |
| profiles.satellite_demo.delay | 550ms | configs/netem.profiles.yaml | profile |
| profiles.satellite_demo.description | 부하 시험용 고지연 위성 구간 | configs/netem.profiles.yaml | profile |
| profiles.satellite_demo.jitter | 120ms | configs/netem.profiles.yaml | profile |
| profiles.satellite_demo.loss | 1.2% | configs/netem.profiles.yaml | profile |
| profiles.satellite_demo.rate | 8mbit | configs/netem.profiles.yaml | profile |
| profiles.wifi_dense.delay | 45ms | configs/netem.profiles.yaml | profile |
| profiles.wifi_dense.description | 혼잡한 Wi-Fi 환경(중간 수준 패킷 손실) | configs/netem.profiles.yaml | profile |
| profiles.wifi_dense.jitter | 15ms | configs/netem.profiles.yaml | profile |
| profiles.wifi_dense.loss | 0.5% | configs/netem.profiles.yaml | profile |
| profiles.wifi_dense.rate | 35mbit | configs/netem.profiles.yaml | profile |
| /sensing/lidar/top/pointcloud.depth | 10 | configs/qos_override.yaml | profile |
| /sensing/lidar/top/pointcloud.durability | volatile | configs/qos_override.yaml | profile |
| /sensing/lidar/top/pointcloud.history | keep_last | configs/qos_override.yaml | profile |
| /sensing/lidar/top/pointcloud.reliability | best_effort | configs/qos_override.yaml | profile |
| monitor.playback_topic | /stream_pair/replay | configs/ros_topics.yaml | profile |
| monitor.rviz_frame | lidar_link | configs/ros_topics.yaml | profile |
| stream.decoded_pointcloud | /stream_pair/decoded | configs/ros_topics.yaml | profile |
| stream.metrics | /stream_pair/metrics | configs/ros_topics.yaml | profile |
| stream.source_pointcloud | /stream_pair/source | configs/ros_topics.yaml | profile |
| icp_odometry.ros__parameters.Icp/CorrespondenceRatio | 0.1 | configs/rtabmap_stream.yaml | profile |
| icp_odometry.ros__parameters.Icp/Epsilon | 0.001 | configs/rtabmap_stream.yaml | profile |
| icp_odometry.ros__parameters.Icp/Iterations | 30 | configs/rtabmap_stream.yaml | profile |
| icp_odometry.ros__parameters.Icp/PointToPlane | true | configs/rtabmap_stream.yaml | profile |
| icp_odometry.ros__parameters.Icp/PointToPlaneK | 20 | configs/rtabmap_stream.yaml | profile |
| icp_odometry.ros__parameters.Icp/PointToPlaneRadius | 0 | configs/rtabmap_stream.yaml | profile |
| icp_odometry.ros__parameters.Icp/VoxelSize | 0.2 | configs/rtabmap_stream.yaml | profile |
| icp_odometry.ros__parameters.Odom/ScanKeyFrameThr | 0.4 | configs/rtabmap_stream.yaml | profile |
| icp_odometry.ros__parameters.OdomF2M/BundleAdjustment | false | configs/rtabmap_stream.yaml | profile |
| icp_odometry.ros__parameters.OdomF2M/ScanMaxSize | 15000 | configs/rtabmap_stream.yaml | profile |
| icp_odometry.ros__parameters.OdomF2M/ScanSubtractRadius | 0.2 | configs/rtabmap_stream.yaml | profile |
| icp_odometry.ros__parameters.approx_sync | False | configs/rtabmap_stream.yaml | profile |
| icp_odometry.ros__parameters.deskewing | False | configs/rtabmap_stream.yaml | profile |
| icp_odometry.ros__parameters.expected_update_rate | 0.0 | configs/rtabmap_stream.yaml | profile |
| icp_odometry.ros__parameters.frame_id | lidar_link | configs/rtabmap_stream.yaml | profile |
| icp_odometry.ros__parameters.odom_frame_id | odom | configs/rtabmap_stream.yaml | profile |
| icp_odometry.ros__parameters.publish_tf | True | configs/rtabmap_stream.yaml | profile |
| icp_odometry.ros__parameters.queue_size | 5 | configs/rtabmap_stream.yaml | profile |
| icp_odometry.ros__parameters.scan_cloud_max_pts | 120000 | configs/rtabmap_stream.yaml | profile |
| icp_odometry.ros__parameters.scan_cloud_min_pts | 50 | configs/rtabmap_stream.yaml | profile |
| icp_odometry.ros__parameters.use_sim_time | False | configs/rtabmap_stream.yaml | profile |
| icp_odometry.ros__parameters.wait_for_transform | 0.2 | configs/rtabmap_stream.yaml | profile |
| rtabmap.ros__parameters.Grid/3D | true | configs/rtabmap_stream.yaml | profile |
| rtabmap.ros__parameters.Grid/CellSize | 0.2 | configs/rtabmap_stream.yaml | profile |
| rtabmap.ros__parameters.Grid/ClusterRadius | 0.5 | configs/rtabmap_stream.yaml | profile |
| rtabmap.ros__parameters.Grid/Sensor | true | configs/rtabmap_stream.yaml | profile |
| rtabmap.ros__parameters.Icp/CorrespondenceRatio | 0.1 | configs/rtabmap_stream.yaml | profile |
| rtabmap.ros__parameters.Icp/Epsilon | 0.001 | configs/rtabmap_stream.yaml | profile |
| rtabmap.ros__parameters.Icp/Iterations | 30 | configs/rtabmap_stream.yaml | profile |
| rtabmap.ros__parameters.Mem/NotLinkedNodesKept | true | configs/rtabmap_stream.yaml | profile |
| rtabmap.ros__parameters.Mem/STMSize | 30 | configs/rtabmap_stream.yaml | profile |
| rtabmap.ros__parameters.Optimizer/GravitySigma | 0 | configs/rtabmap_stream.yaml | profile |
| rtabmap.ros__parameters.RGBD/AngularUpdate | 0 | configs/rtabmap_stream.yaml | profile |
| rtabmap.ros__parameters.RGBD/LinearUpdate | 0 | configs/rtabmap_stream.yaml | profile |
| rtabmap.ros__parameters.RGBD/LoopClosureHypothesis | 5 | configs/rtabmap_stream.yaml | profile |
| rtabmap.ros__parameters.RGBD/LoopClosureIcpType | 1 | configs/rtabmap_stream.yaml | profile |
| rtabmap.ros__parameters.RGBD/ProximityPathMaxNeighbors | 1 | configs/rtabmap_stream.yaml | profile |
| rtabmap.ros__parameters.Reg/Strategy | 1 | configs/rtabmap_stream.yaml | profile |
| rtabmap.ros__parameters.Rtabmap/SavePointCloud | true | configs/rtabmap_stream.yaml | profile |
| rtabmap.ros__parameters.Rtabmap/SaveWMState | false | configs/rtabmap_stream.yaml | profile |
| rtabmap.ros__parameters.SLAM/Strategy | 1 | configs/rtabmap_stream.yaml | profile |
| rtabmap.ros__parameters.Voxel/Size | 0.2 | configs/rtabmap_stream.yaml | profile |
| rtabmap.ros__parameters.approx_sync | False | configs/rtabmap_stream.yaml | profile |
| rtabmap.ros__parameters.detection_rate | 1.0 | configs/rtabmap_stream.yaml | profile |
| rtabmap.ros__parameters.frame_id | lidar_link | configs/rtabmap_stream.yaml | profile |
| rtabmap.ros__parameters.map_frame_id | map | configs/rtabmap_stream.yaml | profile |
| rtabmap.ros__parameters.odom_frame_id | odom | configs/rtabmap_stream.yaml | profile |
| rtabmap.ros__parameters.publish_tf | True | configs/rtabmap_stream.yaml | profile |
| rtabmap.ros__parameters.queue_size | 10 | configs/rtabmap_stream.yaml | profile |
| rtabmap.ros__parameters.subscribe_depth | False | configs/rtabmap_stream.yaml | profile |
| rtabmap.ros__parameters.subscribe_odom_info | True | configs/rtabmap_stream.yaml | profile |
| rtabmap.ros__parameters.subscribe_rgb | False | configs/rtabmap_stream.yaml | profile |
| rtabmap.ros__parameters.subscribe_rgbd | False | configs/rtabmap_stream.yaml | profile |
| rtabmap.ros__parameters.subscribe_scan | False | configs/rtabmap_stream.yaml | profile |
| rtabmap.ros__parameters.subscribe_scan_cloud | True | configs/rtabmap_stream.yaml | profile |
| rtabmap.ros__parameters.subscribe_stereo | False | configs/rtabmap_stream.yaml | profile |
| rtabmap.ros__parameters.subscribe_user_data | False | configs/rtabmap_stream.yaml | profile |
| rtabmap.ros__parameters.use_sim_time | False | configs/rtabmap_stream.yaml | profile |
| data_root | ./data | configs/server.profile.yaml | profile |
| description | Loopback decoder workspace for roundtrip experiments | configs/server.profile.yaml | profile |
| directories.decoded_from_server | decoded_from_server | configs/server.profile.yaml | profile |
| directories.results | results | configs/server.profile.yaml | profile |
| directories.ros_logs | logs/ros | configs/server.profile.yaml | profile |
| directories.server_work | server_tmp | configs/server.profile.yaml | profile |
| name | default-server | configs/server.profile.yaml | profile |

### Environment Variables

| 환경 변수 | 기본값 | 소스 | 비고 |
| - | - | - | - |
| DRACO_CONFIG_ROOT |  | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/config.py:113 | dict.get |
| DRACO_DATA_ROOT |  | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/config.py:259 | dict.get |
| DRACO_DECODER |  | ros2_ws/src/draco_tools/draco_tools/analysis/analyze_draco_quality.py:271 | dict.get |
| DRACO_ENCODER |  | ros2_ws/src/draco_roundtrip/draco_roundtrip/draco/encoder.py:52 | dict.get |
| PATH |  | ros2_ws/src/draco_roundtrip/draco_roundtrip/draco/encoder.py:107<br>ros2_ws/src/draco_roundtrip/draco_roundtrip/draco/encoder.py:107 (direct access)<br>ros2_ws/src/draco_roundtrip/tests/test_e2e_roundtrip.py:61<br>ros2_ws/src/draco_tools/draco_tools/analysis/analyze_draco_quality.py:74 | dict.get, direct access |
| RMW_IMPLEMENTATION |  | ros2_ws/src/draco_tools/draco_tools/offline_pipeline.py:266 (direct access) | direct access |
| ROS_DOMAIN_ID |  | ros2_ws/src/draco_tools/draco_tools/offline_pipeline.py:264 (direct access) | direct access |
| ROS_LOCALHOST_ONLY |  | ros2_ws/src/draco_tools/draco_tools/offline_pipeline.py:268 (direct access) | direct access |
| env_var |  | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/executable.py:33 | dict.get |
<!-- AUTODOC:CONFIG_KEYS:END -->
