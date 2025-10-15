import os
from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess, OpaqueFunction
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    """Generates the launch description for the streaming client setup."""
    
    # Declare launch arguments
    declare_server_host = DeclareLaunchArgument(
        'server_host',
        default_value='127.0.0.1',
        description='IP address or hostname of the streaming server.',
    )
    declare_server_port = DeclareLaunchArgument(
        'server_port',
        default_value='5000',
        description='Uplink port exposed by the streaming server.',
    )
    declare_bag_file = DeclareLaunchArgument(
        'bag_file',
        description='Absolute path to the rosbag2 recording to stream.',
    )
    declare_topic_name = DeclareLaunchArgument(
        'topic_name',
        description='PointCloud2 topic inside the rosbag to replay.',
    )
    declare_prefix = DeclareLaunchArgument(
        'prefix',
        description='Unique namespace prefix used when recording the rosbag.',
    )
    declare_ply_dir = DeclareLaunchArgument(
        'ply_dir',
        default_value='data/ply_stream',
        description='Directory to store intermediate PLY files.',
    )
    declare_use_sim_time = DeclareLaunchArgument(
        'use_sim_time',
        default_value='false',
        description='Use simulation (rosbag) clock if true.',
    )
    declare_idle_timeout = DeclareLaunchArgument(
        'idle_timeout', default_value='10.0', description='Idle timeout for ply_saver.'
    )
    declare_max_frames = DeclareLaunchArgument(
        'max_frames', default_value='0', description='Max frames for ply_saver.'
    )
    declare_best_effort = DeclareLaunchArgument(
        'best_effort', default_value='false', description='Best effort QoS for ply_saver.'
    )

    # Get launch configurations
    server_host = LaunchConfiguration('server_host')
    server_port = LaunchConfiguration('server_port')
    bag_file = LaunchConfiguration('bag_file')
    topic_name = LaunchConfiguration('topic_name')
    prefix = LaunchConfiguration('prefix')
    ply_dir = LaunchConfiguration('ply_dir')
    use_sim_time = LaunchConfiguration('use_sim_time')
    idle_timeout = LaunchConfiguration('idle_timeout')
    max_frames = LaunchConfiguration('max_frames')
    best_effort = LaunchConfiguration('best_effort')

    # Node for saving PointCloud2 to PLY files
    ply_saver_node = Node(
        package='draco_roundtrip',
        executable='ply_saver',
        name='ply_saver',
        output='screen',
        parameters=[
            {
                'topic': topic_name,
                'out': ply_dir,
                'prefix': prefix,
                'idle_timeout_sec': idle_timeout,
                'max_frames': max_frames,
                'best_effort': best_effort,
                'use_sim_time': use_sim_time,
            }
        ],
    )

    # OpaqueFunction to configure and run ros2 bag play
    def run_bag_play(context, *args, **kwargs):
        bag_play_cmd = ['ros2', 'bag', 'play', context.launch_configurations['bag_file']]
        if context.launch_configurations['use_sim_time'] == 'true':
            bag_play_cmd.append('--clock')
        
        # Resolve QoS override path
        pkg_share = get_package_share_directory('draco_roundtrip')
        qos_override_path = os.path.join(pkg_share, 'config', 'qos_override.yaml')
        if os.path.exists(qos_override_path):
            bag_play_cmd += ['--qos-profile-overrides-path', qos_override_path]

        return [ExecuteProcess(cmd=bag_play_cmd, output='screen')]

    bag_play_process = OpaqueFunction(function=run_bag_play)

    # Streaming client node
    stream_client_node = Node(
        package='draco_roundtrip',
        executable='stream_client',
        name='stream_client',
        output='screen',
        parameters=[
            {
                'server_host': server_host,
                'server_port': server_port,
                'downlink_host': server_host,
                'prefix': prefix,
                'ply_dir': ply_dir,
                'use_sim_time': use_sim_time,
                # Pass other relevant parameters
                'work_dir': LaunchConfiguration('work_dir', default='data/client_tmp'),
                'encoder': LaunchConfiguration('encoder', default=''),
                'telemetry_rate': LaunchConfiguration('telemetry_rate', default='10.0'),
                'calculate_metrics': LaunchConfiguration('calculate_metrics', default='false'),
            }
        ],
    )

    return LaunchDescription([
        declare_server_host,
        declare_server_port,
        declare_bag_file,
        declare_topic_name,
        declare_prefix,
        declare_ply_dir,
        declare_use_sim_time,
        declare_idle_timeout,
        declare_max_frames,
        declare_best_effort,
        
        # Declare other arguments used by stream_client
        DeclareLaunchArgument('work_dir', default_value='data/client_tmp'),
        DeclareLaunchArgument('encoder', default_value=''),
        DeclareLaunchArgument('telemetry_rate', default_value='10.0'),
        DeclareLaunchArgument('calculate_metrics', default_value='false'),

        ply_saver_node,
        bag_play_process,
        stream_client_node,
    ])