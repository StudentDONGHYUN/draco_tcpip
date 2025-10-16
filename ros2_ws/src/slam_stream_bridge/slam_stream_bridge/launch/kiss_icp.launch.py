
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import PathJoinSubstitution
from launch_ros.substitutions import FindPackageShare

def generate_launch_description():
    return LaunchDescription([
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                PathJoinSubstitution([
                    FindPackageShare('kiss_icp'),
                    'launch',
                    'odometry.launch.py'
                ])
            ),
            launch_arguments={
                'topic': '/stream_pair/decoded',
                'visualize': 'false',
                'use_sim_time': 'true'
            }.items()
        )
    ])
