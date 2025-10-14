#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PLY(original) vs DRC(Draco) 품질/성능 비교 (멀티코어 + 진행바 강화판)

기능
- drc 디렉토리의 .drc 를 DracoPy 로 메모리상 디코딩(요청 시에만 .ply 저장)
- 원본 ply 와 1:1 매칭하여 기하 오차(양방향 최근접거리 기반, Chamfer-like),
  파일 크기/압축배율, 디코드 시간/디코드 FPS 계산
- (옵션) voxel 다운샘플, 통계적 아웃라이어 제거, 무작위 샘플링
- 임계치(예: 0.01/0.03/0.05m) 통과율 계산
- 결과 CSV + 요약 MD + 누락/불일치 진단

사용 예)
  cd ~/draco-ros2-roundtrip
  python3 analysis/analyze_draco_quality.py \
    --ply_dir data/ply_raw \
    --drc_dir data/draco_out \
    --decoded_dir data/tmp_decoded_ply \
    --results_dir data/results \
    --prefix sample2 \
    --thresholds 0.01 0.03 0.05 \
    --decode-workers 8 \
    --metric-workers 8 \
    --force-tqdm

참고
- Open3D 설치 권장: pip install open3d
"""

from __future__ import annotations

import argparse
import io
import re
import sys
import time
import csv
import math
from pathlib import Path
from datetime import datetime
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np

# 선택 의존성
_HAVE_TQDM = False
_HAVE_O3D  = False
try:
    from tqdm import tqdm  # type: ignore
    _HAVE_TQDM = True
except Exception:
    pass

try:
    import open3d as o3d  # type: ignore
    _HAVE_O3D = True
except Exception:
    pass

from plyfile import PlyData, PlyElement  # type: ignore

from draco_roundtrip.draco._draco_adapter import decode_points_np
from draco_roundtrip.io.ply_codec import load_xyz, voxel_downsample
from draco_tools.analysis.quality import summarize_pair


# ---------- 유틸 ----------
def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)
    sys.stderr.flush()


def ensure_dir(d: Path):
    d.mkdir(parents=True, exist_ok=True)


def find_pairs(ply_dir: Path, drc_dir: Path, prefix: str) -> List[Tuple[Path, Path, str]]:
    """
    prefix_0000000000.ply ↔ prefix_0000000000.drc 형태 매칭
    반환: [(ply_path, drc_path, stem), ...]  where stem = 'prefix_##########'
    """
    pat = re.compile(rf"^{re.escape(prefix)}_(\d+)\.(ply|drc)$")
    ply_map: Dict[str, Path] = {}
    drc_map: Dict[str, Path] = {}

    for p in sorted(ply_dir.glob("*.ply")):
        m = pat.match(p.name)
        if m:
            ply_map[m.group(1)] = p

    for d in sorted(drc_dir.glob("*.drc")):
        m = pat.match(d.name)
        if m:
            drc_map[m.group(1)] = d

    idxs = sorted(set(ply_map.keys()) & set(drc_map.keys()), key=lambda x: int(x))
    return [(ply_map[i], drc_map[i], f"{prefix}_{i}") for i in idxs]


def parse_stat_outlier(s: Optional[str]) -> Optional[Tuple[int, float]]:
    """
    'k:20,nb_std:2.0' 또는 '20,2.0' 형태 지원
    None 또는 빈 문자열이면 사용 안 함
    """
    if not s:
        return None
    if "," in s:
        parts = s.split(",")
    elif ":" in s:
        parts = s.replace(" ", "").split(",")
    else:
        parts = s.split(",")

    k = None
    nb = None
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if ":" in p:
            key, val = p.split(":")
            key = key.strip().lower()
            val = val.strip()
            if key in ("k", "nn", "neighbors"):
                k = int(val)
            elif key in ("nb_std", "std", "sigma"):
                nb = float(val)
        else:
            # 위치기반: 첫번째 = k, 두번째 = nb_std
            if k is None:
                k = int(p)
            elif nb is None:
                nb = float(p)
    if k is None or nb is None:
        return None
    return (int(k), float(nb))


# ---------- 전처리/디코딩 ----------

def _preprocess_xyz(
    points: np.ndarray,
    voxel_size: Optional[float],
    stat_outlier: Optional[Tuple[int, float]],
    max_samples: Optional[int],
    seed: Optional[int],
) -> np.ndarray:
    arr = np.asarray(points, dtype=np.float32)
    if arr.ndim != 2 or arr.shape[1] < 3:
        raise ValueError(f"expected (N,3+) array, got {arr.shape!r}")
    if arr.shape[1] > 3:
        arr = arr[:, :3]

    if voxel_size and voxel_size > 0 and len(arr):
        arr = voxel_downsample(arr, voxel_size)

    if stat_outlier and len(arr):
        if _HAVE_O3D:
            k, nb_std = stat_outlier
            pcd = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(arr.astype(np.float64)))
            filtered, _ = pcd.remove_statistical_outlier(nb_neighbors=int(k), std_ratio=float(nb_std))
            arr = np.asarray(filtered.points, dtype=np.float32)
        else:
            eprint("[WARN] 통계적 아웃라이어 제거를 위해 open3d가 필요하지만 설치되어 있지 않습니다.")

    if max_samples and max_samples > 0 and len(arr) > max_samples:
        rng = np.random.default_rng(seed)
        idx = rng.choice(len(arr), size=max_samples, replace=False)
        arr = arr[idx]

    return np.ascontiguousarray(arr, dtype=np.float32)


def _metric_one(
    stem: str,
    src_pts: np.ndarray,
    dec_pts: np.ndarray,
    thresholds: Iterable[float],
    voxel_size: Optional[float],
    stat_outlier: Optional[Tuple[int, float]],
    max_samples: Optional[int],
    seed: Optional[int],
    src_name: str,
    decoded_label: str,
) -> Dict[str, object]:
    t_metric = time.perf_counter()
    try:
        src_proc = _preprocess_xyz(src_pts, voxel_size, stat_outlier, max_samples, seed)
        dec_proc = _preprocess_xyz(dec_pts, voxel_size, stat_outlier, max_samples, seed)

        if len(src_proc) == 0 or len(dec_proc) == 0:
            raise ValueError("empty cloud after preprocess")

        summary = summarize_pair(
            stem,
            src_proc,
            dec_proc,
            sample=max_samples or 0,
            thresholds=thresholds,
        )
        summary.update({
            "src": src_name,
            "drc_decoded": decoded_label,
            "metric_s": float(time.perf_counter() - t_metric),
        })
        return summary

    except Exception as ex:
        return {
            "name": stem,
            "src": src_name,
            "drc_decoded": decoded_label,
            "n_src": "",
            "n_dec": "",
            "mean_src_to_dec": "",
            "mean_dec_to_src": "",
            "chamfer_mean": "",
            "chamfer_med": "",
            "chamfer_rms": "",
            "hausdorff": "",
            **{f"pass_{t}m": "" for t in thresholds},
            "status": f"metric_fail: {type(ex).__name__}: {ex}",
            "metric_s": "",
        }


def _decode_drc_file(drc_path: Path) -> tuple[str, np.ndarray, float]:
    t0 = time.perf_counter()
    pts = decode_points_np(drc_path.read_bytes())
    dt = time.perf_counter() - t0
    return drc_path.stem, pts, dt


def _points_to_ply_bytes(points: np.ndarray) -> bytes:
    arr = np.asarray(points, dtype=np.float32)
    if arr.ndim != 2 or arr.shape[1] < 3:
        raise ValueError(f"expected (N,3+) array, got {arr.shape!r}")
    if arr.shape[1] > 3:
        arr = arr[:, :3]
    verts = np.zeros(arr.shape[0], dtype=[("x", "<f4"), ("y", "<f4"), ("z", "<f4")])
    verts["x"] = arr[:, 0]
    verts["y"] = arr[:, 1]
    verts["z"] = arr[:, 2]
    ply = PlyData([PlyElement.describe(verts, "vertex")], text=False)
    buf = io.BytesIO()
    ply.write(buf)
    return buf.getvalue()



# ---------- 메인 ----------
def main():
    ap = argparse.ArgumentParser(description="Draco 품질/성능 분석 (병렬 + 진행바)")
    ap.add_argument("--ply_dir", default="data/ply_raw", help="원본 PLY 디렉토리")
    ap.add_argument("--drc_dir", default="data/draco_out", help="DRC 디렉토리")
    ap.add_argument("--decoded_dir", default="data/tmp_decoded_ply", help="복원 PLY 저장 디렉토리")
    ap.add_argument("--results_dir", default="data/results", help="결과 저장 디렉토리")
    ap.add_argument("--prefix", required=True, help="파일 접두어 (예: sample2)")
    ap.add_argument("--thresholds", nargs="*", type=float, default=[0.01, 0.03, 0.05],
                    help="오차 임계치(m) 목록")
    ap.add_argument("--limit", type=int, default=0, help="0이면 전부, 아니면 앞에서 N개만")

    # 성능 옵션
    ap.add_argument("--decode-workers", type=int, default=1, help="DracoPy 디코드 병렬 작업 수")
    ap.add_argument("--metric-workers", type=int, default=1, help="품질 계산 병렬 프로세스 수")

    # 전처리 옵션
    ap.add_argument("--voxel-size", type=float, default=0.0, help="voxel 다운샘플 크기(m), 0=미사용")
    ap.add_argument("--stat-outlier", default=None,
                    help="통계적 아웃라이어 제거 설정 (예: 'k:20,nb_std:2.0' 또는 '20,2.0')")
    ap.add_argument("--max-samples", type=int, default=0, help="무작위 샘플링 최대 포인트 수(0=무제한)")
    ap.add_argument("--seed", type=int, default=None, help="샘플링 시드")
    ap.add_argument("--run-ts", default=None, help="결과 파일명에 사용할 타임스탬프(YYYYmmdd_HHMMSS)")

    # 기타
    ap.add_argument("--keep-decoded", action="store_true", help="디코드 PLY 유지")
    ap.add_argument("--no-tqdm", action="store_true", help="진행바 끄기")
    ap.add_argument("--force-tqdm", action="store_true", help="설치돼 있으면 진행바 강제 표시")

    args = ap.parse_args()

    ply_dir = Path(args.ply_dir).resolve()
    drc_dir = Path(args.drc_dir).resolve()
    dec_dir = Path(args.decoded_dir).resolve()
    res_dir = Path(args.results_dir).resolve()
    ensure_dir(dec_dir)
    ensure_dir(res_dir)

    # tqdm 사용 여부
    use_tqdm = _HAVE_TQDM and (args.force_tqdm or (not args.no_tqdm))

    # 페어 매칭
    pairs = find_pairs(ply_dir, drc_dir, args.prefix)
    if args.limit and args.limit > 0:
        pairs = pairs[: args.limit]
    if not pairs:
        eprint("[WARN] 매칭되는 (PLY, DRC) 쌍이 없습니다.")
        sys.exit(0)

    # 누락/불일치 진단용 집합
    ply_stems_all = {p.stem for p in ply_dir.glob(f"{args.prefix}_*.ply")}
    drc_stems_all = {d.stem for d in drc_dir.glob(f"{args.prefix}_*.drc")}
    matched_stems = {stem for _, _, stem in pairs}
    only_in_ply = sorted(ply_stems_all - matched_stems, key=lambda s: int(s.split("_")[-1]) if s.split("_")[-1].isdigit() else s)
    only_in_drc = sorted(drc_stems_all - matched_stems, key=lambda s: int(s.split("_")[-1]) if s.split("_")[-1].isdigit() else s)

    # 1) 디코딩 (병렬)
    dec_results: Dict[str, Dict[str, object]] = {}
    decoded_points: Dict[str, np.ndarray] = {}
    with ThreadPoolExecutor(max_workers=max(1, args.decode_workers)) as pool:
        if use_tqdm:
            pbar = tqdm(total=len(pairs), unit="file", desc="Decoding", leave=False)
        else:
            pbar = None

        future_map = {}
        for _, drc_path, stem in pairs:
            future = pool.submit(_decode_drc_file, drc_path)
            future_map[future] = (stem, drc_path)

        for fut in as_completed(future_map):
            stem, drc_path = future_map[fut]
            try:
                _, pts, dt = fut.result()
            except Exception as exc:  # noqa: BLE001
                dec_results[stem] = {
                    "decode_s": "",
                    "decode_fps": "",
                    "status": f"decode_fail: {exc}",
                }
                eprint(f"[ERR] 디코드 실패 {drc_path.name}: {exc}")
            else:
                decoded_points[stem] = pts
                dec_results[stem] = {
                    "decode_s": float(dt),
                    "decode_fps": (1.0 / dt) if dt > 0 else float("nan"),
                    "status": "ok",
                }
            if pbar:
                pbar.update(1)
        if pbar:
            pbar.close()

    # 2) 품질 계산 (병렬)
    stat_out = parse_stat_outlier(args.stat_outlier)
    metric_rows: List[Dict[str, object]] = []

    voxel_size = args.voxel_size if args.voxel_size > 0 else None
    max_samples = args.max_samples if args.max_samples > 0 else None
    decoded_label_template = "{stem}.decoded.ply" if args.keep_decoded else "in-memory"

    def _metric_job(stem: str, ply_src: Path, dec_pts: np.ndarray, decoded_label: str) -> Dict[str, object]:
        src_pts = load_xyz(ply_src)
        return _metric_one(
            stem,
            src_pts,
            dec_pts,
            args.thresholds,
            voxel_size,
            stat_out,
            max_samples,
            args.seed,
            ply_src.name,
            decoded_label,
        )

    with ThreadPoolExecutor(max_workers=max(1, args.metric_workers)) as pool:
        scheduled: Dict[Future, str] = {}
        if use_tqdm:
            pbar = tqdm(total=len(pairs), unit="pair", desc="Quality", leave=False)
        else:
            pbar = None

        for ply_path, _, stem in pairs:
            decoded = decoded_points.get(stem)
            decoded_label = decoded_label_template.format(stem=stem)
            if decoded is None:
                metric_rows.append(
                    {
                        "name": stem,
                        "src": ply_path.name,
                        "drc_decoded": decoded_label,
                        "status": dec_results.get(stem, {}).get("status", "decode_fail"),
                    }
                )
                if pbar:
                    pbar.update(1)
                continue
            fut = pool.submit(_metric_job, stem, ply_path, decoded, decoded_label)
            scheduled[fut] = stem

        for fut in as_completed(scheduled):
            stem = scheduled[fut]
            metric_rows.append(fut.result())
            if pbar:
                pbar.update(1)

        if pbar:
            pbar.close()

    # 3) 결과 합치기 + 크기/압축배율
    rows = []
    metric_map = {r.get("name"): r for r in metric_rows if r.get("name")}
    for ply_path, drc_path, stem in pairs:
        base = {
            "name": stem,
            "ply": ply_path.name,
            "drc": drc_path.name,
            "size_ply": ply_path.stat().st_size if ply_path.exists() else "",
            "size_drc": drc_path.stat().st_size if drc_path.exists() else "",
        }
        dec_info = dec_results.get(stem, {})
        base["decode_s"] = dec_info.get("decode_s", "")
        base["decode_fps"] = dec_info.get("decode_fps", "")
        if dec_info.get("status") and dec_info.get("status") != "ok":
            base["decode_status"] = dec_info["status"]
        metric = metric_map.get(stem)
        if metric:
            base.update(metric)
        else:
            base.setdefault("status", dec_info.get("status", "metric_missing"))

        if args.keep_decoded and stem in decoded_points:
            out_path = dec_dir / f"{stem}.decoded.ply"
            out_path.write_bytes(_points_to_ply_bytes(decoded_points[stem]))

        try:
            sz_p = float(base["size_ply"])
            sz_d = float(base["size_drc"])
            base["ratio_ply_over_drc"] = (sz_p / sz_d) if (sz_d > 0) else float("nan")
        except Exception:
            base["ratio_ply_over_drc"] = ""
        rows.append(base)

    decoded_points.clear()

    # 4) CSV 저장
    ts = args.run_ts if args.run_ts else datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = res_dir / f"quality_{args.prefix}_{ts}.csv"
    fieldnames = sorted({k for r in rows for k in r.keys()})
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in sorted(rows, key=lambda x: int(x["name"].split("_")[-1]) if x.get("name","").split("_")[-1].isdigit() else x.get("name","")):
            w.writerow(r)

    # 5) 요약 MD
    md_path = res_dir / f"summary_{args.prefix}_{ts}.md"

    def _flt_mean(col: str):
        vals = [r.get(col) for r in rows if isinstance(r.get(col), (int, float))]
        return float(np.mean(vals)) if vals else float("nan")

    def _flt_max(col: str):
        vals = [r.get(col) for r in rows if isinstance(r.get(col), (int, float))]
        return float(np.max(vals)) if vals else float("nan")

    def fmt(x): 
        return f"{x:.6g}" if isinstance(x, (int, float)) and math.isfinite(x) else "nan"

    n_all = len(rows)
    mean_ratio = _flt_mean("ratio_ply_over_drc")
    mean_decode_fps = _flt_mean("decode_fps")
    mean_chamfer = _flt_mean("chamfer_mean")
    haus_max = _flt_max("hausdorff")

    # 임계치 통과율 평균
    thr_lines = []
    for thr in args.thresholds:
        col = f"pass_{thr}m"
        vals = [r.get(col) for r in rows if isinstance(r.get(col), (int, float))]
        thr_lines.append(f"- 오차 ≤ {thr} m 비율(평균): {fmt(np.mean(vals)*100.0)} %")

    # 누락/불일치 진단
    diag = []
    if only_in_ply:
        diag.append(f"- PLY 전용({len(only_in_ply)}): " + ", ".join(only_in_ply[:10]) + (" ..." if len(only_in_ply) > 10 else ""))
    if only_in_drc:
        diag.append(f"- DRC 전용({len(only_in_drc)}): " + ", ".join(only_in_drc[:10]) + (" ..." if len(only_in_drc) > 10 else ""))

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"# Draco 품질/성능 요약 ({args.prefix})\n\n")
        f.write(f"- 샘플 수(매칭): {n_all}\n")
        f.write(f"- 평균 압축배율(PLY/DRC): {fmt(mean_ratio)}x\n")
        f.write(f"- 평균 디코드 FPS: {fmt(mean_decode_fps)}\n")
        f.write(f"- Chamfer 근사(mean): {fmt(mean_chamfer)} m\n")
        f.write(f"- Hausdorff 근사(max): {fmt(haus_max)} m\n")
        for line in thr_lines:
            f.write(line + "\n")
        f.write("\n## 누락/불일치 진단\n")
        if diag:
            for d in diag:
                f.write(d + "\n")
        else:
            f.write("- 불일치 없음\n")
        f.write(f"\n- CSV: `{csv_path}`\n")

    print(f"[OK] CSV  : {csv_path}")
    print(f"[OK] SUMM : {md_path}")
    print("[TIP] --decode-workers / --metric-workers 를 올리면 CPU 활용이 좋아집니다. "
          "Open3D 가속이 필수이니 미설치 시 `pip install open3d` 하세요.")


if __name__ == "__main__":
    # 출력 버퍼링 완화(프로그레스/로그 실시간)
    try:
        sys.stdout.reconfigure(line_buffering=True)
        sys.stderr.reconfigure(line_buffering=True)
    except Exception:
        pass
    main()
