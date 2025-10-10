from __future__ import annotations

import argparse
from pathlib import Path

from draco_tools.core.encoder import (
    EncodeResult,
    add_encoder_arguments,
    format_encode_log,
    resolve_encoder_options,
)


def test_resolve_encoder_options_defaults() -> None:
    parser = argparse.ArgumentParser()
    add_encoder_arguments(parser)
    args = parser.parse_args([])

    hint, options, skip = resolve_encoder_options(args)

    assert hint is None
    assert options.compress_level == 8
    assert options.position_quantization_bits == 12
    assert options.generic_quantization_bits == 10
    assert options.extra_args == ()
    assert skip is False


def test_resolve_encoder_options_with_skip_toggle() -> None:
    parser = argparse.ArgumentParser()
    add_encoder_arguments(
        parser,
        skip_options=("--skip-existing", "--no-skip-existing"),
        skip_default=True,
    )

    args_default = parser.parse_args([])
    _, _, skip_default = resolve_encoder_options(args_default)
    assert skip_default is True

    args_disable = parser.parse_args(["--no-skip-existing"])
    _, _, skip_disabled = resolve_encoder_options(args_disable)
    assert skip_disabled is False


def test_format_encode_log_variants(tmp_path: Path) -> None:
    out_file = tmp_path / "frame_001.drc"
    result = EncodeResult(output=out_file, duration=0.432, skipped=False)
    skipped_result = EncodeResult(output=out_file, duration=0.0, skipped=True)

    ok_line = format_encode_log(result, source=Path("frame_001.ply"), prefix="[CLI]")
    assert ok_line.startswith("[CLI] OK frame_001.ply -> frame_001.drc (")
    assert ok_line.endswith("s)")

    skip_line = format_encode_log(skipped_result, source=Path("frame_001.ply"))
    assert "cached" in skip_line
