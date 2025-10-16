import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    port = LaunchConfiguration('port')
    downlink_port = LaunchConfiguration('downlink_port')
    use_sim_time = LaunchConfiguration('use_sim_time')
    publish_tf_fallback = LaunchConfiguration('publish_tf_fallback')

    # Find and read the URDF file
    urdf_path = os.path.join(
        get_package_share_directory('draco_roundtrip'),
        'urdf',
        'robot.urdf'
    )
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
            default_value='false',
            description='Use simulation (rosbag) clock if true'),
        # Add robot_state_publisher
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

        # Fallback TF publishers to create a static TF tree for visualization
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
