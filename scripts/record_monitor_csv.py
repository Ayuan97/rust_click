#!/usr/bin/env python3
"""
Record HID Remapper monitor reports into CSV.

Usage:
  python3 record_monitor_csv.py --out monitor_log.csv
  python3 record_monitor_csv.py --out monitor_log.csv --seconds 20
  python3 record_monitor_csv.py --out monitor_log.csv --wait-enter
  python3 record_monitor_csv.py --out monitor_log.csv --wait-buttons
  python3 record_monitor_csv.py --out monitor_log.csv --only 0xfff50003 0xfff50004 0xfff50005 0xfff50006

Notes:
  - Requires Python package "hid" (same dependency as official config-tool).
  - Press Ctrl+C to stop recording.
"""

from __future__ import annotations

import argparse
import binascii
import csv
import signal
import struct
import sys
import time
from typing import Dict, Iterable, Optional, Tuple

import hid


CONFIG_USAGE_PAGE = 0xFF00
CONFIG_USAGE = 0x0020
MONITOR_USAGE = 0x0021

REPORT_ID_CONFIG = 100
REPORT_ID_MONITOR = 101
CONFIG_VERSION = 18
SET_MONITOR_ENABLED = 22
USAGE_MOUSE_LEFT = 0x00090001
USAGE_MOUSE_RIGHT = 0x00090002


def drain_input_reports(dev: "hid.Device", duration_ms: int) -> None:
    """Drop queued monitor reports so recording starts from a clean point."""
    if duration_ms <= 0:
        return
    deadline = time.time() + (duration_ms / 1000.0)
    while time.time() < deadline:
        data = dev.read(64)
        if not data:
            time.sleep(0.001)


def build_set_monitor_report(enabled: bool) -> bytes:
    # Packet layout matches official config-tool:
    # [report_id, version, command, 26-byte payload, crc32]
    payload = bytearray(
        [REPORT_ID_CONFIG, CONFIG_VERSION, SET_MONITOR_ENABLED, 1 if enabled else 0]
        + [0] * 25
    )
    payload += struct.pack("<I", binascii.crc32(payload[1:]) & 0xFFFFFFFF)
    return bytes(payload)


def open_hid_path(path):
    # Support both Python HID APIs:
    # - hid.Device(path=...)
    # - hid.device().open_path(...)
    if hasattr(hid, "Device"):
        return hid.Device(path=path)

    if hasattr(hid, "device"):
        dev = hid.device()
        try:
            dev.open_path(path)
        except TypeError:
            # Some builds require bytes for path.
            if isinstance(path, str):
                dev.open_path(path.encode())
            else:
                raise
        return dev

    raise RuntimeError("Unsupported hid module API: missing Device/device constructor")


def open_remapper_devices():
    all_cfg_page = [
        d for d in hid.enumerate() if d.get("usage_page") == CONFIG_USAGE_PAGE
    ]
    cfg_devices = [d for d in all_cfg_page if d.get("usage") == CONFIG_USAGE]
    if not cfg_devices:
        raise RuntimeError("No HID Remapper found.")
    if len(cfg_devices) > 1:
        raise RuntimeError("More than one HID Remapper found. Please keep one connected.")
    cfg_info = cfg_devices[0]
    cfg_dev = open_hid_path(cfg_info["path"])

    # Prefer dedicated monitor collection (usage 0x21) when available.
    mon_candidates = [
        d
        for d in all_cfg_page
        if d.get("usage") == MONITOR_USAGE
        and d.get("vendor_id") == cfg_info.get("vendor_id")
        and d.get("product_id") == cfg_info.get("product_id")
        and d.get("interface_number") == cfg_info.get("interface_number")
    ]
    if mon_candidates:
        mon_dev = open_hid_path(mon_candidates[0]["path"])
    else:
        # Older firmware/backends may expose monitor input on the config usage.
        mon_dev = cfg_dev

    return cfg_dev, mon_dev


def parse_monitor_frame(data: Iterable[int]) -> Iterable[Tuple[int, int, int]]:
    raw = bytes(data)
    if not raw:
        return []

    # Some backends include report ID in the input report, some do not.
    if len(raw) >= 64 and raw[0] == REPORT_ID_MONITOR:
        body = raw[1:64]
    elif len(raw) >= 63:
        body = raw[:63]
    else:
        return []

    out = []
    for i in range(0, 63, 9):
        usage = struct.unpack_from("<I", body, i)[0]
        value = struct.unpack_from("<i", body, i + 4)[0]
        hub_port = body[i + 8]
        if usage != 0:
            out.append((usage, value, hub_port))
    return out


def parse_usage_list(items: Optional[Iterable[str]]) -> Optional[set[int]]:
    if not items:
        return None
    result = set()
    for item in items:
        result.add(int(item, 16))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Record HID Remapper Monitor data to CSV")
    parser.add_argument("--out", required=True, help="Output CSV path")
    parser.add_argument("--seconds", type=float, default=0.0, help="Stop automatically after N seconds (0 = until Ctrl+C)")
    parser.add_argument(
        "--wait-enter",
        action="store_true",
        help="Arm monitor first, then press Enter to start actual recording",
    )
    parser.add_argument(
        "--wait-buttons",
        action="store_true",
        help="Start recording only after both left+right mouse buttons are pressed",
    )
    parser.add_argument(
        "--flush-ms",
        type=int,
        default=0,
        help="Drop queued reports right before start (ms). Default: 200ms when --wait-enter, otherwise 0",
    )
    parser.add_argument(
        "--only",
        nargs="*",
        help="Optional usage filter, hex list like: 0xfff50003 0xfff50004",
    )
    parser.add_argument(
        "--no-dedupe",
        action="store_true",
        help="Write every sample (default only writes on value change per usage/port)",
    )
    parser.add_argument(
        "--only-while-buttons",
        action="store_true",
        help="Only write rows while both LMB+RMB are held down",
    )
    parser.add_argument(
        "--release-grace-ms",
        type=int,
        default=120,
        help="When using --wait-buttons + --only-while-buttons, stop after both buttons are released for this long (ms)",
    )
    args = parser.parse_args()

    usage_filter = parse_usage_list(args.only)
    dedupe = not args.no_dedupe
    auto_stop_on_release = args.wait_buttons and args.only_while_buttons

    stop = False

    def _handle_sigint(_sig, _frame):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, _handle_sigint)

    cfg_dev, read_dev = open_remapper_devices()
    try:
        if hasattr(read_dev, "set_nonblocking"):
            read_dev.set_nonblocking(True)
        elif hasattr(read_dev, "nonblocking"):
            read_dev.nonblocking = True

        cfg_dev.send_feature_report(build_set_monitor_report(True))

        if args.wait_enter:
            print("Monitor armed. Press Enter to start recording...")
            try:
                input()
            except EOFError:
                # Non-interactive terminal: fall back to immediate start.
                pass

        effective_flush_ms = args.flush_ms if args.flush_ms > 0 else (200 if args.wait_enter else 0)
        drain_input_reports(read_dev, effective_flush_ms)

        start = None if args.wait_buttons else time.time()
        wait_started_at = time.time()
        wait_deadline = (wait_started_at + args.seconds) if (args.wait_buttons and args.seconds > 0) else None
        last_vals: Dict[Tuple[int, int], int] = {}
        button_state: Dict[int, int] = {USAGE_MOUSE_LEFT: 0, USAGE_MOUSE_RIGHT: 0}
        rows_written = 0
        rows_skipped_by_gate = 0
        last_status_ts = 0.0
        release_candidate_since: Optional[float] = None
        if args.wait_buttons:
            if wait_deadline is not None:
                print(f"Waiting for LMB+RMB to start recording (timeout: {args.seconds:g}s)...")
            else:
                print("Waiting for LMB+RMB to start recording...")
        else:
            print("Recording started.")

        with open(args.out, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                ["timestamp_unix", "elapsed_ms", "usage_hex", "value", "hub_port"]
            )

            while not stop:
                now = time.time()

                if start is None and wait_deadline is not None and now >= wait_deadline:
                    print("Timeout waiting for LMB+RMB trigger; no recording started.")
                    break

                # When waiting for button trigger, countdown starts only after recording starts.
                if args.seconds > 0 and start is not None and (now - start) >= args.seconds:
                    break

                if start is None and (now - last_status_ts) >= 2.0:
                    print("Still waiting for LMB+RMB...")
                    last_status_ts = now

                # 64 bytes is enough for report_id + 63-byte monitor payload.
                try:
                    data = read_dev.read(64)
                except OSError:
                    # Some hid backends raise on empty/non-ready reads in nonblocking mode.
                    time.sleep(0.01)
                    continue
                if not data:
                    time.sleep(0.002)
                    continue

                entries = list(parse_monitor_frame(data))
                if not entries:
                    continue

                for usage, value, _hub_port in entries:
                    if usage == USAGE_MOUSE_LEFT or usage == USAGE_MOUSE_RIGHT:
                        button_state[usage] = value

                if start is None:
                    if button_state[USAGE_MOUSE_LEFT] > 0 and button_state[USAGE_MOUSE_RIGHT] > 0:
                        start = now
                        if auto_stop_on_release:
                            print("Recording started by LMB+RMB. Release either button to stop.")
                        else:
                            print("Recording started by LMB+RMB.")
                    else:
                        continue

                elapsed_ms = int((now - start) * 1000)
                gated_on = (
                    button_state[USAGE_MOUSE_LEFT] > 0
                    and button_state[USAGE_MOUSE_RIGHT] > 0
                )

                if auto_stop_on_release:
                    if gated_on:
                        release_candidate_since = None
                    else:
                        if release_candidate_since is None:
                            release_candidate_since = now
                        elif (now - release_candidate_since) * 1000.0 >= args.release_grace_ms:
                            print("Recording stopped by LMB+RMB release.")
                            break

                if args.only_while_buttons and not gated_on:
                    rows_skipped_by_gate += len(entries)
                    continue

                for usage, value, hub_port in entries:
                    if usage_filter is not None and usage not in usage_filter:
                        continue

                    key = (usage, hub_port)
                    if dedupe and last_vals.get(key) == value:
                        continue
                    last_vals[key] = value

                    writer.writerow(
                        [f"{now:.6f}", elapsed_ms, f"0x{usage:08x}", value, hub_port]
                    )
                    rows_written += 1
                f.flush()

        print(f"Saved CSV: {args.out}")
        print(f"Rows written: {rows_written}")
        if args.only_while_buttons:
            print(f"Rows skipped by button gate: {rows_skipped_by_gate}")
        return 0
    finally:
        try:
            cfg_dev.send_feature_report(build_set_monitor_report(False))
        except Exception:
            pass
        if read_dev is not cfg_dev:
            read_dev.close()
        cfg_dev.close()


if __name__ == "__main__":
    sys.exit(main())
