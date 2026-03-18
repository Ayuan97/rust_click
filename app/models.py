from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


WEAPON_FIELD_ORDER = (
    "id",
    "name",
    "select_usage",
    "shot_interval_us",
    "start_delay_us",
    "attack_us",
    "scope_1x_mult",
    "scope_8x_mult",
    "stand_mult",
    "crouch_mult",
    "x_steps",
    "y_steps",
)

GLOBAL_FIELD_ORDER = (
    "mode",
    "fire_mode",
    "scope_toggle_usage",
    "crouch_usage",
    "select_modifier_usage",
    "weapon_off_usage",
    "default_weapon_id",
    "scope_state_reg",
    "weapon_state_reg",
    "base_mult",
    "fov_comp",
    "tune_mult_x",
    "tune_mult_y",
)


def parse_int(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer, got bool")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value, 0)
    raise ValueError(f"{name} must be int or numeric string, got {type(value).__name__}")


def parse_optional_int(value: Any, name: str, default: int) -> int:
    if value in (None, ""):
        return default
    return parse_int(value, name)


def normalize_steps(value: Any, name: str) -> list[int]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a list")
    if len(value) != 30:
        raise ValueError(f"{name} must have exactly 30 values, got {len(value)}")
    return [parse_int(item, f"{name}[{index}]") for index, item in enumerate(value)]


@dataclass
class GlobalConfig:
    mode: str
    fire_mode: str
    scope_toggle_usage: Any
    crouch_usage: Any
    select_modifier_usage: Any
    weapon_off_usage: Any
    default_weapon_id: int
    scope_state_reg: int
    weapon_state_reg: int
    base_mult: int
    fov_comp: int
    tune_mult_x: int
    tune_mult_y: int
    extras: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "GlobalConfig":
        extras = {key: value for key, value in raw.items() if key not in GLOBAL_FIELD_ORDER}
        return cls(
            mode=str(raw.get("mode", "weapon_select")),
            fire_mode=str(raw.get("fire_mode", "lmb_rmb")),
            scope_toggle_usage=raw.get("scope_toggle_usage", "0x00070039"),
            crouch_usage=raw.get("crouch_usage", "0x000700E0"),
            select_modifier_usage=raw.get("select_modifier_usage", ""),
            weapon_off_usage=raw.get("weapon_off_usage", "0x00090003"),
            default_weapon_id=parse_optional_int(raw.get("default_weapon_id"), "global.default_weapon_id", 0),
            scope_state_reg=parse_optional_int(raw.get("scope_state_reg"), "global.scope_state_reg", 9000),
            weapon_state_reg=parse_optional_int(raw.get("weapon_state_reg"), "global.weapon_state_reg", 10000),
            base_mult=parse_optional_int(raw.get("base_mult"), "global.base_mult", 1000),
            fov_comp=parse_optional_int(raw.get("fov_comp"), "global.fov_comp", 1076),
            tune_mult_x=parse_optional_int(raw.get("tune_mult_x"), "global.tune_mult_x", 957),
            tune_mult_y=parse_optional_int(raw.get("tune_mult_y"), "global.tune_mult_y", 957),
            extras=extras,
        )

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "mode": self.mode,
            "fire_mode": self.fire_mode,
            "scope_toggle_usage": self.scope_toggle_usage,
            "crouch_usage": self.crouch_usage,
            "select_modifier_usage": self.select_modifier_usage,
            "weapon_off_usage": self.weapon_off_usage,
            "default_weapon_id": self.default_weapon_id,
            "scope_state_reg": self.scope_state_reg,
            "weapon_state_reg": self.weapon_state_reg,
            "base_mult": self.base_mult,
            "fov_comp": self.fov_comp,
            "tune_mult_x": self.tune_mult_x,
            "tune_mult_y": self.tune_mult_y,
        }
        data.update(self.extras)
        return data


@dataclass
class WeaponProfile:
    weapon_id: int
    name: str
    select_usage: Any
    shot_interval_us: int
    start_delay_us: int
    attack_us: int
    scope_1x_mult: int
    scope_8x_mult: int
    stand_mult: int
    crouch_mult: int
    x_steps: list[int]
    y_steps: list[int]
    extras: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "WeaponProfile":
        extras = {key: value for key, value in raw.items() if key not in WEAPON_FIELD_ORDER}
        return cls(
            weapon_id=parse_int(raw.get("id"), "weapon.id"),
            name=str(raw.get("name", "weapon")),
            select_usage=raw.get("select_usage"),
            shot_interval_us=parse_optional_int(raw.get("shot_interval_us"), "weapon.shot_interval_us", 100000),
            start_delay_us=parse_optional_int(raw.get("start_delay_us"), "weapon.start_delay_us", 5000),
            attack_us=parse_optional_int(raw.get("attack_us"), "weapon.attack_us", 100000),
            scope_1x_mult=parse_optional_int(raw.get("scope_1x_mult"), "weapon.scope_1x_mult", 1000),
            scope_8x_mult=parse_optional_int(raw.get("scope_8x_mult"), "weapon.scope_8x_mult", 1000),
            stand_mult=parse_optional_int(raw.get("stand_mult"), "weapon.stand_mult", 1000),
            crouch_mult=parse_optional_int(raw.get("crouch_mult"), "weapon.crouch_mult", 1000),
            x_steps=normalize_steps(raw.get("x_steps"), "weapon.x_steps"),
            y_steps=normalize_steps(raw.get("y_steps"), "weapon.y_steps"),
            extras=extras,
        )

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.weapon_id,
            "name": self.name,
            "select_usage": self.select_usage,
            "shot_interval_us": self.shot_interval_us,
            "start_delay_us": self.start_delay_us,
            "attack_us": self.attack_us,
            "scope_1x_mult": self.scope_1x_mult,
            "scope_8x_mult": self.scope_8x_mult,
            "stand_mult": self.stand_mult,
            "crouch_mult": self.crouch_mult,
            "x_steps": list(self.x_steps),
            "y_steps": list(self.y_steps),
        }
        data.update(self.extras)
        return data


@dataclass
class ParameterDocument:
    path: Path | None
    top_level_extras: dict[str, Any]
    global_config: GlobalConfig
    weapons: list[WeaponProfile]

    def to_dict(self) -> dict[str, Any]:
        data = dict(self.top_level_extras)
        data["global"] = self.global_config.to_dict()
        data["weapons"] = [weapon.to_dict() for weapon in self.weapons]
        return data

