from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    port = LaunchConfiguration('port')
    downlink_port = LaunchConfiguration('downlink_port')
    use_sim_time = LaunchConfiguration('use_sim_time')

    return LaunchDescription([
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
            default_value='false',
            description='Use simulation (rosbag) clock if true'),
        Node(
            package='draco_roundtrip',
            executable='stream_server',
            name='stream_server',
            output='screen',
            parameters=[
                {
                    'port': port,
                    'downlink_port': downlink_port,
                    'points_topic': '/stream_pair/decoded',  # <-- 이 줄을 추가합니다.
                    'points_frame_id': 'lidar_link',  # <-- 이 줄을 추가합니다.
                },
                {'use_sim_time': use_sim_time} # <-- 이 줄을 추가합니다.
            ],
        ),
    ])

