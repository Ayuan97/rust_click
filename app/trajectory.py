from __future__ import annotations

from .models import GlobalConfig, WeaponProfile


def shot_numbers(count: int) -> list[int]:
    return list(range(1, count + 1))


def scale_factors(
    global_config: GlobalConfig,
    weapon: WeaponProfile,
    *,
    scope_mode: str,
    stance_mode: str,
) -> tuple[float, float]:
    scope_mult = weapon.scope_8x_mult if scope_mode == "8x" else weapon.scope_1x_mult
    stance_mult = weapon.crouch_mult if stance_mode == "crouch" else weapon.stand_mult

    x_scale = (
        global_config.base_mult
        * global_config.fov_comp
        * global_config.tune_mult_x
        * scope_mult
        * stance_mult
        / 1_000_000.0
    )
    y_scale = (
        global_config.base_mult
        * global_config.fov_comp
        * global_config.tune_mult_y
        * scope_mult
        * stance_mult
        / 1_000_000.0
    )
    return x_scale, y_scale


def scaled_step_series(
    global_config: GlobalConfig,
    weapon: WeaponProfile,
    *,
    scope_mode: str,
    stance_mode: str,
) -> tuple[list[float], list[float]]:
    x_scale, y_scale = scale_factors(
        global_config,
        weapon,
        scope_mode=scope_mode,
        stance_mode=stance_mode,
    )

    return (
        [value * x_scale for value in weapon.x_steps],
        [value * y_scale for value in weapon.y_steps],
    )


def cumulative_path(x_values: list[float], y_values: list[float]) -> tuple[list[float], list[float]]:
    total_x = 0.0
    total_y = 0.0
    path_x = [0.0]
    path_y = [0.0]
    for x_value, y_value in zip(x_values, y_values):
        total_x += x_value
        total_y += y_value
        path_x.append(total_x)
        path_y.append(total_y)
    return path_x, path_y


def apply_delta(values: list[int], rows: list[int], delta: int) -> list[int]:
    out = list(values)
    for row in rows:
        out[row] += delta
    return out


def smooth_rows(values: list[int], rows: list[int]) -> list[int]:
    out = list(values)
    source = list(values)
    for row in rows:
        lo = max(0, row - 1)
        hi = min(len(source) - 1, row + 1)
        window = source[lo : hi + 1]
        out[row] = int(round(sum(window) / len(window)))
    return out


def scale_rows(values: list[int], rows: list[int], factor: float) -> list[int]:
    out = list(values)
    for row in rows:
        out[row] = int(round(out[row] * factor))
    return out
