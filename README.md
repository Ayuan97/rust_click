# click

This repository is a small toolchain for building HID Remapper JSON configs.
It is not a standalone application. The main purpose is to:

- record HID monitor data from a HID Remapper device
- retune per-shot recoil tables from CSV captures
- generate importable JSON configs for single-weapon and multi-weapon setups

## Upstream References

- Firmware / upstream project:
  [jfedor2/hid-remapper](https://github.com/jfedor2/hid-remapper)
- Web configuration and debugging tool:
  [remapper.org/config](https://www.remapper.org/config/)

This repo generates JSON files that are intended to be imported into the HID
Remapper configuration tool above.

## Main Workflow

1. Record monitor data into CSV with `rec_lr.cmd`.
2. Generate or retune a single-weapon config with `gen_json.cmd`.
3. Generate a multi-weapon config with `wk.cmd`.
4. Import the generated JSON into the HID Remapper web config tool.

## Entry Scripts

- `rec_lr.cmd`: record monitor output to `data/captures/*.csv`
- `gen_json.cmd`: build a single-weapon JSON config, optionally with auto-retune
- `go.cmd`: run record and generate in sequence
- `wk.cmd`: build the keyboard-driven multi-weapon config
- `trajectory_lab.cmd`: launch the GUI trajectory workbench with temporary GUI dependencies via `uv`

## GUI Workbench

The repo now includes a first-pass desktop editor for multi-weapon params.

- open existing files from `data/params/*.json`
- switch between weapons
- edit the 30-shot `x_steps` / `y_steps` table
- preview per-shot deltas and cumulative trajectory
- drag cumulative trajectory points to adjust a specific shot
- capture a baseline and compare current vs reference with dashed overlays
- save params back to JSON
- export a HID Remapper config by calling `scripts/build_multi_weapon_config.py`

Launch it with:

```bat
trajectory_lab.cmd
```

Or directly:

```bat
uv run --with PySide6 --with pyqtgraph python -m app.main
```

Current scope:

- supports the multi-weapon `global + weapons[]` params format
- does not yet support the single-weapon `ak_tune_params` format

Detailed Chinese usage guide:

- `USAGE.md`

## Python Scripts

- `scripts/record_monitor_csv.py`: reads HID monitor reports through `hidapi`
- `scripts/retune_from_csv.py`: derives offsets from recorded CSV data
- `scripts/apply_ak_tune.py`: applies single-weapon tuning into a base JSON
- `scripts/build_multi_weapon_config.py`: compiles multi-weapon expressions
- `scripts/gen_extra_weapon_configs.py`: generates extra config variants

## Data Layout

- `data/configs/`: base templates and generated import JSON files
- `data/params/`: weapon parameters and tuning tables
- `data/captures/`: recorded monitor CSV files
- `Sorin/`: legacy source material used as a reference during migration

## Notes

- The generated configs target HID Remapper firmware version 18 JSON format.
- The browser-based config tool exposes monitor, expressions, actions, import,
  export, and firmware flashing functions.
- Hardware access is required to run the recording path end-to-end.
