#!/usr/bin/env python3
"""Client for Draco uplink streaming with control-plane downlink."""

from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Iterable

from draco_roundtrip.analysis.metrics import compute_basic_metrics
from draco_roundtrip.draco.encoder import EncoderOptions, encode_frame, find_draco_encoder
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
    MSG_DATA,
    MSG_ERROR,
    MSG_HEARTBEAT,
    MSG_PATH,
    MSG_POSE,
    MSG_TWIST,
    recv_message,
    send_message,
)
from draco_roundtrip.ros.client_bridge import ClientBridge
from draco_roundtrip.utils import ensure_directory, resolve_qos_override


def launch_bag_to_ply(args: argparse.Namespace) -> subprocess.Popen:
    cmd = [
        sys.executable,
        "-m",
        "draco_roundtrip.io.bag_recorder",
        "--topic",
        args.topic,
        "--out",
        str(Path(args.ply_dir).resolve()),
        "--prefix",
        args.prefix,
        "--idle-timeout-sec",
        str(args.idle_timeout),
    ]
    if args.best_effort:
        cmd.append("--best-effort")
    if args.max_frames:
        cmd += ["--max-frames", str(args.max_frames)]
    return subprocess.Popen(cmd, stdout=sys.stdout, stderr=sys.stderr)


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Streaming client with ROS downlink bridge")
    ap.add_argument("--bag", required=True)
    ap.add_argument("--topic", required=True)
    ap.add_argument("--prefix", required=True)
    ap.add_argument("--ply-dir", default="data/ply_stream")
    ap.add_argument("--encoder", default=None)
    ap.add_argument("--cl", type=int, default=8)
    ap.add_argument("--qp", type=int, default=12)
    ap.add_argument("--qg", type=int, default=10)
    ap.add_argument("--encoder-extra", nargs="*", default=[])
    ap.add_argument("--idle-timeout", type=float, default=10.0)
    ap.add_argument("--max-frames", type=int, default=0)
    ap.add_argument("--best-effort", action="store_true")
    ap.add_argument("--work-dir", default="data/client_tmp")
    ap.add_argument("--decoded-dir", default="data/decoded_from_server")
    ap.add_argument("--server-host", default="127.0.0.1")
    ap.add_argument("--server-port", type=int, default=5000)
    ap.add_argument("--play-frame-id", default="lidar_link")
    ap.add_argument("--play-topic-prefix", default="stream_pair")
    ap.add_argument("--play-hz", type=float, default=10.0)
    ap.add_argument("--play-sample", type=int, default=50000)
    ap.add_argument("--downlink-host", default=None, help="Downlink host override (default: server host)")
    ap.add_argument("--downlink-port", type=int, default=None, help="Downlink port (default: server port+1)")
    ap.add_argument(
        "--downlink-protocol",
        choices=("binary", "json"),
        default="binary",
        help="Downlink payload encoding",
    )
    ap.add_argument("--topic-prefix", default="", help="Prefix for downlink ROS topics")
    ap.add_argument("--execute-cmdvel", action="store_true", help="Invoke cmd_vel execution hook")
    ap.add_argument("--heartbeat-interval", type=float, default=1.0, help="Heartbeat interval in seconds")
    return ap


def _time_from_ns(stamp_ns: int) -> tuple[int, int]:
    sec = int(stamp_ns // 1_000_000_000)
    nsec = int(stamp_ns % 1_000_000_000)
    return sec, nsec


def _pose_to_msg(payload: PosePayload) -> "PoseStamped":
    from geometry_msgs.msg import PoseStamped

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


def _path_to_msg(payload: PathPayload) -> "Path":
    from geometry_msgs.msg import PoseStamped
    from nav_msgs.msg import Path

    msg = Path()
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


def _twist_to_msg(payload: TwistPayload) -> "Twist":
    from geometry_msgs.msg import Twist

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


def _downlink_loop(
    host: str,
    port: int,
    protocol: str,
    bridge: ClientBridge,
    stop_event: threading.Event,
) -> None:
    backoff = 1.0
    while not stop_event.is_set():
        try:
            with socket.create_connection((host, port), timeout=5.0) as sock:
                sock.settimeout(5.0)
                print(f"[CLIENT] Downlink connected to {host}:{port}")
                backoff = 1.0
                while not stop_event.is_set():
                    msg = recv_message(sock)
                    if msg is None:
                        break
                    decoded = _decode_downlink_message(msg, protocol)
                    if decoded is None:
                        continue
                    kind, payload = decoded
                    if kind == MSG_POSE:
                        bridge.publish_pose(payload)  # type: ignore[arg-type]
                    elif kind == MSG_TWIST:
                        bridge.publish_twist(payload)  # type: ignore[arg-type]
                        print(
                            "[CLIENT] cmd_vel preview "
                            f"linear=({payload.linear.x:.3f},{payload.linear.y:.3f},{payload.linear.z:.3f}) "
                            f"angular=({payload.angular.x:.3f},{payload.angular.y:.3f},{payload.angular.z:.3f})"
                        )
                    elif kind == MSG_PATH:
                        bridge.publish_path(payload)  # type: ignore[arg-type]
        except Exception as exc:
            if stop_event.is_set():
                break
            print(f"[CLIENT] Downlink error: {exc}, retrying in {backoff:.1f}s")
            stop_event.wait(backoff)
            backoff = min(backoff * 2.0, 5.0)


def main(argv: Iterable[str] | None = None) -> None:
    args = build_arg_parser().parse_args(argv)

    encoder_path = find_draco_encoder(args.encoder)
    encoder_options = EncoderOptions(
        compress_level=args.cl,
        position_quantization_bits=args.qp,
        generic_quantization_bits=args.qg,
        extra_args=tuple(args.encoder_extra),
    )

    ply_dir = ensure_directory(Path(args.ply_dir).resolve())
    work_dir = ensure_directory(Path(args.work_dir).resolve())
    decoded_dir = ensure_directory(Path(args.decoded_dir).resolve())

    bag_cmd = ["ros2", "bag", "play", str(Path(args.bag).resolve())]
    qos_override = resolve_qos_override()
    if qos_override is not None:
        bag_cmd += ["--qos-profile-overrides-path", str(qos_override)]
    else:
        print("[CLIENT] WARN: QoS override file not found, falling back to recorded QoS", file=sys.stderr)
    bag_process = subprocess.Popen(bag_cmd)
    saver_proc = launch_bag_to_ply(args)

    bridge = ClientBridge(
        playback_frame_id=args.play_frame_id,
        playback_prefix=args.play_topic_prefix,
        playback_hz=args.play_hz,
        topic_prefix=args.topic_prefix,
        execute_cmdvel=args.execute_cmdvel,
        cmdvel_callback=None,
    )

    processed: set[Path] = set()
    frame_idx = 0
    start_time = time.monotonic()
    bytes_sent = 0
    bytes_received = 0
    last_send = time.monotonic()
    heartbeat_interval = max(float(args.heartbeat_interval), 0.5)

    downlink_stop = threading.Event()
    downlink_host = args.downlink_host or args.server_host
    downlink_port = args.downlink_port or (args.server_port + 1)
    downlink_thread = threading.Thread(
        target=_downlink_loop,
        args=(downlink_host, downlink_port, args.downlink_protocol, bridge, downlink_stop),
        daemon=True,
    )
    downlink_thread.start()

    try:
        with socket.create_connection((args.server_host, args.server_port)) as sock:
            print(f"[CLIENT] Connected to {args.server_host}:{args.server_port}")
            try:
                while True:
                    new_files = sorted(ply_dir.glob(f"{args.prefix}_*.ply"))
                    sent_any = False
                    for ply_path in new_files:
                        if ply_path in processed:
                            continue
                        try:
                            result = encode_frame(
                                ply_path,
                                work_dir,
                                encoder_options,
                                encoder_hint=encoder_path,
                                skip_existing=False,
                            )
                            drc_bytes = result.output.read_bytes()
                        except Exception as exc:
                            print(f"[CLIENT] ENCODE FAIL {ply_path.name}: {exc}")
                            processed.add(ply_path)
                            continue
                        message = Message(kind=MSG_DATA, name=ply_path.stem, payload=drc_bytes)
                        send_message(sock, message)
                        bytes_sent += len(drc_bytes)
                        last_send = time.monotonic()
                        sent_any = True
                        print(f"[CLIENT] Sent {ply_path.name} ({len(drc_bytes)} bytes)")

                        reply = recv_message(sock)
                        if reply is None:
                            raise ConnectionClosed("server closed uplink")
                        if reply.kind == MSG_ERROR:
                            detail = reply.payload.decode(errors="ignore")
                            print(f"[CLIENT] SERVER ERROR for {ply_path.name}: {reply.name} -> {detail}")
                            processed.add(ply_path)
                            continue
                        if reply.kind == MSG_DATA:
                            bytes_received += len(reply.payload)
                            reply_name = reply.name or f"{ply_path.stem}.decoded"
                            if not reply_name.endswith(".ply"):
                                reply_name = f"{reply_name}.ply"
                            decoded_path = decoded_dir / reply_name
                            decoded_path.write_bytes(reply.payload)
                            pts_dec = load_xyz_from_bytes(reply.payload)
                        else:
                            pts_dec = load_xyz_from_bytes(ply_path.read_bytes())

                        pts_src = load_xyz(ply_path)
                        metrics = compute_basic_metrics(pts_src, pts_dec, args.play_sample)
                        print(
                            f"[CLIENT] Frame {frame_idx:05d} metrics — "
                            f"Δpts={metrics['diff']} centroid_norm={metrics['centroid_norm']:.3f} "
                            f"bboxΔ=({metrics['bbox_delta'][0]:+.3f},{metrics['bbox_delta'][1]:+.3f},{metrics['bbox_delta'][2]:+.3f}) "
                            f"Chamfer(mean/max)={metrics['chamfer_mean']}/{metrics['chamfer_max']}"
                        )
                        bridge.publish_playback(frame_idx, ply_path.stem, pts_src, pts_dec, args.play_frame_id)
                        processed.add(ply_path)
                        frame_idx += 1

                    now = time.monotonic()
                    if not sent_any and now - last_send > heartbeat_interval:
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
        downlink_stop.set()
        if downlink_thread.is_alive():
            downlink_thread.join(timeout=2.0)
        bridge.close()
        if bag_process and bag_process.poll() is None:
            bag_process.terminate()
        if saver_proc and saver_proc.poll() is None:
            saver_proc.terminate()
        elapsed = max(time.monotonic() - start_time, 1e-6)
        print("[CLIENT] ---- Transfer summary ----")
        print(f"  elapsed: {elapsed:.2f} s")
        print(f"  sent: {bytes_sent} bytes ({bytes_sent * 8 / elapsed / 1e6:.3f} Mbps)")
        print(f"  received: {bytes_received} bytes ({bytes_received * 8 / elapsed / 1e6:.3f} Mbps)")


if __name__ == "__main__":
    main()
