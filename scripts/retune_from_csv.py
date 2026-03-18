#!/usr/bin/env python3
"""Auto-adjust AK offsets from a monitor CSV capture.

This script keeps the existing base tables and writes per-shot offsets so
manual retuning is faster and reproducible.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple


DEFAULT_X_USAGE = 0x00010030
DEFAULT_Y_USAGE = 0x00010031


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def median(values: Iterable[float], default: float) -> float:
    vals = list(values)
    if not vals:
        return default
    return float(statistics.median(vals))


def smooth_median3(values: Sequence[int]) -> List[int]:
    src = list(values)
    out: List[int] = []
    for i in range(len(src)):
        win = src[max(0, i - 1) : min(len(src), i + 2)]
        out.append(int(sorted(win)[len(win) // 2]))
    return out


def load_profile_from_csv(
    csv_path: Path,
    x_usage: int,
    y_usage: int,
    shot_interval_ms: int,
    start_delay_ms: int,
    compress_sparse: bool,
) -> List[Tuple[int, int]]:
    buckets: dict[int, list[int]] = defaultdict(lambda: [0, 0])

    with csv_path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            usage = int(row["usage_hex"], 16)
            if usage != x_usage and usage != y_usage:
                continue
            value = int(row["value"])
            elapsed_ms = int(row["elapsed_ms"])
            shot_idx = max(1, (max(0, elapsed_ms - start_delay_ms) // shot_interval_ms) + 1)
            if usage == x_usage:
                buckets[shot_idx][0] += value
            else:
                buckets[shot_idx][1] += value

    seq: List[Tuple[int, int]] = []
    if compress_sparse:
        for idx in sorted(buckets):
            x_sum, y_sum = buckets[idx]
            if x_sum == 0 and y_sum == 0:
                continue
            seq.append((x_sum, y_sum))
    else:
        if not buckets:
            return []
        max_idx = max(buckets)
        for idx in range(1, max_idx + 1):
            x_sum, y_sum = buckets.get(idx, [0, 0])
            seq.append((x_sum, y_sum))
    return seq


def main() -> int:
    parser = argparse.ArgumentParser(description="Auto-adjust AK offsets from monitor CSV")
    parser.add_argument("--csv", default="data/captures/monitor_lr_only.csv", help="Monitor CSV path")
    parser.add_argument("--params", default="data/params/ak_tune_params.json", help="Input params JSON")
    parser.add_argument("--out", default="data/params/ak_tune_params.json", help="Output params JSON")
    parser.add_argument("--x-usage", default=f"0x{DEFAULT_X_USAGE:08x}")
    parser.add_argument("--y-usage", default=f"0x{DEFAULT_Y_USAGE:08x}")
    parser.add_argument("--blend", type=float, default=0.35, help="Blend factor [0..1], higher = more aggressive")
    parser.add_argument("--scale-min", type=float, default=0.4)
    parser.add_argument("--scale-max", type=float, default=2.5)
    parser.add_argument("--min-y-step", type=int, default=8)
    parser.add_argument("--max-y-step", type=int, default=30)
    parser.add_argument("--max-abs-x-step", type=int, default=30)
    parser.add_argument(
        "--exact",
        action="store_true",
        help="Replay CSV-derived per-shot movement directly (no smoothing/scaling/blend)",
    )
    args = parser.parse_args()

    params_path = Path(args.params)
    out_path = Path(args.out)
    csv_path = Path(args.csv)

    params = json.loads(params_path.read_text(encoding="utf-8"))

    x_steps = list(params["x_steps"])
    y_steps = list(params["y_steps"])
    n = len(x_steps)
    if len(y_steps) != n:
        raise ValueError("x_steps and y_steps length mismatch")

    shot_interval_ms = max(1, int(params.get("shot_interval_us", 133000)) // 1000)
    start_delay_ms = max(0, int(params.get("start_delay_us", 5000)) // 1000)

    seq = load_profile_from_csv(
        csv_path=csv_path,
        x_usage=int(args.x_usage, 16),
        y_usage=int(args.y_usage, 16),
        shot_interval_ms=shot_interval_ms,
        start_delay_ms=start_delay_ms,
        compress_sparse=not args.exact,
    )
    if not seq:
        raise RuntimeError("No matching X/Y usage data found in CSV")

    if args.exact:
        while len(seq) < n:
            seq.append((0, 0))
        seq = seq[:n]

        raw_x = [x for x, _ in seq]
        raw_y = [y for _, y in seq]
        sx = 1.0
        sy = 1.0
        blend = 1.0
        target_x = [
            max(-args.max_abs_x_step, min(args.max_abs_x_step, v)) for v in raw_x
        ]
        target_y = [
            max(args.min_y_step, min(args.max_y_step, v)) for v in raw_y
        ]
        method = "exact"
    else:
        while len(seq) < n:
            seq.append(seq[-1])
        seq = seq[:n]

        raw_x = [x for x, _ in seq]
        raw_y = [y for _, y in seq]
        smooth_x = smooth_median3(raw_x)
        smooth_y = smooth_median3(raw_y)

        base_x_med = median((abs(v) for v in x_steps if v != 0), 1.0)
        base_y_med = median((v for v in y_steps if v > 0), 1.0)
        seq_x_med = median((abs(v) for v in smooth_x if v != 0), 1.0)
        seq_y_med = median((v for v in smooth_y if v > 0), 1.0)

        sx = clamp(base_x_med / seq_x_med, args.scale_min, args.scale_max)
        sy = clamp(base_y_med / seq_y_med, args.scale_min, args.scale_max)

        scaled_x = [int(round(v * sx)) for v in smooth_x]
        scaled_y = [int(round(v * sy)) for v in smooth_y]

        blend = clamp(args.blend, 0.0, 1.0)
        target_x = [
            max(-args.max_abs_x_step, min(0, int(round((1.0 - blend) * old + blend * new))))
            for old, new in zip(x_steps, scaled_x)
        ]
        target_y = [
            max(args.min_y_step, min(args.max_y_step, int(round((1.0 - blend) * old + blend * new))))
            for old, new in zip(y_steps, scaled_y)
        ]
        method = "conservative"

    x_offsets = [new - old for old, new in zip(x_steps, target_x)]
    y_offsets = [new - old for old, new in zip(y_steps, target_y)]

    params["x_offsets"] = x_offsets
    params["y_offsets"] = y_offsets
    params["notes"] = dict(params.get("notes", {}))
    params["notes"]["auto_tune_csv"] = str(csv_path)
    params["notes"]["auto_tune_blend"] = blend
    params["notes"]["auto_tune_scale_x"] = round(sx, 4)
    params["notes"]["auto_tune_scale_y"] = round(sy, 4)
    params["notes"]["auto_tune_method"] = method

    out_path.write_text(json.dumps(params, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")

    print(f"Wrote tuned params: {out_path}")
    print(f"Source shots used: {len(seq)}")
    print(f"Method: {method}")
    print(f"Scale factors: x={sx:.3f}, y={sy:.3f}, blend={blend:.2f}")
    print("x_offsets:", x_offsets)
    print("y_offsets:", y_offsets)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
