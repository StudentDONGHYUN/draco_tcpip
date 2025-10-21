import os
from datetime import datetime
from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    IncludeLaunchDescription,
    LogInfo,
    RegisterEventHandler,
)
from launch.conditions import IfCondition, UnlessCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch.event_handlers import OnProcessIO
from launch.events.process import ProcessIO
from launch_ros.actions import Node


def _find_project_root(current_file: Path) -> Path:
    for parent in current_file.parents:
        if (parent / 'README.md').is_file():
            return parent
    raise RuntimeError('프로젝트 루트 디렉터리를 찾을 수 없습니다.')


def generate_launch_description() -> LaunchDescription:
    port = LaunchConfiguration('port')
    downlink_port = LaunchConfiguration('downlink_port')
    use_sim_time = LaunchConfiguration('use_sim_time')
    points_topic = LaunchConfiguration('points_topic')
    points_frame_id = LaunchConfiguration('points_frame_id')
    downlink_protocol = LaunchConfiguration('downlink_protocol')
    downlink_rate = LaunchConfiguration('downlink_rate')

    project_root = _find_project_root(Path(__file__).resolve())
    log_dir = project_root / 'logs'
    log_dir.mkdir(parents=True, exist_ok=True)
    log_timestamp = datetime.now()
    log_file_path = log_dir / f'ros2_server_{log_timestamp.strftime("%Y%m%d_%H%M%S_%f")}.log'
    header_lines = [
        '# 로그 생성 정보',
        f'# 명령어: ros2 launch draco_roundtrip server.launch.py use_sim_time:=true',
        f'# 생성 시각: {log_timestamp.isoformat()}',
        '',
    ]
    log_file_path.write_text('\n'.join(header_lines), encoding='utf-8')

    def _append_launch_output(event: ProcessIO) -> None:
        message = event.text.decode(encoding='utf-8', errors='replace')
        if not message:
            return None

        stream_name = 'STDOUT' if event.from_stdout else 'STDERR'
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')
        prefix = f'[{timestamp}][{event.process_name}][{stream_name}] '
        with log_file_path.open('a', encoding='utf-8') as log_file:
            for chunk in message.splitlines(keepends=True):
                log_file.write(prefix + chunk)
                if not chunk.endswith('\n'):
                    log_file.write('\n')
        return None

    log_event_handler = RegisterEventHandler(
        OnProcessIO(
            on_stdout=_append_launch_output,
            on_stderr=_append_launch_output,
        )
    )

    # Get directories
    draco_roundtrip_share = get_package_share_directory('draco_roundtrip')

    # Find and read the URDF file
    urdf_path = os.path.join(draco_roundtrip_share, 'urdf', 'robot.urdf')
    with open(urdf_path, 'r') as f:
        robot_description = f.read()

    return LaunchDescription([
        log_event_handler,
        LogInfo(msg=f'런치 출력 로그 파일: {log_file_path}'),
        DeclareLaunchArgument(
            'port',
            default_value='5000',
            description='Uplink port for the server to listen on.',
        ),
        DeclareLaunchArgument(
            'downlink_port',
            default_value='0',
            description='Downlink control port (0 uses uplink port + 1).',
        ),
        DeclareLaunchArgument(
            'use_sim_time',
            default_value='true',
            description='Use simulation (rosbag) clock if true'),
        DeclareLaunchArgument(
            'points_topic',
            default_value='/stream_pair/decoded',
            description='Topic where decoded PointCloud2 messages are published.',
        ),
        DeclareLaunchArgument(
            'points_frame_id',
            default_value='lidar_frame',
            description='Frame ID assigned to decoded point clouds.',
        ),
        DeclareLaunchArgument(
            'downlink_protocol',
            default_value='binary',
            description='Control-plane protocol used for downlink telemetry.',
        ),
        DeclareLaunchArgument(
            'downlink_rate',
            default_value='10.0',
            description='Downlink telemetry publishing rate in Hz.',
        ),

        # Always launch the robot_state_publisher and stream_server
        Node(
            package='robot_state_publisher',
            executable='robot_state_publisher',
            name='robot_state_publisher',
            output='screen',
            parameters=[{
                'use_sim_time': use_sim_time,
                'robot_description': robot_description,
            }]
        ),
        Node(
            package='draco_roundtrip',
            executable='stream_server',
            name='stream_server',
            output='screen',
            parameters=[{
                'port': port,
                'downlink_port': downlink_port,
                'points_topic': points_topic,
                'use_sim_time': use_sim_time,
                'points_frame_id': points_frame_id,
                'downlink_protocol': downlink_protocol,
                'downlink_rate': downlink_rate,
            }],
        ),

        # Dummy transform for visualization
        Node(
            package='tf2_ros',
            executable='static_transform_publisher',
            name='static_map_to_odom',
            arguments=['0', '0', '0', '0', '0', '0', 'map', 'odom'],
            parameters=[{'use_sim_time': use_sim_time}],
        ),
        Node(
            package='tf2_ros',
            executable='static_transform_publisher',
            name='static_odom_to_base_link',
            arguments=['0', '0', '0', '0', '0', '0', 'odom', 'base_link'],
            parameters=[{'use_sim_time': use_sim_time}],
        ),
    ])
