#!/usr/bin/env python3
import json
from pathlib import Path
from typing import Dict, List, Optional


def build_lookup(values: List[int], reg_usage: int = 1000) -> str:
    # Maps reg1 shot index (1000..30000) to the per-shot table value (*1000 scale).
    cur = str(values[-1] * 1000)
    for i in range(len(values) - 1, 0, -1):
        val = values[i - 1] * 1000
        idx = i * reg_usage
        cur = f"{cur} 1000 recall {idx} eq swap {val} swap ifte"
    return cur


def make_exprs(
    base_exprs: List[str],
    *,
    x_steps: List[int],
    y_steps: List[int],
    shot_interval_us: int,
    attack_us: int,
    start_delay_us: int,
    base_mult: int,
    fov_comp: int,
    tune_mult_x: int,
    tune_mult_y: int,
    crouch_mult: int,
    stand_mult: int,
    sidekey_mode: str = "stance",
    scope_1x_mult: int = 1000,
    scope_8x_mult: int = 1000,
    fire_key_usage: Optional[int] = None,
    fire_tap_window_us: int = 10000,
) -> List[str]:
    if len(x_steps) != 30 or len(y_steps) != 30:
        raise ValueError("x_steps/y_steps must each have exactly 30 values")

    x_lookup = build_lookup(x_steps)
    y_lookup = build_lookup(y_steps)

    # Side-key latch for stance:
    # Back(0x00090004) -> crouch(1000), Forward(0x00090005) -> stand(0)
    expr1 = (
        "0x00090005 input_state_binary 0 gt 0 "
        "0x00090004 input_state_binary 0 gt 1000 9000 recall ifte "
        "ifte 9000 store 1000 dup 3000 store"
    )

    # Keep trigger behavior: hold RMB then hold LMB.
    expr2 = (
        "0x00090002 input_state_binary 0x00090001 input_state_binary mul "
        "3000 recall 1000 eq mul dup 5000 store"
    )
    expr3 = (
        "0x00090002 prev_input_state_binary 0x00090001 prev_input_state_binary mul "
        "3000 recall 1000 eq mul dup 6000 store"
    )

    expr5 = (
        f"5000 recall time 2000 recall sub {start_delay_us} sub 0 max {shot_interval_us} div "
        "dup 1000 mod sub 1000 add 1000 30000 clamp 1000 ifte dup 1000 store"
    )
    if fire_key_usage is None:
        expr6 = f"time 2000 recall sub {start_delay_us} sub 0 max {shot_interval_us} mod dup 4000 store"
    else:
        # For semi-auto profiles (e.g. SAR), emit a short key pulse each shot:
        # reg10 = (phase < tap_window) * trigger
        expr6 = (
            f"time 2000 recall sub {start_delay_us} sub 0 max {shot_interval_us} mod "
            f"dup 4000 store {fire_tap_window_us} lt 5000 recall mul 10000 store"
        )

    if sidekey_mode == "stance":
        # 9000 register stores stance latch: crouch=1000, stand=0.
        stance_mult_expr = f"9000 recall {crouch_mult} {stand_mult} ifte"
        scope_mult_expr = "1000"
    elif sidekey_mode == "scope":
        # 9000 register stores scope latch: 8x=1000, normal=0.
        stance_mult_expr = str(crouch_mult)  # keep this profile on crouch baseline
        scope_mult_expr = f"9000 recall {scope_8x_mult} {scope_1x_mult} ifte"
    else:
        raise ValueError("sidekey_mode must be 'stance' or 'scope'")

    expr7 = (
        f"{base_mult} {fov_comp} mul {tune_mult_x} mul 1000 div "
        f"{x_lookup} mul {scope_mult_expr} mul 1000 div {stance_mult_expr} mul 1000 div dup 7000 store "
        f"4000 recall 1000 add 1000 {attack_us} clamp swap mul 100000 div round "
        f"4000 recall 1000 {attack_us} clamp 7000 recall mul 100000 div round sub "
        f"5000 recall 4000 recall {attack_us} lt mul mul"
    )

    expr8 = (
        f"{base_mult} {fov_comp} mul {tune_mult_y} mul 1000 div "
        f"{y_lookup} mul {scope_mult_expr} mul 1000 div {stance_mult_expr} mul 1000 div dup 8000 store "
        f"4000 recall 1000 add 1000 {attack_us} clamp swap mul 100000 div round "
        f"4000 recall 1000 {attack_us} clamp 8000 recall mul 100000 div round sub "
        f"5000 recall 4000 recall {attack_us} lt mul mul"
    )

    exprs = list(base_exprs)
    while len(exprs) < 8:
        exprs.append("")
    exprs[0] = expr1
    exprs[1] = expr2
    exprs[2] = expr3
    # expr4 stays unchanged from base.
    exprs[4] = expr5
    exprs[5] = expr6
    exprs[6] = expr7
    exprs[7] = expr8
    return exprs


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    base_cfg_path = root / "data" / "configs" / "BASE_TEMPLATE.json"
    tune_params_path = root / "data" / "params" / "ak_tune_params.json"

    base_cfg = json.loads(base_cfg_path.read_text(encoding="utf-8"))
    tune_params = json.loads(tune_params_path.read_text(encoding="utf-8"))

    base_mult = int(tune_params.get("base_mult", 900))
    fov_comp = int(tune_params.get("fov_comp", 1076))
    tune_mult_x = int(tune_params.get("tune_mult_x", 957))
    tune_mult_y = int(tune_params.get("tune_mult_y", 957))
    start_delay_us = int(tune_params.get("start_delay_us", 5000))
    stand_mult = int(tune_params.get("ak_stand_mult", 1890))
    crouch_mult = int(tune_params.get("ak_crouch_mult", 1000))

    # Values are derived from Sorin Lua offsets under FOV=90, sens=0.83/0.83,
    # then rounded into the same 30-shot integer table format used by this project.
    weapons: Dict[str, Dict[str, object]] = {
        "MP5A4": {
            "x_steps": [0] * 30,
            "y_steps": [9] * 26 + [8] * 4,
            "shot_interval_us": 100000,
            "attack_us": 100000,
            "out": root / "data" / "configs" / "IMPORT_MP5A4_SIDEKEY_STANCE.json",
        },
        "TOM": {
            "x_steps": [1, 0, 0, -1, -1, 1, -1, 0, -2, 0, 1, 0, -1, 1, 0, 1, 3, 1, 0] + [0] * 11,
            "y_steps": [8, 8, 8, 8, 7, 7, 8, 7, 7, 7, 7, 7, 7, 7, 7, 8, 7, 8, 7] + [0] * 11,
            "shot_interval_us": 129870,
            "attack_us": 100000,
            "out": root / "data" / "configs" / "IMPORT_TOM_SIDEKEY_STANCE.json",
        },
        "SAR": {
            "x_steps": [0] * 30,
            "y_steps": [13] * 16 + [0] * 14,
            "shot_interval_us": 174927,
            "attack_us": 145000,
            "fire_key_usage": 0x00070013,  # Keyboard 'P'
            "fire_tap_window_us": 10000,   # Match Lua PressKey("p")+Sleep(10)+ReleaseKey
            "out": root / "data" / "configs" / "IMPORT_SAR_SIDEKEY_STANCE.json",
        },
        "M249": {
            "x_steps": [0, -6] + ([-8] * 28),
            "y_steps": [12] + ([16] * 29),
            "shot_interval_us": 120000,
            "attack_us": 100000,
            "sidekey_mode": "scope",
            "scope_1x_mult": 1000,
            "scope_8x_mult": 7000,
            "out": root / "data" / "configs" / "IMPORT_M249_SIDEKEY_SCOPE.json",
        },
    }

    for name, cfg in weapons.items():
        out_path: Path = cfg["out"]  # type: ignore[assignment]
        out_cfg = json.loads(json.dumps(base_cfg))
        out_cfg["expressions"] = make_exprs(
            out_cfg.get("expressions", [""] * 8),
            x_steps=cfg["x_steps"],  # type: ignore[arg-type]
            y_steps=cfg["y_steps"],  # type: ignore[arg-type]
            shot_interval_us=int(cfg["shot_interval_us"]),
            attack_us=int(cfg["attack_us"]),
            start_delay_us=start_delay_us,
            base_mult=base_mult,
            fov_comp=fov_comp,
            tune_mult_x=tune_mult_x,
            tune_mult_y=tune_mult_y,
            crouch_mult=crouch_mult,
            stand_mult=stand_mult,
            sidekey_mode=str(cfg.get("sidekey_mode", "stance")),
            scope_1x_mult=int(cfg.get("scope_1x_mult", 1000)),
            scope_8x_mult=int(cfg.get("scope_8x_mult", 1000)),
            fire_key_usage=cfg.get("fire_key_usage"),  # type: ignore[arg-type]
            fire_tap_window_us=int(cfg.get("fire_tap_window_us", 10000)),
        )

        fire_key_usage = cfg.get("fire_key_usage")
        if fire_key_usage is not None:
            mappings = out_cfg.get("mappings", [])
            fire_map = {
                "target_usage": f"0x{int(fire_key_usage):08x}",
                "source_usage": "0xfff3000a",
                "scaling": 1000,
                "layers": [0],
                "sticky": False,
                "tap": False,
                "hold": False,
                "source_port": 0,
                "target_port": 0,
            }
            # Avoid duplicate insertion if this script is run repeatedly.
            if not any(
                m.get("source_usage") == fire_map["source_usage"] and m.get("target_usage") == fire_map["target_usage"]
                for m in mappings
            ):
                mappings.append(fire_map)
            out_cfg["mappings"] = mappings

        out_path.write_text(json.dumps(out_cfg, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote: {out_path}")


if __name__ == "__main__":
    main()
