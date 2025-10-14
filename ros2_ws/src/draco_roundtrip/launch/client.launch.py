from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration, PythonExpression
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    server_ip = LaunchConfiguration('server_ip')
    server_port = LaunchConfiguration('server_port')
    bag_file = LaunchConfiguration('bag_file')
    topic_name = LaunchConfiguration('topic_name')
    downlink_port = PythonExpression(['str(int(', server_port, ') + 1)'])

    return LaunchDescription([
        DeclareLaunchArgument(
            'server_ip',
            description='IP address or hostname of the streaming server.',
        ),
        DeclareLaunchArgument(
            'server_port',
            default_value='5000',
            description='Uplink port exposed by the streaming server.',
        ),
        DeclareLaunchArgument(
            'bag_file',
            description='Absolute path to the rosbag2 recording to stream.',
        ),
        DeclareLaunchArgument(
            'topic_name',
            description='PointCloud2 topic inside the rosbag to replay.',
        ),
        Node(
            package='draco_roundtrip',
            executable='stream_client',
            name='stream_client',
            output='screen',
            arguments=[
                '--server-host', server_ip,
                '--server-port', server_port,
                '--downlink-host', server_ip,
                '--downlink-port', downlink_port,
                '--bag', bag_file,
                '--topic', topic_name,
            ],
        ),
    ])

