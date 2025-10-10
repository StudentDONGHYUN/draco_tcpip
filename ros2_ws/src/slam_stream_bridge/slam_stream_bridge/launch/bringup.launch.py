from __future__ import annotations

from pathlib import Path

from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    ExecuteProcess,
    IncludeLaunchDescription,
    OpaqueFunction,
)
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

from draco_roundtrip.utils.config import resolve_data_layout, resolve_qos_override


def _as_bool(value: str) -> bool:
    return value.lower() in {"1", "true", "yes", "on"}


def _launch_setup(context):
    bag = LaunchConfiguration("bag").perform(context)
    topic = LaunchConfiguration("topic").perform(context)
    prefix = LaunchConfiguration("prefix").perform(context)
    layout_profile = LaunchConfiguration("layout_profile").perform(context) or None
    data_root = LaunchConfiguration("data_root").perform(context) or None
    server_host = LaunchConfiguration("server_host").perform(context)
    server_port = LaunchConfiguration("server_port").perform(context)
    decoder_hint = LaunchConfiguration("decoder").perform(context) or None
    qos_override_flag = LaunchConfiguration("qos_override").perform(context) or None
    slam_type = LaunchConfiguration("slam").perform(context)
    slam_params_override = LaunchConfiguration("slam_params").perform(context) or None
    netem_profile = LaunchConfiguration("netem_profile").perform(context)
    netem_iface = LaunchConfiguration("netem_iface").perform(context)
    netem_dry_run = _as_bool(LaunchConfiguration("netem_dry_run").perform(context))

    layout = resolve_data_layout(
        {
            "ply_dir": "ply_stream",
            "client_work": "client_work",
            "decoded_dir": "decoded_from_server",
            "server_work": "server_work",
            "results_dir": "results",
            "ros_logs_dir": "ros_logs",
        },
        profile=layout_profile,
        base=data_root,
        ensure=True,
    )
    qos_path = resolve_qos_override(qos_override_flag, profile=layout.profile)

    actions = []

    if netem_profile and netem_profile.lower() != "skip":
        cmd = ["stream_netem", netem_profile, "--iface", netem_iface, "--clear"]
        if netem_dry_run:
            cmd.append("--dry-run")
        actions.append(ExecuteProcess(cmd=cmd, output="screen"))

    server_args = [
        "--host",
        server_host,
        "--port",
        server_port,
        "--work-dir",
        str(layout["server_work"]),
    ]
    if decoder_hint:
        server_args += ["--decoder", decoder_hint]

    client_args = [
        "--bag",
        bag,
        "--topic",
        topic,
        "--prefix",
        prefix,
        "--layout-profile",
        layout_profile or "",
        "--data-root",
        data_root or "",
        "--ply-dir",
        str(layout["ply_dir"]),
        "--work-dir",
        str(layout["client_work"]),
        "--decoded-dir",
        str(layout["decoded_dir"]),
        "--server-host",
        server_host,
        "--server-port",
        server_port,
    ]
    if qos_path:
        client_args += ["--qos-override", str(qos_path)]

    actions.append(
        Node(
            package="draco_roundtrip",
            executable="stream_server",
            name="stream_server",
            output="screen",
            arguments=server_args,
        )
    )

    actions.append(
        Node(
            package="draco_roundtrip",
            executable="stream_client",
            name="stream_client",
            output="screen",
            arguments=client_args,
        )
    )

    launch_dir = Path(__file__).resolve().parent
    configs_dir = launch_dir.parent / "configs"

    slam_launch: IncludeLaunchDescription
    if slam_type == "rtabmap":
        launch_path = launch_dir / "rtabmap_stream.launch.py"
        params_path = slam_params_override or str(configs_dir / "rtabmap_stream.yaml")
        slam_launch = IncludeLaunchDescription(
            PythonLaunchDescriptionSource(str(launch_path)),
            launch_arguments={
                "params_file": params_path,
                "cloud_topic": "/stream_pair/decoded",
            }.items(),
        )
    elif slam_type == "hdl":
        launch_path = launch_dir / "hdl_graph_slam_stream.launch.py"
        params_path = slam_params_override or str(configs_dir / "hdl_graph_slam_stream.yaml")
        slam_launch = IncludeLaunchDescription(
            PythonLaunchDescriptionSource(str(launch_path)),
            launch_arguments={
                "params_file": params_path,
            }.items(),
        )
    else:
        raise RuntimeError(f"Unsupported slam type: {slam_type}")

    actions.append(slam_launch)
    return actions


def generate_launch_description() -> LaunchDescription:
    return LaunchDescription(
        [
            DeclareLaunchArgument("bag", description="Path to the rosbag to stream"),
            DeclareLaunchArgument("topic", default_value="/sensing/lidar/top/pointcloud", description="ROS topic within the bag"),
            DeclareLaunchArgument("prefix", default_value="bag_frame", description="Prefix used when naming extracted PLY frames"),
            DeclareLaunchArgument("layout_profile", default_value="client.profile.yaml", description="Layout profile used for data directories"),
            DeclareLaunchArgument("data_root", default_value="", description="Optional override for the layout data root"),
            DeclareLaunchArgument("server_host", default_value="127.0.0.1"),
            DeclareLaunchArgument("server_port", default_value="5000"),
            DeclareLaunchArgument("decoder", default_value="", description="Path to draco_decoder override"),
            DeclareLaunchArgument("qos_override", default_value="", description="Optional QoS override YAML path"),
            DeclareLaunchArgument("slam", default_value="rtabmap", description="SLAM pipeline to launch (rtabmap|hdl)"),
            DeclareLaunchArgument("slam_params", default_value="", description="Optional override parameter file for the SLAM launch"),
            DeclareLaunchArgument("netem_profile", default_value="loopback", description="Netem profile applied before launching (use 'skip' to disable)"),
            DeclareLaunchArgument("netem_iface", default_value="lo", description="Network interface for netem configuration"),
            DeclareLaunchArgument("netem_dry_run", default_value="true", description="If true, print netem commands instead of executing"),
            OpaqueFunction(function=_launch_setup),
        ]
    )
