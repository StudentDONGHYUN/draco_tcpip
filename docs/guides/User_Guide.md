# Draco Roundtrip 사용자 가이드
Draco Roundtrip은 결정적 제어 플레인 핸드셰이크와 공유 구성 헬퍼를 기반으로 LiDAR 포인트 클라우드를 TCP 위에서 스트리밍합니다. 이 가이드는 운영자와 개발자를 위해 환경 설정, 스트리밍, 모니터링, 로그 수집 흐름을 순서대로 제시합니다.
_마지막 업데이트: 2025-03-15_

**목차**
- [환경 설정](#환경-설정)
- [스트리밍 운영](#스트리밍-운영)
- [모니터링과 검증](#모니터링과-검증)
- [로그 수집 및 사후 작업](#로그-수집-및-사후-작업)
- [문제 해결 및 빠른 명령](#문제-해결-및-빠른-명령)

## 환경 설정
1. ROS 2 Humble을 설치하고 빌드 전에 환경을 소스합니다.
   ```bash
   source /opt/ros/humble/setup.bash
   ```
2. 저장소를 클론한 뒤 워크스페이스 의존성을 설치하고 빌드합니다.
   ```bash
   cd /path/to/draco_tcpip/ros2_ws
   rosdep install --from-paths src --rosdistro humble --ignore-src -y
   colcon build --symlink-install
   source install/setup.bash
   ```
3. 저장소 루트에서 Python 패키지를 editable 모드로 설치하여 ROS 2 노드와 CLI 도구가 동일한 유틸리티를 공유하도록 합니다.
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -e .
   ```
4. IDE/타입 체크 경로가 런타임 부트스트랩 순서와 동일하도록 설정해 `tests`와 `ros2_ws/src`가 올바르게 해석되게 합니다(자세한 내용은 [개발 프로세스](../development/Development_Process.md) 참고).

### SLAM 통합 빠른 시작
스트리밍 출력을 HDL Graph SLAM으로 바로 연결하려면 통합된 bringup 런치를 사용합니다.
```bash
source /opt/ros/humble/setup.bash
cd /path/to/draco_tcpip/ros2_ws
source install/setup.bash
ros2 launch slam_stream_bridge bringup.launch.py \
  bag:=/data/bags/sample.bag \
  topic:=/sensing/lidar/top/pointcloud \
  layout_profile:=client.profile.yaml \
  slam:=hdl
```
이 런치 파일은 `stream_server`와 `stream_client`를 `/stream_pair/decoded`에 연결하고, [구성 참조](../reference/Configuration_Reference.md)에 문서화된 QoS/프로파일 헬퍼를 재사용합니다. 필요 시 `slam_params`를 덮어써 HDL Graph SLAM 매개변수 파일을 지정할 수 있습니다.

## 스트리밍 운영
1. **결정적 정리와 텔레메트리를 포함해 서버를 시작합니다.**
   ```bash
   ros2 run draco_roundtrip stream_server --port 5000
   ```
   - `--protocol`(`legacy` 또는 `binary`), `--resp-format`, `--metrics-out`, `--socket-buffer-autotune` 등을 지원하며 기본값은 [구성 참조](../reference/Configuration_Reference.md)에서 확인할 수 있습니다.
   - 로그와 텔레메트리는 [프로토콜 및 스키마 참조](../reference/Protocol_and_Schema_Reference.md)의 제어 플레인 계약과 스키마를 따릅니다.

2. **클라이언트를 연결하기 전에 네트워크 에뮬레이션을 선택적으로 적용합니다.**
   ```bash
   # 프로파일 미리보기(dry-run)
   ros2 run draco_roundtrip stream_netem wifi_dense --iface lo --dry-run
   # 프로파일 적용(루트 권한 필요)
   sudo ros2 run draco_roundtrip stream_netem wifi_dense --iface eno1 --clear
   ```

3. **다른 터미널에서 클라이언트를 실행합니다.**
   ```bash
   ros2 run draco_roundtrip stream_client \
       --bag /path/to/bag \
       --topic /sensing/lidar/top/pointcloud \
       --prefix demo_run \
       --layout-profile client.profile.yaml \
       --data-root ./data \
       --quality-thresholds '{"centroid_l2": 0.05}'
   ```
   - 핸드셰이크: `MSG_ACK`, `MSG_HEARTBEAT`, `MSG_EOF`가 제한 큐와 세션 종료를 관리하며, RTT 윈도는 `--ack-timeout*` 플래그로 조정됩니다.
   - 디렉터리/QoS 해석, 프로파일 검색 순서, CLI 기본값은 [구성 참조](../reference/Configuration_Reference.md)에 정의되어 있습니다.
   - 품질 JSONL 메트릭은 `quality_report_dir/<prefix>_quality.jsonl`에 기록됩니다. 서버의 `--keep-artifacts`, 클라이언트의 `--no-save-decoded`로 Draco 아티팩트 유지 여부를 제어합니다.

4. **3D SLAM 스트리밍**: bringup 런치를 사용하지 않을 경우, HDL Graph SLAM을 직접 실행하고 `/stream_pair/decoded`를 구독합니다. 클라이언트의 `--play-frame-id`가 SLAM 프레임과 일치하는지 확인하십시오(기본값 `lidar_link`).

## 모니터링과 검증
- 실시간 모니터링:
  ```bash
  ros2 run draco_roundtrip stream_monitor \
      --source /stream_pair/source \
      --decoded /stream_pair/decoded
  ```
- 오프라인 분석을 위한 저장된 PLY 페어 재생:
  ```bash
  ros2 run draco_roundtrip stream_replay \
      --original data/ply \
      --decoded data/decoded
  ```
- 성능 보호 장치:
  - `pytest tests/perf/test_latency_gate.py`가 [성능 시험 계획](../development/Performance_Test_Plan.md)에 설정된 p95 지연 목표를 강제합니다.
  - `scripts/netem_profile.sh <profile>`은 사전에 정의된 지연/손실 패턴을 활성화하며, 실험 후 `scripts/netem_profile.sh clear`로 초기화해야 합니다.
- 가시성: 구조화된 로그에는 세션 상태, 큐 깊이, 지연 분위수가 포함되며, 텔레메트리 JSON은 [프로토콜 및 스키마 참조](../reference/Protocol_and_Schema_Reference.md)의 스키마와 검증되어야 합니다.

## 로그 수집 및 사후 작업
`stream_collect_logs`로 결과 수집을 자동화합니다.
```bash
ros2 run draco_roundtrip stream_collect_logs run_20240315 \
  --layout-profile client.profile.yaml \
  --data-root ./data \
  --metadata bag=sample.bag --metadata slam=rtabmap \
  --ros-log ~/.ros/log/latest \
  --attach data/ply_stream/sample_0001.ply \
  --notes "Baseline roundtrip with wifi_dense profile"
```
이 명령은 `data/results/<run_id>/` 아래에 `artifacts/`, `metrics/`, `ros_logs/`, `manifest.json`을 생성합니다. 매니페스트는 실행 ID, 프로파일, QoS 오버라이드, 메타데이터, EOF 핸드셰이크 상태를 기록합니다. 자동화가 불가능하면 동일한 디렉터리 구조를 수동으로 맞추고 [결과 템플릿](../reports/results_template.md)으로 실행을 문서화하십시오.

SLAM 실험 이후에는 ROS 로그와 SLAM 결과를 `ros_logs/` 및 `artifacts/`에 보관해 매니페스트 참조가 유효하도록 합니다.

## 문제 해결 및 빠른 명령
- 환경 전제를 검증합니다.
  ```bash
  ruff check .
  pyright
  pytest --maxfail=1 --disable-warnings
  ```
- 네트워크 문제:
  - ACK 타임아웃이 증가하면 `--ack-timeout`, `--ack-timeout-min`, `--ack-timeout-max` 값을 조정하십시오.
  - 고지연 링크로 인해 버퍼 압력이 발생하면 양쪽 끝점에서 `--socket-buffer-autotune`을 활성화하십시오.
- 파일 시스템 전송:
  - 파일 시스템 기반 캡처 시 `--spool-gc-window`를 설정하여 기억하는 스풀 항목 수를 제한하십시오.
  - 레이아웃 프로파일에 `ply_stream`, `client_work`, `decoded_from_server` 디렉터리가 포함되었는지 확인하십시오(자세한 내용은 [구성 참조](../reference/Configuration_Reference.md) 참고).
- 전체 복구 절차 또는 감사 기대치는 [개발 프로세스](../development/Development_Process.md)와 [리팩터 및 감사 로그](../reports/Refactor_and_Audit_Log.md)를 확인하십시오.

## 자동 생성 CLI 참조
<!-- AUTODOC:CLI_FLAGS:BEGIN -->
| 명령 | 플래그 | 기본값 | 설명 |
| - | - | - | - |
| encode_ply_to_draco | --in | ./ply_raw | 입력 PLY 디렉터리(기본: ./ply_raw) |
| encode_ply_to_draco | --log-csv |  | 프레임별 인코딩 시간 로그 CSV |
| encode_ply_to_draco | --name |  | 대상 접두어. 지정 시 '<name>_*.ply'만 인코딩 |
| encode_ply_to_draco | --out | ./draco_out | 출력 DRC 디렉터리(기본: ./draco_out) |
| encode_ply_to_draco | --workers | os.cpu_count() or 4 | 병렬 작업 수 |
| offline_pipeline | --bag |  | rosbag 디렉터리(메타/DB3 포함). 비우면 재생 안 함 |
| offline_pipeline | --bag-args | [] | `ros2 bag play` 추가 인자 |
| offline_pipeline | --bag-loop | False | bag 재생을 반복 실행 |
| offline_pipeline | --bag-rate | 1.0 | bag 재생 속도 배수 |
| offline_pipeline | --bag-remap |  | `ros2 bag play` remap 규칙 문자열 |
| offline_pipeline | --bag-warmup-sec | 0.0 | 재생 시작 전 웜업 시간(초) |
| offline_pipeline | --best-effort | False | QoS best_effort 모드를 활성화 |
| offline_pipeline | --cl | DEFAULT_CL | Draco 압축 레벨 |
| offline_pipeline | --data-root |  | 생성 아티팩트 기본 디렉터리(프로파일/데이터 루트 덮어씀) |
| offline_pipeline | --decoded-dir |  | 임시 디코드 디렉터리 덮어쓰기 |
| offline_pipeline | --decoder | draco_decoder | 사용할 `draco_decoder` 실행 파일 경로 |
| offline_pipeline | --drc-dir |  | Draco 출력 디렉터리 덮어쓰기 |
| offline_pipeline | --encoder-extra | [] | `draco_encoder`에 전달할 추가 인자 문자열(예: `--speed 10`) |
| offline_pipeline | --fast-preset | False | 30FPS 목표용 빠른 설정 적용 |
| offline_pipeline | --force-tqdm | False | QA 단계에서 tqdm 진행률 표시 강제 |
| offline_pipeline | --jobs | 1 | 병렬 작업자 수 |
| offline_pipeline | --keep-decoded | False | QA 단계에서 디코드 PLY 삭제 금지 |
| offline_pipeline | --layout-profile |  | 디렉터리 해석에 사용할 레이아웃 프로파일 이름/경로 |
| offline_pipeline | --max-frames | 0 | 처리할 최대 프레임 수(0은 무제한) |
| offline_pipeline | --no-qa | False | 품질 분석 단계를 건너뜀 |
| offline_pipeline | --ply-dir |  | 원본 PLY 출력 디렉터리 덮어쓰기 |
| offline_pipeline | --prefix |  | 결과 파일 접두어 |
| offline_pipeline | --qg | DEFAULT_QG | Draco `quantization_bits[geom]` |
| offline_pipeline | --qp | DEFAULT_QP | Draco `quantization_bits[pos]` |
| offline_pipeline | --results-dir |  | 결과 집계 디렉터리 덮어쓰기 |
| offline_pipeline | --reuse-drc | False | 기존 DRC 재사용(재인코딩 생략) |
| offline_pipeline | --rmw-impl |  | 하위 프로세스에 전달할 `RMW_IMPLEMENTATION` |
| offline_pipeline | --ros-domain-id |  | 하위 프로세스에 전달할 `ROS_DOMAIN_ID` |
| offline_pipeline | --ros-localhost-only |  | 하위 프로세스에 전달할 `ROS_LOCALHOST_ONLY` 값(0 또는 1) |
| offline_pipeline | --saver-timeout | 180.0 | `bag_to_ply` 단계의 전체 타임아웃(초). 0은 비활성 |
| offline_pipeline | --saver-voxel-size | 0.0 | `bag_to_ply` 다운샘플링 보xel 크기(미터) |
| offline_pipeline | --thresholds | [0.01, 0.03, 0.05] | 품질 임계값 목록 |
| offline_pipeline | --topic |  | 입력 포인트 클라우드 토픽 |
| stream_client | --ack-timeout | 0.5 | 적응 제어가 적용되기 전 기본 ACK 타임아웃(초) |
| stream_client | --ack-timeout-max | 2.0 | 적응 ACK 타임아웃 상한(초) |
| stream_client | --ack-timeout-min | 0.5 | 적응 ACK 타임아웃 하한(초) |
| stream_client | --ack-timeout-strikes | 3 | 연속 ACK 타임아웃 허용 횟수 |
| stream_client | --adaptive-window | False | RTT/처리량 기반 TX 윈도 적응 기능 활성화 |
| stream_client | --bag |  | 재생할 rosbag 경로 |
| stream_client | --best-effort | False | ROS QoS best_effort 모드 사용 |
| stream_client | --capture-queue | 4 | 백프레셔 전까지 허용되는 캡처 큐 깊이 |
| stream_client | --capture-transport | shared-memory | 캡처 백엔드 선택(파일 시스템 또는 공유 메모리) |
| stream_client | --control-port | 0 | 전용 제어 플레인 TCP 포트(0은 비활성) |
| stream_client | --data-root |  | 생성 아티팩트 기본 디렉터리(프로파일/데이터 루트 덮어씀) |
| stream_client | --decoded-dir |  | 서버에서 받은 디코드 프레임 저장 디렉터리 |
| stream_client | --encode-workers | 2 | 비동기 파이프라인의 인코더 워커 수 |
| stream_client | --heartbeat-timeout | 10.0 | 이 시간(초) 동안 ACK/하트비트가 없으면 세션 실패 |
| stream_client | --idle-timeout | 10.0 | 비활성 상태 감시 타임아웃(초) |
| stream_client | --initial-inflight |  | 적응 제어가 조정하기 전 초기 TX 윈도 |
| stream_client | --layout-profile |  | `configs/*.profile.{yaml,json}` 경로 또는 이름 |
| stream_client | --max-frames | 0 | 처리할 최대 프레임 수(0은 무제한) |
| stream_client | --max-inflight, --max-pending | 4 | ACK/디코드 응답을 기다리는 최대 동시 프레임 |
| stream_client | --metrics-out, --telemetry-out | artifacts/perf/client_latest.json | 스키마 준수 텔레메트리 JSON 출력 경로 |
| stream_client | --metrics-sample | 50000 | 클라이언트 메트릭 계산에 사용할 최대 포인트 수(0은 전체) |
| stream_client | --no-save-decoded | False | 서버 응답을 디스크에 저장하지 않음 |
| stream_client | --play-frame-id | lidar_link | 재생 시 사용할 `frame_id` |
| stream_client | --play-hz | 10.0 | 재생 주파수(Hz) |
| stream_client | --play-sample | 50000 | 재생 시 샘플링할 포인트 수 |
| stream_client | --play-topic-prefix | stream_pair | 재생 시 게시할 토픽 접두어 |
| stream_client | --ply-dir |  | 캡처한 PLY 스풀 디렉터리 덮어쓰기 |
| stream_client | --prefix |  | 실행 식별 접두어 |
| stream_client | --print-metrics | False | 재생 중 프레임별 지연/정확도 메트릭을 stdout에 출력 |
| stream_client | --protocol | binary | 사용할 프레이밍 프로토콜(기본: binary). `protocol_help`에서 설명을 제공 |
| stream_client | --qos-override |  | QoS 프로파일 파일 경로. 기본은 레이아웃 프로파일 또는 패키지 구성 |
| stream_client | --quality-report-dir | artifacts/quality | 프레임별 품질 JSONL을 쓰는 디렉터리 |
| stream_client | --quality-thresholds | {} | 품질 메트릭 허용 최대 편차를 정의하는 JSON 객체(빈 객체는 정보용) |
| stream_client | --resp-format | ply | 서버가 반환하는 디코드 페이로드 형식(기본: ply) |
| stream_client | --server-host | 127.0.0.1 | 서버 주소 |
| stream_client | --server-port | 5000 | 서버 포트 |
| stream_client | --socket-buffer-autotune | False | 커널 소켓 버퍼 자동 튜닝 요청(SO_SNDBUF/SO_RCVBUF=0) |
| stream_client | --socket-buffer-kb | 0 | 고속 링크 포화를 위한 소켓 버퍼 크기(KiB) |
| stream_client | --socket-timeout | 15.0 | 소켓 연산 타임아웃(초). 0은 보호 비활성 |
| stream_client | --spool-gc-window | 0 | 파일 시스템 스풀 스캔 시 기억할 최대 항목 수(0은 무제한) |
| stream_client | --tcp-nodelay | False | 대화형 재생 지연 감소를 위해 Nagle 비활성 |
| stream_client | --topic |  | 입력 토픽 경로 |
| stream_client | --transport | tcp | 데이터 평면 전송 계층 선택. 현재 tcp만 구현(추가 값은 예약) |
| stream_client | --tx-fragment-size | 0 | 바이너리 프로토콜에서 MTU 안전 조각 크기(0은 비활성) |
| stream_client | --window-ema-alpha | 0.2 | 적응형 윈도 텔레메트리 EMA 평활 계수(0–1) |
| stream_client | --work-dir |  | 인코더 임시 데이터를 저장할 디렉터리 |
| stream_collect_logs | --attach | [] | 아티팩트 디렉터리에 추가로 복사할 파일/디렉터리 목록 |
| stream_collect_logs | --data-root |  | 데이터 루트 덮어쓰기 |
| stream_collect_logs | --layout-profile |  | 레이아웃 프로파일 경로 |
| stream_collect_logs | --metadata | [] | 매니페스트에 기록할 키=값 메타데이터 |
| stream_collect_logs | --notes |  | `notes/README.txt`에 기록할 자유 형식 노트 |
| stream_collect_logs | --ros-log | [] | 보관할 ROS 로그 디렉터리 경로 |
| stream_collect_logs | run_id |  | 실행 식별자(디렉터리 이름으로 사용) |
| stream_monitor | --decoded-dir | data/tmp_decoded_ply | 디코드 PLY 디렉터리 |
| stream_monitor | --decoded-suffix | .decoded.ply | 디코드 파일 접미사 |
| stream_monitor | --frame-id | lidar_link | 게시할 메시지의 `frame_id` |
| stream_monitor | --hz | 10.0 | 재생 주파수(Hz) |
| stream_monitor | --limit | 0 | 표시할 최대 프레임 수(0은 전체) |
| stream_monitor | --loop | False | 끝나면 처음부터 반복 |
| stream_monitor | --orig-dir | data/ply_raw | 원본 PLY 디렉터리 |
| stream_monitor | --orig-suffix | .ply | 원본 파일 접미사 |
| stream_monitor | --prefix | sample2 | 파일 접두어 |
| stream_monitor | --sample | 50000 | 샘플링 포인트 수 |
| stream_monitor | --topic-prefix | sample2_pair | 게시 토픽 접두어 |
| stream_netem | --clear | False | 선택된 프로파일 적용 전 기존 netem qdisc 제거 |
| stream_netem | --config |  | netem 프로파일 파일 경로 덮어쓰기 |
| stream_netem | --dry-run | False | 명령을 실행하지 않고 출력만 표시 |
| stream_netem | --iface | lo | 설정할 네트워크 인터페이스(기본: loopback) |
| stream_netem | profile |  | 적용할 프로파일 이름 또는 `list`로 조회 |
| stream_replay | --decoded-dir | data/tmp_decoded_ply | 디코드 PLY 디렉터리 |
| stream_replay | --decoded-suffix | .decoded.ply | 디코드 파일 접미사 |
| stream_replay | --frame-id | map | 게시할 메시지 `frame_id` |
| stream_replay | --hz | 5.0 | 재생 주파수(Hz) |
| stream_replay | --limit | 0 | 재생할 최대 프레임 수(0은 전체) |
| stream_replay | --loop | False | 재생 완료 시 처음부터 반복 |
| stream_replay | --orig-dir | data/ply_raw | 원본 PLY 디렉터리 |
| stream_replay | --orig-suffix | .ply | 원본 파일 접미사 |
| stream_replay | --prefix | sample2 | 파일 접두어 |
| stream_replay | --topic-prefix | compare | 게시 토픽 접두어 |
| stream_server | --control-port | 0 | 제어 플레인 전용 TCP 포트(0은 비활성) |
| stream_server | --decode-timeout | 30.0 | 외부 디코더 최대 허용 시간(초) |
| stream_server | --decode-workers | 2 | 비동기 파이프라인 디코드 워커 수 |
| stream_server | --decoder |  | 사용할 `draco_decoder` 경로 |
| stream_server | --heartbeat-interval | 2.0 | 하트비트 전송 간격(초). 0은 keepalive 비활성 |
| stream_server | --host | 0.0.0.0 | 바인딩 주소 |
| stream_server | --keep-artifacts | False | 디코드 아티팩트(.drc/.ply)를 정리하지 않고 유지 |
| stream_server | --legacy-mode | False | 문제 해결용 동기식 레거시 루프로 폴백 |
| stream_server | --max-inflight | 2 | 동시에 디코드할 최대 프레임 수 |
| stream_server | --metrics-sample | 50000 | 품질 메트릭 계산에 사용할 최대 포인트 수(0은 전체) |
| stream_server | --port | 5000 | 수신 포트 |
| stream_server | --protocol | binary | 클라이언트가 사용할 프레이밍 프로토콜(기본: binary) |
| stream_server | --resp-format | ply | 클라이언트에 반환할 디코드 페이로드 형식(기본: ply) |
| stream_server | --socket-buffer-kb | 0 | 고처리량 링크를 위한 소켓 버퍼 크기(KiB) |
| stream_server | --socket-timeout | 30.0 | 소켓 연산 타임아웃(초). 0은 보호 비활성 |
| stream_server | --tcp-nodelay | False | 수락한 소켓에서 Nagle 비활성 |
| stream_server | --work-dir | data/server_tmp | 서버 임시 디렉터리 |
| stream_server | --zero-copy-reply | False | 디코드 PLY를 메모리 매핑해 전송 복사를 최소화 |
<!-- AUTODOC:CLI_FLAGS:END -->
