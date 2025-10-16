import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition, UnlessCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    port = LaunchConfiguration('port')
    downlink_port = LaunchConfiguration('downlink_port')
    use_sim_time = LaunchConfiguration('use_sim_time')
    run_slam = LaunchConfiguration('run_slam')

    # Get directories
    draco_roundtrip_share = get_package_share_directory('draco_roundtrip')
    slam_stream_bridge_share = get_package_share_directory('slam_stream_bridge')

    # Find and read the URDF file
    urdf_path = os.path.join(draco_roundtrip_share, 'urdf', 'robot.urdf')
    with open(urdf_path, 'r') as f:
        robot_description = f.read()

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
            default_value='true',
            description='Use simulation (rosbag) clock if true'),
        DeclareLaunchArgument(
            'run_slam',
            default_value='false',
            description='Whether to launch the SLAM system or just the visualization fallback.'),

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
                'points_topic': '/stream_pair/decoded',
                'use_sim_time': use_sim_time,
                'points_frame_id': 'lidar_frame'
            }],
        ),

        # === Visualization/Testing Mode (run_slam:=false) ===
        Node(
            condition=UnlessCondition(run_slam),
            package='tf2_ros',
            executable='static_transform_publisher',
            name='static_map_to_odom',
            arguments=['0', '0', '0', '0', '0', '0', 'map', 'odom'],
            parameters=[{'use_sim_time': use_sim_time}],
        ),
        Node(
            condition=UnlessCondition(run_slam),
            package='tf2_ros',
            executable='static_transform_publisher',
            name='static_odom_to_base_link',
            arguments=['0', '0', '0', '0', '0', '0', 'odom', 'base_link'],
            parameters=[{'use_sim_time': use_sim_time}],
        ),

        # === SLAM Mode (run_slam:=true) ===
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(slam_stream_bridge_share, 'launch', 'rtabmap_stream.launch.py')
            ),
            condition=IfCondition(run_slam),
            launch_arguments={
                'use_sim_time': use_sim_time,
                'launch_robot_state_publisher': 'false', # Already launched above
            }.items(),
        ),
    ])
