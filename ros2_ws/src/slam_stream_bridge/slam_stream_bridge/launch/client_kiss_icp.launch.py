"""Launch streaming client and KISS-ICP odometry (with RViz enabled)."""

from __future__ import annotations

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.substitutions import FindPackageShare


def generate_launch_description() -> LaunchDescription:
    server_host = LaunchConfiguration("server_host")
    server_port = LaunchConfiguration("server_port")
    bag_file = LaunchConfiguration("bag_file")
    topic_name = LaunchConfiguration("topic_name")
    prefix = LaunchConfiguration("prefix")
    use_sim_time = LaunchConfiguration("use_sim_time")
    qos_best_effort = LaunchConfiguration("qos_best_effort")
    loop = LaunchConfiguration("loop")
    base_frame = LaunchConfiguration("base_frame")
    telemetry_rate = LaunchConfiguration("telemetry_rate")
    idle_shutdown_timeout = LaunchConfiguration("idle_shutdown_timeout")
    compress_level = LaunchConfiguration("compress_level")
    position_quantization_bits = LaunchConfiguration("position_quantization_bits")
    generic_quantization_bits = LaunchConfiguration("generic_quantization_bits")

    client_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            PathJoinSubstitution([FindPackageShare("draco_roundtrip"), "launch", "client.launch.py"])
        ),
        launch_arguments={
            "server_host": server_host,
            "server_port": server_port,
            "bag_file": bag_file,
            "topic_name": topic_name,
            "prefix": prefix,
            "use_sim_time": use_sim_time,
            "save_ply_files": "false",
            "qos_best_effort": qos_best_effort,
            "loop": loop,
            "telemetry_rate": telemetry_rate,
            "idle_shutdown_timeout": idle_shutdown_timeout,
            "compress_level": compress_level,
            "position_quantization_bits": position_quantization_bits,
            "generic_quantization_bits": generic_quantization_bits,
        }.items(),
    )

    kiss_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            PathJoinSubstitution([FindPackageShare("kiss_icp"), "ros", "launch", "odometry.launch.py"])
        ),
        launch_arguments={
            "topic": "/stream_pair/decoded",
            "base_frame": base_frame,
            "visualize": "true",
            "use_sim_time": use_sim_time,
        }.items(),
    )

    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "server_host",
                default_value="127.0.0.1",
                description="IP or hostname of the streaming server.",
            ),
            DeclareLaunchArgument(
                "server_port",
                default_value="5000",
                description="Uplink port exposed by the streaming server.",
            ),
            DeclareLaunchArgument(
                "bag_file",
                description="Absolute path to the rosbag2 dataset to stream.",
            ),
            DeclareLaunchArgument(
                "topic_name",
                default_value="/sensing/lidar/top/pointcloud",
                description="PointCloud2 topic inside the rosbag to stream.",
            ),
            DeclareLaunchArgument(
                "prefix",
                default_value="client",
                description="Namespace prefix used by the streaming client.",
            ),
            DeclareLaunchArgument(
                "use_sim_time",
                default_value="true",
                description="Use simulated time for all nodes.",
            ),
            DeclareLaunchArgument(
                "qos_best_effort",
                default_value="false",
                description="Subscribe to the rosbag with BEST_EFFORT QoS.",
            ),
            DeclareLaunchArgument(
                "loop",
                default_value="false",
                description="Loop rosbag playback indefinitely.",
            ),
            DeclareLaunchArgument(
                "telemetry_rate",
                default_value="10.0",
                description="Heartbeat/telemetry rate for the sender node.",
            ),
            DeclareLaunchArgument(
                "idle_shutdown_timeout",
                default_value="5.0",
                description="Seconds of inactivity before shutting down (0 disables).",
            ),
            DeclareLaunchArgument(
                "compress_level",
                default_value="8",
                description="Draco compression level (0-10) used by the encoder.",
            ),
            DeclareLaunchArgument(
                "position_quantization_bits",
                default_value="12",
                description="Number of quantisation bits for point positions.",
            ),
            DeclareLaunchArgument(
                "generic_quantization_bits",
                default_value="10",
                description="Generic attribute quantisation bits (kept for compatibility).",
            ),
            DeclareLaunchArgument(
                "base_frame",
                default_value="lidar_frame",
                description="Base frame used by KISS-ICP for TF publishing.",
            ),
            client_launch,
            kiss_launch,
        ]
    )
