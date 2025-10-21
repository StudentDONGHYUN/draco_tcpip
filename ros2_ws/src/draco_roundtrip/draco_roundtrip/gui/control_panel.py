"""Tkinter GUI for managing the Draco streaming server and client SLAM pipeline."""

from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import threading
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import List, Sequence


def _as_launch_arg(name: str, value: str) -> str:
    """Format a ROS 2 launch argument ensuring spaces are preserved."""

    if value == "":
        return f"{name}:="
    return f"{name}:={value}"


def _normalise_path(path_value: str) -> str:
    """Strip surrounding quotes and whitespace from a path-like string."""

    return path_value.strip().strip('"').strip("'")


class ManagedProcess:
    """Simple subprocess wrapper that manages process groups for ROS launch files."""

    def __init__(self, label: str) -> None:
        self._label = label
        self._process: subprocess.Popen[str] | None = None

    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def start(self, command: Sequence[str]) -> None:
        if self.is_running():
            raise RuntimeError(f"{self._label} is already running")
        creationflags = 0
        preexec_fn = None
        if os.name == "nt":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        else:
            preexec_fn = os.setsid  # type: ignore[assignment]
        self._process = subprocess.Popen(
            list(command),
            stdout=None,
            stderr=None,
            text=False,
            creationflags=creationflags,
            preexec_fn=preexec_fn,
        )

    def stop(self, timeout: float = 5.0) -> None:
        proc = self._process
        if proc is None:
            return
        if proc.poll() is None:
            try:
                if os.name == "nt":
                    proc.send_signal(signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]
                else:
                    os.killpg(proc.pid, signal.SIGINT)
                proc.wait(timeout=timeout)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                if os.name == "nt":
                    proc.kill()
                else:
                    os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    proc.kill()
        self._process = None


@dataclass(slots=True)
class ServerConfig:
    port: str
    downlink_port: str
    use_sim_time: bool
    points_topic: str
    points_frame_id: str
    downlink_protocol: str
    downlink_rate: str

    def as_launch_args(self) -> List[str]:
        args = [
            f"port:={self.port or '5000'}",
            f"downlink_port:={self.downlink_port or '0'}",
            _as_launch_arg("points_topic", self.points_topic or "/stream_pair/decoded"),
            _as_launch_arg("points_frame_id", self.points_frame_id or "lidar_frame"),
            f"downlink_protocol:={self.downlink_protocol or 'binary'}",
            f"downlink_rate:={self.downlink_rate or '10.0'}",
            f"use_sim_time:={'true' if self.use_sim_time else 'false'}",
        ]
        return args


@dataclass(slots=True)
class ClientConfig:
    server_host: str
    server_port: str
    bag_file: str
    topic_name: str
    prefix: str
    use_sim_time: bool
    telemetry_rate: str
    loop: bool
    idle_shutdown_timeout: str
    compress_level: int
    position_quantization_bits: int
    generic_quantization_bits: int

    def as_launch_args(self) -> List[str]:
        bag_path = _normalise_path(self.bag_file)
        if not bag_path:
            raise ValueError("Bag file path is required for the client launch.")
        if not Path(bag_path).exists():
            raise ValueError(f"Bag path does not exist: {bag_path}")
        args = [
            _as_launch_arg("server_host", self.server_host or "127.0.0.1"),
            f"server_port:={self.server_port or '5000'}",
            _as_launch_arg("bag_file", bag_path),
            _as_launch_arg("topic_name", self.topic_name or "/sensing/lidar/top/pointcloud"),
            _as_launch_arg("prefix", self.prefix or "client"),
            f"use_sim_time:={'true' if self.use_sim_time else 'false'}",
            f"telemetry_rate:={self.telemetry_rate or '10.0'}",
            f"loop:={'true' if self.loop else 'false'}",
            f"idle_shutdown_timeout:={self.idle_shutdown_timeout or '5.0'}",
            f"compress_level:={self.compress_level}",
            f"position_quantization_bits:={self.position_quantization_bits}",
            f"generic_quantization_bits:={self.generic_quantization_bits}",
        ]
        return args


@dataclass(slots=True)
class SlamConfig:
    topic: str
    base_frame: str
    use_sim_time: bool
    visualize: bool
    map_save_directory: str
    keep_full_history: bool
    publish_saved_map: bool

    def as_launch_args(self) -> List[str]:
        args = [
            _as_launch_arg("topic", self.topic or "/stream_pair/decoded"),
            _as_launch_arg("base_frame", self.base_frame or "lidar_frame"),
            f"use_sim_time:={'true' if self.use_sim_time else 'false'}",
            f"visualize:={'true' if self.visualize else 'false'}",
        ]
        map_dir = _normalise_path(self.map_save_directory)
        if map_dir:
            args.append(_as_launch_arg("map_save_directory", map_dir))
        args.append(f"map_keep_full_history:={'true' if self.keep_full_history else 'false'}")
        args.append(f"map_publish_saved_map:={'true' if self.publish_saved_map else 'false'}")
        return args


class ControlPanel(tk.Tk):
    """Main Tkinter window for the control panel."""

    def __init__(self) -> None:
        super().__init__()
        self.title("Draco Streaming Control Panel")
        self.resizable(False, False)

        self.server_process = ManagedProcess("Server")
        self.client_process = ManagedProcess("Client")
        self.slam_process = ManagedProcess("SLAM")

        self._build_widgets()
        self._schedule_status_refresh()

    def _build_widgets(self) -> None:
        padding = {"padx": 10, "pady": 5}

        server_frame = ttk.Labelframe(self, text="Server Settings")
        server_frame.grid(row=0, column=0, sticky="nsew", **padding)

        self.server_port = tk.StringVar(value="5000")
        self.server_downlink_port = tk.StringVar(value="0")
        self.server_use_sim_time = tk.BooleanVar(value=True)
        self.server_points_topic = tk.StringVar(value="/stream_pair/decoded")
        self.server_points_frame = tk.StringVar(value="lidar_frame")
        self.server_downlink_protocol = tk.StringVar(value="binary")
        self.server_downlink_rate = tk.StringVar(value="10.0")

        self._add_labeled_entry(server_frame, "Port", self.server_port, row=0)
        self._add_labeled_entry(server_frame, "Downlink Port", self.server_downlink_port, row=1)
        ttk.Checkbutton(
            server_frame,
            text="Use Simulation Time",
            variable=self.server_use_sim_time,
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(0, 5))
        self._add_labeled_entry(server_frame, "Points Topic", self.server_points_topic, row=3)
        self._add_labeled_entry(server_frame, "Points Frame ID", self.server_points_frame, row=4)
        ttk.Label(server_frame, text="Downlink Protocol").grid(row=5, column=0, sticky="e")
        ttk.OptionMenu(
            server_frame,
            self.server_downlink_protocol,
            self.server_downlink_protocol.get(),
            "binary",
            "json",
        ).grid(row=5, column=1, sticky="we", pady=2)
        self._add_labeled_entry(server_frame, "Downlink Rate (Hz)", self.server_downlink_rate, row=6)

        ttk.Button(server_frame, text="Start Server", command=self._start_server).grid(
            row=7, column=0, sticky="we", pady=(8, 0)
        )
        ttk.Button(server_frame, text="Stop Server", command=self._stop_server).grid(
            row=7, column=1, sticky="we", pady=(8, 0)
        )

        self.server_status = tk.StringVar(value="Stopped")
        ttk.Label(server_frame, textvariable=self.server_status).grid(
            row=8, column=0, columnspan=2, sticky="we", pady=(5, 0)
        )

        client_frame = ttk.Labelframe(self, text="Client Settings")
        client_frame.grid(row=1, column=0, sticky="nsew", **padding)

        self.client_host = tk.StringVar(value="127.0.0.1")
        self.client_port = tk.StringVar(value="5000")
        self.client_bag_file = tk.StringVar(value="")
        self.client_topic_name = tk.StringVar(value="/sensing/lidar/top/pointcloud")
        self.client_prefix = tk.StringVar(value="client")
        self.client_use_sim_time = tk.BooleanVar(value=True)
        self.client_loop = tk.BooleanVar(value=False)
        self.client_telemetry_rate = tk.StringVar(value="10.0")
        self.client_idle_timeout = tk.StringVar(value="5.0")
        self.client_compress_level = tk.IntVar(value=8)
        self.client_position_q = tk.IntVar(value=12)
        self.client_generic_q = tk.IntVar(value=10)

        self._add_labeled_entry(client_frame, "Server Host", self.client_host, row=0)
        self._add_labeled_entry(client_frame, "Server Port", self.client_port, row=1)
        ttk.Label(client_frame, text="Bag File").grid(row=2, column=0, sticky="e")
        bag_entry = ttk.Entry(client_frame, textvariable=self.client_bag_file, width=32)
        bag_entry.grid(row=2, column=1, sticky="we", pady=2)
        ttk.Button(client_frame, text="Browse", command=self._browse_bag_file).grid(
            row=2, column=2, sticky="we", padx=(5, 0)
        )
        self._add_labeled_entry(client_frame, "Topic Name", self.client_topic_name, row=3, columnspan=2)
        self._add_labeled_entry(client_frame, "Prefix", self.client_prefix, row=4, columnspan=2)
        ttk.Checkbutton(
            client_frame, text="Use Simulation Time", variable=self.client_use_sim_time
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=(0, 5))
        ttk.Checkbutton(client_frame, text="Loop Bag", variable=self.client_loop).grid(
            row=6, column=0, columnspan=2, sticky="w", pady=(0, 5)
        )
        self._add_labeled_entry(client_frame, "Telemetry Rate (Hz)", self.client_telemetry_rate, row=7, columnspan=2)
        self._add_labeled_entry(
            client_frame, "Idle Shutdown Timeout (s)", self.client_idle_timeout, row=8, columnspan=2
        )

        ttk.Label(client_frame, text="Compression Level").grid(row=9, column=0, sticky="e")
        ttk.Spinbox(
            client_frame, from_=0, to=10, textvariable=self.client_compress_level, width=5
        ).grid(row=9, column=1, sticky="w", pady=2)
        ttk.Label(client_frame, text="Position QBits").grid(row=10, column=0, sticky="e")
        ttk.Spinbox(
            client_frame, from_=1, to=30, textvariable=self.client_position_q, width=5
        ).grid(row=10, column=1, sticky="w", pady=2)
        ttk.Label(client_frame, text="Generic QBits").grid(row=11, column=0, sticky="e")
        ttk.Spinbox(
            client_frame, from_=1, to=30, textvariable=self.client_generic_q, width=5
        ).grid(row=11, column=1, sticky="w", pady=2)

        ttk.Button(client_frame, text="Start Client", command=self._start_client).grid(
            row=12, column=0, sticky="we", pady=(8, 0)
        )
        ttk.Button(client_frame, text="Stop Client", command=self._stop_client).grid(
            row=12, column=1, sticky="we", pady=(8, 0), padx=(5, 0)
        )

        self.client_status = tk.StringVar(value="Stopped")
        ttk.Label(client_frame, textvariable=self.client_status).grid(
            row=13, column=0, columnspan=3, sticky="we", pady=(5, 0)
        )

        slam_frame = ttk.Labelframe(self, text="KISS-ICP SLAM")
        slam_frame.grid(row=2, column=0, sticky="nsew", **padding)
        slam_frame.grid_columnconfigure(1, weight=1)

        self.slam_topic = tk.StringVar(value="/stream_pair/decoded")
        self.slam_base_frame = tk.StringVar(value="lidar_frame")
        self.slam_use_sim_time = tk.BooleanVar(value=True)
        self.slam_visualize = tk.BooleanVar(value=True)
        self.slam_map_directory = tk.StringVar(value=str(Path.home() / "kiss_icp_maps"))
        self.slam_keep_full_history = tk.BooleanVar(value=True)
        self.slam_publish_saved_map = tk.BooleanVar(value=True)

        self._add_labeled_entry(slam_frame, "Input Topic", self.slam_topic, row=0)
        self._add_labeled_entry(slam_frame, "Base Frame", self.slam_base_frame, row=1)
        ttk.Checkbutton(
            slam_frame, text="Use Simulation Time", variable=self.slam_use_sim_time
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(0, 5))
        ttk.Checkbutton(
            slam_frame, text="Launch RViz", variable=self.slam_visualize
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(0, 5))
        ttk.Checkbutton(
            slam_frame, text="Keep Full Map History", variable=self.slam_keep_full_history
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(0, 5))
        ttk.Checkbutton(
            slam_frame, text="Publish Saved Map Topic", variable=self.slam_publish_saved_map
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=(0, 5))

        ttk.Label(slam_frame, text="Map Save Dir").grid(row=6, column=0, sticky="e")
        ttk.Entry(slam_frame, textvariable=self.slam_map_directory, width=24).grid(
            row=6, column=1, sticky="we", pady=2
        )
        ttk.Button(slam_frame, text="Browse", command=self._browse_map_directory).grid(
            row=6, column=2, sticky="we", padx=(5, 0)
        )

        ttk.Button(slam_frame, text="Start SLAM", command=self._start_slam).grid(
            row=7, column=0, sticky="we", pady=(8, 0)
        )
        ttk.Button(slam_frame, text="Stop SLAM", command=self._stop_slam).grid(
            row=7, column=1, sticky="we", pady=(8, 0), padx=(5, 0)
        )
        ttk.Button(slam_frame, text="Save Map", command=self._save_map).grid(
            row=7, column=2, sticky="we", pady=(8, 0)
        )

        self.slam_status = tk.StringVar(value="Stopped")
        ttk.Label(slam_frame, textvariable=self.slam_status).grid(
            row=8, column=0, columnspan=3, sticky="we", pady=(5, 0)
        )

    def _add_labeled_entry(
        self,
        container: ttk.Widget,
        label: str,
        variable: tk.Variable,
        *,
        row: int,
        columnspan: int = 1,
    ) -> None:
        ttk.Label(container, text=label).grid(row=row, column=0, sticky="e")
        entry = ttk.Entry(container, textvariable=variable, width=24)
        entry.grid(row=row, column=1, columnspan=columnspan, sticky="we", pady=2)

    def _browse_bag_file(self) -> None:
        filename = filedialog.askopenfilename(
            title="Select rosbag2 file",
            filetypes=[
                ("rosbag2 database", "*.db3"),
                ("All files", "*.*"),
            ],
        )
        if filename:
            self.client_bag_file.set(filename)

    def _browse_map_directory(self) -> None:
        directory = filedialog.askdirectory(
            title="Select map output directory",
        )
        if directory:
            self.slam_map_directory.set(directory)

    def _start_server(self) -> None:
        if self.server_process.is_running():
            messagebox.showinfo("Server", "Server is already running.")
            return
        config = ServerConfig(
            port=self.server_port.get(),
            downlink_port=self.server_downlink_port.get(),
            use_sim_time=self.server_use_sim_time.get(),
            points_topic=self.server_points_topic.get(),
            points_frame_id=self.server_points_frame.get(),
            downlink_protocol=self.server_downlink_protocol.get(),
            downlink_rate=self.server_downlink_rate.get(),
        )
        command = ["ros2", "launch", "draco_roundtrip", "server.launch.py", *config.as_launch_args()]
        try:
            self.server_process.start(command)
            self.server_status.set("Running")
        except Exception as exc:
            messagebox.showerror("Server", f"Failed to start server: {exc}")

    def _stop_server(self) -> None:
        self.server_process.stop()
        self.server_status.set("Stopped")

    def _start_client(self) -> None:
        if self.client_process.is_running():
            messagebox.showinfo("Client", "Client pipeline is already running.")
            return
        bag_value = _normalise_path(self.client_bag_file.get())
        self.client_bag_file.set(bag_value)
        config = ClientConfig(
            server_host=self.client_host.get(),
            server_port=self.client_port.get(),
            bag_file=bag_value,
            topic_name=self.client_topic_name.get(),
            prefix=self.client_prefix.get(),
            use_sim_time=self.client_use_sim_time.get(),
            telemetry_rate=self.client_telemetry_rate.get(),
            loop=self.client_loop.get(),
            idle_shutdown_timeout=self.client_idle_timeout.get(),
            compress_level=int(self.client_compress_level.get()),
            position_quantization_bits=int(self.client_position_q.get()),
            generic_quantization_bits=int(self.client_generic_q.get()),
        )
        try:
            args = config.as_launch_args()
        except ValueError as exc:
            messagebox.showerror("Client", str(exc))
            return
        command = [
            "ros2",
            "launch",
            "draco_roundtrip",
            "client.launch.py",
            *args,
        ]
        try:
            self.client_process.start(command)
            self.client_status.set("Running")
        except Exception as exc:
            messagebox.showerror("Client", f"Failed to start client pipeline: {exc}")

    def _stop_client(self) -> None:
        self.client_process.stop()
        self.client_status.set("Stopped")

    def _start_slam(self) -> None:
        if self.slam_process.is_running():
            messagebox.showinfo("SLAM", "KISS-ICP is already running.")
            return
        config = SlamConfig(
            topic=self.slam_topic.get(),
            base_frame=self.slam_base_frame.get(),
            use_sim_time=self.slam_use_sim_time.get(),
            visualize=self.slam_visualize.get(),
            map_save_directory=self.slam_map_directory.get(),
            keep_full_history=self.slam_keep_full_history.get(),
            publish_saved_map=self.slam_publish_saved_map.get(),
        )
        command = [
            "ros2",
            "launch",
            "slam_stream_bridge",
            "kiss_icp.launch.py",
            *config.as_launch_args(),
        ]
        try:
            self.slam_process.start(command)
            self.slam_status.set("Running")
        except Exception as exc:
            messagebox.showerror("SLAM", f"Failed to start KISS-ICP: {exc}")

    def _stop_slam(self) -> None:
        self.slam_process.stop()
        self.slam_status.set("Stopped")

    def _save_map(self) -> None:
        if not self.slam_process.is_running():
            messagebox.showinfo("SLAM", "KISS-ICP가 실행 중일 때만 맵을 저장할 수 있습니다.")
            return

        command = [
            "ros2",
            "service",
            "call",
            "/kiss/save_map",
            "std_srvs/srv/Trigger",
            "{}",
        ]

        def _invoke() -> None:
            try:
                completed = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    check=True,
                )
                output = (completed.stdout or "") + (completed.stderr or "")
                success, detail = self._parse_trigger_response(output)
                if success:
                    self.after(
                        0,
                        lambda: messagebox.showinfo(
                            "SLAM", detail or "KISS-ICP 맵을 저장했습니다."
                        ),
                    )
                else:
                    self.after(
                        0,
                        lambda: messagebox.showerror(
                            "SLAM", detail or "맵 저장 서비스가 실패로 응답했습니다."
                        ),
                    )
            except subprocess.CalledProcessError as exc:
                output = (exc.stdout or "") + (exc.stderr or "")
                self.after(
                    0,
                    lambda: messagebox.showerror(
                        "SLAM",
                        f"맵 저장 명령이 실패했습니다: {output.strip() or exc}",
                    ),
                )

        threading.Thread(target=_invoke, daemon=True).start()

    def _schedule_status_refresh(self) -> None:
        self._refresh_status()
        self.after(1000, self._schedule_status_refresh)

    def _refresh_status(self) -> None:
        self.server_status.set("Running" if self.server_process.is_running() else "Stopped")
        self.client_status.set("Running" if self.client_process.is_running() else "Stopped")
        self.slam_status.set("Running" if self.slam_process.is_running() else "Stopped")

    def destroy(self) -> None:
        self.server_process.stop()
        self.client_process.stop()
        self.slam_process.stop()
        super().destroy()

    @staticmethod
    def _parse_trigger_response(output: str) -> tuple[bool, str]:
        success = bool(re.search(r"success\s*=\s*True", output))
        match = re.search(r"message\s*=\s*['\"]([^'\"]*)['\"]", output)
        message = match.group(1) if match else ""
        return success, message


def main() -> None:
    """Entry point used by console_scripts."""

    try:
        app = ControlPanel()
        app.mainloop()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
