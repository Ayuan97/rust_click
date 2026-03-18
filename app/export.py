from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def default_base_template() -> Path:
    return repo_root() / "data" / "configs" / "BASE_TEMPLATE.json"


def suggest_output_path(params_path: Path) -> Path:
    root = repo_root()
    params_dir = root / "data" / "params"
    configs_dir = root / "data" / "configs"
    if params_path.parent == params_dir:
        return configs_dir / params_path.name
    return params_path.with_name(f"{params_path.stem}.generated.json")


def export_multi_weapon_config(
    params_path: Path,
    out_path: Path,
    *,
    base_path: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    script_path = repo_root() / "scripts" / "build_multi_weapon_config.py"
    resolved_base = base_path or default_base_template()
    return subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--in-json",
            str(resolved_base),
            "--params",
            str(params_path),
            "--out-json",
            str(out_path),
        ],
        cwd=str(repo_root()),
        capture_output=True,
        text=True,
    )

