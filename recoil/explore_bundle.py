"""
Dump weapon recoil data from Rust content.bundle.

Strategy: Find weapon prefab GameObjects, traverse their MonoBehaviour
components, and read raw bytes to extract recoil-related float fields.
Also tries matching MonoScript class names.
"""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

import UnityPy


def explore_weapon_prefabs(bundle_path: str) -> None:
    print(f"Loading: {bundle_path}")
    env = UnityPy.load(bundle_path)

    # Step 1: Find all MonoScript names (class names for MonoBehaviours)
    print("\n=== MonoScript class names ===")
    script_map: dict[int, str] = {}
    weapon_scripts: set[int] = set()
    for obj in env.objects:
        if obj.type.name == "MonoScript":
            try:
                data = obj.read()
                name = data.m_Name
                script_map[obj.path_id] = name
                if any(kw in name.lower() for kw in (
                    "recoil", "baseprojectile", "weapon", "aimcone",
                    "projectile", "magazine", "attackentity",
                )):
                    weapon_scripts.add(obj.path_id)
                    print(f"  {name} (path_id={obj.path_id})")
            except Exception:
                continue

    # Step 2: Find weapon prefab paths in container
    print("\n=== Container paths for weapon prefabs ===")
    weapon_paths: dict[str, list] = {}
    for path, obj_info in env.container.items():
        path_lower = path.lower()
        if any(kw in path_lower for kw in (
            "rifle.ak", "smg.mp5", "smg.thompson", "lmg.m249",
            "rifle.m39", "rifle.lr300", "rifle.semiauto",
            "smg.2", "pistol.semiauto", "pistol.m92",
        )):
            if "prefab" in path_lower or "entity" in path_lower:
                print(f"  {path}")

    # Step 3: Try to find MonoBehaviours that reference weapon-related scripts
    print("\n=== MonoBehaviours referencing weapon scripts ===")
    weapon_monos: list[dict] = []
    for obj in env.objects:
        if obj.type.name == "MonoBehaviour":
            try:
                data = obj.read()
                # Check if this MB references a weapon-related script
                script_ref = getattr(data, "m_Script", None)
                if script_ref:
                    ref_id = getattr(script_ref, "path_id", None) or getattr(script_ref, "m_PathID", None)
                    if ref_id and ref_id in weapon_scripts:
                        script_name = script_map.get(ref_id, "unknown")
                        go_ref = getattr(data, "m_GameObject", None)
                        go_name = ""
                        if go_ref:
                            go_id = getattr(go_ref, "path_id", None) or getattr(go_ref, "m_PathID", None)
                            if go_id:
                                try:
                                    for go_obj in env.objects:
                                        if go_obj.path_id == go_id and go_obj.type.name == "GameObject":
                                            go_data = go_obj.read()
                                            go_name = go_data.m_Name
                                            break
                                except Exception:
                                    pass

                        print(f"  Script={script_name}, GameObject={go_name}, path_id={obj.path_id}")

                        # Try to read raw bytes for float values
                        try:
                            raw = obj.get_raw_data()
                            if raw and len(raw) > 20:
                                weapon_monos.append({
                                    "script": script_name,
                                    "game_object": go_name,
                                    "path_id": obj.path_id,
                                    "raw_size": len(raw),
                                })
                        except Exception:
                            pass
            except Exception:
                continue

    # Step 4: Print all MonoScript names for reference
    print(f"\n=== All {len(script_map)} MonoScript names ===")
    for pid, name in sorted(script_map.items(), key=lambda x: x[1]):
        print(f"  {name}")

    # Save findings
    out = {
        "weapon_scripts": {str(k): script_map[k] for k in weapon_scripts},
        "weapon_monos": weapon_monos,
        "all_scripts": {str(k): v for k, v in script_map.items()},
    }
    out_path = Path(__file__).parent / "output" / "bundle_explore.json"
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved to: {out_path}")


if __name__ == "__main__":
    bundle = sys.argv[1] if len(sys.argv) > 1 else r"D:\steam\steamapps\common\Rust\Bundles\shared\content.bundle"
    explore_weapon_prefabs(bundle)
