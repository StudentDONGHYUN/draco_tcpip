"""Batch encoder CLI that reuses shared core helpers."""

from __future__ import annotations

import argparse
import csv
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Iterable

from draco_tools.core.encoder import EncoderOptions, EncodeResult, encode_frame, find_draco_encoder


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Batch encode PLY -> Draco (.drc)")
    ap.add_argument("--in", dest="indir", default="./ply_raw", help="입력 PLY 디렉터리 (기본: ./ply_raw)")
    ap.add_argument("--out", dest="outdir", default="./draco_out", help="출력 DRC 디렉터리 (기본: ./draco_out)")
    ap.add_argument("--name", required=False, help="대상 접두어(prefix). 지정 시 '<name>_*.ply'만 인코딩")
    ap.add_argument("--draco", dest="draco_hint", default=None, help="draco_encoder 경로(파일/디렉토리)")
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 4, help="병렬 작업 수")
    ap.add_argument("--cl", type=int, default=8, help="-cl compress level")
    ap.add_argument("--qp", type=int, default=12, help="-qp position quantization bits")
    ap.add_argument("--qg", type=int, default=10, help="-qg generic quantization bits")
    ap.add_argument("--skip-existing", action="store_true", default=True, help="이미 존재하는 .drc는 건너뜀")
    ap.add_argument("--no-skip-existing", dest="skip_existing", action="store_false", help="기존 파일도 다시 인코딩")
    ap.add_argument("--extra", nargs=argparse.REMAINDER, default=[], help="draco_encoder에 그대로 넘길 추가 인자")
    ap.add_argument("--log-csv", default=None, help="프레임별 인코드 시간 로그 CSV")
    return ap


def _collect_inputs(indir: Path, prefix: str | None) -> list[Path]:
    pattern = f"{prefix}_*.ply" if prefix else "*.ply"
    return sorted(indir.glob(pattern))


def _encode_one(ply: Path, outdir: Path, options: EncoderOptions,
                encoder_hint: str | None, skip_existing: bool) -> tuple[Path, EncodeResult]:
    result = encode_frame(ply, outdir, options, encoder_hint=encoder_hint, skip_existing=skip_existing)
    return ply, result


def main(argv: Iterable[str] | None = None) -> None:
    args = build_arg_parser().parse_args(argv)

    indir = Path(args.indir).expanduser().resolve()
    outdir = Path(args.outdir).expanduser().resolve()
    outdir.mkdir(parents=True, exist_ok=True)

    log_path = Path(args.log_csv).expanduser().resolve() if args.log_csv else None
    if log_path:
        log_path.parent.mkdir(parents=True, exist_ok=True)

    encoder_path = find_draco_encoder(args.draco_hint)
    options = EncoderOptions(
        compress_level=args.cl,
        position_quantization_bits=args.qp,
        generic_quantization_bits=args.qg,
        extra_args=tuple(args.extra),
    )

    ply_files = _collect_inputs(indir, args.name)
    if not ply_files:
        hint = f"{indir} (prefix='{args.name}')" if args.name else f"{indir}"
        print(f"[WARN] 대상 PLY가 없습니다: {hint}")
        return

    print(f"[INFO] encoder: {encoder_path}")
    print(f"[INFO] in : {indir} (총 {len(ply_files)}개, prefix={args.name or 'ALL'})")
    print(f"[INFO] out: {outdir}")
    print(f"[INFO] opts: -cl {options.compress_level} -qp {options.position_quantization_bits} -qg {options.generic_quantization_bits}  workers={args.workers}  skip_existing={args.skip_existing}")
    if options.extra_args:
        print(f"[INFO] extra args -> {' '.join(options.extra_args)}")

    timings: list[tuple[str, float]] = []
    ok = fail = skipped = 0

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = [executor.submit(_encode_one, ply, outdir, options, encoder_path, args.skip_existing)
                   for ply in ply_files]
        for fut in as_completed(futures):
            try:
                ply, result = fut.result()
            except Exception as exc:  # noqa: BLE001
                fail += 1
                print(f"[ERR]  {ply.name} -> {exc}", file=sys.stderr)
                continue

            out_path = result.output
            if result.skipped:
                skipped += 1
                print(f"[SKIP] {out_path.name}")
            else:
                ok += 1
                timings.append((out_path.stem, result.duration))
                print(f"[OK]   {out_path.name} ({result.duration:.3f} s)")

    print(f"\n[SUMMARY] 성공 {ok}  건너뜀 {skipped}  실패 {fail}  (총 {len(ply_files)})")

    if log_path and timings:
        timings.sort(key=lambda item: int(item[0].split('_')[-1]) if item[0].split('_')[-1].isdigit() else item[0])
        with log_path.open('w', newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(['name', 'encode_s'])
            for stem, duration in timings:
                writer.writerow([stem, duration])
        print(f"[LOG] encode timings -> {log_path}")

    if fail:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
