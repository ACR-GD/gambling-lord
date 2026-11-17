# Gambling Lord (賭霸) — English Translation Project

Full English localization of *Gambling Lord* (賭霸) for the **Super A'Can** (Dunhuang Technology / Funtech Entertainment Corp., 1995–1996), translating all pre-rendered Traditional Chinese 4bpp tilemaps, sprite banks, menus, nameplates, yaku names, opponent taunts, mini-games, cutscenes, and credits using variable-width bitmap fonts (VWF) matched to hardware palette and sprite constraints.

## Source & Build Artifacts

- **Original ROM (unmodified):** `Gambling Lord (Taiwan).bin` (`2,097,152` bytes / `0x200000`, 16-bit byte-swapped)
  - `SHA-1`: `0fda223817f0b50f0ce9687076d29df3d1b86960`
  - `SHA-256`: `c789145655bb06f5f896e72060c2c4d814233b995d3889715f2d131a76d77688`
- **Translated ROM:** `build/Gambling Lord (EN).bin` (`2,097,152` bytes, 16-bit byte-swapped)
- **IPS Patch:** `build/Gambling Lord (EN).ips` (`144,452` bytes; apply to unmodified `Gambling Lord (Taiwan).bin` with any standard IPS patcher)
- **Build Report:** `build/report.txt`

## How to Play

Apply `build/Gambling Lord (EN).ips` to `Gambling Lord (Taiwan).bin` (2,097,152 bytes, CRC32 `ac4fa721`,
SHA-1 `0fda223817f0b50f0ce9687076d29df3d1b86960`, the MAME `gamblord` dump `16006.bin`). The ROM keeps its size.

- **Repo emulator:** open the patched file.
- **MAME:** put the patched file in `roms/gamblord/` as `16006.bin` and run `mame supracan gamblord`
  (MAME warns about the checksum; that's expected).

The 賭霸 title logo is left as artwork.

## Technical Architecture

1. **No Text Engine in ROM:** *Gambling Lord* stores all text as pre-rendered 4bpp tilemaps and OAM sprite banks (both raw and `$02E658` `d222`-compressed blocks in modes `0xF1`–`0xF4`).
2. **Hardware Sprite & Tilemap Flipping (`$0006BA`):** Disassembly of `$0006BA` (`0x000758..0x000770`) confirms both BG tilemap words and sprite pattern words use `0x0800` for horizontal flip and `0x0400` for vertical flip, enabling clean tile deduplication across `TileBankAllocator(allow_flip=True)`.
3. **Title Banner Circular Ribbon (`0x09FE2E..0x0A7D50`):** `27x3` map scrolled in 9-tile increments across 3 diamond-separated stops:
   - `TOURNAMENT` (`賭霸大賽`, `fg=1`, `cols 0..7`, `$fc1f20 == 1`) — 16-player Bracket
   - `FREE PLAY` (`自由對戰`, `fg=2`, `cols 9..16`, `$fc1f20 == 0` default) — 4-pick Exhibition
   - `COMPETE` (`競技賭霸`, `fg=3`, `cols 18..25`, `$fc1f20 == 2`) — Story Campaign
4. **Character Select Dual-Palette Highlights (`0x0285DA`):** All 16 wood-framed plaques coexist across two sprite palettes (`CS Pal 4` for slots `0,1,2,3,9,12,15` and `CS Pal 8` for slots `4,5,6,7,8,10,11,13,14`) with per-character CRAM background/highlight indices looked up from `0x0285DA`.
5. **Jade Emperor Cutscene (`0x00E884`, `0x0FC128..0x0FF0F6`):** The original `3x5` (`48x80` px) `16x16` sprite box iterates column-major for vertical Chinese. The patch rewrites `0x00E8F8..0x00E918` to row-major (`3` cols left-to-right × `5` rows top-to-bottom), disables special-char hooks at `0x00E8AC`/`0x00E8C2`, and keeps all 7 pages across streams `0..5` padded to 15 sprites using `59 / 63` unique sprites and `179 / 247` tiles.
6. **Space Allocation & Relocations (`0x1FB76E..0x200000`):** Blocks that grew after `d222` recompression (`cs_headers_map_reloc`, `cs_headers_tiles_reloc`, `vs_intro_map_reloc`) are placed in unused tail ROM space with pointer repointing, leaving `16,571 / 18,578` bytes free and zero patch overlaps.

## Translated Subsystems (17 / 17)

| Subsystem | Scope | Budget Used |
|---|---|---|
| `title_banner` | Mode selector ribbon (`TOURNAMENT · FREE PLAY · COMPETE`) | `43 / 71` tiles |
| `edict` | Opening Imperial Decree (`IMPERIAL DECREE`) | `121 / 137` tiles |
| `cs_headers` | 4-box CS headers (`PLAYER`, `RIVAL` x3) | `18 / 36` tiles |
| `cs_names` | 16 Character Select nameplates (`CS Pal 4` & `CS Pal 8`) | `325 / 334` tiles |
| `vs_intro` | `RND 1..7 SET` overlays & `GAMBLING LORD` crest | `173 / 259` tiles |
| `bracket` | Tournament Bracket banners & crest | `210 / 284` tiles |
| `bracket_names` | 16 vertical bracket nameplates | `162 / 266` tiles |
| `ingame_names` | 16 in-game Mahjong table nameplates (`NP`) | `159 / 235` tiles |
| `jade_emperor` | 6 Jade Emperor speech streams (7 `48x80` pages) | `59 / 63` text sprites, `179 / 247` tiles |
| `set1` | Table prompts, meld calls, cheats & waiting taunts (`59` sprites) | `666 / 767` tiles |
| `set2` | 63 Yaku names, 16 rival names, status/result badges (`90` sprites) | `397 / 591` tiles |
| `set3` | Opponent speech-bubble quips (`68` pointers, `116` sprites) | `690 / 920` tiles |
| `cheat_skill` | Pre-match Charm/Cheat menu (`VITAL`, `SPIRIT`, `GOLD`, 10 skills) | `184 / 224` tiles |
| `leaderboard` | Rankings table (`RANK`, `NAME`, `CASH`, `WINS`, `SELF`, `DEAL`) | `62 / 84` tiles |
| `minigames_bg` | `TRIPLE HIT`, `TWIN CANNON`, `BLACKJACK` boards & felt cleanup | `27/28`, `32/32`, `25/27` tiles |
| `bank3` | Mini-game sprites (prompts, stakes, rewards, `HIT`/`STAY`/`PUSH`) | `167 / 241` tiles |
| `ending` | Staff & company credits (`PLANNER`, `ART`, `PROGRAMMING`, `MUSIC`) | `160 / 171` tiles |

See `notes/text_inventory.md` for complete ROM address ranges and formats.

## Repository Structure

```
gambling-lord/
├── README.md
├── tools/
│   ├── d222.py          # $02E658 compression / decompression codec
│   ├── gl_rom.py        # 16-bit swap, SpaceAllocator, 4bpp tile/map, IPS generator
│   ├── vwf.py           # VWF bitmap font loader, measurer, word-wrapper, tile slicer
│   ├── patchers.py      # All 17 subsystem patchers + static verification sheet builder
│   └── build_rom.py     # Master build + overlap + IPS round-trip verifier
├── notes/
│   ├── translations_en.json
│   ├── text_inventory.md
│   ├── font_vwf_{banner,body,display}.{png,json}
│   ├── verify_{screens,nameplates,set1,set2,set3,minigames}.png
│   └── verify_live.png
└── build/
    ├── Gambling Lord (EN).bin
    ├── Gambling Lord (EN).ips
    └── report.txt
```

## Rebuilding from Source

Requirements: Python 3.9+, `Pillow` (`PIL`), and your own `Gambling Lord (Taiwan).bin` in this folder.

```bash
python3 tools/build_rom.py
```

The build script verifies the source ROM SHA-1/SHA-256, applies all 17 patchers, checks non-overlapping allocations, writes `build/Gambling Lord (EN).bin` and `build/Gambling Lord (EN).ips`, confirms lossless IPS round-trip reconstruction against the original ROM, writes `build/report.txt`, and regenerates all static PNG contact sheets under `notes/`.

## Verification

- **Automated Checks:** `build_rom.py` passes source SHA verification, all 17 tile/sprite capacity assertions, `Overlap Check: PASS`, and `IPS Round-Trip: PASS`.
- **Static Contact Sheets:** `notes/verify_screens.png`, `notes/verify_nameplates.png`, `notes/verify_set1.png`, `notes/verify_set2.png`, `notes/verify_set3.png`, and `notes/verify_minigames.png` decode every patched map/sprite directly back from `build/Gambling Lord (EN).bin`.
- **Live Emulation Capture (`notes/verify_live.png`):** Verified in the Super A'Can headless emulator harness across `FREE PLAY` (4-pick CS, 4-portrait `PLAYER / RIVAL`, Mahjong table `NP` plates, `20000` bankrolls, dealt hand & `FLOWER`), `TOURNAMENT` (`MATCH 1 - PRELIMS` Bracket + `BN` plates + VS Intro), and `COMPETE` (Jade Emperor `3x5` speech Pages 0 & 1 + VS Intro), including live CS `pal=4`/`pal=8` nameplates and per-slot purple highlights.

## License

The tools, fonts and patch are MIT-licensed (see `LICENSE`). The game itself is not included;
you need your own dump.
