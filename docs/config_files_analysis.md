# 설정 파일 분석 문서

## 설정 파일 목록

### ROS QoS 설정
1. `/home/kkit/newdisk/draco_tcpip/configs/qos_override.yaml`
   - **정보**: ROS2 QoS 프로파일 오버라이드 설정 파일
   - **분석**: 
     - LiDAR 포인트 클라우드 토픽에 대한 QoS 설정
     - best_effort 신뢰성으로 설정하여 실시간성 강화
     - volatile 내구성으로 메모리 사용 최적화
     - 10개의 최신 메시지만 유지하여 리소스 관리

2. `/home/kkit/newdisk/draco_tcpip/ros2_ws/src/draco_roundtrip/draco_roundtrip/configs/qos_override.yaml`
   - **정보**: 패키지 수준의 QoS 설정 파일
   - **분석**: 메인 QoS 설정의 복제본으로, 패키지 내부에서 참조 가능

### Draco 설정
1. `/home/kkit/newdisk/draco_tcpip/configs/draco.json`
   - **정보**: Draco 압축 설정 파일
   - **분석**: 빈 파일이나, Draco 압축 설정을 위한 템플릿으로 존재

### 네트워크 설정
1. `/home/kkit/newdisk/draco_tcpip/configs/netem.profiles.yaml`
   - **정보**: 네트워크 에뮬레이션 프로파일
   - **분석**: 빈 파일이나, 네트워크 조건 에뮬레이션을 위한 템플릿으로 존재

2. `/home/kkit/newdisk/draco_tcpip/configs/server.profile.yaml`
   - **정보**: 서버 프로파일 설정
   - **분석**: 빈 파일이나, 서버 구성을 위한 템플릿으로 존재

3. `/home/kkit/newdisk/draco_tcpip/configs/client.profile.yaml`
   - **정보**: 클라이언트 프로파일 설정
   - **분석**: 빈 파일이나, 클라이언트 구성을 위한 템플릿으로 존재

### SLAM 설정
1. `/home/kkit/newdisk/draco_tcpip/configs/hdl_graph_slam_stream.yaml`
   - **정보**: HDL Graph SLAM 스트리밍 설정
   - **분석**: 
     - 입력 토픽 설정 (/stream_pair/decoded)
     - 프레임 ID 설정 (lidar_link, odom, map)
     - 키프레임 파라미터 설정:
       - 이동 거리: 0.5m
       - 회전 각도: 0.2rad
       - 시간 간격: 1.0초
     - 복셀 필터 설정 (0.2m 해상도)
     - NDT 정합 파라미터
     - 루프 클로저 파라미터

2. `/home/kkit/newdisk/draco_tcpip/configs/rtabmap_stream.yaml`
   - **정보**: RTAB-Map 스트리밍 설정
   - **분석**:
     - SLAM 노드 설정:
      - 프레임 설정
        - `frame_id`는 `base_link`, `odom_frame_id`는 `odom`으로 유지해 로봇 상태 퍼블리셔가 제공하는 `base_link -> lidar_frame` 정적 변환과 충돌하지 않도록 함. LiDAR 데이터는 여전히 `lidar_frame`에서 수신되지만, 오도메트리 출력은 `odom -> base_link` 체인을 유지해 TF 트리에서 부모가 이중으로 정의되는 문제를 방지함.
     - 메모리 관리
     - 루프 클로저 파라미터
     - 그리드 맵 설정
     - ICP 오도메트리 노드 설정:
       - 포인트 투 플레인 ICP
       - 복셀 크기 0.2m
       - 반복 횟수 30회
       - 키프레임 설정

### ROS 토픽 설정
1. `/home/kkit/newdisk/draco_tcpip/configs/ros_topics.yaml`
   - **정보**: ROS 토픽 설정 파일
   - **분석**: 빈 파일이나, ROS 토픽 구성을 위한 템플릿으로 존재

### 텔레메트리 설정
1. `/home/kkit/newdisk/draco_tcpip/docs/reference/telemetry_schema.json`
   - **정보**: 텔레메트리 데이터 스키마 정의
   - **분석**: 
     - 프레임 카운터 (인코딩/디코딩)
     - 데이터 전송량 (업링크/다운링크)
     - 다운링크 성능 지표
     - 포즈 업데이트 지연 시간
     - 경로 계획 메트릭
     - JSON Schema Draft-07 형식
     - 추가 속성 허용

### ROS Bag 메타데이터
1. `/home/kkit/newdisk/draco_tcpip/ros2_ws/data/bags/rosbag2_2024_09_24-14_28_57/metadata.yaml`
   - **정보**: ROS Bag 메타데이터
   - **분석**: 
     - 녹화 시간: 약 73.1초
     - 메시지 수: 1,464개
     - 토픽:
       - raw 포인트 클라우드 (732 메시지)
       - 처리된 포인트 클라우드 (732 메시지)
     - SQLite3 저장소 사용
     - QoS 프로파일 정보 포함

2. `/home/kkit/newdisk/draco_tcpip/ros2_ws/data/bags/rosbag2_2024_09_24-14_30_22/metadata.yaml`
   - **정보**: ROS Bag 메타데이터
   - **분석**: 
     - 녹화 시간: 약 43.4초
     - 메시지 수: 870개
     - 토픽:
       - raw 포인트 클라우드 (435 메시지)
       - 처리된 포인트 클라우드 (435 메시지)
     - SQLite3 저장소 사용
     - QoS 프로파일 정보 포함