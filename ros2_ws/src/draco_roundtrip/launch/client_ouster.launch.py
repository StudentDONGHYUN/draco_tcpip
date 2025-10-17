"""Launch file for streaming live Ouster OS1 point clouds without rosbag playback."""

from __future__ import annotations

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    """Create a launch description that brings up the Ouster driver and streaming nodes."""

    declare_server_host = DeclareLaunchArgument(
        "server_host",
        default_value="127.0.0.1",
        description="IP address or hostname of the streaming server.",
    )
    declare_server_port = DeclareLaunchArgument(
        "server_port",
        default_value="5000",
        description="Uplink port exposed by the streaming server.",
    )
    declare_prefix = DeclareLaunchArgument(
        "prefix",
        default_value="robot1",
        description=(
            "Prefix used for encoder frame names and downlink topic namespaces."
        ),
    )
    declare_telemetry_rate = DeclareLaunchArgument(
        "telemetry_rate",
        default_value="10.0",
        description="Frequency in Hz for telemetry status messages sent to the server.",
    )
    declare_idle_shutdown_timeout = DeclareLaunchArgument(
        "idle_shutdown_timeout",
        default_value="0.0",
        description=(
            "Seconds of inactivity before shutting down the sender (0 disables the timeout)."
        ),
    )
    declare_driver_params = DeclareLaunchArgument(
        "driver_params_file",
        default_value=os.path.join(
            get_package_share_directory("ros2_ouster"),
            "params",
            "driver_config.yaml",
        ),
        description="Path to the ros2_ouster driver parameter file.",
    )
    declare_pointcloud_topic = DeclareLaunchArgument(
        "pointcloud_topic",
        default_value="/points",
        description="PointCloud2 topic published by the Ouster driver to compress.",
    )
    declare_qos_best_effort = DeclareLaunchArgument(
        "qos_best_effort",
        default_value="true",
        description="Use Best Effort QoS when subscribing to the live point cloud stream.",
    )

    server_host = LaunchConfiguration("server_host")
    server_port = LaunchConfiguration("server_port")
    prefix = LaunchConfiguration("prefix")
    telemetry_rate = LaunchConfiguration("telemetry_rate")
    idle_shutdown_timeout = LaunchConfiguration("idle_shutdown_timeout")
    driver_params_file = LaunchConfiguration("driver_params_file")
    pointcloud_topic = LaunchConfiguration("pointcloud_topic")
    qos_best_effort = LaunchConfiguration("qos_best_effort")

    driver_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(
                get_package_share_directory("ros2_ouster"),
                "launch",
                "driver_launch.py",
            )
        ),
        launch_arguments={"params_file": driver_params_file}.items(),
    )

    encoder_node = Node(
        package="draco_roundtrip",
        executable="encoder_node",
        name="encoder_node",
        output="log",
        parameters=[
            {
                "topic_name": pointcloud_topic,
                "qos_best_effort": qos_best_effort,
                "prefix": prefix,
            }
        ],
    )

    sender_node = Node(
        package="draco_roundtrip",
        executable="sender_node",
        name="sender_node",
        output="log",
        parameters=[
            {
                "server_host": server_host,
                "server_port": server_port,
                "topic_prefix": prefix,
                "telemetry_rate": telemetry_rate,
                "idle_shutdown_timeout": idle_shutdown_timeout,
                "loop": False,
            }
        ],
    )

    return LaunchDescription(
        [
            declare_server_host,
            declare_server_port,
            declare_prefix,
            declare_telemetry_rate,
            declare_idle_shutdown_timeout,
            declare_driver_params,
            declare_pointcloud_topic,
            declare_qos_best_effort,
            driver_launch,
            encoder_node,
            sender_node,
        ]
    )
