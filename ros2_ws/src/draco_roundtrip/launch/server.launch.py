from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration, PythonExpression
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    port = LaunchConfiguration('port')
    downlink_port = PythonExpression(['str(int(', port, ') + 1)'])

    return LaunchDescription([
        DeclareLaunchArgument(
            'port',
            default_value='5000',
            description='Uplink port for the server to listen on.',
        ),
        Node(
            package='draco_roundtrip',
            executable='stream_server',
            name='stream_server',
            output='screen',
            arguments=[
                '--port', port,
                '--downlink-port', downlink_port,
            ],
        ),
    ])

