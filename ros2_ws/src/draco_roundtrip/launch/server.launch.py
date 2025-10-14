from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    port = LaunchConfiguration('port')
    downlink_port = LaunchConfiguration('downlink_port')

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
                }
            ],
        ),
    ])

