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
        default_value='/sensing/lidar/top/pointcloud',
        description='PointCloud2 topic to stream.',
    )
    declare_prefix = DeclareLaunchArgument(
        'prefix',
        default_value='client',
        description='Unique namespace prefix, used for PLY file names in file mode.',
    )
    declare_ply_dir = DeclareLaunchArgument(
        'ply_dir',
        default_value='data/ply_stream',
        description='Directory to store intermediate PLY files (if save_ply_files is true).',
    )
    declare_use_sim_time = DeclareLaunchArgument(
        'use_sim_time',
        default_value='false',
        description='Use simulation (rosbag) clock if true.',
    )
    declare_save_ply_files = DeclareLaunchArgument(
        'save_ply_files',
        default_value='false',
        description='If true, save intermediate PLY files and use them as the source.'
    )
    declare_qos_best_effort = DeclareLaunchArgument(
        'qos_best_effort',
        default_value='false',
        description='Use Best Effort QoS for the PointCloud2 subscriber.'
    )
    declare_play_rate = DeclareLaunchArgument(
        'play_rate',
        default_value='1.0',
        description='Rate at which to play the rosbag file.',
    )
    declare_loop = DeclareLaunchArgument(
        'loop',
        default_value='false',
        description='If true, loop the rosbag playback.',
    )
    declare_idle_shutdown_timeout = DeclareLaunchArgument(
        'idle_shutdown_timeout',
        default_value='5.0',
        description='Seconds of inactivity before client shuts down (0 to disable). Only active if loop is false.'
    )

    # Arguments for ply_saver, only used if save_ply_files is true
    declare_idle_timeout = DeclareLaunchArgument(
        'idle_timeout', default_value='10.0', description='Idle timeout for ply_saver.'
    )
    declare_max_frames = DeclareLaunchArgument(
        'max_frames', default_value='0', description='Max frames for ply_saver.'
    )

    # Get launch configurations
    server_host = LaunchConfiguration('server_host')
    server_port = LaunchConfiguration('server_port')
    bag_file = LaunchConfiguration('bag_file')
    topic_name = LaunchConfiguration('topic_name')
    prefix = LaunchConfiguration('prefix')
    ply_dir = LaunchConfiguration('ply_dir')
    use_sim_time = LaunchConfiguration('use_sim_time')
    save_ply_files = LaunchConfiguration('save_ply_files')
    qos_best_effort = LaunchConfiguration('qos_best_effort')
    idle_timeout = LaunchConfiguration('idle_timeout')
    max_frames = LaunchConfiguration('max_frames')
    play_rate = LaunchConfiguration('play_rate')
    loop = LaunchConfiguration('loop')

    # Node for saving PointCloud2 to PLY files (conditional)
    ply_saver_node = Node(
        package='draco_roundtrip',
        executable='ply_saver',
        name='ply_saver',
        output='log',
        parameters=[
            {
                'topic': topic_name,
                'out': ply_dir,
                'prefix': prefix,
                'idle_timeout_sec': idle_timeout,
                'max_frames': max_frames,
                'best_effort': qos_best_effort,
                'use_sim_time': use_sim_time,
            }
        ],
        condition=IfCondition(save_ply_files)
    )

    # OpaqueFunction to configure and run ros2 bag play
    def run_bag_play(context, *args, **kwargs):
        bag_play_cmd = [
            'ros2', 'bag', 'play',
            context.launch_configurations['bag_file'],
            '--rate', context.launch_configurations['play_rate']
        ]
        if context.launch_configurations['use_sim_time'] == 'true':
            bag_play_cmd.append('--clock')
        if context.launch_configurations['loop'] == 'true':
            bag_play_cmd.append('--loop')
        
        pkg_share = get_package_share_directory('draco_roundtrip')
        qos_override_path = os.path.join(pkg_share, 'config', 'qos_override.yaml')
        if os.path.exists(qos_override_path):
            bag_play_cmd += ['--qos-profile-overrides-path', qos_override_path]

        return [ExecuteProcess(cmd=bag_play_cmd, output='log')]

    bag_play_process = OpaqueFunction(function=run_bag_play)

    # Encoder node
    encoder_node = Node(
        package='draco_roundtrip',
        executable='encoder_node',
        name='encoder_node',
        output='log',
        parameters=[
            {
                'topic_name': topic_name,
                'qos_best_effort': qos_best_effort,
                'prefix': prefix,
                'use_sim_time': use_sim_time,
            }
        ],
    )

    # Sender node
    sender_node = Node(
        package='draco_roundtrip',
        executable='sender_node',
        name='sender_node',
        output='log',
        parameters=[
            {
                'server_host': server_host,
                'server_port': server_port,
                'downlink_host': server_host,
                'telemetry_rate': LaunchConfiguration('telemetry_rate', default='10.0'),
                'loop': loop,
                'idle_shutdown_timeout': LaunchConfiguration('idle_shutdown_timeout'),
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
        declare_save_ply_files,
        declare_qos_best_effort,
        declare_play_rate,
        declare_loop,
        declare_idle_shutdown_timeout,
        DeclareLaunchArgument('telemetry_rate', default_value='10.0'),
        declare_idle_timeout,
        declare_max_frames,

        ply_saver_node,
        bag_play_process,
        encoder_node,
        sender_node,
    ])
