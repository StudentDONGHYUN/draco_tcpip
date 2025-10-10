"""Compatibility layer exposing shared Draco encoder helpers and CLI bindings."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Sequence

from draco_roundtrip.draco import encoder as _encoder

EncoderOptions = _encoder.EncoderOptions
EncodeResult = _encoder.EncodeResult
find_draco_encoder = _encoder.find_draco_encoder
encode_frame = _encoder.encode_frame

__all__ = [
    "EncoderOptions",
    "EncodeResult",
    "EncoderCLIConfig",
    "add_encoder_arguments",
    "resolve_encoder_options",
    "format_encode_log",
    "find_draco_encoder",
    "encode_frame",
]

_ENCODER_CONFIG_ATTR = "_encoder_cli_config"


@dataclass(frozen=True)
class EncoderCLIConfig:
    """Metadata describing how encoder CLI arguments were registered."""

    hint_attr: str
    extra_attr: str
    skip_attr: str | None
    cl_attr: str = "cl"
    qp_attr: str = "qp"
    qg_attr: str = "qg"


def add_encoder_arguments(
    parser: argparse.ArgumentParser,
    *,
    hint_option: str = "--encoder",
    hint_dest: str = "encoder",
    extra_option: str = "--encoder-extra",
    extra_dest: str = "encoder_extra",
    skip_options: tuple[str, str] | None = None,
    skip_dest: str = "skip_existing",
    skip_default: bool = False,
    group_title: str = "Draco encoder options",
) -> EncoderCLIConfig:
    """Register standard Draco encoder CLI arguments on *parser*.

    Returns an :class:`EncoderCLIConfig` that can later be fed to
    :func:`resolve_encoder_options`.
    """

    group = parser.add_argument_group(group_title)
    if hint_option:
        group.add_argument(
            hint_option,
            dest=hint_dest,
            default=None,
            help="Path to the draco_encoder executable (overrides env lookup).",
        )
    group.add_argument(
        "--cl",
        dest="cl",
        type=int,
        default=8,
        help="Compression level passed to draco_encoder (-cl).",
    )
    group.add_argument(
        "--qp",
        dest="qp",
        type=int,
        default=12,
        help="Position quantisation bits passed to draco_encoder (-qp).",
    )
    group.add_argument(
        "--qg",
        dest="qg",
        type=int,
        default=10,
        help="Generic quantisation bits passed to draco_encoder (-qg).",
    )
    if extra_option:
        group.add_argument(
            extra_option,
            dest=extra_dest,
            nargs=argparse.REMAINDER,
            default=(),
            metavar="ARG",
            help="Additional raw arguments forwarded to draco_encoder.",
        )

    skip_attr: str | None = None
    if skip_options:
        enable_flag, disable_flag = skip_options
        group.add_argument(
            enable_flag,
            dest=skip_dest,
            action="store_true",
            default=skip_default,
            help="Skip frames that already have an encoded .drc output.",
        )
        group.add_argument(
            disable_flag,
            dest=skip_dest,
            action="store_false",
            help="Force re-encoding even when the .drc exists.",
        )
        skip_attr = skip_dest

    config = EncoderCLIConfig(hint_attr=hint_dest, extra_attr=extra_dest, skip_attr=skip_attr)
    parser.set_defaults(**{_ENCODER_CONFIG_ATTR: config})
    return config


def _as_tuple(extra: Iterable[str] | Sequence[str] | None) -> tuple[str, ...]:
    if not extra:
        return ()
    return tuple(str(item) for item in extra)


def resolve_encoder_options(
    args: argparse.Namespace,
    config: EncoderCLIConfig | None = None,
) -> tuple[Optional[str | Path], EncoderOptions, bool]:
    """Extract encoder hint/options/skip flags from *args*.

    The *config* emitted by :func:`add_encoder_arguments` is automatically
    looked up on *args* when omitted.
    """

    if config is None:
        config = getattr(args, _ENCODER_CONFIG_ATTR, None)
    if config is None:
        raise ValueError("Encoder CLI configuration metadata is not attached to the parsed arguments")

    hint = getattr(args, config.hint_attr, None)
    extra = _as_tuple(getattr(args, config.extra_attr, ()))
    options = EncoderOptions(
        compress_level=getattr(args, config.cl_attr),
        position_quantization_bits=getattr(args, config.qp_attr),
        generic_quantization_bits=getattr(args, config.qg_attr),
        extra_args=extra,
    )
    skip_existing = bool(getattr(args, config.skip_attr)) if config.skip_attr else False
    return hint, options, skip_existing


def format_encode_log(
    result: EncodeResult,
    *,
    source: Path | None = None,
    prefix: str = "[ENCODER]",
) -> str:
    """Produce a concise, shared log line for an encoder invocation."""

    src_name = source.name if source else result.output.stem
    status = "SKIP" if result.skipped else "OK"
    detail = "cached" if result.skipped else f"{result.duration:.3f}s"
    return f"{prefix} {status} {src_name} -> {result.output.name} ({detail})"

