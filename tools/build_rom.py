#!/usr/bin/env python3
"""Master build script for Gambling Lord (賭霸) English translation."""

from __future__ import annotations

import sys
import time
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
PROJECT_DIR = TOOLS_DIR.parent
NOTES_DIR = PROJECT_DIR / "notes"
BUILD_DIR = PROJECT_DIR / "build"

if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import gl_rom
import patchers
import vwf


def main() -> int:
    t0 = time.perf_counter()
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    NOTES_DIR.mkdir(parents=True, exist_ok=True)

    cpu_rom, orig_swapped = gl_rom.load_rom(verify_hash=True)
    alloc = gl_rom.SpaceAllocator()
    tr = patchers.load_translations()
    fonts = vwf.load_fonts(NOTES_DIR)

    stats = {}
    steps = [
        ("title_banner", patchers.patch_title_banner),
        ("edict", patchers.patch_imperial_edict),
        ("cs_headers", patchers.patch_cs_headers),
        ("cs_names", patchers.patch_cs_nameplates),
        ("vs_intro", patchers.patch_vs_intro),
        ("bracket", patchers.patch_bracket),
        ("bracket_names", patchers.patch_bracket_nameplates),
        ("ingame_names", patchers.patch_ingame_nameplates),
        ("jade_emperor", patchers.patch_jade_emperor),
        ("set1", patchers.patch_set1),
        ("set2", patchers.patch_set2),
        ("set3", patchers.patch_set3),
        ("cheat_skill", patchers.patch_cheat_skill),
        ("leaderboard", patchers.patch_leaderboard),
        ("minigames_bg", patchers.patch_minigames_bg),
        ("bank3", patchers.patch_bank3),
        ("ending", patchers.patch_ending_credits),
    ]

    for key, fn in steps:
        res = fn(cpu_rom, alloc, tr, fonts)
        stats[key] = res
        print(f"[OK] {key:15s}: {res}")

    alloc.verify_non_overlapping()
    if len(cpu_rom) != gl_rom.ORIG_ROM_SIZE:
        raise AssertionError(f"Output ROM size {len(cpu_rom)} != {gl_rom.ORIG_ROM_SIZE}")

    out_bin = BUILD_DIR / "Gambling Lord (EN).bin"
    out_ips = BUILD_DIR / "Gambling Lord (EN).ips"
    out_report = BUILD_DIR / "report.txt"

    mod_swapped = gl_rom.save_rom(bytes(cpu_rom), out_bin)
    gl_rom.write_ips(orig_swapped, mod_swapped, out_ips)

    roundtrip = gl_rom.apply_ips(orig_swapped, out_ips)
    if roundtrip != mod_swapped:
        raise AssertionError("IPS round-trip verification FAILED!")
    if len(out_bin.read_bytes()) != gl_rom.ORIG_ROM_SIZE:
        raise AssertionError("Saved .bin file size mismatch!")

    sheet_paths = patchers.generate_verification_sheets(cpu_rom, stats, NOTES_DIR)
    elapsed = time.perf_counter() - t0

    report_lines = [
        "Gambling Lord (賭霸) English Translation Build Report",
        "=" * 60,
        f"Source ROM      : {gl_rom.ORIG_ROM_PATH.name}",
        f"Output ROM      : {out_bin.name} ({len(mod_swapped):,} bytes)",
        f"Output IPS      : {out_ips.name} ({out_ips.stat().st_size:,} bytes)",
        f"IPS Round-Trip  : PASS",
        f"Overlap Check   : PASS",
        f"Free Space Left : {alloc.remaining_bytes():,} / {gl_rom.FREE_SPACE_REGIONS[0][1] - gl_rom.FREE_SPACE_REGIONS[0][0]:,} bytes",
        f"Elapsed Time    : {elapsed:.2f}s",
        "",
        "Subsystem Results:",
    ]
    for key in stats:
        report_lines.append(f"  - {key:15s}: {stats[key]}")
    report_lines.append("")
    report_lines.append("Space Allocations (0x1FB76E..0x200000):")
    for s, e, label in alloc.allocations:
        report_lines.append(f"  - {label:24s}: 0x{s:06X}..0x{e:06X} ({e - s:,} B)")
    report_lines.append("")
    report_lines.append("Verification Contact Sheets:")
    for p in sheet_paths:
        report_lines.append(f"  - notes/{Path(p).name}")

    out_report.write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    print("\n" + out_report.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
