"""
Generate x_steps / y_steps from game RecoilProperties extracted from content.bundle.

Usage:
    uv run python scripts/gen_steps_from_recoil.py
    uv run python scripts/gen_steps_from_recoil.py --jitter-x 2 --jitter-y 3
    uv run python scripts/gen_steps_from_recoil.py --jitter-x 2 --jitter-y 3 --seed 42

Reads  : data/recoil_parsed.json   (extracted from content.bundle)
Reads  : data/params/wk.json       (current weapon config)
Writes : data/params/wk.json       (updated x_steps / y_steps)
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RECOIL_JSON = Path(__file__).resolve().parent / "output" / "recoil_parsed.json"
WK_JSON = REPO / "data" / "params" / "wk.json"

# Map wk.json weapon name -> game RecoilProperties name
WEAPON_MAP = {
    "AK": "AR.Recoil",
    "MP5A4": "mp5Recoil",
    "SAR": "semiautorifle.recoil",
    "TOM": "ThompsonRecoil",
    "M249": "m249Recoil",
    "M39": "m39Recoil",
}

# Weapons with limited active shots (semi-auto etc.)
ACTIVE_SHOTS = {
    "SAR": 16,
    "M39": 20,
    "TOM": 19,
}

# Precise shot intervals (microseconds) based on RPM
SHOT_INTERVALS = {
    "AK": 133333,      # 450 RPM
    "MP5A4": 100000,    # 600 RPM
    "SAR": 174927,      # ~343 RPM (semi)
    "TOM": 129870,      # ~462 RPM
    "M249": 120000,     # 500 RPM
    "M39": 174927,      # ~343 RPM (semi)
}

NUM_SHOTS = 30

# Calibration: M249 has flat pitchCurve and simple recoil.
# Original M249 y_step ≈ 16, game avg pitch = |(-5 + -6) / 2| = 5.5
# scale = 16 / 5.5 ≈ 2.909
SCALE_FACTOR = 16.0 / 5.5


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def evaluate_curve(keys: list[dict], t: float) -> float:
    """Evaluate a Unity AnimationCurve at time t using linear interpolation."""
    if not keys:
        return 1.0
    if len(keys) == 1:
        return keys[0]["value"]
    if t <= keys[0]["time"]:
        return keys[0]["value"]
    if t >= keys[-1]["time"]:
        return keys[-1]["value"]
    for i in range(len(keys) - 1):
        t0, v0 = keys[i]["time"], keys[i]["value"]
        t1, v1 = keys[i + 1]["time"], keys[i + 1]["value"]
        if t0 <= t <= t1:
            if abs(t1 - t0) < 1e-9:
                return v0
            frac = (t - t0) / (t1 - t0)
            return lerp(v0, v1, frac)
    return keys[-1]["value"]


def compute_steps(
    recoil: dict,
    active_shots: int = NUM_SHOTS,
    *,
    jitter_x: int = 0,
    jitter_y: int = 0,
) -> tuple[list[int], list[int]]:
    """Compute x_steps and y_steps from a RecoilProperties entry."""
    pitch_min = recoil["recoilPitchMin"]
    pitch_max = recoil["recoilPitchMax"]
    yaw_min = recoil["recoilYawMin"]
    yaw_max = recoil["recoilYawMax"]

    pitch_curve = recoil.get("pitchCurve", [{"time": 0, "value": 1}, {"time": 1, "value": 1}])

    # Average expected recoil (these are negative = upward kick)
    avg_pitch = (pitch_min + pitch_max) / 2.0
    avg_yaw = (yaw_min + yaw_max) / 2.0

    x_steps: list[int] = []
    y_steps: list[int] = []

    for i in range(NUM_SHOTS):
        if i >= active_shots:
            x_steps.append(0)
            y_steps.append(0)
            continue

        # t normalized over active shots
        t = i / max(active_shots - 1, 1)
        pitch_scale = evaluate_curve(pitch_curve, t)

        # Pitch is negative (upward), compensation is positive (pull down)
        y_val = -avg_pitch * pitch_scale * SCALE_FACTOR
        # Yaw: positive = rightward recoil, compensation = negative (pull left)
        x_val = -avg_yaw * SCALE_FACTOR

        # Static jitter: random per-shot offset baked into the steps
        if jitter_x > 0:
            x_val += random.randint(-jitter_x, jitter_x)
        if jitter_y > 0:
            y_val += random.randint(-jitter_y, jitter_y)

        x_steps.append(int(round(x_val)))
        y_steps.append(int(round(y_val)))

    return x_steps, y_steps


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate x_steps/y_steps from game recoil data")
    ap.add_argument("--jitter-x", type=int, default=2, help="Static X jitter per shot (±N steps, default 2)")
    ap.add_argument("--jitter-y", type=int, default=3, help="Static Y jitter per shot (±N steps, default 3)")
    ap.add_argument("--seed", type=int, default=None, help="Random seed for reproducibility")
    args = ap.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    recoil_data = json.loads(RECOIL_JSON.read_text(encoding="utf-8"))
    wk = json.loads(WK_JSON.read_text(encoding="utf-8"))

    print(f"Scale factor: {SCALE_FACTOR:.3f}")
    print(f"Static jitter: X=±{args.jitter_x}, Y=±{args.jitter_y}, seed={args.seed}")
    print(f"{'Weapon':<8} {'Game Name':<25} {'Avg Pitch':>10} {'Avg Yaw':>9} {'Sum Y':>7} {'Sum X':>7}")
    print("-" * 75)

    for weapon in wk["weapons"]:
        name = weapon["name"]
        game_key = WEAPON_MAP.get(name)
        if game_key is None:
            print(f"  {name}: no mapping, skipped")
            continue

        recoil = recoil_data.get(game_key)
        if recoil is None:
            print(f"  {name}: game data '{game_key}' not found, skipped")
            continue

        active = ACTIVE_SHOTS.get(name, NUM_SHOTS)
        x_steps, y_steps = compute_steps(
            recoil, active,
            jitter_x=args.jitter_x,
            jitter_y=args.jitter_y,
        )

        weapon["x_steps"] = x_steps
        weapon["y_steps"] = y_steps

        # Update shot interval if we have a precise value
        if name in SHOT_INTERVALS:
            weapon["shot_interval_us"] = SHOT_INTERVALS[name]

        avg_pitch = (recoil["recoilPitchMin"] + recoil["recoilPitchMax"]) / 2
        avg_yaw = (recoil["recoilYawMin"] + recoil["recoilYawMax"]) / 2

        print(
            f"{name:<8} {game_key:<25} {avg_pitch:>10.2f} {avg_yaw:>9.2f} "
            f"{sum(y_steps):>7} {sum(x_steps):>7}"
        )
        print(f"  x_steps: {x_steps}")
        print(f"  y_steps: {y_steps}")

    WK_JSON.write_text(
        json.dumps(wk, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"\nWritten to: {WK_JSON}")


if __name__ == "__main__":
    main()
