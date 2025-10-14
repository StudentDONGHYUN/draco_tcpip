#!/usr/bin/env python3
"""Client for Draco uplink streaming with control-plane downlink."""

from __future__ import annotations

import json
import queue
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Tuple

import numpy as np
import rclpy
from geometry_msgs.msg import PoseStamped, Twist
from nav_msgs.msg import Path as NavPath
from rclpy.node import Node
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
from rclpy.utilities import remove_ros_args
from sensor_msgs.msg import PointCloud2
from sensor_msgs_py import point_cloud2 as pc2
from std_msgs.msg import Header

from draco_roundtrip.analysis.metrics import compute_basic_metrics
from draco_roundtrip.draco.encoder import EncoderOptions, encode_points
from draco_roundtrip.io.ply_codec import load_xyz, load_xyz_from_bytes
from draco_roundtrip.net.control_plane import (
    PathPayload,
    PathPose,
    PosePayload,
    TwistPayload,
    decode_path_payload,
    decode_pose_payload,
    decode_twist_payload,
)
from draco_roundtrip.net.protocol import (
    ConnectionClosed,
    Message,
    MSG_ACK,
    MSG_DATA,
    MSG_ERROR,
    MSG_HEARTBEAT,
    MSG_PATH,
    MSG_POSE,
    MSG_TWIST,
    recv_message,
    send_message,
)
from draco_roundtrip.utils import ensure_directory, resolve_qos_override

QueueItem = Tuple[str, object]


@dataclass(slots=True)
class PlaybackJob:
    frame_idx: int
    name: str
    source: np.ndarray
    decoded: np.ndarray
    frame_id: str


def _resolve_topic(prefix: str, base: str) -> str:
    if not prefix:
        return base
    prefix = prefix.strip()
    if not prefix.startswith("/"):
        prefix = f"/{prefix}"
    prefix = prefix.rstrip("/")
    return f"{prefix}/{base.lstrip('/')}"


def _time_from_ns(stamp_ns: int) -> tuple[int, int]:
    sec = int(stamp_ns // 1_000_000_000)
    nsec = int(stamp_ns % 1_000_000_000)
    return sec, nsec


def _pose_to_msg(payload: PosePayload) -> PoseStamped:
    msg = PoseStamped()
    msg.header.stamp.sec, msg.header.stamp.nanosec = _time_from_ns(payload.stamp_ns)
    msg.header.frame_id = payload.frame_id or "map"
    msg.pose.position.x = payload.x
    msg.pose.position.y = payload.y
    msg.pose.position.z = payload.z
    msg.pose.orientation.x = payload.qx
    msg.pose.orientation.y = payload.qy
    msg.pose.orientation.z = payload.qz
    msg.pose.orientation.w = payload.qw
    return msg


def _path_to_msg(payload: PathPayload) -> NavPath:
    msg = NavPath()
    msg.header.stamp.sec, msg.header.stamp.nanosec = _time_from_ns(payload.stamp_ns)
    msg.header.frame_id = payload.frame_id or "map"
    msg.poses = []
    for pose in payload.poses:
        pose_msg = PoseStamped()
        pose_msg.header = msg.header
        pose_msg.pose.position.x = pose.x
        pose_msg.pose.position.y = pose.y
        pose_msg.pose.position.z = pose.z
        pose_msg.pose.orientation.x = pose.qx
        pose_msg.pose.orientation.y = pose.qy
        pose_msg.pose.orientation.z = pose.qz
        pose_msg.pose.orientation.w = pose.qw
        msg.poses.append(pose_msg)
    return msg


def _twist_to_msg(payload: TwistPayload) -> Twist:
    msg = Twist()
    msg.linear.x = payload.vx
    msg.linear.y = payload.vy
    msg.linear.z = payload.vz
    msg.angular.x = payload.wx
    msg.angular.y = payload.wy
    msg.angular.z = payload.wz
    return msg


def _decode_downlink_message(msg: Message, protocol: str) -> Optional[tuple[str, object]]:
    if protocol == "json":
        try:
            data = json.loads(msg.payload.decode("utf-8"))
        except Exception as exc:
            print(f"[CLIENT] Failed to parse JSON downlink: {exc}")
            return None
        kind = data.get("type", msg.kind)
        if kind == MSG_POSE:
            payload = PosePayload(
                stamp_ns=int(data["stamp_ns"]),
                frame_id=str(data.get("frame_id", "map")),
                x=float(data["position"]["x"]),
                y=float(data["position"]["y"]),
                z=float(data["position"]["z"]),
                qx=float(data["orientation"]["x"]),
                qy=float(data["orientation"]["y"]),
                qz=float(data["orientation"]["z"]),
                qw=float(data["orientation"]["w"]),
            )
            return (MSG_POSE, _pose_to_msg(payload))
        if kind == MSG_TWIST:
            payload = TwistPayload(
                stamp_ns=int(data["stamp_ns"]),
                vx=float(data["linear"]["x"]),
                vy=float(data["linear"]["y"]),
                vz=float(data["linear"]["z"]),
                wx=float(data["angular"]["x"]),
                wy=float(data["angular"]["y"]),
                wz=float(data["angular"]["z"]),
            )
            return (MSG_TWIST, _twist_to_msg(payload))
        if kind == MSG_PATH:
            poses = []
            for entry in data.get("poses", []):
                pos = entry.get("position", {})
                ori = entry.get("orientation", {})
                poses.append(
                    PathPose(
                        x=float(pos.get("x", 0.0)),
                        y=float(pos.get("y", 0.0)),
                        z=float(pos.get("z", 0.0)),
                        qx=float(ori.get("x", 0.0)),
                        qy=float(ori.get("y", 0.0)),
                        qz=float(ori.get("z", 0.0)),
                        qw=float(ori.get("w", 1.0)),
                    )
                )
            payload = PathPayload(
                stamp_ns=int(data["stamp_ns"]),
                frame_id=str(data.get("frame_id", "map")),
                poses=poses,
            )
            return (MSG_PATH, _path_to_msg(payload))
        return None

    if msg.kind == MSG_POSE:
        return (MSG_POSE, _pose_to_msg(decode_pose_payload(msg.payload)))
    if msg.kind == MSG_TWIST:
        return (MSG_TWIST, _twist_to_msg(decode_twist_payload(msg.payload)))
    if msg.kind == MSG_PATH:
        return (MSG_PATH, _path_to_msg(decode_path_payload(msg.payload)))
    return None


def _launch_bag_to_ply(
    topic: str,
    ply_dir: Path,
    prefix: str,
    idle_timeout: float,
    best_effort: bool,
    max_frames: int,
    use_sim_time: bool,
) -> subprocess.Popen:
    cmd = [
        sys.executable,
        "-m",
        "draco_roundtrip.io.bag_recorder",
        "--topic",
        topic,
        "--out",
        str(ply_dir.resolve()),
        "--prefix",
        prefix,
        "--idle-timeout-sec",
        str(idle_timeout),
    ]
    if best_effort:
        cmd.append("--best-effort")
    if max_frames:
        cmd += ["--max-frames", str(max_frames)]
        
    if use_sim_time:
        cmd += ["--ros-args", "--param", "use_sim_time:=true"]
        
    return subprocess.Popen(cmd, stdout=sys.stdout, stderr=sys.stderr)


class StreamClientNode(Node):
    """Streaming client that uses ROS 2 parameters for configuration."""

    def __init__(self) -> None:
        super().__init__("draco_stream_client")

        # Declare parameters for configuration compatibility.
        self.declare_parameter("bag", "")
        self.declare_parameter("topic", "")
        self.declare_parameter("prefix", "")
        self.declare_parameter("ply_dir", "data/ply_stream")
        self.declare_parameter("encoder", "")
        self.declare_parameter("cl", 8)
        self.declare_parameter("qp", 12)
        self.declare_parameter("qg", 10)
        self.declare_parameter("encoder_extra", [])
        self.declare_parameter("idle_timeout", 10.0)
        self.declare_parameter("max_frames", 0)
        self.declare_parameter("best_effort", False)
        self.declare_parameter("work_dir", "data/client_tmp")
        self.declare_parameter("decoded_dir", "data/decoded_from_server")
        self.declare_parameter("server_host", "127.0.0.1")
        self.declare_parameter("server_port", 5000)
        self.declare_parameter("play_frame_id", "lidar_link")
        self.declare_parameter("play_topic_prefix", "stream_pair")
        self.declare_parameter("play_hz", 10.0)
        self.declare_parameter("play_sample", 50000)
        self.declare_parameter("downlink_host", "")
        self.declare_parameter("downlink_port", 0)
        self.declare_parameter("downlink_protocol", "binary")
        self.declare_parameter("topic_prefix", "")
        self.declare_parameter("execute_cmdvel", False)
        self.declare_parameter("heartbeat_interval", 1.0)
        self.declare_parameter("telemetry_rate", 10.0)
        self.declare_parameter("max_inflight", 8)
        self.declare_parameter("protocol", "binary")
        self.declare_parameter("socket_timeout", 3.0)
        self.declare_parameter("calculate_metrics", False)  # <-- 신규 파라미터 추가

        self.bag_path = str(self.get_parameter("bag").value)
        self.topic = str(self.get_parameter("topic").value)
        self.prefix = str(self.get_parameter("prefix").value)
        self.ply_dir = ensure_directory(Path(str(self.get_parameter("ply_dir").value)).resolve())
        self.work_dir = ensure_directory(Path(str(self.get_parameter("work_dir").value)).resolve())
        self.decoded_dir = ensure_directory(
            Path(str(self.get_parameter("decoded_dir").value)).resolve()
        )
        encoder_extra = self.get_parameter("encoder_extra").value
        extra_args = tuple(encoder_extra) if isinstance(encoder_extra, (list, tuple)) else ()
        self.encoder_options = EncoderOptions(
            compress_level=int(self.get_parameter("cl").value),
            position_quantization_bits=int(self.get_parameter("qp").value),
            generic_quantization_bits=int(self.get_parameter("qg").value),
            extra_args=extra_args,
        )
        self.idle_timeout = float(self.get_parameter("idle_timeout").value)
        self.max_frames = int(self.get_parameter("max_frames").value)
        self.best_effort = bool(self.get_parameter("best_effort").value)
        self.server_host = str(self.get_parameter("server_host").value)
        self.server_port = int(self.get_parameter("server_port").value)
        self.play_frame_id = str(self.get_parameter("play_frame_id").value)
        playback_prefix = str(self.get_parameter("play_topic_prefix").value or "").strip("/")
        self.playback_hz = float(self.get_parameter("play_hz").value)
        self.play_sample = int(self.get_parameter("play_sample").value)
        self.topic_prefix = str(self.get_parameter("topic_prefix").value)
        self.execute_cmdvel = bool(self.get_parameter("execute_cmdvel").value)
        self.heartbeat_interval = max(float(self.get_parameter("heartbeat_interval").value), 0.5)
        self.telemetry_rate = float(self.get_parameter("telemetry_rate").value)
        self.max_inflight = int(self.get_parameter("max_inflight").value)
        self.protocol = str(self.get_parameter("protocol").value)
        self.socket_timeout = max(float(self.get_parameter("socket_timeout").value), 0.5)
        downlink_host_param = str(self.get_parameter("downlink_host").value)
        self.downlink_host = downlink_host_param or self.server_host
        downlink_port_param = int(self.get_parameter("downlink_port").value)
        self.downlink_port = downlink_port_param if downlink_port_param else self.server_port + 1
        self.downlink_protocol = str(self.get_parameter("downlink_protocol").value)
        self.calculate_metrics = bool(self.get_parameter("calculate_metrics").value)
        self.use_sim_time = bool(self.get_parameter("use_sim_time").value) # <-- 파라미터 값 읽어오기

        qos = QoSProfile(depth=10)
        qos.history = HistoryPolicy.KEEP_LAST
        qos.reliability = ReliabilityPolicy.RELIABLE
        src_topic = f"/{playback_prefix}/source" if playback_prefix else "/stream_pair/source"
        dec_topic = f"/{playback_prefix}/decoded" if playback_prefix else "/stream_pair/decoded"
        self.pub_src = self.create_publisher(PointCloud2, src_topic, qos)
        self.pub_dec = self.create_publisher(PointCloud2, dec_topic, qos)
        pose_topic = _resolve_topic(self.topic_prefix, "/server_pose")
        path_topic = _resolve_topic(self.topic_prefix, "/planned_path")
        twist_topic = _resolve_topic(self.topic_prefix, "/cmd_vel")
        self.pub_pose = self.create_publisher(PoseStamped, pose_topic, qos)
        self.pub_path = self.create_publisher(NavPath, path_topic, qos)
        self.pub_twist = self.create_publisher(Twist, twist_topic, qos)

        self._queue: "queue.Queue[QueueItem]" = queue.Queue()
        playback_period = 1.0 / self.playback_hz if self.playback_hz > 0 else 0.1
        self._queue_timer = self.create_timer(playback_period, self._process_queue)

        self._metrics_lock = threading.Lock()
        self._bytes_sent = 0
        self._bytes_received = 0
        self._frames_sent = 0
        self._start_time = time.monotonic()
        self._telemetry_timer = None
        if self.telemetry_rate > 0:
            period = 1.0 / self.telemetry_rate
            self._telemetry_timer = self.create_timer(period, self._telemetry_tick)

        self._stop_event = threading.Event()
        self._downlink_stop = threading.Event()
        self._downlink_thread: Optional[threading.Thread] = None
        self._bag_process: Optional[subprocess.Popen] = None
        self._saver_process: Optional[subprocess.Popen] = None
        self._worker_thread = threading.Thread(target=self._run_client, daemon=True)
        self._worker_thread.start()

    # ------------------------------------------------------------------
    # Queue helpers

    def _process_queue(self) -> None:
        processed = 0
        while processed < 16:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                return
            processed += 1
            kind, payload = item
            if kind == "playback":
                job = payload  # type: ignore[assignment]
                assert isinstance(job, PlaybackJob)
                self._publish_playback(job)
            elif kind == "pose":
                assert isinstance(payload, PoseStamped)
                self.pub_pose.publish(payload)
            elif kind == "path":
                assert isinstance(payload, NavPath)
                self.pub_path.publish(payload)
            elif kind == "twist":
                assert isinstance(payload, Twist)
                self.pub_twist.publish(payload)
                if self.execute_cmdvel:
                    try:
                        self._handle_cmdvel(payload)
                    except Exception as exc:  # pragma: no cover - user hook
                        self.get_logger().warning(f"cmd_vel handler failed: {exc}")

    def _publish_playback(self, job: PlaybackJob) -> None:
        now = self.get_clock().now().to_msg()
        header = Header()
        header.stamp = now
        header.frame_id = job.frame_id or self.play_frame_id
        msg_src = pc2.create_cloud_xyz32(header, job.source)
        msg_dec = pc2.create_cloud_xyz32(header, job.decoded)
        self.pub_src.publish(msg_src)
        self.pub_dec.publish(msg_dec)

    def _handle_cmdvel(self, twist: Twist) -> None:
        # Placeholder hook for cmd_vel execution callbacks if needed.
        pass

    def _enqueue_playback(self, job: PlaybackJob) -> None:
        self._queue.put(("playback", job))

    def _enqueue_pose(self, pose: PoseStamped) -> None:
        self._queue.put(("pose", pose))

    def _enqueue_path(self, path: NavPath) -> None:
        self._queue.put(("path", path))

    def _enqueue_twist(self, twist: Twist) -> None:
        self._queue.put(("twist", twist))

    # ------------------------------------------------------------------
    def _telemetry_tick(self) -> None:
        with self._metrics_lock:
            bytes_sent = self._bytes_sent
            bytes_received = self._bytes_received
            frames_sent = self._frames_sent
            start_time = self._start_time
        elapsed = max(time.monotonic() - start_time, 1e-6)
        uplink_mbps = bytes_sent * 8 / elapsed / 1e6
        downlink_mbps = bytes_received * 8 / elapsed / 1e6
        self.get_logger().info(
            f"Telemetry: frames={frames_sent} uplink={uplink_mbps:.3f} Mbps downlink={downlink_mbps:.3f} Mbps"
        )

    # ------------------------------------------------------------------
    def _run_client(self) -> None:
        try:
            self._execute_streaming_loop()
        except Exception as exc:  # pragma: no cover - defensive logging
            self.get_logger().error(f"Client loop error: {exc}")
            self._stop_event.set()

    def _execute_streaming_loop(self) -> None:
        if not self.bag_path or not self.topic or not self.prefix:
            self.get_logger().error(
                "Parameters 'bag', 'topic', and 'prefix' must be set before starting the client"
            )
            self._stop_event.set()
            return

        bag_path = Path(self.bag_path).resolve()
        bag_cmd = ["ros2", "bag", "play", str(bag_path)]
        
        # use_sim_time 값에 따라 --clock 옵션 추가
        if self.use_sim_time:
            bag_cmd.append("--clock")
        
        qos_override = resolve_qos_override()
        if qos_override is not None:
            bag_cmd += ["--qos-profile-overrides-path", str(qos_override)]
        else:
            print(
                "[CLIENT] WARN: QoS override file not found, falling back to recorded QoS",
                file=sys.stderr,
            )
        self._bag_process = subprocess.Popen(bag_cmd)
        self._saver_process = _launch_bag_to_ply(
            self.topic,
            self.ply_dir,
            self.prefix,
            self.idle_timeout,
            self.best_effort,
            self.max_frames,
            self.use_sim_time,
        )

        processed: set[Path] = set()
        frame_idx = 0
        start_time = time.monotonic()
        bytes_sent = 0
        bytes_received = 0
        last_send = time.monotonic()
        self._start_time = start_time

        self._downlink_thread = threading.Thread(
            target=self._downlink_loop,
            args=(self.downlink_host, self.downlink_port, self.downlink_protocol),
            daemon=True,
        )
        self._downlink_thread.start()

        try:
            with socket.create_connection(
                (self.server_host, self.server_port), timeout=self.socket_timeout
            ) as sock:
                sock.settimeout(self.socket_timeout)
                print(f"[CLIENT] Connected to {self.server_host}:{self.server_port}")
                try:
                    while not self._stop_event.is_set():
                        new_files = sorted(self.ply_dir.glob(f"{self.prefix}_*.ply"))
                        sent_any = False
                        for ply_path in new_files:
                            if ply_path in processed:
                                continue
                            try:
                                pts_src = load_xyz(ply_path)
                                result = encode_points(pts_src, self.encoder_options)
                                drc_bytes = result.encoded_data
                            except Exception as exc:
                                print(f"[CLIENT] ENCODE FAIL {ply_path.name}: {exc}")
                                processed.add(ply_path)
                                continue
                            message = Message(kind=MSG_DATA, name=ply_path.stem, payload=drc_bytes)
                            send_message(sock, message)
                            bytes_sent += len(drc_bytes)
                            with self._metrics_lock:
                                self._bytes_sent = bytes_sent
                            last_send = time.monotonic()
                            sent_any = True
                            print(f"[CLIENT] Sent {ply_path.name} ({len(drc_bytes)} bytes)")

                            reply = recv_message(sock)
                            if reply is None:
                                raise ConnectionClosed("server closed uplink")
                            if reply.kind == MSG_ERROR:
                                detail = reply.payload.decode(errors="ignore")
                                print(
                                    f"[CLIENT] SERVER ERROR for {ply_path.name}: {reply.name} -> {detail}"
                                )
                                processed.add(ply_path)
                                continue
                            if reply.kind == MSG_DATA:
                                bytes_received += len(reply.payload)
                                with self._metrics_lock:
                                    self._bytes_received = bytes_received
                                reply_name = reply.name or f"{ply_path.stem}.decoded"
                                if not reply_name.endswith(".ply"):
                                    reply_name = f"{reply_name}.ply"
                                decoded_path = self.decoded_dir / reply_name
                                decoded_path.write_bytes(reply.payload)
                                pts_dec = load_xyz_from_bytes(reply.payload)
                            else:
                                pts_dec = load_xyz_from_bytes(ply_path.read_bytes())

                            pts_src_metrics = pts_src
                            # <-- 메트릭 계산 로직을 조건부로 변경
                            if self.calculate_metrics:
                                metrics = compute_basic_metrics(
                                    pts_src_metrics, pts_dec, self.play_sample
                                )
                                print(
                                    f"[CLIENT] Frame {frame_idx:05d} metrics — "
                                    f"Δpts={metrics['diff']} centroid_norm={metrics['centroid_norm']:.3f} "
                                    f"bboxΔ=({metrics['bbox_delta'][0]:+.3f},{metrics['bbox_delta'][1]:+.3f},{metrics['bbox_delta'][2]:+.3f}) "
                                    f"Chamfer(mean/max)={metrics['chamfer_mean']}/{metrics['chamfer_max']}"
                                )
                            self._enqueue_playback(
                                PlaybackJob(frame_idx, ply_path.stem, pts_src, pts_dec, self.play_frame_id)
                            )
                            processed.add(ply_path)
                            frame_idx += 1
                            with self._metrics_lock:
                                self._frames_sent = frame_idx

                        now = time.monotonic()
                        if not sent_any and now - last_send > self.heartbeat_interval:
                            send_message(sock, Message(kind=MSG_HEARTBEAT, name="hb", payload=b""))
                            last_send = now
                            ack = recv_message(sock)
                            if ack is None:
                                raise ConnectionClosed("server closed uplink during heartbeat")
                            if ack.kind != MSG_ACK:
                                print(
                                    f"[CLIENT] Unexpected heartbeat reply kind={ack.kind}, name={ack.name}"
                                )
                        time.sleep(0.1)
                except ConnectionClosed:
                    print("[CLIENT] Connection closed, stopping loop")
        finally:
            self._downlink_stop.set()
            if self._downlink_thread and self._downlink_thread.is_alive():
                self._downlink_thread.join(timeout=2.0)
            if self._bag_process and self._bag_process.poll() is None:
                self._bag_process.terminate()
            if self._saver_process and self._saver_process.poll() is None:
                self._saver_process.terminate()
            elapsed = max(time.monotonic() - start_time, 1e-6)
            with self._metrics_lock:
                self._bytes_sent = bytes_sent
                self._bytes_received = bytes_received
            print("[CLIENT] ---- Transfer summary ----")
            print(f"  elapsed: {elapsed:.2f} s")
            print(f"  sent: {bytes_sent} bytes ({bytes_sent * 8 / elapsed / 1e6:.3f} Mbps)")
            print(
                f"  received: {bytes_received} bytes ({bytes_received * 8 / elapsed / 1e6:.3f} Mbps)"
            )

    # ------------------------------------------------------------------
    def _downlink_loop(self, host: str, port: int, protocol: str) -> None:
        backoff = 1.0
        while not self._downlink_stop.is_set():
            try:
                with socket.create_connection((host, port), timeout=self.socket_timeout) as sock:
                    sock.settimeout(self.socket_timeout)
                    print(f"[CLIENT] Downlink connected to {host}:{port}")
                    backoff = 1.0
                    while not self._downlink_stop.is_set():
                        msg = recv_message(sock)
                        if msg is None:
                            break
                        decoded = _decode_downlink_message(msg, protocol)
                        if decoded is None:
                            continue
                        kind, payload = decoded
                        if kind == MSG_POSE:
                            self._enqueue_pose(payload)  # type: ignore[arg-type]
                        elif kind == MSG_TWIST:
                            self._enqueue_twist(payload)  # type: ignore[arg-type]
                            print(
                                "[CLIENT] cmd_vel preview "
                                f"linear=({payload.linear.x:.3f},{payload.linear.y:.3f},{payload.linear.z:.3f}) "
                                f"angular=({payload.angular.x:.3f},{payload.angular.y:.3f},{payload.angular.z:.3f})"
                            )
                        elif kind == MSG_PATH:
                            self._enqueue_path(payload)  # type: ignore[arg-type]
            except Exception as exc:
                if self._downlink_stop.is_set():
                    break
                print(f"[CLIENT] Downlink error: {exc}, retrying in {backoff:.1f}s")
                self._downlink_stop.wait(backoff)
                backoff = min(backoff * 2.0, 5.0)

    # ------------------------------------------------------------------
    def destroy_node(self) -> None:  # pragma: no cover - shutdown path
        self._stop_event.set()
        self._downlink_stop.set()
        if self._worker_thread.is_alive():
            self._worker_thread.join(timeout=2.0)
        if self._downlink_thread and self._downlink_thread.is_alive():
            self._downlink_thread.join(timeout=2.0)
        if self._bag_process and self._bag_process.poll() is None:
            self._bag_process.terminate()
        if self._saver_process and self._saver_process.poll() is None:
            self._saver_process.terminate()
        super().destroy_node()


def _partition_ros_args(argv: list[str]) -> tuple[list[str], list[str]]:
    argv = list(argv)
    filtered = remove_ros_args(["stream_client", *argv])[1:]
    extras: list[str] = []
    ros_args: list[str] = []
    idx = 0
    for arg in argv:
        if idx < len(filtered) and arg == filtered[idx]:
            extras.append(arg)
            idx += 1
        else:
            ros_args.append(arg)
    return ros_args, extras


def main(argv: Iterable[str] | None = None) -> None:
    raw_args = list(argv) if argv is not None else sys.argv[1:]
    ros_args, extras = _partition_ros_args(raw_args)
    if extras:
        print(
            f"[stream_client] Ignoring legacy CLI arguments: {' '.join(extras)}",
            file=sys.stderr,
        )
    rclpy.init(args=ros_args)
    node = StreamClientNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
