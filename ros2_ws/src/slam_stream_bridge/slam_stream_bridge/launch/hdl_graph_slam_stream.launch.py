import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    use_sim_time_arg = DeclareLaunchArgument(
        'use_sim_time',
        default_value='true',
        description='Use simulation clock if true.'
    )

    default_params = os.path.join(
        get_package_share_directory('slam_stream_bridge'), 'configs', 'hdl_graph_slam_stream.yaml'
    )
    params_arg = DeclareLaunchArgument(
        'params_file',
        default_value=default_params,
        description='Path to HDL Graph SLAM parameter file'
    )

    urdf_path = os.path.join(
        get_package_share_directory('slam_stream_bridge'), 'urdf', 'robot.urdf'
    )
    with open(urdf_path, 'r') as f:
        robot_description = f.read()

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

    slam_node = Node(
        package='hdl_graph_slam',
        executable='hdl_graph_slam_node',
        name='hdl_graph_slam',
        output='screen',
        parameters=[
            LaunchConfiguration('params_file'),
            {'use_sim_time': LaunchConfiguration('use_sim_time')}
        ]
    )

    return LaunchDescription([
        use_sim_time_arg,
        params_arg,
        robot_state_publisher_node,
        slam_node,
    ])
