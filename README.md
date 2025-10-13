# Draco TCP/IP Roundtrip Workspace

이 리포지터리는 LiDAR 포인트클라우드를 Draco로 압축해 TCP를 통해 왕복 전송하고, 복원 품질을 검증하는 ROS 2 워크스페이스입니다. `ros2_ws` 아래의 `draco_roundtrip`, `draco_tools`, `slam_stream_bridge` 패키지가 동일한 코드베이스를 공유하며 스트리밍과 오프라인 분석을 모두 지원합니다.

## 주요 기능
- **실시간 스트리밍**: rosbag 또는 라이브 토픽에서 추출한 PLY 프레임을 Draco로 인코딩하여 서버로 전송하고, 복원된 포인트클라우드를 다시 ROS 토픽으로 퍼블리시합니다.
- **배치 파이프라인**: `draco_tools` 모듈을 이용해 bag → PLY → Draco → 품질 분석을 일괄 수행하고 CSV/Markdown 리포트를 생성합니다.
- **품질 지표 분석**: Chamfer-like 지표, 바운딩 박스 비교 등 스트리밍과 배치가 동일한 metric 모듈을 사용하도록 통합했습니다.
- **SLAM 연동**: `slam_stream_bridge` 런치 파일을 통해 복원된 포인트클라우드를 SLAM 패키지에 연결할 수 있습니다.

## 리포지터리 구조
```
.
├── configs/                # QoS, 네트워크 에뮬레이션 등 공용 설정
├── docs/                   # 운영 가이드 및 리포트 템플릿
├── refac.md                # 리팩토링 제안 및 현황 문서
└── ros2_ws/
    └── src/
        ├── draco_roundtrip/
        │   ├── draco_roundtrip/  # 스트리밍 노드, 공용 utils, CLI
        │   ├── package.xml
        │   └── setup.*
        ├── draco_tools/
        │   ├── draco_tools/      # 배치 파이프라인, 분석 모듈
        │   ├── package.xml
        │   └── setup.*
        └── slam_stream_bridge/
            ├── slam_stream_bridge/  # SLAM 연계 런치 파일
            ├── package.xml
            └── setup.*
```

## 사전 준비
1. **ROS 2**: Humble(권장) 또는 호환 배포판을 설치하고 `source /opt/ros/<distro>/setup.bash`로 환경을 불러옵니다.
2. **Draco 바이너리**: [Google Draco 릴리스](https://github.com/google/draco/releases)에서 `draco_encoder`, `draco_decoder`를 받아 PATH에 추가하거나 다음 환경 변수를 설정합니다.
   ```bash
   export DRACO_HOME=/path/to/draco/build
   export PATH="$DRACO_HOME:$PATH"
   export DRACO_ENCODER=$DRACO_HOME/draco_encoder
   export DRACO_DECODER=$DRACO_HOME/draco_decoder
   ```
3. **Python 의존성**: `ros2_ws`에서 `colcon build`를 실행하면 필요한 파이썬 패키지가 `setup.cfg`에 따라 설치됩니다. 수동 설치가 필요하면 `pip install numpy plyfile scipy open3d` 등을 실행하세요.
4. **데이터 준비**: 테스트 rosbag을 별도 디렉터리에 보관하고, 실행 시 `--bag` 옵션으로 경로를 넘기거나 `draco_tools.bag_to_ply`를 사용해 PLY 프레임을 생성합니다.

## 빌드
```bash
source /opt/ros/<distro>/setup.bash
cd /workspace/draco_tcpip/ros2_ws
colcon build --symlink-install
source install/setup.bash
```
`~/.bashrc`에 위 두 개의 `source` 명령을 추가하면 새 터미널에서 바로 ROS 2 환경을 사용할 수 있습니다.

## 실행 예시
### 1. 스트리밍 서버
```bash
ros2 run draco_roundtrip stream_server --port 5000
```
`draco_decoder`가 PATH에 없으면 `--decoder /absolute/path/to/draco_decoder`로 직접 지정할 수 있습니다.
- 제어 평면 하트비트와 ACK 전송 주기는 `--heartbeat-interval`로 조정할 수 있습니다. 기본 2초 간격으로 빈 구간에서도 클라이언트를 깨워
  지연 경보를 발생시키며, `0`으로 설정하면 keepalive를 비활성화합니다.

### 2. 스트리밍 클라이언트
다른 터미널에서 아래 명령을 실행합니다.
```bash
ros2 run draco_roundtrip stream_client \
    --bag /path/to/rosbag_directory \
    --topic /sensing/lidar/top/pointcloud \
    --prefix cycle_sample
```
- QoS override는 기본적으로 `configs/qos_override.yaml`을 참조합니다. 필요 시 `--qos-override`로 다른 파일을 지정하거나 레이아웃 프로필에서 `qos_override`를 정의할 수 있습니다.
- `--layout-profile`을 지정하면 `configs/*.profile.yaml|json`에 정의된 데이터 루트와 디렉터리 구성이 적용됩니다. `--data-root`, `--ply-dir`, `--work-dir`, `--decoded-dir`를 통해 필요한 경로만 덮어쓸 수 있습니다.
- `--encoder`, `--decoder` 옵션으로 Draco 실행 파일 경로를 직접 지정할 수 있으며, `--cl`, `--qp`, `--qg`로 압축 품질을 조정할 수 있습니다.
- 수신/복원된 포인트클라우드는 `stream_pair/source`, `stream_pair/decoded` 토픽으로 퍼블리시됩니다.
- `--max-inflight/--max-pending`는 동시에 전송 중인 프레임 윈도우를 제한합니다. `--initial-inflight`로 초기 값을, `--adaptive-window`와 `--window-ema-alpha`로 RTT 기반 적응형 제어를 활성화할 수 있습니다.
- `--heartbeat-timeout`은 서버에서 ACK/하트비트를 받지 못했을 때 세션을 중단하는 임계 시간을 정의합니다. 기본 10초이며, 로그에는 펜딩
  프레임 수가 함께 출력됩니다.
- `--print-metrics`를 지정하면 각 프레임의 복원 품질 지표와 순단계 지연 시간이 로그로 출력됩니다. 지정하지 않더라도 최종 요약에는 p50/p95/p99 지연과 대역폭, 대기열 사용량이 포함됩니다.
- 클라이언트와 서버는 바이너리 프로토콜에서 제어 채널(`control/…`)과 데이터 채널(`data/…`)을 구분하며, 데이터 프레임이 도착하면 즉시 ACK를
  돌려보내 송신 윈도우를 해제합니다. EOF/오류/하트비트 역시 제어 채널로 송수신되며, 로그에 `EOF sent/received`가 표시되면 모든 큐가 비워지고 안전하게 종료된 것입니다. 구형 서버와 연동해야 할 경우 `--protocol legacy`를 이용해 텍스트 프레이밍으로도 동일한 메시지를 주고받을 수 있습니다.

#### 바이너리 전송 프로토콜 요약

- 모든 메시지는 `docs/specs/binary_transport.md`에 정리된 단일 헤더(`MAGIC=DRTC`, version, flags, type, sequence, …)를 사용합니다. 헤더 다음의 페이로드는 순수 Draco 바이트(데이터) 또는 JSON 제어 메시지(ACK/ERROR/HEARTBEAT)입니다.
- `--tx-fragment-size=0`은 조각내지 않은 전송을 의미하며, 양수로 설정하면 프레임이 메타데이터(`total_length/offset/chunk_length`)와 함께 여러 메시지로 쪼개집니다. 서버는 모든 조각을 재조립한 뒤에만 디코더를 호출합니다.
- ACK/ERROR/HEARTBEAT는 동일한 헤더 형식을 공유하고 `{"seq":123,"msg":"…"}` 형태의 JSON으로 응답합니다. 구형 서버가 텍스트 오류만 반환하더라도 클라이언트는 경고를 남기고 세션을 유지합니다.
- EOF는 HEARTBEAT 타입 + 예약 필드(`0x45`)로 전달되며, 양측 큐가 비워지면 `shutdown(SHUT_WR)`로 TCP를 정리합니다.

### 3. 배치 품질 분석
```bash
ros2 run draco_tools encode_ply_to_draco --input data/ply_stream --out data/drc
ros2 run draco_tools offline_pipeline --bag /path/to/rosbag_directory --config configs/draco.json
```
위 명령은 PLY → Draco 변환 및 품질 분석 리포트를 생성합니다. `offline_pipeline`도 `--layout-profile`, `--data-root`, `--ply-dir` 등 동일한 디렉터리 헬퍼를 사용하므로 스트리밍 환경과 동일한 결과 디렉터리를 간편하게 재사용할 수 있습니다. 상세 옵션은 `--help`로 확인하세요.

### 4. 통합 Bringup (스트리밍 + SLAM)
```bash
ros2 launch slam_stream_bridge bringup.launch.py \
    bag:=/path/to/bag \
    topic:=/sensing/lidar/top/pointcloud \
    layout_profile:=client.profile.yaml \
    slam:=rtabmap \
    netem_profile:=wifi_dense
```
- `slam` 인자로 `rtabmap` 또는 `hdl`을 지정할 수 있으며, `slam_params:=<파일>`로 파라미터 파일을 덮어쓸 수 있습니다.
- `netem_profile`은 `configs/netem.profiles.yaml`에 정의된 프리셋을 적용합니다. 기본값은 `loopback`이며, `netem_dry_run:=false`로 설정하면 실제로 `tc` 명령을 실행합니다. (필요 시 `sudo` 권한 필요)
- bringup 런치는 `stream_server`, `stream_client`, 선택한 SLAM 노드, 그리고 필요 시 네트워크 에뮬레이션을 순차적으로 실행합니다.

### 5. SLAM 단독 런치
기존 개별 런치 파일은 여전히 사용할 수 있습니다.
```bash
ros2 launch slam_stream_bridge hdl_graph_slam_stream.launch.py
ros2 launch slam_stream_bridge rtabmap_stream.launch.py cloud_topic:=/stream_pair/decoded
```
필요한 토픽 remap 및 QoS 설정은 런치 인자 또는 `configs/*.yaml` 파일에서 조정합니다.

## 추가 자료
- `docs/guides/HOWTO.md`: 세부 운영 시나리오와 환경 설정 가이드
- `docs/guides/3d_slam_setup.md`: SLAM 연동 구성 절차
- `docs/references/config_reference.md`: `configs/*.yaml` 및 프로파일 파일 설명과 활용 예시
- `docs/guides/logging_guidelines.md`: 결과 디렉터리 구조와 로그 수집 자동화 절차
- `docs/guides/encoder_cli.md`: Draco 인코더 CLI 헬퍼와 통합 로그 포맷 가이드
- `docs/references/layout_profiles.md`: 디렉터리/프로필 설정 규칙과 예시
- `docs/templates/results_template.md`: 실험 결과 정리 템플릿
- `docs/reports/refactor_report.md`: 리팩토링 완료 보고서 및 마이그레이션 안내
- `refac.md`: 현재 진행 중인 리팩토링 제안 및 단계별 목표

기여 시에는 리팩토링 로드맵과 체크리스트를 참고하여 코드 구조와 문서가 일관되도록 유지해주세요.

## 레거시 스크립트 정리 현황
- 과거 리포지터리 루트에 위치했던 `draco-ros2-roundtrip/scripts/*.py` 실행 파일은 모두 ROS 2 패키지 내부의 콘솔 엔트리포인트로 대체되었습니다.
- 기존 스크립트 경로를 사용하는 자동화는 `ros2 run draco_roundtrip ...` 또는 `ros2 run draco_tools ...` 형태로 교체해 주세요.
- 필요한 경우 `ros2 run <package> <entrypoint> --help`로 최신 인자 목록을 확인할 수 있으며, 본 README와 `docs/guides/encoder_cli.md`에서 대표적인 사용 예시를 제공합니다.
