#!/usr/bin/env python3
"""Stream rosbag frames, encode/send to server, replay decoded results to RViz."""

from __future__ import annotations

import argparse
import queue
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterable, Set

import numpy as np

from draco_tools.core.encoder import (
    add_encoder_arguments,
    encode_frame,
    find_draco_encoder,
    format_encode_log,
    resolve_encoder_options,
)
from draco_roundtrip.analysis.metrics import compute_basic_metrics
from draco_roundtrip.io.ply_codec import load_xyz, load_xyz_from_bytes
from draco_roundtrip.utils import ensure_directory, resolve_qos_override
from draco_roundtrip.net.protocol import (
    ConnectionClosed,
    Message,
    MSG_DATA,
    MSG_ERROR,
    recv_message,
    send_message,
)
from draco_roundtrip.ros.playback import start_playback_thread



def launch_bag_to_ply(args: argparse.Namespace) -> subprocess.Popen:
    cmd = [sys.executable, '-m', 'draco_roundtrip.io.bag_recorder',
           '--topic', args.topic,
           '--out', str(Path(args.ply_dir).resolve()),
           '--prefix', args.prefix,
           '--idle-timeout-sec', str(args.idle_timeout)]
    if args.best_effort:
        cmd.append('--best-effort')
    if args.max_frames:
        cmd += ['--max-frames', str(args.max_frames)]
    return subprocess.Popen(cmd, stdout=sys.stdout, stderr=sys.stderr)


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Streaming client with live playback")
    ap.add_argument('--bag', required=True)
    ap.add_argument('--topic', required=True)
    ap.add_argument('--prefix', required=True)
    ap.add_argument('--ply-dir', default='data/ply_stream')
    add_encoder_arguments(
        ap,
        hint_option='--encoder',
        hint_dest='encoder',
        extra_option='--encoder-extra',
        extra_dest='encoder_extra',
    )
    ap.add_argument('--idle-timeout', type=float, default=10.0)
    ap.add_argument('--max-frames', type=int, default=0)
    ap.add_argument('--best-effort', action='store_true')
    ap.add_argument('--work-dir', default='data/client_tmp')
    ap.add_argument('--decoded-dir', default='data/decoded_from_server')
    ap.add_argument('--server-host', default='127.0.0.1')
    ap.add_argument('--server-port', type=int, default=5000)
    ap.add_argument('--play-frame-id', default='lidar_link')
    ap.add_argument('--play-topic-prefix', default='stream_pair')
    ap.add_argument('--play-hz', type=float, default=10.0)
    ap.add_argument('--play-sample', type=int, default=50000)
    return ap


def main(argv: Iterable[str] | None = None) -> None:
    args = build_arg_parser().parse_args(argv)

    encoder_hint, encoder_options, _ = resolve_encoder_options(args)
    encoder_path = find_draco_encoder(encoder_hint)

    ply_dir = ensure_directory(Path(args.ply_dir).resolve())
    work_dir = ensure_directory(Path(args.work_dir).resolve())
    decoded_dir = ensure_directory(Path(args.decoded_dir).resolve())

    bag_cmd = ['ros2', 'bag', 'play', str(Path(args.bag).resolve())]
    qos_override = resolve_qos_override()
    if qos_override is not None:
        bag_cmd += ['--qos-profile-overrides-path', str(qos_override)]
    else:
        print('[CLIENT] WARN: QoS override file not found, falling back to recorded QoS', file=sys.stderr)
    bag_process = subprocess.Popen(bag_cmd)
    saver_proc = launch_bag_to_ply(args)

    to_play: queue.Queue = queue.Queue()
    playback_thread = start_playback_thread(to_play, args.play_frame_id, args.play_topic_prefix, args.play_hz)

    processed: Set[Path] = set()
    frame_idx = 0
    start_time = time.monotonic()
    bytes_sent = 0
    bytes_received = 0

    try:
        with socket.create_connection((args.server_host, args.server_port)) as sock:
            print(f"[CLIENT] Connected to {args.server_host}:{args.server_port}")
            try:
                while True:
                    new_files = sorted(ply_dir.glob(f"{args.prefix}_*.ply"))
                    for ply_path in new_files:
                        if ply_path in processed:
                            continue
                        try:
                            result = encode_frame(ply_path, work_dir, encoder_options,
                                                   encoder_hint=encoder_path, skip_existing=False)
                            drc_bytes = result.output.read_bytes()
                        except Exception as exc:
                            print(f"[CLIENT] ENCODE FAIL {ply_path.name}: {exc}")
                            processed.add(ply_path)
                            continue
                        print(format_encode_log(result, source=ply_path, prefix='[CLIENT][ENCODER]'))
                        message = Message(kind=MSG_DATA, name=ply_path.stem, payload=drc_bytes)
                        send_message(sock, message)
                        bytes_sent += len(drc_bytes)
                        print(f"[CLIENT] Sent {ply_path.name} ({len(drc_bytes)} bytes)")

                        reply = recv_message(sock)
                        if reply is None:
                            print("[CLIENT] Server closed connection")
                            raise ConnectionClosed("server closed")
                        if reply.kind == MSG_ERROR:
                            detail = reply.payload.decode(errors='ignore')
                            print(f"[CLIENT] SERVER ERROR for {ply_path.name}: {reply.name} -> {detail}")
                            processed.add(ply_path)
                            continue
                        bytes_received += len(reply.payload)

                        reply_name = reply.name or f"{ply_path.stem}.decoded"
                        if not reply_name.endswith('.ply'):
                            reply_name = f"{reply_name}.ply"
                        decoded_path = decoded_dir / reply_name
                        decoded_path.write_bytes(reply.payload)

                        pts_src = load_xyz(ply_path)
                        pts_dec = load_xyz_from_bytes(reply.payload)
                        metrics = compute_basic_metrics(pts_src, pts_dec, args.play_sample)
                        print(
                            f"[CLIENT] Frame {frame_idx:05d} metrics — "
                            f"Δpts={metrics['diff']} centroid_norm={metrics['centroid_norm']:.3f} "
                            f"bboxΔ=({metrics['bbox_delta'][0]:+.3f},{metrics['bbox_delta'][1]:+.3f},{metrics['bbox_delta'][2]:+.3f}) "
                            f"Chamfer(mean/max)={metrics['chamfer_mean']}/{metrics['chamfer_max']}"
                        )
                        to_play.put((frame_idx, ply_path.stem, pts_src, pts_dec))
                        processed.add(ply_path)
                        frame_idx += 1
                    time.sleep(0.1)
            except ConnectionClosed:
                print('[CLIENT] Connection closed, stopping loop')
    finally:
        to_play.put(None)
        if playback_thread.is_alive():
            playback_thread.join(timeout=1.0)
        for proc, name in ((bag_process, 'ros2 bag'), (saver_proc, 'bag_to_ply')):
            if proc and proc.poll() is None:
                proc.terminate()
        elapsed = max(time.monotonic() - start_time, 1e-6)
        print('[CLIENT] ---- Transfer summary ----')
        print(f"  elapsed: {elapsed:.2f} s")
        print(f"  sent: {bytes_sent} bytes ({bytes_sent * 8 / elapsed / 1e6:.3f} Mbps)")
        print(f"  received: {bytes_received} bytes ({bytes_received * 8 / elapsed / 1e6:.3f} Mbps)")


if __name__ == '__main__':
    main()
