#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
from typing import List


def build_lookup(values: List[int], reg_usage: int = 1000) -> str:
    # Returns expression that maps reg1 (1000..30000) -> per-bullet value (*1000 scale)
    cur = str(values[-1] * 1000)
    for i in range(len(values) - 1, 0, -1):
        val = values[i - 1] * 1000
        idx = i * reg_usage
        cur = f"{cur} 1000 recall {idx} eq swap {val} swap ifte"
    return cur


def arr30(name: str, v: List[int]) -> List[int]:
    if len(v) != 30:
        raise ValueError(f"{name} must contain exactly 30 items, got {len(v)}")
    return v


def parse_usage(value, default_hex: str) -> int:
    raw = default_hex if value is None else value
    if isinstance(raw, str):
        return int(raw, 0)
    return int(raw)


def parse_usage_list(value, default_hexes: List[str]) -> List[int]:
    raw = default_hexes if value is None else value
    if isinstance(raw, list):
        items = raw
    else:
        items = [raw]
    out: List[int] = []
    for item in items:
        if isinstance(item, str):
            out.append(int(item, 0))
        else:
            out.append(int(item))
    return out


def usage_any_pressed_expr(usages: List[int]) -> str:
    if not usages:
        return "0"
    expr = f"0x{usages[0]:08x} input_state_binary"
    for usage in usages[1:]:
        expr = f"{expr} 0x{usage:08x} input_state_binary add"
    return f"{expr} 0 gt"


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply AK per-step tuning to HID Remapper JSON")
    parser.add_argument("--in-json", default="data/configs/sorin_rust_fs_10_1_3_hid_ak_0_9_img_tuned_v2.json")
    parser.add_argument("--params", default="data/params/ak_tune_params.json")
    parser.add_argument("--out-json", default="data/configs/IMPORT_THIS_TO_HID.json")
    args = parser.parse_args()

    in_json = Path(args.in_json)
    params_path = Path(args.params)
    out_json = Path(args.out_json)

    cfg = json.loads(in_json.read_text())
    params = json.loads(params_path.read_text())

    base_mult = int(params.get("base_mult", 900))
    fov_comp = int(params.get("fov_comp", 1076))
    tune_mult_x = int(params.get("tune_mult_x", 940))
    tune_mult_y = int(params.get("tune_mult_y", 860))
    shot_interval_us = int(params.get("shot_interval_us", 133000))
    start_delay_us = int(params.get("start_delay_us", 5000))
    scope8x_toggle_usage = parse_usage(params.get("scope8x_toggle_usage"), "0x00070039")
    crouch_usage = parse_usage(params.get("crouch_usage"), "0x000700E0")
    scope_sidekey_8x_usage = parse_usage(params.get("scope_sidekey_8x_usage"), "0x00090004")
    scope_sidekey_1x_usage = parse_usage(params.get("scope_sidekey_1x_usage"), "0x00090005")
    scope_sidekey_8x_usages = parse_usage_list(
        params.get("scope_sidekey_8x_usages"), [f"0x{scope_sidekey_8x_usage:08x}"]
    )
    scope_sidekey_1x_usages = parse_usage_list(
        params.get("scope_sidekey_1x_usages"), [f"0x{scope_sidekey_1x_usage:08x}"]
    )
    # Registers are indexed in 1.000 steps (e.g. 1000 = reg1, 3000 = reg3).
    # Keep this on reg9 (9000): avoids reg1..reg8 collisions and works on older firmware too.
    scope_state_reg = int(params.get("scope_state_reg", 9000))
    if scope_state_reg < 1000 or scope_state_reg % 1000 != 0:
        raise ValueError("scope_state_reg must be a register literal like 9000/10000 (multiple of 1000)")
    if scope_state_reg in {1000, 2000, 3000, 4000, 5000, 6000, 7000, 8000}:
        raise ValueError("scope_state_reg collides with runtime registers (1000..8000), use 9000 or above")
    ak_scope_1x_mult = int(params.get("ak_scope_1x_mult", 1000))
    ak_scope_8x_mult = int(params.get("ak_scope_8x_mult", 6900))
    ak_scope_mode = str(params.get("ak_scope_mode", "toggle_capslock")).lower()
    if ak_scope_mode not in {"toggle_capslock", "force_1x", "force_8x", "sidekeys_8x_1x"}:
        raise ValueError("ak_scope_mode must be toggle_capslock/force_1x/force_8x/sidekeys_8x_1x")
    ak_fire_mode = str(params.get("ak_fire_mode", "lmb_rmb")).lower()
    if ak_fire_mode not in {"lmb_rmb", "lmb_only"}:
        raise ValueError("ak_fire_mode must be lmb_rmb/lmb_only")
    ak_stand_mult = int(params.get("ak_stand_mult", 1890))
    ak_crouch_mult = int(params.get("ak_crouch_mult", 1000))
    ak_stance_mode = str(params.get("ak_stance_mode", "auto")).lower()
    if ak_stance_mode not in {"auto", "force_crouch", "force_stand"}:
        raise ValueError("ak_stance_mode must be auto/force_crouch/force_stand")

    x_steps = arr30("x_steps", params["x_steps"])
    y_steps = arr30("y_steps", params["y_steps"])
    x_offsets = arr30("x_offsets", params.get("x_offsets", [0] * 30))
    y_offsets = arr30("y_offsets", params.get("y_offsets", [0] * 30))

    x_vals = [x + dx for x, dx in zip(x_steps, x_offsets)]
    y_vals = [y + dy for y, dy in zip(y_steps, y_offsets)]

    x_lookup = build_lookup(x_vals)
    y_lookup = build_lookup(y_vals)

    # Keep expression 4 unchanged; rebuild 1/2/3/5/6/7/8 from params.
    mode = params.get("mode", "always_on")
    if mode == "always_on":
        mode_expr = "1000"
    elif mode == "sidekey_4_or_5_on_m3_off":
        mode_expr = (
            "0x00090004 input_state_binary 0x00090005 input_state_binary add 0 gt "
            "1000 0x00090003 input_state_binary 0 3000 recall ifte ifte"
        )
    else:
        raise ValueError("mode must be 'always_on' or 'sidekey_4_or_5_on_m3_off'")

    if ak_scope_mode == "toggle_capslock":
        # Toggle scope-state register on CapsLock rising edge:
        # new_scope = edge ? (not old_scope) : old_scope
        scope_toggle_expr = (
            f"0x{scope8x_toggle_usage:08x} input_state_binary "
            f"0x{scope8x_toggle_usage:08x} prev_input_state_binary 0 eq mul "
            f"{scope_state_reg} recall 0 eq {scope_state_reg} recall ifte"
        )
        expr1 = f"{scope_toggle_expr} {scope_state_reg} store {mode_expr} dup 3000 store"
        scope_mult_expr = f"{scope_state_reg} recall {ak_scope_8x_mult} {ak_scope_1x_mult} ifte"
    elif ak_scope_mode == "sidekeys_8x_1x":
        # Latching side-key switch (no swap ops):
        # if any 1x sidekey is pressed -> state = 0
        # else if any 8x sidekey is pressed -> state = 1000
        # else keep previous state
        sidekey_1x_set = usage_any_pressed_expr(scope_sidekey_1x_usages)
        sidekey_8x_set = usage_any_pressed_expr(scope_sidekey_8x_usages)
        scope_state_expr = (
            f"{sidekey_1x_set} 0 "
            f"{sidekey_8x_set} 1000 {scope_state_reg} recall ifte "
            "ifte"
        )
        expr1 = f"{scope_state_expr} {scope_state_reg} store {mode_expr} dup 3000 store"
        scope_mult_expr = f"{scope_state_reg} recall {ak_scope_8x_mult} {ak_scope_1x_mult} ifte"
    elif ak_scope_mode == "force_8x":
        expr1 = f"{mode_expr} dup 3000 store"
        scope_mult_expr = str(ak_scope_8x_mult)
    else:
        expr1 = f"{mode_expr} dup 3000 store"
        scope_mult_expr = str(ak_scope_1x_mult)
    if ak_stance_mode == "force_crouch":
        stance_mult_expr = str(ak_crouch_mult)
    elif ak_stance_mode == "force_stand":
        stance_mult_expr = str(ak_stand_mult)
    else:
        stance_mult_expr = (
            f"0x{crouch_usage:08x} input_state_binary {ak_crouch_mult} {ak_stand_mult} ifte"
        )

    if ak_fire_mode == "lmb_only":
        expr2 = "0x00090001 input_state_binary 3000 recall 1000 eq mul dup 5000 store"
        expr3 = "0x00090001 prev_input_state_binary 3000 recall 1000 eq mul dup 6000 store"
    else:
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

    expr6 = f"time 2000 recall sub {start_delay_us} sub 0 max {shot_interval_us} mod dup 4000 store"

    expr7 = (
        f"{base_mult} {fov_comp} mul {tune_mult_x} mul 1000 div "
        f"{x_lookup} mul {scope_mult_expr} mul 1000 div {stance_mult_expr} mul 1000 div dup 7000 store "
        "4000 recall 1000 add 1000 100000 clamp swap mul 100000 div round "
        "4000 recall 1000 100000 clamp 7000 recall mul 100000 div round sub "
        "5000 recall 4000 recall 100000 lt mul mul"
    )

    expr8 = (
        f"{base_mult} {fov_comp} mul {tune_mult_y} mul 1000 div "
        f"{y_lookup} mul {scope_mult_expr} mul 1000 div {stance_mult_expr} mul 1000 div dup 8000 store "
        "4000 recall 1000 add 1000 100000 clamp swap mul 100000 div round "
        "4000 recall 1000 100000 clamp 8000 recall mul 100000 div round sub "
        "5000 recall 4000 recall 100000 lt mul mul"
    )

    exprs = cfg.get("expressions", [""] * 8)
    while len(exprs) < 8:
        exprs.append("")

    exprs[0] = expr1
    exprs[1] = expr2
    exprs[2] = expr3
    exprs[4] = expr5
    exprs[5] = expr6
    exprs[6] = expr7
    exprs[7] = expr8

    cfg["expressions"] = exprs

    out_json.write_text(json.dumps(cfg, ensure_ascii=True, indent=2) + "\n")

    print(f"Wrote: {out_json}")
    print("X values:", x_vals)
    print("Y values:", y_vals)
    print(f"scale: base={base_mult}, fov_comp={fov_comp}, x={tune_mult_x}, y={tune_mult_y}")
    print(
        "ak multipliers: "
        f"scope1x={ak_scope_1x_mult}, scope8x={ak_scope_8x_mult}, scope_mode={ak_scope_mode}, "
        f"fire_mode={ak_fire_mode}, stand={ak_stand_mult}, crouch={ak_crouch_mult}, "
        f"stance_mode={ak_stance_mode}"
    )
    if ak_scope_mode == "toggle_capslock" and ak_stance_mode == "auto":
        print(
            f"toggle/crouch usages: scope8x=0x{scope8x_toggle_usage:08x}, "
            f"crouch=0x{crouch_usage:08x}"
        )
    elif ak_scope_mode == "sidekeys_8x_1x" and ak_stance_mode == "auto":
        print(
            f"sidekeys/crouch usages: scope8x=0x{scope_sidekey_8x_usage:08x}, "
            f"scope1x=0x{scope_sidekey_1x_usage:08x}, crouch=0x{crouch_usage:08x}"
        )
    elif ak_scope_mode == "toggle_capslock":
        print(f"toggle usage: scope8x=0x{scope8x_toggle_usage:08x}")
    elif ak_scope_mode == "sidekeys_8x_1x":
        print(
            "sidekeys usage: "
            f"scope8x_primary=0x{scope_sidekey_8x_usage:08x}, "
            f"scope1x_primary=0x{scope_sidekey_1x_usage:08x}, "
            f"scope8x_all={[hex(u) for u in scope_sidekey_8x_usages]}, "
            f"scope1x_all={[hex(u) for u in scope_sidekey_1x_usages]}"
        )
    elif ak_stance_mode == "auto":
        print(f"crouch usage: 0x{crouch_usage:08x}")
    else:
        print("no keyboard usage dependency in expression")
    print(f"timing: interval={shot_interval_us}us, start_delay={start_delay_us}us")


if __name__ == "__main__":
    main()
