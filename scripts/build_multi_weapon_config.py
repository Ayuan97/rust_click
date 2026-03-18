#!/usr/bin/env python3
import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional


RUNTIME_REG_LITERALS = {1000, 2000, 3000, 4000, 5000, 6000, 7000, 8000}


def parse_int(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer, got bool")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value, 0)
    raise ValueError(f"{name} must be int or numeric string, got {type(value).__name__}")


def parse_usage(value: Any, name: str) -> int:
    usage = parse_int(value, name)
    if usage < 0 or usage > 0xFFFFFFFF:
        raise ValueError(f"{name} out of range: {usage}")
    return usage


def parse_reg_literal(value: Any, name: str) -> int:
    reg = parse_int(value, name)
    if reg < 1000 or reg % 1000 != 0:
        raise ValueError(f"{name} must be register literal 1000*n, got {reg}")
    if reg in RUNTIME_REG_LITERALS:
        raise ValueError(f"{name} collides with runtime register literals {sorted(RUNTIME_REG_LITERALS)}")
    return reg


def arr30(name: str, value: Any) -> List[int]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be an array")
    if len(value) != 30:
        raise ValueError(f"{name} must have exactly 30 values, got {len(value)}")
    out: List[int] = []
    for i, item in enumerate(value):
        out.append(parse_int(item, f"{name}[{i}]"))
    return out


def build_lookup(values: List[int], reg_usage: int = 1000) -> str:
    # Maps reg1 shot index (1000..30000) to per-shot value (*1000 scale).
    # To stay within persisted-config limits, emit only indices that differ
    # from the most common default value instead of all 30 bullets.
    default_value = Counter(values).most_common(1)[0][0]
    cur = str(default_value * 1000)
    for shot_index in range(len(values), 0, -1):
        val = values[shot_index - 1]
        if val == default_value:
            continue
        idx = shot_index * reg_usage
        cur = f"{cur} 1000 recall {idx} eq swap {val * 1000} swap ifte"
    return cur


def usage_edge_expr(usage: int, modifier_usage: Optional[int] = None) -> str:
    edge_expr = f"0x{usage:08x} input_state_binary 0x{usage:08x} prev_input_state_binary 0 eq mul"
    if modifier_usage is None:
        return edge_expr
    return f"0x{modifier_usage:08x} input_state_binary {edge_expr} mul"


def select_by_weapon_expr(
    *,
    weapon_state_reg: int,
    weapons: List[Dict[str, Any]],
    value_key: str,
    default_expr: str,
) -> str:
    cur = default_expr
    default_expr_str = str(default_expr)
    for weapon in reversed(weapons):
        value_expr = str(weapon[value_key])
        if value_expr == default_expr_str:
            continue
        cond = f"{weapon_state_reg} recall {weapon['id_lit']} eq"
        cur = f"{cond} {value_expr} {cur} ifte"
    return cur


def most_common_weapon_value_expr(weapons: List[Dict[str, Any]], value_key: str) -> str:
    return Counter(str(weapon[value_key]) for weapon in weapons).most_common(1)[0][0]


def compile_expressions(cfg: Dict[str, Any], params: Dict[str, Any]) -> List[str]:
    global_cfg = params.get("global")
    weapons_cfg = params.get("weapons")
    if not isinstance(global_cfg, dict):
        raise ValueError("params.global must be an object")
    if not isinstance(weapons_cfg, list) or not weapons_cfg:
        raise ValueError("params.weapons must be a non-empty array")

    mode = str(global_cfg.get("mode", "")).lower()
    if mode != "weapon_select":
        raise ValueError("global.mode must be 'weapon_select'")

    fire_mode = str(global_cfg.get("fire_mode", "lmb_rmb")).lower()
    if fire_mode not in {"lmb_rmb", "lmb_only"}:
        raise ValueError("global.fire_mode must be lmb_rmb or lmb_only")

    scope_toggle_usage = parse_usage(global_cfg.get("scope_toggle_usage", "0x00070055"), "global.scope_toggle_usage")
    crouch_usage = parse_usage(global_cfg.get("crouch_usage", "0x000700e0"), "global.crouch_usage")
    select_modifier_usage_raw = global_cfg.get("select_modifier_usage")
    select_modifier_usage: Optional[int]
    if select_modifier_usage_raw in (None, ""):
        select_modifier_usage = None
    else:
        select_modifier_usage = parse_usage(select_modifier_usage_raw, "global.select_modifier_usage")
    weapon_off_usage = parse_usage(global_cfg.get("weapon_off_usage", "0x00090003"), "global.weapon_off_usage")
    default_weapon_id = parse_int(global_cfg.get("default_weapon_id", 0), "global.default_weapon_id")
    scope_state_reg = parse_reg_literal(global_cfg.get("scope_state_reg", 9000), "global.scope_state_reg")
    weapon_state_reg = parse_reg_literal(global_cfg.get("weapon_state_reg", 10000), "global.weapon_state_reg")
    if scope_state_reg == weapon_state_reg:
        raise ValueError("global.scope_state_reg and global.weapon_state_reg must be different")

    base_mult = parse_int(global_cfg.get("base_mult", 900), "global.base_mult")
    fov_comp = parse_int(global_cfg.get("fov_comp", 1076), "global.fov_comp")
    tune_mult_x = parse_int(global_cfg.get("tune_mult_x", 957), "global.tune_mult_x")
    tune_mult_y = parse_int(global_cfg.get("tune_mult_y", 957), "global.tune_mult_y")

    compiled_weapons: List[Dict[str, Any]] = []
    seen_ids = set()
    seen_select_usage = set()
    for idx, weapon in enumerate(weapons_cfg):
        if not isinstance(weapon, dict):
            raise ValueError(f"weapons[{idx}] must be an object")

        weapon_id = parse_int(weapon.get("id"), f"weapons[{idx}].id")
        if weapon_id <= 0:
            raise ValueError(f"weapons[{idx}].id must be > 0")
        if weapon_id in seen_ids:
            raise ValueError(f"duplicate weapon id: {weapon_id}")
        seen_ids.add(weapon_id)

        name = str(weapon.get("name", f"weapon_{weapon_id}"))
        select_usage = parse_usage(weapon.get("select_usage"), f"weapons[{idx}].select_usage")
        if select_usage in seen_select_usage:
            raise ValueError(f"duplicate select usage: 0x{select_usage:08x}")
        seen_select_usage.add(select_usage)

        shot_interval_us = parse_int(weapon.get("shot_interval_us"), f"weapons[{idx}].shot_interval_us")
        start_delay_us = parse_int(weapon.get("start_delay_us"), f"weapons[{idx}].start_delay_us")
        attack_us = parse_int(weapon.get("attack_us", 100000), f"weapons[{idx}].attack_us")
        if shot_interval_us <= 0:
            raise ValueError(f"weapons[{idx}].shot_interval_us must be > 0")
        if start_delay_us < 0:
            raise ValueError(f"weapons[{idx}].start_delay_us must be >= 0")
        if attack_us <= 0:
            raise ValueError(f"weapons[{idx}].attack_us must be > 0")

        scope_1x_mult = parse_int(weapon.get("scope_1x_mult", 1000), f"weapons[{idx}].scope_1x_mult")
        scope_8x_mult = parse_int(weapon.get("scope_8x_mult", 1000), f"weapons[{idx}].scope_8x_mult")
        stand_mult = parse_int(weapon.get("stand_mult", 1000), f"weapons[{idx}].stand_mult")
        crouch_mult = parse_int(weapon.get("crouch_mult", 1000), f"weapons[{idx}].crouch_mult")

        x_steps = arr30(f"weapons[{idx}].x_steps", weapon.get("x_steps"))
        y_steps = arr30(f"weapons[{idx}].y_steps", weapon.get("y_steps"))

        compiled_weapons.append(
            {
                "id": weapon_id,
                "id_lit": weapon_id * 1000,
                "name": name,
                "select_usage": select_usage,
                "select_edge_expr": usage_edge_expr(select_usage, select_modifier_usage),
                "shot_interval_us": shot_interval_us,
                "start_delay_us": start_delay_us,
                "attack_us": attack_us,
                "scope_1x_mult": scope_1x_mult,
                "scope_8x_mult": scope_8x_mult,
                "stand_mult": stand_mult,
                "crouch_mult": crouch_mult,
                "x_lookup": build_lookup(x_steps),
                "y_lookup": build_lookup(y_steps),
            }
        )

    if default_weapon_id not in seen_ids and default_weapon_id != 0:
        raise ValueError("global.default_weapon_id must be 0 or one of weapons[].id")
    default_weapon_lit = default_weapon_id * 1000

    # Per-weapon helper expressions.
    for weapon in compiled_weapons:
        weapon["scope_mult_expr"] = (
            f"{scope_state_reg} recall {weapon['scope_8x_mult']} {weapon['scope_1x_mult']} ifte"
        )
        weapon["stance_mult_expr"] = (
            f"0x{crouch_usage:08x} input_state_binary {weapon['crouch_mult']} {weapon['stand_mult']} ifte"
        )

    # Scope toggle state: 0=1x, 1000=8x
    scope_edge = usage_edge_expr(scope_toggle_usage)
    scope_next_expr = (
        f"{scope_edge} {scope_state_reg} recall 0 eq {scope_state_reg} recall ifte"
    )

    # Weapon select state: 0=off, id*1000=selected weapon.
    if default_weapon_lit == 0:
        select_fallback_expr = f"{weapon_state_reg} recall"
    else:
        # When register is 0, use configured default id.
        select_fallback_expr = (
            f"{weapon_state_reg} recall 0 eq {default_weapon_lit} {weapon_state_reg} recall ifte"
        )
    select_expr = select_fallback_expr
    for weapon in reversed(compiled_weapons):
        select_expr = f"{weapon['select_edge_expr']} {weapon['id_lit']} {select_expr} ifte"
    weapon_off_edge = usage_edge_expr(weapon_off_usage)
    weapon_next_expr = f"{weapon_off_edge} 0 {select_expr} ifte"

    interval_default_expr = most_common_weapon_value_expr(compiled_weapons, "shot_interval_us")
    start_delay_default_expr = most_common_weapon_value_expr(compiled_weapons, "start_delay_us")
    attack_default_expr = most_common_weapon_value_expr(compiled_weapons, "attack_us")
    scope_mult_default_expr = most_common_weapon_value_expr(compiled_weapons, "scope_mult_expr")
    stance_mult_default_expr = most_common_weapon_value_expr(compiled_weapons, "stance_mult_expr")
    x_lookup_default_expr = most_common_weapon_value_expr(compiled_weapons, "x_lookup")
    y_lookup_default_expr = most_common_weapon_value_expr(compiled_weapons, "y_lookup")

    interval_expr = select_by_weapon_expr(
        weapon_state_reg=weapon_state_reg,
        weapons=compiled_weapons,
        value_key="shot_interval_us",
        default_expr=interval_default_expr,
    )
    start_delay_expr = select_by_weapon_expr(
        weapon_state_reg=weapon_state_reg,
        weapons=compiled_weapons,
        value_key="start_delay_us",
        default_expr=start_delay_default_expr,
    )
    attack_expr = select_by_weapon_expr(
        weapon_state_reg=weapon_state_reg,
        weapons=compiled_weapons,
        value_key="attack_us",
        default_expr=attack_default_expr,
    )
    scope_mult_expr = select_by_weapon_expr(
        weapon_state_reg=weapon_state_reg,
        weapons=compiled_weapons,
        value_key="scope_mult_expr",
        default_expr=scope_mult_default_expr,
    )
    stance_mult_expr = select_by_weapon_expr(
        weapon_state_reg=weapon_state_reg,
        weapons=compiled_weapons,
        value_key="stance_mult_expr",
        default_expr=stance_mult_default_expr,
    )
    x_lookup_expr = select_by_weapon_expr(
        weapon_state_reg=weapon_state_reg,
        weapons=compiled_weapons,
        value_key="x_lookup",
        default_expr=x_lookup_default_expr,
    )
    y_lookup_expr = select_by_weapon_expr(
        weapon_state_reg=weapon_state_reg,
        weapons=compiled_weapons,
        value_key="y_lookup",
        default_expr=y_lookup_default_expr,
    )

    start_delay_reg = 11000
    interval_reg = 12000
    attack_reg = 13000
    combined_mult_reg = 14000

    expr1 = (
        f"{scope_next_expr} {scope_state_reg} store "
        f"{weapon_next_expr} {weapon_state_reg} store "
        f"{weapon_state_reg} recall 0 gt 1000 0 ifte dup 3000 store "
        f"{start_delay_expr} {start_delay_reg} store "
        f"{interval_expr} {interval_reg} store "
        f"{attack_expr} {attack_reg} store "
        f"{scope_mult_expr} {stance_mult_expr} mul 1000 div {combined_mult_reg} store"
    )

    if fire_mode == "lmb_only":
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
        f"5000 recall time 2000 recall sub {start_delay_reg} recall sub 0 max {interval_reg} recall div "
        "dup 1000 mod sub 1000 add 1000 30000 clamp 1000 ifte dup 1000 store"
    )
    expr6 = (
        f"time 2000 recall sub {start_delay_reg} recall sub 0 max {interval_reg} recall mod dup 4000 store"
    )

    expr7 = (
        f"{base_mult} {fov_comp} mul {tune_mult_x} mul 1000 div "
        f"{x_lookup_expr} mul {combined_mult_reg} recall mul 1000 div dup 7000 store "
        f"4000 recall 1000 add 1000 {attack_reg} recall clamp swap mul 100000 div round "
        f"4000 recall 1000 {attack_reg} recall clamp 7000 recall mul 100000 div round sub "
        f"5000 recall 4000 recall {attack_reg} recall lt mul mul"
    )
    expr8 = (
        f"{base_mult} {fov_comp} mul {tune_mult_y} mul 1000 div "
        f"{y_lookup_expr} mul {combined_mult_reg} recall mul 1000 div dup 8000 store "
        f"4000 recall 1000 add 1000 {attack_reg} recall clamp swap mul 100000 div round "
        f"4000 recall 1000 {attack_reg} recall clamp 8000 recall mul 100000 div round sub "
        f"5000 recall 4000 recall {attack_reg} recall lt mul mul"
    )

    exprs = cfg.get("expressions", [""] * 8)
    while len(exprs) < 8:
        exprs.append("")
    exprs[0] = expr1
    exprs[1] = expr2
    exprs[2] = expr3
    # Keep expression 4 unchanged from base config.
    exprs[4] = expr5
    exprs[5] = expr6
    exprs[6] = expr7
    exprs[7] = expr8
    return exprs


def collect_control_usages(params: Dict[str, Any]) -> List[int]:
    global_cfg = params.get("global")
    weapons_cfg = params.get("weapons")
    if not isinstance(global_cfg, dict):
        return []
    if not isinstance(weapons_cfg, list):
        weapons_cfg = []

    out: List[int] = []
    for key in ("scope_toggle_usage", "crouch_usage", "weapon_off_usage"):
        if key in global_cfg:
            out.append(parse_usage(global_cfg[key], f"global.{key}"))
    if "select_modifier_usage" in global_cfg and global_cfg["select_modifier_usage"] not in (None, ""):
        out.append(parse_usage(global_cfg["select_modifier_usage"], "global.select_modifier_usage"))
    for idx, weapon in enumerate(weapons_cfg):
        if isinstance(weapon, dict) and "select_usage" in weapon:
            out.append(parse_usage(weapon["select_usage"], f"weapons[{idx}].select_usage"))

    # Optional user-defined passthrough list.
    extra = global_cfg.get("extra_passthrough_usages")
    if isinstance(extra, list):
        for i, item in enumerate(extra):
            out.append(parse_usage(item, f"global.extra_passthrough_usages[{i}]"))

    seen = set()
    dedup: List[int] = []
    for usage in out:
        if usage not in seen:
            seen.add(usage)
            dedup.append(usage)
    return dedup


def ensure_identity_mapping(cfg: Dict[str, Any], usage: int) -> None:
    usage_hex = f"0x{usage:08x}"
    mapping = {
        "target_usage": usage_hex,
        "source_usage": usage_hex,
        "scaling": 1000,
        "layers": [0],
        "sticky": False,
        "tap": False,
        "hold": False,
        "source_port": 0,
        "target_port": 0,
    }

    mappings = cfg.get("mappings")
    if not isinstance(mappings, list):
        mappings = []

    exists = any(
        isinstance(m, dict)
        and str(m.get("source_usage", "")).lower() == usage_hex.lower()
        and str(m.get("target_usage", "")).lower() == usage_hex.lower()
        for m in mappings
    )
    if not exists:
        mappings.append(mapping)
    cfg["mappings"] = mappings


def main() -> None:
    parser = argparse.ArgumentParser(description="Build single HID config with keyboard weapon select")
    parser.add_argument("--in-json", default="data/configs/BASE_TEMPLATE.json")
    parser.add_argument("--params", default="data/params/wk.json")
    parser.add_argument("--out-json", default="data/configs/wk.json")
    args = parser.parse_args()

    in_json = Path(args.in_json)
    params_path = Path(args.params)
    out_json = Path(args.out_json)

    cfg = json.loads(in_json.read_text())
    params = json.loads(params_path.read_text())
    for usage in collect_control_usages(params):
        # Keep control keys/buttons working in-game even when used in expressions.
        ensure_identity_mapping(cfg, usage)
    cfg["expressions"] = compile_expressions(cfg, params)
    out_json.write_text(json.dumps(cfg, ensure_ascii=True, indent=2) + "\n")
    print(f"Wrote: {out_json}")


if __name__ == "__main__":
    main()
