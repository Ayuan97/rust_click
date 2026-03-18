from __future__ import annotations

import json
from pathlib import Path

from .models import GlobalConfig, ParameterDocument, WeaponProfile


def document_from_raw(raw: dict, *, path: Path | None = None) -> ParameterDocument:
    if not isinstance(raw, dict):
        raise ValueError("参数文件根节点必须是对象")
    if "global" not in raw or "weapons" not in raw:
        raise ValueError("当前界面只支持多武器参数文件（需要包含 global 和 weapons）")

    global_raw = raw.get("global")
    weapons_raw = raw.get("weapons")
    if not isinstance(global_raw, dict):
        raise ValueError("global 必须是对象")
    if not isinstance(weapons_raw, list) or not weapons_raw:
        raise ValueError("weapons 必须是非空数组")

    top_level_extras = {key: value for key, value in raw.items() if key not in {"global", "weapons"}}
    weapons = [WeaponProfile.from_dict(item) for item in weapons_raw if isinstance(item, dict)]
    if not weapons:
        raise ValueError("weapons 数组中没有可用的武器对象")

    return ParameterDocument(
        path=path,
        top_level_extras=top_level_extras,
        global_config=GlobalConfig.from_dict(global_raw),
        weapons=weapons,
    )


def load_params(path: Path) -> ParameterDocument:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return document_from_raw(raw, path=path)


def serialize_document(document: ParameterDocument) -> str:
    return json.dumps(document.to_dict(), ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def document_from_json(snapshot: str, *, path: Path | None = None) -> ParameterDocument:
    raw = json.loads(snapshot)
    return document_from_raw(raw, path=path)


def save_params(document: ParameterDocument, path: Path | None = None) -> Path:
    out_path = path or document.path
    if out_path is None:
        raise ValueError("没有可用的保存路径")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(document.to_dict(), ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )
    document.path = out_path
    return out_path
