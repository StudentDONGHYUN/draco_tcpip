import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    default_params = os.path.join(
        get_package_share_directory('slam_stream_bridge'), 'configs', 'rtabmap_stream.yaml'
    )

    urdf_path = os.path.join(
        get_package_share_directory('slam_stream_bridge'), 'urdf', 'robot.urdf'
    )
    with open(urdf_path, 'r') as f:
        robot_description = f.read()

    params_arg = DeclareLaunchArgument(
        'params_file',
        default_value=default_params,
        description='Full path to the RTAB-Map parameter file.'
    )

    cloud_topic_arg = DeclareLaunchArgument(
        'cloud_topic',
        default_value='/stream_pair/decoded',
        description='PointCloud2 topic published by the streaming decoder.'
    )

    use_sim_time_arg = DeclareLaunchArgument(
        'use_sim_time',
        default_value='true',
        description='Use simulation clock if true.'
    )

    time_jump_threshold_arg = DeclareLaunchArgument(
        'time_jump_threshold',
        default_value='0.5',
        description='Simulation time jump size (seconds) that triggers odometry reset.'
    )

    robot_state_publisher_node = Node(
        package='robot_state_publisher',
        executable='robot_state_publisher',
        name='robot_state_publisher',
        output='screen',
        parameters=[{
            'use_sim_time': LaunchConfiguration('use_sim_time'),
            'robot_description': robot_description,
        }]
    )

    static_transform_publisher_node = Node(
        package='tf2_ros',
        executable='static_transform_publisher',
        name='static_transform_publisher_lidar',
        arguments=['0', '0', '0.5', '0', '0', '0', 'base_link', 'lidar_frame'],
    )

    icp_odometry_node = Node(
        package='rtabmap_odom',
        executable='icp_odometry',
        name='icp_odometry',
        output='screen',
        parameters=[
            LaunchConfiguration('params_file'),
            {'use_sim_time': LaunchConfiguration('use_sim_time')}
        ],
        remappings=[('scan_cloud', LaunchConfiguration('cloud_topic'))]
    )

    rtabmap_node = Node(
        package='rtabmap_slam',
        executable='rtabmap',
        name='rtabmap',
        output='screen',
        parameters=[
            LaunchConfiguration('params_file'),
            {'use_sim_time': LaunchConfiguration('use_sim_time')}
        ],
        remappings=[('scan_cloud', LaunchConfiguration('cloud_topic'))],
        arguments=['--delete_db_on_start']
    )

    time_jump_reset_node = Node(
        package='slam_stream_bridge',
        executable='time_jump_reset',
        name='time_jump_reset',
        output='screen',
        parameters=[{
            'use_sim_time': LaunchConfiguration('use_sim_time'),
            'jump_back_threshold_sec': LaunchConfiguration('time_jump_threshold'),
        }]
    )

    return LaunchDescription([
        params_arg,
        cloud_topic_arg,
        use_sim_time_arg,
        time_jump_threshold_arg,
        robot_state_publisher_node,
        static_transform_publisher_node,
        icp_odometry_node,
        rtabmap_node,
        time_jump_reset_node,
    ])
