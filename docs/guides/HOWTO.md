# Draco Roundtrip 시작 가이드

이 문서는 워크스페이스를 처음 세팅할 때 필요한 순서를 요약합니다. 전체 코드 구조와 데이터 흐름은 `../references/codebase_overview.md`에서 다루고 있으므로, 각 단계가 어떤 패키지와 연관되는지 함께 확인하세요.

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
   - 주요 로직: `draco_roundtrip/nodes/stream_server.py`가 TCP 수신, Draco 디코딩, ROS 토픽 퍼블리시를 담당합니다.【F:ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_server.py†L1-L160】
   - 기본값으로 디코딩 중간 산출물(`.drc`, `.decoded.ply`)은 자동 정리됩니다. 분석 목적이라면 `--keep-artifacts` 플래그를 추가해 세션이 끝난 뒤에도 파일을 보존하세요.
2. 필요 시 네트워크 조건을 설정합니다.
   ```bash
   # 명령만 확인하고자 할 때 (dry-run)
   ros2 run draco_roundtrip stream_netem wifi_dense --iface lo --dry-run

   # 실제 적용 예시 (sudo 필요)
   sudo ros2 run draco_roundtrip stream_netem wifi_dense --iface eno1 --clear
   ```
3. 다른 터미널에서 클라이언트를 실행합니다.
   ```bash
   ros2 run draco_roundtrip stream_client \
       --bag /path/to/bag \
       --topic /sensing/lidar/top/pointcloud \
       --prefix demo_run
   ```
   - 클라이언트는 `draco_roundtrip/nodes/stream_client.py`에서 인플라이트 제어, 공유 메모리, Draco 인코더 연동을 처리합니다.【F:ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_client.py†L1-L222】
   - `--layout-profile` 또는 `--data-root`로 출력 디렉터리를 손쉽게 구성할 수 있습니다. 프로파일 구조는 `../references/layout_profiles.md`를 참고하세요.
   - QoS 설정을 변경하려면 `--qos-override configs/qos_override.yaml`를 지정하거나 프로파일에 `qos_override` 항목을 추가합니다.
   - 스트림이 종료되면 클라이언트가 `MSG_EOF`를 서버에 전송하고 로그에 `[CLIENT] Sent EOF marker to server`/`[CLIENT] EOF handshake complete`가 출력됩니다. 해당 메시지가 보이면 큐가 모두 비워졌고 양쪽에서 세션이 정상적으로 마무리됐음을 의미합니다.【F:ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/stream_client.py†L650-L825】
4. 서버는 복원된 포인트클라우드를 `/stream_pair/decoded` 토픽으로 퍼블리시하며, 클라이언트는 원본/복원 토픽을 동시에 노출합니다.

## 3. 모니터링 및 재생 도구
- 실시간 품질 확인: `ros2 run draco_roundtrip stream_monitor --source /stream_pair/source --decoded /stream_pair/decoded`
- 저장된 PLY 쌍 재생: `ros2 run draco_roundtrip stream_replay --original data/ply --decoded data/decoded`
- 두 도구 모두 `draco_roundtrip/tools` 하위 모듈이 `utils.metrics`와 `io.ply_codec`을 재사용해 일관된 지표를 출력합니다.【F:ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/__init__.py†L1-L78】

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
   - `offline_pipeline`은 bag 재생부터 metrics 계산까지 한 번에 실행하며, 스트리밍과 동일한 레이아웃 헬퍼(`draco_roundtrip.utils.config`)를 재사용합니다.【F:ros2_ws/src/draco_tools/draco_tools/offline_pipeline.py†L1-L120】

## 5. 통합 Bringup과 SLAM 연동
- `slam_stream_bridge/launch/bringup.launch.py`는 스트리밍 서버/클라이언트와 SLAM 파이프라인을 한 번에 기동합니다.【F:ros2_ws/src/slam_stream_bridge/slam_stream_bridge/launch/bringup.launch.py†L1-L128】
  ```bash
  ros2 launch slam_stream_bridge bringup.launch.py \
      bag:=/path/to/bag \
      topic:=/sensing/lidar/top/pointcloud \
      layout_profile:=client.profile.yaml \
      slam:=rtabmap \
      netem_profile:=wifi_dense
  ```
- `slam` 인자로 `rtabmap` 또는 `hdl`을 선택하고, 필요 시 `slam_params`로 파라미터 파일을 덮어씁니다. 기본 파라미터는 `configs/rtabmap_stream.yaml`, `configs/hdl_graph_slam_stream.yaml`에 있습니다.
- `netem_profile`은 `configs/netem.profiles.yaml`을 기반으로 하며, `netem_dry_run:=false`로 설정하면 실제 `tc` 명령이 실행됩니다.
- 개별 SLAM 런치 파일(`hdl_graph_slam_stream.launch.py`, `rtabmap_stream.launch.py`)도 그대로 사용할 수 있습니다. 세부 절차는 `3d_slam_setup.md`(동일 폴더)에 정리되어 있습니다.

## 6. 엔드투엔드 회귀 테스트
- `ros2_ws/src/draco_roundtrip/tests/e2e_roundtrip.sh` 스크립트는 numpy 기반 스텁 인코더/디코더를 사용해 최소 왕복 경로를 검증합니다.
- GitHub Actions CI 역시 동일 스크립트를 호출해 회귀를 방지합니다.
- 테스트 결과는 `../templates/results_template.md`를 활용해 기록하는 것을 권장합니다.

## 7. 로그 수집 및 결과 정리
- 실험 종료 후에는 `stream_collect_logs` CLI로 결과 디렉터리를 구조화하세요.
  ```bash
  ros2 run draco_roundtrip stream_collect_logs run_20240315 \
      --layout-profile client.profile.yaml \
      --data-root ./data \
      --metadata bag=sample.bag --metadata netem=wifi_dense --metadata slam=rtabmap \
      --ros-log ~/.ros/log/latest \
      --notes "Baseline roundtrip"
  ```
- 생성된 `manifest.json`과 디렉터리 구조는 `logging_guidelines.md`(동일 폴더)에서 설명합니다.
- 프로파일과 디렉터리 구조의 전체 필드는 `../references/config_reference.md`를 확인하세요.

## 8. 레거시 경고
- 과거 `draco-ros2-roundtrip/scripts/*.py` 실행 파일은 모두 삭제되었습니다. 모든 워크플로는 `ros2 run` 또는 `ros2 launch` 명령을 사용해야 합니다.
- 레거시 자동화 스크립트가 필요하다면, 새 CLI를 import한 thin wrapper를 만들거나 본 문서의 명령을 그대로 호출하세요.

### 관련 코드 살펴보기
- 스트리밍 노드: `ros2_ws/src/draco_roundtrip/draco_roundtrip/nodes/`
- Draco 래퍼: `ros2_ws/src/draco_roundtrip/draco_roundtrip/draco/`
- 네트워크/레이아웃 유틸리티: `ros2_ws/src/draco_roundtrip/draco_roundtrip/utils/`
- 로그 수집 도구: `ros2_ws/src/draco_roundtrip/draco_roundtrip/tools/log_collection.py`

보다 심층적인 설계 맥락은 `../designs/async_pipeline_design.md`를 참고해 주세요.
