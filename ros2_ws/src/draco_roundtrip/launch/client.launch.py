from launch import LaunchDescription
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    server_host = LaunchConfiguration('server_host')
    server_port = LaunchConfiguration('server_port')
    bag_file = LaunchConfiguration('bag_file')
    topic_name = LaunchConfiguration('topic_name')
    prefix = LaunchConfiguration('prefix')
    work_dir = LaunchConfiguration('work_dir')
    encoder = LaunchConfiguration('encoder')
    telemetry_rate = LaunchConfiguration('telemetry_rate')

    return LaunchDescription([
        DeclareLaunchArgument(
            'server_host',
            default_value='127.0.0.1',
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
        DeclareLaunchArgument(
            'prefix',
            description='Unique namespace prefix used when recording the rosbag.',
        ),
        DeclareLaunchArgument(
            'work_dir',
            default_value='data/client_tmp',
            description='Working directory for temporary streaming artifacts.',
        ),
        DeclareLaunchArgument(
            'encoder',
            default_value='',
            description='Optional override for the Draco encoder executable.',
        ),
        DeclareLaunchArgument(
            'telemetry_rate',
            default_value='10.0',
            description='Telemetry reporting rate in Hz.',
        ),
        Node(
            package='draco_roundtrip',
            executable='stream_client',
            name='stream_client',
            output='screen',
            parameters=[
                {
                    'server_host': server_host,
                    'server_port': server_port,
                    'downlink_host': server_host,
                    'bag': bag_file,
                    'topic': topic_name,
                    'prefix': prefix,
                    'work_dir': work_dir,
                    'encoder': encoder,
                    'telemetry_rate': telemetry_rate,
                }
            ],
        ),
    ])

