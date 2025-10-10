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

### 2. 스트리밍 클라이언트
다른 터미널에서 아래 명령을 실행합니다.
```bash
ros2 run draco_roundtrip stream_client \
    --bag /path/to/rosbag_directory \
    --topic /sensing/lidar/top/pointcloud \
    --prefix cycle_sample
```
- QoS override는 기본적으로 `configs/qos_override.yaml`을 참조합니다. 필요 시 `--qos-override`로 다른 파일을 지정할 수 있습니다.
- `--encoder`, `--decoder` 옵션으로 Draco 실행 파일 경로를 직접 지정할 수 있으며, `--cl`, `--qp`, `--qg`로 압축 품질을 조정할 수 있습니다.
- 수신/복원된 포인트클라우드는 `stream_pair/source`, `stream_pair/decoded` 토픽으로 퍼블리시됩니다.

### 3. 배치 품질 분석
```bash
ros2 run draco_tools encode_ply_to_draco --input data/ply_stream --out data/drc
ros2 run draco_tools offline_pipeline --bag /path/to/rosbag_directory --config configs/draco.json
```
위 명령은 PLY → Draco 변환 및 품질 분석 리포트를 생성합니다. 상세 옵션은 `--help`로 확인하세요.

### 4. SLAM 연계 런치
```bash
ros2 launch slam_stream_bridge hdl_graph_slam_stream.launch.py
```
필요한 토픽 remap 및 QoS 설정은 런치 인자 또는 `configs/*.yaml` 파일에서 조정합니다.

## 추가 자료
- `docs/HOWTO.md`: 세부 운영 시나리오와 환경 설정 가이드
- `docs/3d_slam_setup.md`: SLAM 연동 구성 절차
- `docs/encoder_cli.md`: Draco 인코더 CLI 헬퍼와 통합 로그 포맷 가이드
- `docs/results_template.md`: 실험 결과 정리 템플릿
- `refac.md`: 현재 진행 중인 리팩토링 제안 및 단계별 목표

기여 시에는 리팩토링 로드맵과 체크리스트를 참고하여 코드 구조와 문서가 일관되도록 유지해주세요.
