# XML 파일 분석 문서

## ROS2 패키지 XML 파일

### draco_roundtrip 패키지
1. `/home/kkit/newdisk/draco_tcpip/ros2_ws/src/draco_roundtrip/package.xml`
   - **정보**: draco_roundtrip 패키지 매니페스트 파일
   - **분석**: 
     - 패키지 정보:
       - 버전: 0.1.0
       - 설명: Draco 포인트 클라우드 실험용 ROS 2 클라이언트/서버 노드
       - 관리자: GodokSa (ppakdone@gmail.com)
     - 빌드 시스템:
       - ament_python 사용
     - 실행 의존성:
       - ROS 2 기본: rclpy, sensor_msgs, std_msgs
       - 수치 계산: python3-numpy, python3-scipy
       - 포인트 클라우드: python3-plyfile, python3-open3d
       - 런치 시스템: launch, launch_ros
     - 테스트 의존성:
       - ament_pytest

### draco_tools 패키지
1. `/home/kkit/newdisk/draco_tcpip/ros2_ws/src/draco_tools/package.xml`
   - **정보**: draco_tools 패키지 매니페스트 파일
   - **분석**: 
     - 패키지 정보:
       - 버전: 0.1.0
       - 설명: Draco 실험용 지원 유틸리티 (bag 변환, 인코딩)
       - 관리자: GodokSa (ppakdone@gmail.com)
     - 빌드 시스템:
       - ament_python 사용
     - 실행 의존성:
       - ROS 2 기본: rclpy, sensor_msgs, std_msgs
       - 수치 계산: python3-numpy, python3-scipy
       - 포인트 클라우드: python3-plyfile, python3-open3d
     - 테스트 의존성:
       - ament_pytest

### slam_stream_bridge 패키지
1. `/home/kkit/newdisk/draco_tcpip/ros2_ws/src/slam_stream_bridge/package.xml`
   - **정보**: slam_stream_bridge 패키지 매니페스트 파일
   - **분석**: 
     - 패키지 정보:
       - 버전: 0.1.0
       - 설명: SLAM 파이프라인과 Draco 스트리밍 유틸리티 연결 런치 파일
       - 관리자: GodokSa (ppakdone@gmail.com)
     - 빌드 시스템:
       - ament_python 사용
     - 실행 의존성:
       - 런치 시스템: launch, launch_ros
     - 특징:
       - 최소한의 의존성
       - 런치 파일 중심의 패키지