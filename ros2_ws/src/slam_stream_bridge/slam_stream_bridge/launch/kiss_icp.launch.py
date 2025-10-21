
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    topic = LaunchConfiguration("topic")
    base_frame = LaunchConfiguration("base_frame")
    visualize = LaunchConfiguration("visualize")
    use_sim_time = LaunchConfiguration("use_sim_time")

    kiss_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            PathJoinSubstitution([
                FindPackageShare('kiss_icp'),
                'launch',
                'odometry.launch.py'
            ])
        ),
        launch_arguments={
            'topic': topic,
            'base_frame': base_frame,
            'visualize': visualize,
            'use_sim_time': use_sim_time,
        }.items()
    )

    return LaunchDescription([
        DeclareLaunchArgument(
            "topic",
            default_value="/stream_pair/decoded",
            description="PointCloud2 topic to feed into KISS-ICP.",
        ),
        DeclareLaunchArgument(
            "base_frame",
            default_value="lidar_frame",
            description="Base frame used when publishing TF from KISS-ICP.",
        ),
        DeclareLaunchArgument(
            "visualize",
            default_value="true",
            description="Launch RViz alongside the odometry node.",
        ),
        DeclareLaunchArgument(
            "use_sim_time",
            default_value="true",
            description="Use simulation clock for KISS-ICP.",
        ),
        kiss_launch,
    ])
