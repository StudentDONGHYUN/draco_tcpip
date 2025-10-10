#!/usr/bin/env python3
"""Receive Draco .drc files over TCP, decode to PLY, send back to client."""

from __future__ import annotations

import argparse
import socket
import subprocess
import sys
import time
from contextlib import suppress
from pathlib import Path

from draco_roundtrip.utils import ensure_directory, resolve_executable
from draco_roundtrip.utils.protocol import (
    Message,
    MSG_DATA,
    MSG_EOF,
    MSG_ERROR,
    available_protocols,
    resolve_protocol,
)


def decode_drc(
    decoder: Path,
    drc_bytes: bytes,
    out_dir: Path,
    stem: str,
    *,
    timeout: float | None = None,
) -> bytes:
    ensure_directory(out_dir)
    drc_path = out_dir / f"{stem}.drc"
    ply_path = out_dir / f"{stem}.decoded.ply"
    drc_path.write_bytes(drc_bytes)
    cmd = [str(decoder), "-i", str(drc_path), "-o", str(ply_path)]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout if timeout and timeout > 0 else None,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"draco_decoder failed (rc={proc.returncode}):\n"
                f"STDOUT: {proc.stdout.strip()}\nSTDERR: {proc.stderr.strip()}"
            )
        return ply_path.read_bytes()
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"draco_decoder timed out after {exc.timeout:.1f}s"
        ) from exc
    finally:
        # NOTE: Clean up intermediate artifacts to keep long-lived servers tidy.
        with suppress(FileNotFoundError):
            drc_path.unlink()
        with suppress(FileNotFoundError):
            ply_path.unlink()


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Draco streaming server")
    ap.add_argument('--host', default='0.0.0.0')
    ap.add_argument('--port', type=int, default=5000)
    ap.add_argument('--decoder', default=None, help="Path to draco_decoder")
    ap.add_argument('--work-dir', default='data/server_tmp')
    ap.add_argument('--decode-timeout', type=float, default=30.0,
                    help='Fail decoding if the external tool exceeds this timeout (seconds)')
    ap.add_argument('--tcp-nodelay', action='store_true',
                    help='Disable Nagle aggregation on accepted sockets for lower latency')
    ap.add_argument('--socket-buffer-kb', type=int, default=0,
                    help='Resize socket send/receive buffers (KiB) for high-throughput links')
    protocol_help = available_protocols()
    ap.add_argument('--protocol',
                    choices=sorted(protocol_help.keys()),
                    default='binary',
                    help='Framing protocol expected from clients (default: %(default)s). Options: '
                    + ', '.join(f"{name}={desc}" for name, desc in protocol_help.items()))
    return ap


def main(argv: list[str] | None = None) -> None:
    args = build_arg_parser().parse_args(argv)

    decoder = resolve_executable('draco_decoder', args.decoder, env_var='DRACO_DECODER')
    work_dir = ensure_directory(Path(args.work_dir).resolve())

    start_time = time.monotonic()
    bytes_in = 0
    bytes_out = 0

    try:
        server = socket.create_server((args.host, args.port), reuse_port=True)
    except OSError as exc:
        # NOTE: Retry without SO_REUSEPORT for platforms lacking the option.
        print(f"[SERVER] WARN: reuse_port failed ({exc}), retrying without it")
        server = socket.create_server((args.host, args.port))

    with server:
        print(f"[SERVER] Listening on {args.host}:{args.port}")
        conn, addr = server.accept()
        print(f"[SERVER] Connection from {addr}")
        with conn:
            if args.tcp_nodelay:
                with suppress(OSError):
                    conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            if args.socket_buffer_kb > 0:
                buf_size = args.socket_buffer_kb * 1024
                for opt in (socket.SO_SNDBUF, socket.SO_RCVBUF):
                    with suppress(OSError):
                        conn.setsockopt(socket.SOL_SOCKET, opt, buf_size)
            protocol = resolve_protocol(args.protocol)
            print(f"[SERVER] Using {protocol.name} protocol for framing")
            while True:
                msg = protocol.recv(conn)
                if msg is None:
                    print("[SERVER] End of stream")
                    break
                if msg.kind == MSG_EOF:
                    print("[SERVER] Received EOF marker from client")
                    protocol.send(conn, Message(kind=MSG_EOF, name="", payload=b""))
                    break
                if msg.kind != MSG_DATA:
                    print(f"[SERVER] Ignoring unexpected message kind: {msg.kind}")
                    continue
                stem = msg.name or "frame"
                bytes_in += len(msg.payload)
                print(f"[SERVER] Received {stem} ({len(msg.payload)} bytes)")
                try:
                    ply_bytes = decode_drc(
                        decoder,
                        msg.payload,
                        work_dir,
                        stem,
                        timeout=args.decode_timeout,
                    )
                except Exception as exc:
                    error_msg = Message(kind=MSG_ERROR, name=stem, payload=str(exc).encode())
                    protocol.send(conn, error_msg)
                    print(f"[SERVER] ERROR decoding {stem}: {exc}")
                    continue
                reply = Message(kind=MSG_DATA, name=f"{stem}.decoded", payload=ply_bytes)
                protocol.send(conn, reply)
                bytes_out += len(ply_bytes)
                print(f"[SERVER] Sent {reply.name} ({len(ply_bytes)} bytes)")

    elapsed = max(time.monotonic() - start_time, 1e-6)
    total = bytes_in + bytes_out
    print("[SERVER] ---- Bandwidth summary ----")
    print(f"  elapsed: {elapsed:.2f} s")
    print(f"  inbound: {bytes_in} bytes ({bytes_in * 8 / elapsed / 1e6:.3f} Mbps)")
    print(f"  outbound: {bytes_out} bytes ({bytes_out * 8 / elapsed / 1e6:.3f} Mbps)")
    print(f"  total: {total} bytes ({total * 8 / elapsed / 1e6:.3f} Mbps)")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)

# 변경 요약:
# - 외부 draco_decoder 실행에 타임아웃을 적용하고, CLI 옵션으로 조정 가능하도록 했습니다.
# - TCP_NODELAY 및 버퍼 크기 조정 옵션을 추가해 스트림 지연과 처리량을 상황에 맞게 튜닝할 수 있게 했습니다.
