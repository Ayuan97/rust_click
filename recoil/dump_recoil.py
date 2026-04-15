"""
Parse and display RecoilProperties data extracted from Rust content.bundle.

Based on the binary structure observed:
  float recoilYawMin     (offset 0)
  float recoilYawMax     (offset 4)
  float recoilPitchMin   (offset 8)
  float recoilPitchMax   (offset 12)
  float timeToTakeMin    (offset 16)
  float timeToTakeMax    (offset 20)
  float ADSScale         (offset 24)
  float movementPenalty  (offset 28)
  int   (unknown/pad)    (offset 32)
  int   numCurveKeys     (offset 36)  -- then animation curve keyframes follow
"""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

import UnityPy


def parse_recoil(raw: bytes, data_start: int) -> dict:
    """Parse the known float fields from RecoilProperties raw data."""
    d = raw[data_start:]
    if len(d) < 36:
        return {}

    fields = {}
    float_names = [
        "recoilYawMin",
        "recoilYawMax",
        "recoilPitchMin",
        "recoilPitchMax",
        "timeToTakeMin",
        "timeToTakeMax",
        "ADSScale",
        "movementPenalty",
    ]
    for i, name in enumerate(float_names):
        val = struct.unpack_from("<f", d, i * 4)[0]
        fields[name] = round(val, 6)

    # After the 8 floats (32 bytes), there's typically an int (pad/flags) and
    # then an int for number of animation curve keyframes
    if len(d) >= 40:
        fields["_pad_or_flags"] = struct.unpack_from("<i", d, 32)[0]
        fields["_curve_key_count"] = struct.unpack_from("<i", d, 36)[0]

    # Try to read animation curve keyframes (each keyframe is typically 7 floats = 28 bytes)
    # time, value, inTangent, outTangent, inWeight, outWeight, weightedMode
    curve_offset = 40
    num_keys = fields.get("_curve_key_count", 0)
    if 0 < num_keys <= 20 and len(d) >= curve_offset + num_keys * 28:
        keys = []
        for k in range(num_keys):
            ko = curve_offset + k * 28
            key_data = struct.unpack_from("<7f", d, ko)
            keys.append({
                "time": round(key_data[0], 6),
                "value": round(key_data[1], 6),
                "inTangent": round(key_data[2], 6),
                "outTangent": round(key_data[3], 6),
                "inWeight": round(key_data[4], 6),
                "outWeight": round(key_data[5], 6),
            })
        fields["pitchCurve"] = keys

        # After pitch curve, there might be a yaw curve
        next_offset = curve_offset + num_keys * 28
        # Read wrap modes (2 ints)
        if len(d) >= next_offset + 8:
            next_offset += 8  # skip wrap modes

        # Read next curve key count
        if len(d) >= next_offset + 4:
            num_keys2 = struct.unpack_from("<i", d, next_offset)[0]
            next_offset += 4
            if 0 < num_keys2 <= 20 and len(d) >= next_offset + num_keys2 * 28:
                keys2 = []
                for k in range(num_keys2):
                    ko = next_offset + k * 28
                    key_data = struct.unpack_from("<7f", d, ko)
                    keys2.append({
                        "time": round(key_data[0], 6),
                        "value": round(key_data[1], 6),
                        "inTangent": round(key_data[2], 6),
                        "outTangent": round(key_data[3], 6),
                    })
                fields["yawCurve"] = keys2

    return fields


def dump_all(bundle_path: str) -> None:
    print(f"Loading: {bundle_path}")
    env = UnityPy.load(bundle_path)

    # Find RecoilProperties script id
    recoil_script_id = None
    for obj in env.objects:
        if obj.type.name == "MonoScript":
            try:
                data = obj.read()
                if data.m_Name == "RecoilProperties":
                    recoil_script_id = obj.path_id
                    break
            except Exception:
                continue

    results = {}
    for obj in env.objects:
        if obj.type.name == "MonoBehaviour":
            try:
                data = obj.read()
                script_ref = getattr(data, "m_Script", None)
                if not script_ref:
                    continue
                ref_id = getattr(script_ref, "path_id", None) or getattr(script_ref, "m_PathID", None)
                if ref_id != recoil_script_id:
                    continue

                raw = obj.get_raw_data()
                if raw is None or len(raw) < 80:
                    continue

                # Parse name
                header_size = 28
                name_len = struct.unpack_from("<I", raw, header_size)[0]
                if 0 < name_len < 200:
                    name = raw[header_size + 4 : header_size + 4 + name_len].decode("utf-8", errors="replace")
                    name_total = (4 + name_len + 3) & ~3
                    data_start = header_size + name_total
                else:
                    name = f"unknown_{obj.path_id}"
                    data_start = header_size

                parsed = parse_recoil(raw, data_start)
                parsed["_name"] = name
                results[name] = parsed

            except Exception:
                continue

    # Print results
    print(f"\nFound {len(results)} RecoilProperties\n")
    print(f"{'Name':<30} {'YawMin':>8} {'YawMax':>8} {'PitchMin':>9} {'PitchMax':>9} {'ADSScale':>9} {'MovPen':>8}")
    print("-" * 90)
    for name, d in sorted(results.items()):
        print(
            f"{name:<30} {d.get('recoilYawMin', 0):>8.2f} {d.get('recoilYawMax', 0):>8.2f} "
            f"{d.get('recoilPitchMin', 0):>9.2f} {d.get('recoilPitchMax', 0):>9.2f} "
            f"{d.get('ADSScale', 0):>9.2f} {d.get('movementPenalty', 0):>8.2f}"
        )
        if "pitchCurve" in d:
            print(f"  pitchCurve ({len(d['pitchCurve'])} keys): {[(k['time'], k['value']) for k in d['pitchCurve']]}")
        if "yawCurve" in d:
            print(f"  yawCurve ({len(d['yawCurve'])} keys): {[(k['time'], k['value']) for k in d['yawCurve']]}")

    out_path = Path(__file__).parent / "output" / "recoil_parsed.json"
    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved to: {out_path}")


if __name__ == "__main__":
    bundle = sys.argv[1] if len(sys.argv) > 1 else r"D:\steam\steamapps\common\Rust\Bundles\shared\content.bundle"
    dump_all(bundle)
