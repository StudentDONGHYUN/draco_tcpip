"""Shared Draco encoder helpers for streaming and batch utilities."""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Sequence

__all__ = [
    "EncoderOptions",
    "EncodeResult",
    "find_draco_encoder",
    "encode_frame",
]


@dataclass(slots=True)
class EncoderOptions:
    compress_level: int = 8
    position_quantization_bits: int = 12
    generic_quantization_bits: int = 10
    extra_args: Sequence[str] = ()


@dataclass(slots=True)
class EncodeResult:
    output: Path
    duration: float
    skipped: bool = False


def _candidate_from_hint(hint: str | Path | None) -> Optional[Path]:
    if not hint:
        return None
    hint_path = Path(hint).expanduser().resolve()
    if hint_path.is_file():
        return hint_path
    candidate = hint_path / "draco_encoder"
    if candidate.exists():
        return candidate
    return None


def find_draco_encoder(hint: Optional[str | Path] = None) -> Path:
    path = _candidate_from_hint(hint)
    if path:
        return path

    env_hint = os.environ.get("DRACO_ENCODER")
    path = _candidate_from_hint(env_hint)
    if path:
        return path

    from shutil import which

    found = which("draco_encoder")
    if found:
        return Path(found).resolve()

    home = Path.home()
    fallbacks = [
        home / "draco" / "build" / "bin" / "draco_encoder",
        home / "draco" / "build" / "draco_encoder",
    ]
    for candidate in fallbacks:
        if candidate.exists():
            return candidate.resolve()

    raise FileNotFoundError("Cannot locate draco_encoder executable")


def _build_cmd(encoder: Path, src: Path, dest: Path, options: EncoderOptions) -> list[str]:
    cmd: list[str] = [
        str(encoder),
        "-i",
        str(src),
        "-o",
        str(dest),
        "-cl",
        str(options.compress_level),
        "-qp",
        str(options.position_quantization_bits),
        "-qg",
        str(options.generic_quantization_bits),
    ]
    if options.extra_args:
        cmd.extend(options.extra_args)
    return cmd


def encode_frame(src_ply: Path, out_dir: Path, options: EncoderOptions,
                 *, encoder_hint: Optional[str | Path] = None,
                 skip_existing: bool = False) -> EncodeResult:
    encoder = find_draco_encoder(encoder_hint)
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    out_path = out_dir / (src_ply.stem + ".drc")
    if skip_existing and out_path.exists():
        return EncodeResult(output=out_path, duration=0.0, skipped=True)

    cmd = _build_cmd(encoder, src_ply, out_path, options)
    # ensure encoder directory is on PATH so subprocess can locate dependencies
    os.environ["PATH"] = f"{encoder.parent}:{os.environ.get('PATH', '')}"

    start = time.perf_counter()
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    duration = time.perf_counter() - start
    if proc.returncode != 0:
        raise RuntimeError(
            f"draco_encoder failed (rc={proc.returncode})\nSTDOUT: {proc.stdout.strip()}\nSTDERR: {proc.stderr.strip()}"
        )
    return EncodeResult(output=out_path, duration=duration)
