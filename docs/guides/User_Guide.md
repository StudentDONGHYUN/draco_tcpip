# Draco Roundtrip 사용자 가이드
Draco Roundtrip은 결정적 제어 플레인 핸드셰이크와 공유 구성 헬퍼를 기반으로 LiDAR 포인트 클라우드를 TCP 위에서 스트리밍합니다. 이 가이드는 운영자와 개발자를 위해 환경 설정, 스트리밍, 모니터링, 로그 수집 흐름을 순서대로 제시합니다.
_마지막 업데이트: 2025-03-16_

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
    - `--protocol`(`binary`, `text`, `legacy`), `--resp-format`, `--metrics-out`, `--socket-buffer-autotune` 등을 지원하며 기본값은 [구성 참조](../reference/Configuration_Reference.md)에서 확인할 수 있습니다.
    - 로그와 텔레메트리는 [프로토콜 및 스키마 참조](../reference/Protocol_and_Schema_Reference.md)의 제어 플레인 계약과 스키마를 따릅니다.
    - `--control-port`는 더 이상 별도 소켓을 열지 않고 경고만 출력합니다. 모든 제어 메시지는 단일 TCP 연결에서 `FrameType`으로 다중화되며, 서버는 프래그먼트를 TTL(300 초)과 128 MiB 상한으로 관리합니다.
    - v2 기본 헤더(`magic=b"DRC0"`, `version=2`)에는 타임스탬프와 콘텐츠 타입이 포함되며, `--legacy-mode`를 켜면 레거시 헤더(`b"DRTC"`, `version=1`) 수신만 허용합니다.

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
    - 핸드셰이크: `FrameType.ACK`, `FrameType.HEARTBEAT`, `FrameType.EOF`가 제한 큐와 세션 종료를 관리하며, RTT 윈도는 `--ack-timeout*` 플래그로 조정됩니다.
   - 디렉터리/QoS 해석, 프로파일 검색 순서, CLI 기본값은 [구성 참조](../reference/Configuration_Reference.md)에 정의되어 있습니다.
   - 품질 JSONL 메트릭은 `quality_report_dir/<prefix>_quality.jsonl`에 기록됩니다. 서버의 `--keep-artifacts`, 클라이언트의 `--no-save-decoded`로 Draco 아티팩트 유지 여부를 제어합니다.
    - `--control-port` 옵션은 경고 후 무시되며, 텍스트 프로토콜(`--protocol text`)을 사용할 때는 이름/페이로드 상한(4096 B/100 MiB)을 넘지 않도록 주의해야 합니다. 제한을 위반하면 연결이 즉시 닫히고 `_text_limit_drops` 카운터가 증가합니다.

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
| Command | Flag | Default | Description |
| - | - | - | - |
| encode_ply_to_draco | --in | ./ply_raw | 입력 PLY 디렉터리 (기본: ./ply_raw) |
| encode_ply_to_draco | --log-csv |  | 프레임별 인코드 시간 로그 CSV |
| encode_ply_to_draco | --name |  | 대상 접두어(prefix). 지정 시 '<name>_*.ply'만 인코딩 |
| encode_ply_to_draco | --out | ./draco_out | 출력 DRC 디렉터리 (기본: ./draco_out) |
| encode_ply_to_draco | --workers | os.cpu_count() or 4 | 병렬 작업 수 |
| offline_pipeline | --bag |  | rosbag 디렉터리(메타/DB3 포함). 비우면 재생 안 함 |
| offline_pipeline | --bag-args | [] | ros2 bag play 추가 인자 |
| offline_pipeline | --bag-loop | False |  |
| offline_pipeline | --bag-rate | 1.0 |  |
| offline_pipeline | --bag-remap |  | ros2 bag play의 remap 규칙 문자열 |
| offline_pipeline | --bag-warmup-sec | 0.0 |  |
| offline_pipeline | --best-effort | False |  |
| offline_pipeline | --cl | DEFAULT_CL |  |
| offline_pipeline | --data-root |  | Base directory for generated artifacts (overrides profile/data root) |
| offline_pipeline | --decoded-dir |  | Override decoded temporary directory |
| offline_pipeline | --decoder | draco_decoder |  |
| offline_pipeline | --drc-dir |  | Override Draco output directory |
| offline_pipeline | --encoder-extra | [] | draco_encoder에 넘길 추가 인자 문자열 (예: '--speed 10') |
| offline_pipeline | --fast-preset | False | 30FPS 목표용 빠른 설정 적용 |
| offline_pipeline | --force-tqdm | False | QA 단계(analyze_draco_quality.py)에서 tqdm 강제 표시 |
| offline_pipeline | --jobs | 1 |  |
| offline_pipeline | --keep-decoded | False | QA 단계에서 디코드 PLY를 삭제하지 않음 |
| offline_pipeline | --layout-profile |  | Name or path of a layout profile for directories |
| offline_pipeline | --max-frames | 0 | 0=무제한 (bag 끝날 때까지) |
| offline_pipeline | --no-qa | False | 품질 분석 단계 생략 |
| offline_pipeline | --ply-dir |  | Override raw PLY output directory |
| offline_pipeline | --prefix |  |  |
| offline_pipeline | --qg | DEFAULT_QG |  |
| offline_pipeline | --qp | DEFAULT_QP |  |
| offline_pipeline | --results-dir |  | Override aggregated results directory |
| offline_pipeline | --reuse-drc | False | 기존 DRC를 재사용(재인코딩 생략) |
| offline_pipeline | --rmw-impl |  | 하위 프로세스에 전달할 RMW_IMPLEMENTATION 덮어쓰기 |
| offline_pipeline | --ros-domain-id |  | 하위 프로세스에 전달할 ROS_DOMAIN_ID 덮어쓰기 |
| offline_pipeline | --ros-localhost-only |  | 하위 프로세스에 전달할 ROS_LOCALHOST_ONLY 값 Choices: 0, 1 |
| offline_pipeline | --saver-timeout | 180.0 | Global timeout (seconds) for bag_to_ply stage; 0 disables |
| offline_pipeline | --saver-voxel-size | 0.0 | bag_to_ply voxel downsample 크기(m) |
| offline_pipeline | --thresholds | [0.01, 0.03, 0.05] |  |
| offline_pipeline | --topic |  |  |
| stream_client | --ack-timeout | 0.5 | Base ACK timeout in seconds before adaptive adjustments (minimum clamp) |
| stream_client | --ack-timeout-max | 2.0 | Upper bound for adaptive ACK timeout (seconds) |
| stream_client | --ack-timeout-min | 0.5 | Lower bound for adaptive ACK timeout (seconds) |
| stream_client | --ack-timeout-strikes | 3 | Number of consecutive ACK timeout strikes before failing the session |
| stream_client | --adaptive-window | False | Enable RTT/throughput based TX window adaptation |
| stream_client | --bag |  |  |
| stream_client | --best-effort | False |  |
| stream_client | --capture-queue | 4 | Maximum capture queue depth before applying backpressure |
| stream_client | --capture-transport | shared-memory | Frame capture backend: filesystem spool (legacy) or shared-memory zero copy Choices: filesystem, shared-memory |
| stream_client | --control-port | 0 | Optional TCP port for a dedicated control-plane connection (0 disables) |
| stream_client | --data-root |  | Base directory for generated artifacts (overrides profile/data root) |
| stream_client | --decoded-dir |  | Override directory where decoded frames from the server are stored |
| stream_client | --encode-workers | 2 | Number of concurrent encoder workers for the async pipeline |
| stream_client | --heartbeat-timeout | 10.0 | Fail the session if no ACK/heartbeat is observed within this many seconds |
| stream_client | --idle-timeout | 10.0 |  |
| stream_client | --initial-inflight |  | Initial TX window before adaptive control adjusts it (defaults to max) |
| stream_client | --layout-profile |  | Name or path of a layout profile (configs/*.profile.{yaml,json}) |
| stream_client | --max-frames | 0 |  |
| stream_client | --max-inflight, --max-pending | 4 | Upper bound on in-flight frames awaiting ACK/decoded replies |
| stream_client | --metrics-out, --telemetry-out | artifacts/perf/client_latest.json | 텔레메트리 JSON 출력 경로 (스키마 준수). |
| stream_client | --metrics-sample | 50000 | Maximum number of points sampled for client-side metrics (0 means use all points) |
| stream_client | --no-save-decoded | False | Do not persist decoded responses from the server to disk |
| stream_client | --play-frame-id | lidar_link |  |
| stream_client | --play-hz | 10.0 |  |
| stream_client | --play-sample | 50000 |  |
| stream_client | --play-topic-prefix | stream_pair |  |
| stream_client | --ply-dir |  | Override the spool directory for captured PLY frames |
| stream_client | --prefix |  |  |
| stream_client | --print-metrics | False | Stream per-frame latency/accuracy metrics to stdout during playback |
| stream_client | --protocol | binary | 'Framing protocol to use (default: %(default)s). Options: ' + ', '.join((f'{name}={desc}' for name, desc in protocol_help.items())) Choices: sorted(protocol_help.keys()) |
| stream_client | --qos-override |  | Override QoS profile file. Defaults to layout profile or package configs |
| stream_client | --quality-report-dir | artifacts/quality | Directory where per-frame quality JSONL reports are written |
| stream_client | --quality-thresholds | {} | JSON object describing max deltas for quality metrics (empty for informational only) |
| stream_client | --resp-format | ply | Expected format for decoded payloads returned by the server (default: %(default)s) Choices: ply, pcd |
| stream_client | --server-host | 127.0.0.1 |  |
| stream_client | --server-port | 5000 |  |
| stream_client | --socket-buffer-autotune | False | 커널 소켓 버퍼 자동 튜닝을 요청한다 (SO_SNDBUF/SO_RCVBUF=0). |
| stream_client | --socket-buffer-kb | 0 | Resize socket send/receive buffers (KiB) to better saturate fast links |
| stream_client | --socket-timeout | 15.0 | Timeout (seconds) for socket operations; 0 disables the safeguard |
| stream_client | --spool-gc-window | 0 | Maximum number of discovered spool files to remember before pruning (0 disables) |
| stream_client | --tcp-nodelay | False | Disable Nagle aggregation to reduce latency for interactive playback |
| stream_client | --topic |  |  |
| stream_client | --transport | tcp | Transport layer for data plane. tcp만 구현되어 있으며 quic/udp_fec는 예약 상태입니다. Choices: tcp, quic, udp_fec |
| stream_client | --tx-fragment-size | 0 | Binary 프로토콜에서 payload를 MTU 안전 조각으로 분할한다 (0은 비활성). |
| stream_client | --window-ema-alpha | 0.2 | EMA smoothing factor for adaptive window telemetry (0-1) |
| stream_client | --work-dir |  | Override temporary directory for encoder scratch data |
| stream_collect_logs | --attach | [] | Additional files or directories to copy into artifacts/ |
| stream_collect_logs | --data-root |  | Override base data root |
| stream_collect_logs | --layout-profile |  | Layout profile used to resolve directories |
| stream_collect_logs | --metadata | [] | Key=Value metadata to record in the manifest |
| stream_collect_logs | --notes |  | Free-form note written into notes/README.txt |
| stream_collect_logs | --ros-log | [] | Path(s) to ROS log directories to archive |
| stream_collect_logs | run_id |  | Identifier for the experiment run (used as directory name) |
| stream_monitor | --decoded-dir | data/tmp_decoded_ply |  |
| stream_monitor | --decoded-suffix | .decoded.ply |  |
| stream_monitor | --frame-id | lidar_link |  |
| stream_monitor | --hz | 10.0 |  |
| stream_monitor | --limit | 0 |  |
| stream_monitor | --loop | False |  |
| stream_monitor | --orig-dir | data/ply_raw |  |
| stream_monitor | --orig-suffix | .ply |  |
| stream_monitor | --prefix | sample2 |  |
| stream_monitor | --sample | 50000 |  |
| stream_monitor | --topic-prefix | sample2_pair |  |
| stream_netem | --clear | False | Remove existing netem qdisc before applying the selected profile |
| stream_netem | --config |  | Override path to netem profiles file |
| stream_netem | --dry-run | False | Print commands without executing them |
| stream_netem | --iface | lo | Network interface to configure (default: loopback) |
| stream_netem | profile |  | Name of the profile to apply or 'list' to inspect available profiles |
| stream_replay | --decoded-dir | data/tmp_decoded_ply | 디코드 PLY 디렉토리 |
| stream_replay | --decoded-suffix | .decoded.ply | 디코드 파일 접미사 |
| stream_replay | --frame-id | map | header frame_id |
| stream_replay | --hz | 5.0 | 재생 속도(Hz) |
| stream_replay | --limit | 0 | 0=전체, 양수=앞에서 N개만 |
| stream_replay | --loop | False | 끝나면 처음부터 반복 |
| stream_replay | --orig-dir | data/ply_raw | 원본 PLY 디렉토리 |
| stream_replay | --orig-suffix | .ply | 원본 파일 접미사 |
| stream_replay | --prefix | sample2 | 파일 접두어 |
| stream_replay | --topic-prefix | compare | 퍼블리시 토픽 접두어 |
| stream_server | --control-port | 0 | Optional TCP port dedicated to control-plane messages (0 disables) |
| stream_server | --decode-timeout | 30.0 | Fail decoding if the external tool exceeds this timeout (seconds) |
| stream_server | --decode-workers | 2 | Number of concurrent decode workers in the async pipeline |
| stream_server | --decoder |  | Path to draco_decoder |
| stream_server | --heartbeat-interval | 2.0 | Interval (seconds) for control-plane heartbeat messages; 0 disables keepalive |
| stream_server | --host | 0.0.0.0 |  |
| stream_server | --keep-artifacts | False | Retain .drc/.ply decode artifacts for debugging (default cleans up) |
| stream_server | --legacy-mode | False | Fallback to the synchronous legacy loop for troubleshooting |
| stream_server | --max-inflight | 2 | Maximum number of frames to decode concurrently before backpressuring the client |
| stream_server | --metrics-sample | 50000 | Maximum number of points sampled when computing quality metrics (0 disables sampling) |
| stream_server | --port | 5000 |  |
| stream_server | --protocol | binary | 'Framing protocol expected from clients (default: %(default)s). Options: ' + ', '.join((f'{name}={desc}' for name, desc in protocol_help.items())) Choices: sorted(protocol_help.keys()) |
| stream_server | --queue-size | 0 | Maximum server queue depth before applying backpressure (0 uses --max-inflight) |
| stream_server | --resp-format | ply | Format used for decoded payloads returned to the client (default: %(default)s) Choices: ply, pcd |
| stream_server | --socket-buffer-kb | 0 | Resize socket send/receive buffers (KiB) for high-throughput links |
| stream_server | --socket-timeout | 30.0 | Timeout (seconds) for socket operations; 0 disables the safeguard |
| stream_server | --tcp-nodelay | False | Disable Nagle aggregation on accepted sockets for lower latency |
| stream_server | --work-dir | data/server_tmp |  |
| stream_server | --zero-copy-reply | False | Memory-map decoded PLY payloads to reduce copy overhead when sending replies |
<!-- AUTODOC:CLI_FLAGS:END -->

<!-- AUTODOC:TROUBLESHOOT:BEGIN -->
| Symptom | Likely Cause | Recommended Fix | Source |
| - | - | - | - |
| Shared memory publish failed for <stem> | SharedMemoryPublisher backend unavailable or exhausted | Ensure shared memory daemon is running or disable --shared-memory-only | ros2_ws/src/draco_roundtrip/draco_roundtrip/io/bag_recorder.py:104 |
| Telemetry validation failed: pending frames remain | Telemetry exported before ControlPlane reached TERMINATED | Drain outstanding ACKs or wait for on_eof handshake before exporting | ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/telemetry.py:146 |
| ACK timeout strikes exceeded | Network congestion or control-plane heartbeat stalled | Increase --ack-timeout-max or investigate link health (check metrics logs) | ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_client.py:1798 |
| No messages for idle-timeout. Shutting down. | Rosbag stream exhausted or topic inactive | Lower --idle-timeout or verify rosbag playback | ros2_ws/src/draco_roundtrip/draco_roundtrip/io/bag_recorder.py:82 |
<!-- AUTODOC:TROUBLESHOOT:END -->
