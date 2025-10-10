# Draco Roundtrip HOWTO

이 문서는 리포지터리를 처음 받아 워크스페이스를 빌드하고, 스트리밍 파이프라인과 배치 분석을 실행하는 기본 절차를 정리합니다. 모든 명령은 ROS 2 Humble 환경을 기준으로 작성되었습니다.

## 1. 워크스페이스 준비
1. ROS 2를 설치하고 `source /opt/ros/humble/setup.bash`로 환경을 불러옵니다.
2. 리포지터리를 원하는 위치에 클론합니다.
3. 의존성을 설치하고 워크스페이스를 빌드합니다.
   ```bash
   cd /path/to/draco_tcpip/ros2_ws
   rosdep install --from-paths src --rosdistro humble --ignore-src -y
   colcon build --symlink-install
   source install/setup.bash
   ```
   > GitHub Actions CI(`.github/workflows/ros-ci.yaml`)는 위 단계를 자동화하여 회귀 테스트를 수행합니다.

## 2. 스트리밍 서버/클라이언트 실행
1. 서버를 먼저 실행합니다.
   ```bash
   ros2 run draco_roundtrip stream_server --port 5000
   ```
2. 다른 터미널에서 클라이언트를 실행합니다.
   ```bash
   ros2 run draco_roundtrip stream_client \
       --bag /path/to/bag \
       --topic /sensing/lidar/top/pointcloud \
       --prefix demo_run
   ```
   - `--layout-profile` 또는 `--data-root`를 사용해 출력 디렉터리를 손쉽게 구성할 수 있습니다. (`docs/layout_profiles.md` 참고)
   - QoS 설정을 변경하려면 `--qos-override configs/qos_override.yaml`를 지정하거나, 프로필 파일에 `qos_override` 섹션을 추가하세요.
3. 서버는 복원된 포인트클라우드를 `/stream_pair/decoded` 토픽으로 퍼블리시하며, 클라이언트는 원본/복원 토픽을 동시에 노출합니다.

## 3. 모니터링 및 재생 도구
- 실시간 품질 확인: `ros2 run draco_roundtrip stream_monitor --source /stream_pair/source --decoded /stream_pair/decoded`
- 저장된 PLY 쌍 재생: `ros2 run draco_roundtrip stream_replay --original data/ply --decoded data/decoded`
- 두 도구 모두 `draco_roundtrip.utils` 모듈을 통해 동일한 metrics/PLY 헬퍼를 사용하므로 CLI 인자가 일관됩니다.

## 4. 배치 파이프라인
1. rosbag을 PLY로 변환합니다.
   ```bash
   ros2 run draco_tools bag_to_ply --bag /path/to/bag --out data/ply_stream
   ```
2. PLY를 Draco로 변환하고 품질 리포트를 생성합니다.
   ```bash
   ros2 run draco_tools encode_ply_to_draco --input data/ply_stream --out data/drc
   ros2 run draco_tools offline_pipeline --bag /path/to/bag --config configs/draco.json
   ```
   - `offline_pipeline`은 bag 재생부터 metrics 계산까지 한 번에 실행하며, 스트리밍과 동일한 레이아웃 헬퍼를 공유합니다.

## 5. SLAM 연동
- `slam_stream_bridge` 패키지의 런치 파일을 사용해 SLAM 노드를 동시에 기동할 수 있습니다.
  ```bash
  ros2 launch slam_stream_bridge hdl_graph_slam_stream.launch.py
  ```
- 세부 설정과 RTAB-Map 구성은 `docs/3d_slam_setup.md`를 참고하세요.

## 6. 엔드투엔드 회귀 테스트
- `ros2_ws/src/draco_roundtrip/tests/e2e_roundtrip.sh` 스크립트는 pytest 기반 스텁 인코더/디코더를 사용해 회귀 테스트를 수행합니다.
- GitHub Actions CI 역시 동일 스크립트를 호출하여 numpy가 설치된 환경에서 왕복 경로를 검증합니다.
- 테스트 결과는 `docs/results_template.md`에 맞춰 기록하는 것을 권장합니다.

## 7. 레거시 경고
- 기존 `draco-ros2-roundtrip/scripts/*.py` 실행 파일은 제거되었습니다. 모든 워크플로는 `ros2 run` 또는 `ros2 launch` 명령으로 교체해야 합니다.
- 레거시 자동화 스크립트를 유지해야 한다면, 새 CLI를 import하여 thin wrapper를 구현하거나 본 문서의 명령을 그대로 호출하세요.

필요한 추가 정보는 `README.md`, `docs/encoder_cli.md`, `docs/utils_usage.md`에서 찾아볼 수 있습니다.
