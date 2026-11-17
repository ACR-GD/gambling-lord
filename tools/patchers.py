"""Modular ROM patchers and verification sheet renderers for Gambling Lord (賭霸)."""

from __future__ import annotations

import json
import struct
from collections import Counter
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from PIL import Image, ImageDraw

import d222
import gl_rom
import vwf

NOTES_DIR = Path(__file__).resolve().parent.parent / "notes"
TRANSLATIONS_PATH = NOTES_DIR / "translations_en.json"


# ---------------------------------------------------------------------------
# Generic helpers for grids, maps, sprite banks, and text rendering
# ---------------------------------------------------------------------------

def load_translations(path: Path = TRANSLATIONS_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def unpack_words(raw: bytes) -> List[int]:
    if len(raw) % 2 != 0:
        raise ValueError(f"Word buffer length {len(raw)} not even")
    return list(struct.unpack(f">{len(raw) // 2}H", raw))


def pack_words(words: Sequence[int]) -> bytes:
    return struct.pack(f">{len(words)}H", *(w & 0xFFFF for w in words))


def clone_tiles(tiles: Sequence[Sequence[Sequence[int]]]) -> List[List[List[int]]]:
    return [[list(row) for row in tile] for tile in tiles]


def flip_coord(v: int, flip: bool) -> int:
    return 7 - v if flip else v


def render_region_to_grid(
    tiles: Sequence[Sequence[Sequence[int]]],
    words: Sequence[int],
    map_w: int,
    x0: int,
    y0: int,
    w_t: int,
    h_t: int,
    is_sprite: bool = False,
) -> List[List[int]]:
    """Decode a `(w_t, h_t)` tilemap region into a `(h_t*8) x (w_t*8)` pixel grid."""
    h_mask = 0x0800
    v_mask = 0x0400
    grid = [[0] * (w_t * 8) for _ in range(h_t * 8)]
    for ty in range(h_t):
        for tx in range(w_t):
            w = words[(y0 + ty) * map_w + (x0 + tx)]
            ti = w & 0x3FF
            hf = bool(w & h_mask)
            vf = bool(w & v_mask)
            t = tiles[ti]
            for py in range(8):
                sy = 7 - py if vf else py
                for px in range(8):
                    sx = 7 - px if hf else px
                    grid[ty * 8 + py][tx * 8 + px] = t[sy][sx]
    return grid


def write_grid_to_region(
    words: List[int],
    map_w: int,
    x0: int,
    y0: int,
    w_t: int,
    h_t: int,
    grid: Sequence[Sequence[int]],
    allocator: vwf.TileBankAllocator,
    pal_grid: Optional[Sequence[Sequence[int]]] = None,
    default_pal: int = 0,
    prio_grid: Optional[Sequence[Sequence[bool]]] = None,
    default_prio: bool = False,
    zero_word_if_all: Optional[int] = 0,
    is_sprite: bool = False,
    default_pal_words: Optional[Sequence[int]] = None,
) -> None:
    """Slice `grid` into `8x8` tiles using `allocator` and write back into `words`."""
    word_fn = gl_rom.sprite_word if is_sprite else gl_rom.tilemap_word
    for ty in range(h_t):
        for tx in range(w_t):
            idx = (y0 + ty) * map_w + (x0 + tx)
            orig_w = default_pal_words[idx] if default_pal_words is not None else words[idx]
            pal = pal_grid[ty][tx] if pal_grid is not None else ((orig_w >> 12) & 0xF if orig_w else default_pal)
            prio = prio_grid[ty][tx] if prio_grid is not None else (bool(orig_w & 0x8000) if not is_sprite else False)
            if default_prio:
                prio = True

            cell = [grid[ty * 8 + py][tx * 8 : tx * 8 + 8] for py in range(8)]
            if zero_word_if_all is not None and all(v == zero_word_if_all for row in cell for v in row):
                if zero_word_if_all == 0:
                    words[idx] = 0
                else:
                    words[idx] = word_fn(0, pal) if is_sprite else gl_rom.tilemap_word(0, pal, prio=prio)
            else:
                if is_sprite:
                    words[idx] = allocator.get_or_alloc_word(cell, pal, word_fn=gl_rom.sprite_word)
                else:
                    fn = (lambda ti, p, hflip=False, vflip=False, pr=prio: gl_rom.tilemap_word(ti, p, hflip=hflip, vflip=vflip, prio=pr))
                    words[idx] = allocator.get_or_alloc_word(cell, pal, word_fn=fn)


def fill_rect(
    grid: List[List[int]],
    x0: int,
    y0: int,
    w: int,
    h: int,
    color: int,
) -> None:
    for y in range(y0, y0 + h):
        row = grid[y]
        for x in range(x0, x0 + w):
            row[x] = color


def clear_rect_row_mode(
    grid: List[List[int]],
    x0: int,
    y0: int,
    w: int,
    h: int,
    keep_colors: Optional[Set[int]] = None,
) -> None:
    """Clear text pixels inside rect to each scanline's dominant background color."""
    for y in range(y0, y0 + h):
        row = grid[y]
        vals = [row[x] for x in range(x0, x0 + w)]
        if keep_colors:
            cand = [v for v in vals if v in keep_colors]
            bg = Counter(cand).most_common(1)[0][0] if cand else Counter(vals).most_common(1)[0][0]
        else:
            bg = Counter(vals).most_common(1)[0][0]
        for x in range(x0, x0 + w):
            row[x] = bg


def make_blank_grid(w: int, h: int, bg: int = 0) -> List[List[int]]:
    return [[bg] * w for _ in range(h)]


def fit_text_mask(
    fonts: Dict[str, vwf.BitmapFont],
    text: str,
    max_w: int,
    max_h: int,
    prefer_order: Sequence[str] = ("display", "body", "mini"),
    allow_wrap: bool = True,
    tracking: int = 1,
    line_gap: int = 1,
) -> vwf.Grid2D:
    """Render text mask trying single-line, multiline (`\\n`), and fitted fonts whose glyph set covers `text`."""
    norm = text.replace("·", "-")
    supported = [
        fn for fn in prefer_order
        if fn in fonts and all(ch in (" ", "\n") or ch in fonts[fn].glyphs for ch in norm)
    ]
    if not supported:
        for fb in ("body", "mini"):
            if fb in fonts and fb not in supported:
                supported.append(fb)
        fb_font = fonts[supported[-1]]
        norm = "".join(ch if (ch in (" ", "\n") or ch in fb_font.glyphs) else " " for ch in norm)

    if "\n" not in norm:
        m = vwf.render_fitted_mask(fonts, norm, max_w, max_h, prefer_order=tuple(supported), allow_wrap=allow_wrap)
        mw = len(m[0]) if m else 0
        if mw > max_w:
            m = vwf.scale_mask(m, sx=max_w / float(mw), sy=1.0)
        return m

    s_lines = norm.split("\n")
    for fname in supported:
        f = fonts[fname]
        for tr in (tracking, 0):
            sp = 2 if fname == "mini" else 3
            m = vwf.render_multiline_mask(f, s_lines, tracking=tr, line_gap=line_gap, space_w=sp if tr == 0 else None, align="center")
            ymin, ymax = vwf._ink_y_bounds(m)
            ih = ymax - ymin + 1
            iw = len(m[0]) if m else 0
            if iw <= max_w and ih <= max_h:
                return m
    f = fonts[supported[-1]]
    m = vwf.render_multiline_mask(f, s_lines, tracking=0, line_gap=line_gap, space_w=2, align="center")
    ymin, ymax = vwf._ink_y_bounds(m)
    ih = ymax - ymin + 1
    iw = len(m[0]) if m else 0
    sx = min(1.0, max_w / float(iw)) if iw else 1.0
    sy = min(1.0, max_h / float(ih)) if ih else 1.0
    return vwf.scale_mask(m, sx=sx, sy=sy) if (sx < 1.0 or sy < 1.0) else m


def collect_map_tiles(words: Sequence[int], skip_indices: Optional[Set[int]] = None) -> Set[int]:
    used = {0}
    for idx, w in enumerate(words):
        if skip_indices and idx in skip_indices:
            continue
        used.add(w & 0x3FF)
    return used


def free_indices_from_protected(total_tiles: int, protected: Set[int], preferred_first: Iterable[int] = ()) -> List[int]:
    prot = set(protected) | {0}
    first = [t for t in preferred_first if t not in prot and 0 < t < total_tiles]
    first_set = set(first)
    rest = [t for t in range(1, total_tiles) if t not in prot and t not in first_set]
    return first + rest


# ---------------------------------------------------------------------------
# Generic $0006BA Sprite Bank Loader / Saver
# ---------------------------------------------------------------------------

def load_sprite_bank(
    rom: bytearray,
    ptr_addr: int,
    size_addr: int,
    count: int,
    tile_addr: int,
    end_addr: int,
) -> Tuple[List[int], List[Tuple[int, int]], List[List[int]], List[List[List[int]]], List[int]]:
    ptrs = [struct.unpack(">I", rom[ptr_addr + i * 4 : ptr_addr + (i + 1) * 4])[0] for i in range(count)]
    szs = [struct.unpack(">H", rom[size_addr + i * 2 : size_addr + (i + 1) * 2])[0] for i in range(count)]
    dims = [(1 << (s & 7), (s >> 8) + 1) for s in szs]
    word_lists = []
    for i, (wt, ht) in enumerate(dims):
        p = ptrs[i]
        word_lists.append(unpack_words(bytes(rom[p : p + wt * ht * 2])))
    tiles = gl_rom.decode_tiles_bytes(bytes(rom[tile_addr:end_addr]))
    return ptrs, dims, word_lists, tiles, szs


def save_sprite_bank(
    rom: bytearray,
    alloc: gl_rom.SpaceAllocator,
    ptrs: Sequence[int],
    word_lists: Sequence[Sequence[int]],
    tile_addr: int,
    end_addr: int,
    tiles: Sequence[Sequence[Sequence[int]]],
    label: str,
) -> None:
    map_start = min(ptrs)
    for i, p in enumerate(ptrs):
        raw = pack_words(word_lists[i])
        rom[p : p + len(raw)] = raw
    raw_tiles = gl_rom.encode_tiles_bytes(tiles)
    if len(raw_tiles) != (end_addr - tile_addr):
        raise AssertionError(f"{label} tile size mismatch: {len(raw_tiles)} != {end_addr - tile_addr}")
    rom[tile_addr:end_addr] = raw_tiles
    alloc.record_patch(map_start, end_addr, label)


# ---------------------------------------------------------------------------
# Area 1: Title Mode Banner (0x09FE2E..0x0A7D50)
# ---------------------------------------------------------------------------

def patch_title_banner(rom: bytearray, alloc: gl_rom.SpaceAllocator, tr: dict, fonts: Dict[str, vwf.BitmapFont]) -> dict:
    map_addr, tile_addr, tile_end = 0x09FE2E, 0x09FED0, 0x0A7D50
    w_t, h_t = 27, 3
    words = unpack_words(bytes(rom[map_addr:tile_addr]))
    other_words = unpack_words(bytes(rom[0x09EF86:map_addr]))
    protected = collect_map_tiles(other_words)
    tiles = gl_rom.decode_tiles_bytes(bytes(rom[tile_addr:tile_end]))

    free = free_indices_from_protected(len(tiles), protected)
    allocator = vwf.TileBankAllocator(tiles, free, allow_flip=True)

    orig_grid = render_region_to_grid(tiles, words, w_t, 0, 0, w_t, h_t, is_sprite=False)
    canvas = make_blank_grid(w_t * 8, h_t * 8, bg=13)
    # Preserve the 3 separator diamond columns (cols 8, 17, 26) for circular 9-tile viewport scrolling
    for c in (8, 17, 26):
        x_col = c * 8
        for y in range(h_t * 8):
            canvas[y][x_col : x_col + 8] = orig_grid[y][x_col : x_col + 8]

    # Stamp the 3 stops into their 64px slots using their dedicated palette-flashed color indices
    slots = [
        ("TOURNAMENT", 0, 64, 1, 0),
        ("FREE PLAY", 72, 64, 2, 1),
        ("COMPETE", 144, 64, 3, 1),
    ]
    disp_font = fonts["display"]
    for label, x0, w_slot, fg_col, trk in slots:
        m = vwf.render_multiline_mask(disp_font, [label], tracking=trk, align="center")
        vwf.stamp_mask_onto(canvas, m, fg=fg_col, x_off=x0 + (w_slot - len(m[0])) // 2, y_off=7)

    # Zero is NOT blank here; bg=13 (non-zero), pal=11
    new_words = vwf.slice_canvas_to_words(canvas, pal=11, allocator=allocator, zero_word_if_all=None, word_fn=gl_rom.tilemap_word)
    rom[map_addr:tile_addr] = pack_words(new_words)
    rom[tile_addr:tile_end] = gl_rom.encode_tiles_bytes(allocator.tiles)
    alloc.record_patch(map_addr, tile_end, "title_banner")
    return {"allocated": len(allocator.allocated), "capacity": len(free)}


# ---------------------------------------------------------------------------
# Area 2: Imperial Edict (0x08E294 tiles d222 + 0x090BBA raw 32x32 map)
# ---------------------------------------------------------------------------

def patch_imperial_edict(rom: bytearray, alloc: gl_rom.SpaceAllocator, tr: dict, fonts: Dict[str, vwf.BitmapFont]) -> dict:
    tile_addr = 0x08E294
    raw_tiles, tile_end = d222.decompress_d222(rom, tile_addr)
    tiles = gl_rom.decode_tiles_bytes(raw_tiles)
    map_addr, map_end = 0x090BBA, 0x0913BA
    words = unpack_words(bytes(rom[map_addr:map_end]))

    skip_indices: Set[int] = set()
    for r in range(3, 14):
        for c in range(4, 29):
            if 11 <= r <= 13 and 4 <= c <= 6:
                continue  # Imperial red seal
            skip_indices.add(r * 32 + c)
    # Also tiles 0..648 are pre-edict scenery/prologue per inventory
    protected = collect_map_tiles(words, skip_indices=skip_indices) | set(range(0, 649))
    free = free_indices_from_protected(len(tiles), protected)
    allocator = vwf.TileBankAllocator(tiles, free, allow_flip=True)

    # Clear entire text zone to parchment 7 and stamp Title + 3 decree lines cleanly
    canvas = render_region_to_grid(tiles, words, 32, 4, 3, 25, 11, is_sprite=False)
    for ty in range(11):
        for tx in range(25):
            r, c = 3 + ty, 4 + tx
            if 11 <= r <= 13 and 4 <= c <= 6:
                continue
            fill_rect(canvas, tx * 8, ty * 8, 8, 8, 7)

    # Top box (c4..28 = 200px, y=0..23): IMPERIAL DECREE
    title_mask = fit_text_mask(fonts, tr["edict"]["en_title"], 188, 16, prefer_order=("banner", "display"))
    vwf.stamp_mask_onto(canvas, title_mask, fg=6, center_rect=(4, 4, 192, 16))

    # Decree 3 lines inside y=24..87; note bottom-left x=0..23, y=64..87 holds the red seal!
    lines = tr["edict"]["en_lines"]
    row_rects = [
        (8, 26, 184, 16),
        (8, 46, 184, 16),
        (28, 66, 168, 16),  # avoid seal on cols 4..6 (x=0..23)
    ]
    for line, rect in zip(lines, row_rects):
        m = fit_text_mask(fonts, line, rect[2], rect[3], prefer_order=("display", "body"))
        vwf.stamp_mask_onto(canvas, m, fg=6, center_rect=rect)

    # Write back everything except the 3x3 seal at (tx=0..2, ty=8..10)
    for ty in range(11):
        for tx in range(25):
            r, c = 3 + ty, 4 + tx
            if 11 <= r <= 13 and 4 <= c <= 6:
                continue
            cell = [canvas[ty * 8 + py][tx * 8 : tx * 8 + 8] for py in range(8)]
            words[r * 32 + c] = allocator.get_or_alloc_word(
                cell, 14, word_fn=lambda ti, p, hflip=False, vflip=False: gl_rom.tilemap_word(ti, p, hflip=hflip, vflip=vflip)
            )

    rom[map_addr:map_end] = pack_words(words)
    alloc.record_patch(map_addr, map_end, "edict_map")
    new_tile_addr = gl_rom.patch_compressed_block(
        rom, alloc, tile_addr, tile_end, gl_rom.encode_tiles_bytes(allocator.tiles), "edict_tiles"
    )
    return {"allocated": len(allocator.allocated), "capacity": len(free), "tile_addr": f"0x{new_tile_addr:06X}"}


# ---------------------------------------------------------------------------
# Area 3: Character Select Headers (0x095018 map, 0x095146 tiles)
# ---------------------------------------------------------------------------

def patch_cs_headers(rom: bytearray, alloc: gl_rom.SpaceAllocator, tr: dict, fonts: Dict[str, vwf.BitmapFont]) -> dict:
    map_addr, tile_addr = 0x095018, 0x095146
    raw_map, map_end = d222.decompress_d222(rom, map_addr)
    raw_tiles, tile_end = d222.decompress_d222(rom, tile_addr)
    words = unpack_words(raw_map)
    tiles = gl_rom.decode_tiles_bytes(raw_tiles)

    # Protect 0 and frame tiles 37..65; replace interior tiles 1..36 across 4 boxes r0..2, c1..7 / 9..15 / 17..23 / 25..31
    protected = {0} | set(range(37, len(tiles)))
    free = free_indices_from_protected(len(tiles), protected)
    allocator = vwf.TileBankAllocator(tiles, free, allow_flip=True)

    cols = [(1, tr["char_select_cols"][0]["en"]), (9, tr["char_select_cols"][1]["en"]),
            (17, tr["char_select_cols"][2]["en"]), (25, tr["char_select_cols"][3]["en"])]
    # Build a clean shared 56x24 wooden nameplate template using the empty center columns (col 3 = tile 4, 27)
    tmpl = render_region_to_grid(tiles, words, 64, 1, 0, 7, 3, is_sprite=False)
    for tx in (1, 2, 4, 5):
        top_clean = tiles[words[0 * 64 + 4] & 0x3FF]
        bot_clean = tiles[words[2 * 64 + 4] & 0x3FF]
        for py in range(8):
            tmpl[py][tx * 8 : tx * 8 + 8] = top_clean[py]
            tmpl[16 + py][tx * 8 : tx * 8 + 8] = bot_clean[py]
    fill_rect(tmpl, 2, 8, 52, 8, 10)  # clean interior of Row 1 while keeping left/right wood frame

    for c0, label in cols:
        canvas = [list(r) for r in tmpl]
        # Keep text cleanly inside Row 1, cols 1..5 (40x8 px) so Row 0 & Row 2 & outer left/right border reuse 8 tiles total (< 20/36)
        m = fit_text_mask(fonts, label, 38, 7, prefer_order=("mini", "body"))
        vwf.stamp_mask_onto(canvas, m, fg=8, shadow=9, center_rect=(8, 8, 40, 8))
        write_grid_to_region(words, 64, c0, 0, 7, 3, canvas, allocator, default_pal=14, zero_word_if_all=None)

    m_out = gl_rom.patch_compressed_block(rom, alloc, map_addr, map_end, pack_words(words), "cs_headers_map")
    t_out = gl_rom.patch_compressed_block(rom, alloc, tile_addr, tile_end, gl_rom.encode_tiles_bytes(allocator.tiles), "cs_headers_tiles")
    return {"allocated": len(allocator.allocated), "capacity": len(free), "addrs": (hex(m_out), hex(t_out))}


# ---------------------------------------------------------------------------
# Area 4: Character Select Nameplates (0x0936F8 map, 0x093C98 tiles)
# ---------------------------------------------------------------------------

def patch_cs_nameplates(rom: bytearray, alloc: gl_rom.SpaceAllocator, tr: dict, fonts: Dict[str, vwf.BitmapFont]) -> dict:
    map_addr, map_end = 0x0936F8, 0x093C98
    tile_addr = 0x093C98
    words = unpack_words(bytes(rom[map_addr:map_end]))  # 720 words: 16 * (8x3=24) + 336 orb/reticle
    raw_tiles, tile_end = d222.decompress_d222(rom, tile_addr)
    tiles = gl_rom.decode_tiles_bytes(raw_tiles)
    orig_tiles = clone_tiles(tiles)
    sel_tbl = struct.unpack(">16H", rom[0x0285DA:0x0285FA])

    # Protect reticle/orb words 384..719 (tiles 335..394); tiles 1..334 are 100% dedicated to the 16 plaques
    protected = {0} | collect_map_tiles(words[384:])
    free = free_indices_from_protected(len(tiles), protected)
    allocator = vwf.TileBankAllocator(tiles, free, allow_flip=True)

    # Two hardware sprite palettes (CS Pal 4 vs CS Pal 8) and per-slot CRAM highlight indices at 0x0285DA
    tmpl4 = render_region_to_grid(orig_tiles, words[0:24], 8, 0, 0, 8, 3, is_sprite=False)
    tmpl8 = render_region_to_grid(orig_tiles, words[4 * 24 : 5 * 24], 8, 0, 0, 8, 3, is_sprite=False)

    for i, ch in enumerate(tr["characters"]):
        v = sel_tbl[i]
        is_pal8 = bool(v & 0x100)
        bg = v & 0xFF
        pal = 8 if is_pal8 else 4
        fg = 6 if is_pal8 else 8
        sh = 5 if is_pal8 else 7
        base = i * 24
        sub_words = list(words[base : base + 24])
        canvas = [list(row) for row in (tmpl8 if is_pal8 else tmpl4)]
        fill_rect(canvas, 3, 3, 50, 18, bg)
        m = fit_text_mask(fonts, ch["en"], 47, 16, prefer_order=("body", "mini", "display"), allow_wrap=True, line_gap=1)
        vwf.stamp_mask_onto(canvas, m, fg=fg, shadow=sh, center_rect=(3, 3, 50, 18))
        write_grid_to_region(sub_words, 8, 0, 0, 8, 3, canvas, allocator, default_pal=pal, zero_word_if_all=0)
        words[base : base + 24] = sub_words

    rom[map_addr:map_end] = pack_words(words)
    alloc.record_patch(map_addr, map_end, "cs_names_map")
    t_out = gl_rom.patch_compressed_block(rom, alloc, tile_addr, tile_end, gl_rom.encode_tiles_bytes(allocator.tiles), "cs_names_tiles")
    return {"allocated": len(allocator.allocated), "capacity": len(free), "tile_addr": f"0x{t_out:06X}"}


# ---------------------------------------------------------------------------
# Area 5: VS Intro Screen (0x0953FE map, 0x095770 ov, 0x09580A tiles)
# ---------------------------------------------------------------------------

def patch_vs_intro(rom: bytearray, alloc: gl_rom.SpaceAllocator, tr: dict, fonts: Dict[str, vwf.BitmapFont]) -> dict:
    map_addr, ov_addr, ov_end, tile_addr = 0x0953FE, 0x095770, 0x09580A, 0x09580A
    raw_map, map_end = d222.decompress_d222(rom, map_addr)
    raw_tiles, tile_end = d222.decompress_d222(rom, tile_addr)
    words = unpack_words(raw_map)
    tiles = gl_rom.decode_tiles_bytes(raw_tiles)

    ov_ptrs = [struct.unpack(">I", rom[ov_addr + i * 4 : ov_addr + (i + 1) * 4])[0] for i in range(7)]
    ov_maps = [unpack_words(bytes(rom[p : p + 18])) for p in ov_ptrs]

    # Identify skip indices: center crest interior (c16..23, r8..26) + 5 diamonds (r2..4, c12..26)
    skip: Set[int] = set()
    for r in range(7, 28):
        for c in range(15, 25):
            skip.add(r * 64 + c)
    for r in range(2, 5):
        for c in range(12, 27):
            skip.add(r * 64 + c)

    protected = collect_map_tiles(words, skip_indices=skip)
    # Also keep diamond corner/edge tiles in ov_0? Wait: corners of r2..4,c12..26 are shared or cleanable;
    # keep corners of ov[0] out of protected only if inside 475..511? Better: pre-reserve 475..511 specifically for diamonds & crest
    # Wait: let's keep outer border of diamonds untouched? Check which pixels in diamond have text (10 and 14)!
    # Keep ANY tile outside 475..511 unless it only appears in skip indices and NOT in protected!
    free = free_indices_from_protected(len(tiles), protected, preferred_first=range(475, len(tiles)))
    orig_tiles = clone_tiles(tiles)
    allocator = vwf.TileBankAllocator(tiles, free, allow_flip=True)

    # Helper to erase yellow/brown text pixels (10, 14) on a diamond by nearest neighbor bg {1..5,6}
    def clean_and_stamp_diamond(orig_3x3_words: Sequence[int], label: str) -> List[int]:
        g = render_region_to_grid(orig_tiles, list(orig_3x3_words), 3, 0, 0, 3, 3, is_sprite=False)
        for y in range(24):
            for x in range(24):
                if g[y][x] in (10, 14):
                    # sample nearest bg pixel in {1,2,3,4,5,6}
                    repl = 3
                    for rad in range(1, 8):
                        found = False
                        for dy, dx in ((-rad, 0), (rad, 0), (0, -rad), (0, rad), (-rad, -rad), (rad, rad)):
                            ny, nx = y + dy, x + dx
                            if 0 <= ny < 24 and 0 <= nx < 24 and g[ny][nx] in (1, 2, 3, 4, 5, 6):
                                repl = g[ny][nx]
                                found = True
                                break
                        if found:
                            break
                    g[y][x] = repl
        m = fit_text_mask(fonts, label, 18, 12, prefer_order=("display", "body"))
        vwf.stamp_mask_onto(g, m, fg=14, shadow=10, center_rect=(3, 6, 18, 12))
        out_w = list(orig_3x3_words)
        write_grid_to_region(out_w, 3, 0, 0, 3, 3, g, allocator, default_pal=3, zero_word_if_all=None)
        return out_w

    # Use spotless Diamond #1 (ov_maps[0]) as clean base template for all 5 diamonds + 7 overlays
    base_d1 = list(ov_maps[0])
    d_labels = tr["vs_intro"]["diamonds"]
    for idx_d, lbl in enumerate(d_labels):
        c0 = 12 + idx_d * 3
        new_sub = clean_and_stamp_diamond(base_d1, lbl)
        for r in range(3):
            for c in range(3):
                words[(2 + r) * 64 + (c0 + c)] = new_sub[r * 3 + c]

    # 7 round overlays sharing the same spotless diamond #1 base
    for idx_ov, lbl in enumerate(tr["vs_intro"]["round_overlays"]):
        new_ov = clean_and_stamp_diamond(base_d1, lbl)
        p = ov_ptrs[idx_ov]
        rom[p : p + 18] = pack_words(new_ov)
    alloc.record_patch(ov_ptrs[0], ov_end, "vs_intro_overlays")

    # Center crest c15..24, r7..27 (10x21 = 80x168 px): preserve zigzag wallpaper {7..12}, erase {1..6, 13, 14, 15}
    crest_grid = render_region_to_grid(orig_tiles, words, 64, 15, 7, 10, 21, is_sprite=False)
    h_cr, w_cr = len(crest_grid), len(crest_grid[0])
    wp_cols = (7, 8, 9, 10, 11, 12)
    orig_cr = [list(row) for row in crest_grid]
    for y in range(h_cr):
        for x in range(w_cr):
            if orig_cr[y][x] not in wp_cols:
                repl = None
                for rad in range(1, 32):
                    for dy, dx in ((0, -rad), (0, rad), (-rad, 0), (rad, 0), (-rad, -rad), (rad, rad), (-rad, rad), (rad, -rad)):
                        ny, nx = y + dy, x + dx
                        if 0 <= ny < h_cr and 0 <= nx < w_cr and orig_cr[ny][nx] in wp_cols:
                            repl = orig_cr[ny][nx]
                            break
                    if repl is not None:
                        break
                crest_grid[y][x] = repl if repl is not None else 11

    # Render vertical dark crimson/gold emblem box for GAMBLING LORD cleanly centered over crest
    fill_rect(crest_grid, 8, 42, 64, 84, 1)
    fill_rect(crest_grid, 10, 44, 60, 80, 3)
    fill_rect(crest_grid, 12, 46, 56, 76, 2)
    m1 = fit_text_mask(fonts, tr["vs_intro"]["en_crest_lines"][0], 52, 18, prefer_order=("banner", "display"))
    m2 = fit_text_mask(fonts, tr["vs_intro"]["en_crest_lines"][1], 52, 18, prefer_order=("banner", "display"))
    vwf.stamp_mask_onto(crest_grid, m1, fg=15, outline=1, shadow=14, neighbors=4, center_rect=(12, 56, 56, 22))
    vwf.stamp_mask_onto(crest_grid, m2, fg=15, outline=1, shadow=14, neighbors=4, center_rect=(12, 88, 56, 22))
    write_grid_to_region(words, 64, 15, 7, 10, 21, crest_grid, allocator, default_pal=2, zero_word_if_all=None)

    m_out = gl_rom.patch_compressed_block(rom, alloc, map_addr, map_end, pack_words(words), "vs_intro_map")
    t_out = gl_rom.patch_compressed_block(rom, alloc, tile_addr, tile_end, gl_rom.encode_tiles_bytes(allocator.tiles), "vs_intro_tiles")
    return {"allocated": len(allocator.allocated), "capacity": len(free), "addrs": (hex(m_out), hex(t_out))}


# ---------------------------------------------------------------------------
# Area 6: Tournament Bracket (BR1 0x097654, BR2 0x09A9AC, BRTiles 0x097B8A)
# ---------------------------------------------------------------------------

def patch_bracket(rom: bytearray, alloc: gl_rom.SpaceAllocator, tr: dict, fonts: Dict[str, vwf.BitmapFont]) -> dict:
    br1_addr, brt_addr, br2_addr = 0x097654, 0x097B8A, 0x09A9AC
    br1_raw, br1_end = d222.decompress_d222(rom, br1_addr)
    brt_raw, brt_end = d222.decompress_d222(rom, brt_addr)
    br2_raw, br2_end = d222.decompress_d222(rom, br2_addr)
    br1_w = unpack_words(br1_raw)
    br2_w = unpack_words(br2_raw)
    tiles = gl_rom.decode_tiles_bytes(brt_raw)

    skip1: Set[int] = set()
    for b in tr["bracket"]["br1"]:
        for r in range(b["rows"][0], b["rows"][1]):  # rows r0, r1 contain text; r2 is bottom scroll shadow
            for c in range(7, 33):
                skip1.add(r * 64 + c)

    skip2: Set[int] = set()
    for b in tr["bracket"]["br2"]:
        for r in range(b["rows"][0], b["rows"][1]):
            for c in range(7, 33):
                skip2.add(r * 64 + c)
    for r in range(4, 13):
        for c in range(11, 29):
            skip2.add(r * 64 + c)

    protected = collect_map_tiles(br1_w, skip1) | collect_map_tiles(br2_w, skip2)
    free = free_indices_from_protected(len(tiles), protected)
    allocator = vwf.TileBankAllocator(tiles, free, allow_flip=True)

    def render_scroll_banner(words: List[int], r0: int, text: str) -> None:
        # Rows r0..r0+1, cols 7..32 (26x2 = 208x16 px)
        g = make_blank_grid(26 * 8, 16, bg=5)
        # Subtle scroll top highlight/trim and bottom border to blend seamlessly with scroll rolls at c4..6, c33..35
        fill_rect(g, 0, 0, 26 * 8, 2, 13)
        fill_rect(g, 0, 2, 26 * 8, 1, 9)
        fill_rect(g, 0, 3, 26 * 8, 11, 5)
        fill_rect(g, 0, 14, 26 * 8, 2, 1)
        m = fit_text_mask(fonts, text, 200, 11, prefer_order=("body", "display", "mini"), tracking=1)
        vwf.stamp_mask_onto(g, m, fg=7, outline=1, shadow=None, neighbors=4, center_rect=(4, 3, 200, 11))
        write_grid_to_region(words, 64, 7, r0, 26, 2, g, allocator, default_pal=0, zero_word_if_all=None)

    for b in tr["bracket"]["br1"]:
        render_scroll_banner(br1_w, b["rows"][0], b["en"])
    for b in tr["bracket"]["br2"]:
        render_scroll_banner(br2_w, b["rows"][0], b["en"])

    # BR2 crest (c11..28, r4..12 = 18x9 = 144x72 px): restore repeating 9x4 wallpaper on r4..7 & r9..12, clean r8 kanji edge
    for r in range(4, 13):
        if r == 8:
            continue
        src_r = 4 + ((r - 4) if r < 8 else (r - 9))
        for c in range(11, 29):
            src_c = 2 + (c - 2) % 9
            br2_w[r * 64 + c] = br2_w[src_r * 64 + src_c]
    g_cr = render_region_to_grid(tiles, br2_w, 64, 11, 4, 18, 9, is_sprite=False)
    orig_cr_r8 = [list(g_cr[y]) for y in range(32, 40)]
    for dy in range(8):
        y = 32 + dy
        for x in range(144):
            if orig_cr_r8[dy][x] in (8, 14):
                repl = None
                for rad in range(1, 24):
                    for ddy, ddx in ((0, -rad), (0, rad), (-rad, 0), (rad, 0)):
                        ny, nx = dy + ddy, x + ddx
                        if 0 <= ny < 8 and 0 <= nx < 144 and orig_cr_r8[ny][nx] in (9, 10, 11, 12, 13):
                            repl = orig_cr_r8[ny][nx]
                            break
                    if repl is not None:
                        break
                g_cr[y][x] = repl if repl is not None else 11
    # Clean central plaque box with rich gold/crimson border centered over (16, 12, 112, 48)
    fill_rect(g_cr, 16, 12, 112, 48, 9)
    fill_rect(g_cr, 18, 14, 108, 44, 5)
    fill_rect(g_cr, 20, 16, 104, 40, 10)
    m_cr = fit_text_mask(fonts, tr["bracket"]["crest"]["en"], 96, 34, prefer_order=("banner", "display"), allow_wrap=True, line_gap=2)
    vwf.stamp_mask_onto(g_cr, m_cr, fg=1, outline=7, shadow=8, neighbors=4, center_rect=(20, 16, 104, 40))
    write_grid_to_region(br2_w, 64, 11, 4, 18, 9, g_cr, allocator, default_pal=0, zero_word_if_all=None)

    a1 = gl_rom.patch_compressed_block(rom, alloc, br1_addr, br1_end, pack_words(br1_w), "bracket_br1_map")
    at = gl_rom.patch_compressed_block(rom, alloc, brt_addr, brt_end, gl_rom.encode_tiles_bytes(allocator.tiles), "bracket_tiles")
    a2 = gl_rom.patch_compressed_block(rom, alloc, br2_addr, br2_end, pack_words(br2_w), "bracket_br2_map")
    return {"allocated": len(allocator.allocated), "capacity": len(free), "addrs": (hex(a1), hex(at), hex(a2))}


# ---------------------------------------------------------------------------
# Area 7: Bracket Nameplates (0x09AED0..0x09D3B0)
# ---------------------------------------------------------------------------

def patch_bracket_nameplates(rom: bytearray, alloc: gl_rom.SpaceAllocator, tr: dict, fonts: Dict[str, vwf.BitmapFont]) -> dict:
    map_addr, tile_addr, tile_end = 0x09AED0, 0x09B250, 0x09D3B0
    words = unpack_words(bytes(rom[map_addr:tile_addr]))  # 16 * 28 (4x7)
    tiles = gl_rom.decode_tiles_bytes(bytes(rom[tile_addr:tile_end]))

    free = list(range(1, len(tiles)))
    allocator = vwf.TileBankAllocator(tiles, free, allow_flip=True)

    new_words: List[int] = []
    for ch in tr["characters"]:
        canvas = make_blank_grid(32, 56, bg=0)
        # Render horizontal wrapped name cleanly inside 32x56 plaque
        m = fit_text_mask(fonts, ch["br_wrapped"], 30, 50, prefer_order=("mini", "body"), allow_wrap=True, tracking=0, line_gap=2)
        vwf.stamp_mask_onto(canvas, m, fg=9, outline=8, neighbors=4, center_rect=(1, 3, 30, 50))
        new_words.extend(
            vwf.slice_canvas_to_words(canvas, pal=1, allocator=allocator, zero_word_if_all=0, word_fn=gl_rom.tilemap_word)
        )

    rom[map_addr:tile_addr] = pack_words(new_words)
    rom[tile_addr:tile_end] = gl_rom.encode_tiles_bytes(allocator.tiles)
    alloc.record_patch(map_addr, tile_end, "bracket_nameplates")
    return {"allocated": len(allocator.allocated), "capacity": len(free)}


# ---------------------------------------------------------------------------
# Area 8: In-Game Nameplates (0x04D956..0x04FB76)
# ---------------------------------------------------------------------------

def patch_ingame_nameplates(rom: bytearray, alloc: gl_rom.SpaceAllocator, tr: dict, fonts: Dict[str, vwf.BitmapFont]) -> dict:
    ptr_addr, tile_addr, tile_end = 0x04D956, 0x04DCF6, 0x04FB76
    ptrs = [struct.unpack(">I", rom[ptr_addr + i * 4 : ptr_addr + (i + 1) * 4])[0] for i in range(16)]
    tiles = gl_rom.decode_tiles_bytes(bytes(rom[tile_addr:tile_end]))

    protected = {0, 1, 2, 3, 11, 19, 29, 40, 66}
    # Preserve row 2 bottom border tiles (0x13, 0x28, etc.) and outer col 0 / col 8
    orig_maps = [unpack_words(bytes(rom[p : p + 54])) for p in ptrs]
    for mw in orig_maps:
        for idx, w in enumerate(mw):
            if (idx % 9 in (0, 8)) or (idx >= 18 and (w & 0x3FF) in (0x13, 0x28)):
                protected.add(w & 0x3FF)
    # Specifically construct from blank nameplate canvas row0..1 + keep row2
    blank_row0 = [0xE003, 0xE01D, 0xE01D, 0xE01D, 0xE01D, 0xE01D, 0xE01D, 0xE01D, 0xE803]
    blank_row1 = [0xE00B, 0xE042, 0xE042, 0xE042, 0xE042, 0xE042, 0xE042, 0xE042, 0xE80B]
    blank_row2 = [0xE013, 0xE028, 0xE028, 0xE028, 0xE028, 0xE028, 0xE028, 0xE028, 0xE813]
    protected.update({w & 0x3FF for w in (blank_row0 + blank_row1 + blank_row2)})

    free = free_indices_from_protected(len(tiles), protected)
    allocator = vwf.TileBankAllocator(tiles, free, allow_flip=True)

    blank_words = blank_row0 + blank_row1 + blank_row2
    blank_canvas = render_region_to_grid(tiles, blank_words, 9, 0, 0, 9, 3, is_sprite=False)

    mini_font = fonts["mini"]
    for i, ch in enumerate(tr["characters"]):
        canvas = [list(row) for row in blank_canvas]
        m = vwf.render_multiline_mask(mini_font, [ch["en"]], tracking=1, align="center")
        if not m or len(m[0]) > 54:
            m_tight = vwf.render_multiline_mask(mini_font, [ch["en"]], tracking=0, space_w=1, align="center")
            if m_tight and len(m_tight[0]) <= 54:
                m = m_tight
            else:
                short_name = ch["wrapped"].replace("\n", " ")
                m_short = vwf.render_multiline_mask(mini_font, [short_name], tracking=1, align="center")
                if not m_short or len(m_short[0]) > 54:
                    m_short = vwf.render_multiline_mask(mini_font, [short_name], tracking=0, space_w=1, align="center")
                m = m_short if (m_short and len(m_short[0]) <= 54) else fit_text_mask(
                    fonts, short_name, 54, 11, prefer_order=("mini", "body", "display"), allow_wrap=False, tracking=0
                )
        vwf.stamp_mask_onto(canvas, m, fg=8, center_rect=(8, 4, 56, 12))
        out_w = list(blank_words)
        # Only rewrite cols 1..7, rows 0..1; row 2 and cols 0/8 stay verbatim
        for ty in (0, 1):
            for tx in range(1, 8):
                cell = [canvas[ty * 8 + py][tx * 8 : tx * 8 + 8] for py in range(8)]
                out_w[ty * 9 + tx] = allocator.get_or_alloc_word(
                    cell, 14, word_fn=lambda ti, p, hflip=False, vflip=False: gl_rom.tilemap_word(ti, p, hflip=hflip, vflip=vflip, prio=True)
                )
        rom[ptrs[i] : ptrs[i] + 54] = pack_words(out_w)

    rom[tile_addr:tile_end] = gl_rom.encode_tiles_bytes(allocator.tiles)
    alloc.record_patch(0x04D996, tile_end, "ingame_nameplates")
    return {"allocated": len(allocator.allocated), "capacity": len(free)}


# ---------------------------------------------------------------------------
# Area 9: Jade Emperor Speeches (0x0FC128..0x0FF0F6 + 0x00E8AC / 0x00E8C2)
# ---------------------------------------------------------------------------

def patch_jade_emperor(rom: bytearray, alloc: gl_rom.SpaceAllocator, tr: dict, fonts: Dict[str, vwf.BitmapFont]) -> dict:
    ptr_addr, size_addr, tile_addr, tile_end = 0x0FC128, 0x0FC2D2, 0x0FC698, 0x0FEFB8
    stream_ptr_addr, stream_data_start, stream_end = 0x0FEFB8, 0x0FEFD0, 0x0FF0F6
    ptrs, dims, word_lists, tiles, _ = load_sprite_bank(rom, ptr_addr, size_addr, 71, tile_addr, tile_end)

    # Protect sprites #0..#5 + tile 0 (for blank sprite #70)
    protected = {0} | {w & 0x3FF for i in range(6) for w in word_lists[i]}
    free_tiles = free_indices_from_protected(len(tiles), protected)
    tile_alloc = vwf.TileBankAllocator(tiles, free_tiles, allow_flip=True)

    # Disable special-char Y/X/substitute hooks at 0x00E8AC and 0x00E8C2
    rom[0x00E8AC:0x00E8B0] = bytes.fromhex("0C45FFFF")
    rom[0x00E8C2:0x00E8C6] = bytes.fromhex("0C45FFFF")
    alloc.record_patch(0x00E8AC, 0x00E8C6, "jade_emperor_code_hooks")

    # Convert 0x00E8F8..0x00E918 sprite loop from column-major (3x5 vertical Chinese) to row-major (left-to-right English)
    rom[0x00E8F8:0x00E918] = bytes.fromhex("064300100C43004C660000D6363C001C064400100C4400D1660000C6383C0081")
    alloc.record_patch(0x00E8F8, 0x00E918, "jade_emperor_row_loop")

    # Pack 16x16 (2x2) unique text cells into sprites #6..#68 (63 sprites); #69 shares orig ptr with #13 so repoint #69 -> #70
    cell_to_sprite: Dict[Tuple[Tuple[int, ...], ...], int] = {}
    next_sprite = 6
    streams_encoded: List[List[int]] = []

    def sprite_for_cell(cell16: List[List[int]]) -> int:
        nonlocal next_sprite
        if all(v == 0 for row in cell16 for v in row):
            return 70
        key = tuple(tuple(row) for row in cell16)
        if key in cell_to_sprite:
            return cell_to_sprite[key]
        if next_sprite >= 69:
            raise RuntimeError("Jade Emperor exceeded 63 text sprites (#6..#68)")
        words_2x2 = vwf.slice_canvas_to_words(cell16, pal=15, allocator=tile_alloc, zero_word_if_all=0, word_fn=gl_rom.sprite_word)
        word_lists[next_sprite] = words_2x2
        cell_to_sprite[key] = next_sprite
        sp_id = next_sprite
        next_sprite += 1
        return sp_id

    for st in tr["jade_emperor_streams"]:
        seq: List[int] = []
        for page_lines in st["pages"]:
            page_ids: List[int] = []
            for row_idx in range(5):
                line = page_lines[row_idx] if row_idx < len(page_lines) else ""
                if not line:
                    page_ids.extend([70] * 3)
                    continue
                row_canvas = make_blank_grid(48, 16, bg=0)
                m = fit_text_mask(fonts, line, 44, 14, prefer_order=("body", "mini"), allow_wrap=False, tracking=1)
                mw = len(m[0]) if m else 0
                x_off = 2 if mw <= 44 else max(0, (48 - mw) // 2)
                vwf.stamp_mask_onto(row_canvas, m, fg=6, outline=1, neighbors=4, x_off=x_off, y_off=max(0, (16 - len(m)) // 2))
                for c in range(3):
                    cell16 = [row_canvas[py][c * 16 : c * 16 + 16] for py in range(16)]
                    page_ids.append(sprite_for_cell(cell16))
            seq.extend(page_ids)
        streams_encoded.append(seq)

    # Avoid #69 overwriting #13 (both original ptrs point to 0x0FC4CC): repoint #69 to blank sprite #70
    ptrs[69] = ptrs[70]
    word_lists[69] = list(word_lists[70])
    struct.pack_into(">I", rom, ptr_addr + 69 * 4, ptrs[70])
    alloc.record_patch(ptr_addr + 69 * 4, ptr_addr + 70 * 4, "jade_emperor_ptr69")
    save_sprite_bank(rom, alloc, ptrs, word_lists, tile_addr, tile_end, tile_alloc.tiles, "jade_emperor_bank")

    # Pack streams [len_w = len(seq) - 1, *seq] at 0x0FEFD0..0x0FF0F6 and update pointers 0x0FEFB8..0x0FEFD0
    cur = stream_data_start
    for i, seq in enumerate(streams_encoded):
        struct.pack_into(">I", rom, stream_ptr_addr + i * 4, cur)
        blob = pack_words([len(seq) - 1] + seq)
        if cur + len(blob) > stream_end:
            raise RuntimeError(f"Jade Emperor stream {i} overflows 0x{stream_end:06X}")
        rom[cur : cur + len(blob)] = blob
        cur += len(blob)
    if cur < stream_end:
        rom[cur:stream_end] = b"\x00" * (stream_end - cur)
    alloc.record_patch(stream_ptr_addr, stream_end, "jade_emperor_streams")
    return {
        "sprites_used": next_sprite - 6,
        "sprites_cap": 64,
        "tiles_allocated": len(tile_alloc.allocated),
        "tiles_cap": len(free_tiles),
        "stream_bytes_used": cur - stream_data_start,
    }


# ---------------------------------------------------------------------------
# Area 10: Set 1 Table Prompts & Taunts (0x0379EE..0x03E80A)
# ---------------------------------------------------------------------------

def patch_set1(rom: bytearray, alloc: gl_rom.SpaceAllocator, tr: dict, fonts: Dict[str, vwf.BitmapFont]) -> dict:
    ptr_addr, size_addr, tile_addr, tile_end = 0x0379EE, 0x037B50, 0x0385AA, 0x03E80A
    ptrs, dims, word_lists, tiles, _ = load_sprite_bank(rom, ptr_addr, size_addr, 59, tile_addr, tile_end)

    # Set 1 is self-contained; only #21, #22, #45 are kept verbatim, freeing all other tiles for deduplicated rebuilds
    protected = {0} | {w & 0x3FF for idx in (21, 22, 45) for w in word_lists[idx]}
    free = free_indices_from_protected(len(tiles), protected)
    orig_tiles = clone_tiles(tiles)
    allocator = vwf.TileBankAllocator(tiles, free, allow_flip=True)

    def _clean_red_pill(grid_src: List[List[int]], w_p: int, h_p: int) -> List[List[int]]:
        out = [list(r) for r in grid_src]
        for y in range(4, h_p - 4):
            xs_red = [x for x in range(w_p) if grid_src[y][x] in (1, 2, 5, 10, 14, 15)]
            if not xs_red:
                continue
            vals = [grid_src[y][x] for x in xs_red if grid_src[y][x] in (1, 2, 5, 10)]
            if not vals:
                continue
            bg_row = Counter(vals).most_common(1)[0][0]
            x_l, x_r = min(xs_red) + 3, max(xs_red) - 3
            for x in range(x_l, x_r + 1):
                if out[y][x] in (3, 14, 15):
                    out[y][x] = bg_row
        return out

    # Shared clean templates so matching frames (#0..3, #5..8/#17..18, #10..13) deduplicate borders
    tmpl_panel_0 = render_region_to_grid(orig_tiles, word_lists[0], 8, 0, 0, 8, 4, is_sprite=True)
    clear_rect_row_mode(tmpl_panel_0, 3, 5, 64 - 6, 32 - 10, keep_colors={1, 2, 3, 4, 5})
    tmpl_tile_5 = render_region_to_grid(orig_tiles, word_lists[5], 2, 0, 0, 2, 3, is_sprite=True)
    clear_rect_row_mode(tmpl_tile_5, 2, 4, 12, 16, keep_colors={1, 2, 3, 4, 5})
    tmpl_stamp_10 = _clean_red_pill(render_region_to_grid(orig_tiles, word_lists[10], 4, 0, 0, 4, 4, is_sprite=True), 32, 32)

    texts = tr["set1"]
    for idx in range(59):
        key = str(idx)
        if idx in (21, 22, 45) or key not in texts:
            continue
        txt = texts[key]
        wt, ht = dims[idx]
        w_px, h_px = wt * 8, ht * 8
        pal = (word_lists[idx][0] >> 12) & 0xF
        orig_grid = render_region_to_grid(orig_tiles, word_lists[idx], wt, 0, 0, wt, ht, is_sprite=True)

        if idx in (0, 1, 2, 3):  # 8x4 green bevel panel
            canvas = [list(r) for r in tmpl_panel_0]
            m = fit_text_mask(fonts, txt, w_px - 10, 14, prefer_order=("display", "body"))
            vwf.stamp_mask_onto(canvas, m, fg=7, shadow=6, center_rect=(3, 8, w_px - 6, 16))
        elif idx in (4, 16):  # 16x3 (cols 0..9) / 8x3 (cols 0..6)
            canvas = [list(r) for r in orig_grid]
            xs = [x for y in range(h_px) for x in range(w_px) if orig_grid[y][x] != 0]
            px0, px1 = min(xs) + 3, max(xs) - 2
            clear_rect_row_mode(canvas, px0, 4, px1 - px0, h_px - 8, keep_colors={1, 2, 3, 4, 5})
            m = fit_text_mask(fonts, txt, px1 - px0, 12, prefer_order=("body", "mini", "display"))
            vwf.stamp_mask_onto(canvas, m, fg=7, center_rect=(px0, 4, px1 - px0, h_px - 8))
        elif idx in (5, 6, 7, 8, 17, 18):  # 2x3 compact green tiles (16x24)
            canvas = [list(r) for r in tmpl_tile_5]
            m = fit_text_mask(fonts, txt, 13, 12, prefer_order=("mini", "body"), tracking=0)
            vwf.stamp_mask_onto(canvas, m, fg=7, center_rect=(1, 4, 14, 16))
        elif idx == 9:  # 2x3 white Mahjong tile (Dealer marker), bg=8/5/14, dark ink 15
            canvas = [list(r) for r in orig_grid]
            clear_rect_row_mode(canvas, 2, 7, 12, 13, keep_colors={8, 5, 14})
            m = fit_text_mask(fonts, txt, 12, 11, prefer_order=("mini",), tracking=0)
            vwf.stamp_mask_onto(canvas, m, fg=15, center_rect=(2, 7, 12, 13))
        elif idx in (10, 11, 12, 13, 14, 19):  # Red circular/pill stamps pal=15
            if idx in (10, 11, 12, 13):
                canvas = [list(r) for r in tmpl_stamp_10]
            else:
                canvas = _clean_red_pill(orig_grid, w_px, h_px)
            xs = [x for y in range(h_px) for x in range(w_px) if orig_grid[y][x] != 0]
            px0, px1 = min(xs) + 3, max(xs) - 2
            m = fit_text_mask(fonts, txt, px1 - px0, h_px - 10, prefer_order=("display", "body", "mini"), allow_wrap=True)
            vwf.stamp_mask_onto(canvas, m, fg=15, shadow=14, center_rect=(px0, 4, px1 - px0, h_px - 8))
        elif idx == 15:  # 16x6 Exhausted Draw plaque
            canvas = [list(r) for r in orig_grid]
            clear_rect_row_mode(canvas, 6, 8, w_px - 12, h_px - 16, keep_colors={1, 2, 3, 4})
            m = fit_text_mask(fonts, txt, w_px - 16, 16, prefer_order=("banner", "display"))
            vwf.stamp_mask_onto(canvas, m, fg=7, shadow=6, center_rect=(6, 16, w_px - 12, 16))
        else:
            # Transparent-bg overlay text (#20=13, #23..44 & #54=7, #46..51=11, #52=12, #53,55,56..58=15)
            fg_map = {20: 13, 52: 12, 53: 15, 55: 15, 56: 15, 57: 15, 58: 15}
            fg = fg_map.get(idx, 11 if 46 <= idx <= 51 else 7)
            canvas = make_blank_grid(w_px, h_px, bg=0)
            if h_px >= 24:
                # Place in middle 16px band (rows 1..2) to avoid allocating empty edge tiles in rows 0 and 3
                m = fit_text_mask(fonts, txt, w_px, 14, prefer_order=("display", "body", "mini"), allow_wrap=False)
                vwf.stamp_mask_onto(canvas, m, fg=fg, center_rect=(0, 8, w_px, 16))
            else:
                m = fit_text_mask(fonts, txt, w_px, 13, prefer_order=("body", "mini", "display"), allow_wrap=False)
                vwf.stamp_mask_onto(canvas, m, fg=fg, center_rect=(0, 1, w_px, 14))

        word_lists[idx] = vwf.slice_canvas_to_words(canvas, pal=pal, allocator=allocator, zero_word_if_all=0, word_fn=gl_rom.sprite_word)

    save_sprite_bank(rom, alloc, ptrs, word_lists, tile_addr, tile_end, allocator.tiles, "set1")
    return {"allocated": len(allocator.allocated), "capacity": len(free)}


# ---------------------------------------------------------------------------
# Area 11: Set 2 Yaku, Rivals & HUD (0x03E80A..0x043FA6)
# ---------------------------------------------------------------------------

def patch_set2(rom: bytearray, alloc: gl_rom.SpaceAllocator, tr: dict, fonts: Dict[str, vwf.BitmapFont]) -> dict:
    ptr_addr, size_addr, tile_addr, tile_end = 0x03E80A, 0x03EA26, 0x03F4E6, 0x043FA6
    ptrs, dims, word_lists, tiles, _ = load_sprite_bank(rom, ptr_addr, size_addr, 90, tile_addr, tile_end)

    protected = {0} | {w & 0x3FF for w in word_lists[84]}
    free = free_indices_from_protected(len(tiles), protected)
    orig_tiles = clone_tiles(tiles)
    allocator = vwf.TileBankAllocator(tiles, free, allow_flip=True)

    texts = tr["set2"]
    chars = tr["characters"]
    for idx in range(90):
        if idx == 84:
            continue
        wt, ht = dims[idx]
        w_px, h_px = wt * 8, ht * 8
        pal = (word_lists[idx][0] >> 12) & 0xF
        orig_grid = render_region_to_grid(orig_tiles, word_lists[idx], wt, 0, 0, wt, ht, is_sprite=True)

        if idx == 81:  # 2x3 Dealer tile
            canvas = [list(r) for r in orig_grid]
            clear_rect_row_mode(canvas, 2, 7, 12, 13, keep_colors={8, 5, 14})
            m = fit_text_mask(fonts, texts["81"], 12, 12, prefer_order=("mini",), tracking=0)
            vwf.stamp_mask_onto(canvas, m, fg=15, center_rect=(2, 7, 12, 13))
        elif idx == 51:  # 8x2 STK  [gap]  +  [gap]
            canvas = make_blank_grid(w_px, h_px, bg=0)
            m_a = fit_text_mask(fonts, texts["51_a"], 16, 7, prefer_order=("mini",), tracking=0)
            m_b = fit_text_mask(fonts, texts["51_b"], 16, 7, prefer_order=("mini",), tracking=0)
            vwf.stamp_mask_onto(canvas, m_a, fg=15, center_rect=(0, 8, 16, 8))
            vwf.stamp_mask_onto(canvas, m_b, fg=15, center_rect=(32, 8, 16, 8))
        elif 63 <= idx <= 78:
            name = chars[idx - 63]["en"]
            canvas = make_blank_grid(w_px, h_px, bg=0)
            # Single tile row y=8..15 keeps all 89 sprites safely inside Set 2's 591-tile bank
            m = fit_text_mask(fonts, name, w_px, 7, prefer_order=("mini",), tracking=0)
            vwf.stamp_mask_onto(canvas, m, fg=11, center_rect=(0, 8, w_px, 8))
        elif idx == 83 and texts.get("83") == "LOST":
            # Crisp 16x7 condensed bitmap ("." = 1px gap) so LOST fits 2x2 cleanly without downscaling
            g_l = ("#..", "#..", "#..", "#..", "#..", "#..", "###")
            g_o = (".##.", "#..#", "#..#", "#..#", "#..#", "#..#", ".##.")
            g_s = (".##", "#..", "#..", ".#.", "..#", "..#", "##.")
            g_t = ("###", ".#.", ".#.", ".#.", ".#.", ".#.", ".#.")
            lost_mask = [[1 if c == "#" else 0 for c in f"{g_l[r]}.{g_o[r]}.{g_s[r]}.{g_t[r]}"] for r in range(7)]
            canvas = make_blank_grid(w_px, h_px, bg=0)
            vwf.stamp_mask_onto(canvas, lost_mask, fg=15, center_rect=(0, 8, w_px, 8))
        elif str(idx) in texts:
            canvas = make_blank_grid(w_px, h_px, bg=0)
            m = fit_text_mask(fonts, texts[str(idx)], w_px, 7, prefer_order=("mini",), tracking=0)
            mw = len(m[0]) if m else 0
            # Align 8px multiples for shared prefixes like STREAK 1..10
            x_off = max(0, ((w_px - mw) // 16) * 8) if idx in range(53, 63) else None
            if x_off is not None:
                vwf.stamp_mask_onto(canvas, m, fg=15, x_off=x_off, y_off=8)
            else:
                vwf.stamp_mask_onto(canvas, m, fg=15, center_rect=(0, 8, w_px, 8))
        else:
            continue

        word_lists[idx] = vwf.slice_canvas_to_words(canvas, pal=pal, allocator=allocator, zero_word_if_all=0, word_fn=gl_rom.sprite_word)

    save_sprite_bank(rom, alloc, ptrs, word_lists, tile_addr, tile_end, allocator.tiles, "set2")
    return {"allocated": len(allocator.allocated), "capacity": len(free)}


# ---------------------------------------------------------------------------
# Area 12: Set 3 Opponent Quips (0x043FA6..0x04D956)
# ---------------------------------------------------------------------------

def patch_set3(rom: bytearray, alloc: gl_rom.SpaceAllocator, tr: dict, fonts: Dict[str, vwf.BitmapFont]) -> dict:
    ptr_addr, size_addr, tile_addr, tile_end = 0x043FA6, 0x04425E, 0x045CF6, 0x04D956
    ptrs, dims, word_lists, tiles, _ = load_sprite_bank(rom, ptr_addr, size_addr, 116, tile_addr, tile_end)

    protected = {0} | {w & 0x3FF for idx in (114, 115) for w in word_lists[idx]}
    free = free_indices_from_protected(len(tiles), protected)
    allocator = vwf.TileBankAllocator(tiles, free, allow_flip=True)

    texts = tr["set3"]
    for idx in range(114):
        key = str(idx)
        if key not in texts:
            continue
        wt, ht = dims[idx]
        w_px, h_px = wt * 8, ht * 8
        pal = (word_lists[idx][0] >> 12) & 0xF
        canvas = make_blank_grid(w_px, h_px, bg=0)
        # Keep quips inside single tile row y=8..15 (7px mini) so all 114 sprites fit comfortably inside 939 free tiles
        m = fit_text_mask(fonts, texts[key], w_px - 2, 7, prefer_order=("mini",), tracking=0)
        vwf.stamp_mask_onto(canvas, m, fg=15, center_rect=(0, 8, w_px, 8))
        word_lists[idx] = vwf.slice_canvas_to_words(canvas, pal=pal, allocator=allocator, zero_word_if_all=0, word_fn=gl_rom.sprite_word)

    save_sprite_bank(rom, alloc, ptrs, word_lists, tile_addr, tile_end, allocator.tiles, "set3")
    return {"allocated": len(allocator.allocated), "capacity": len(free)}


# ---------------------------------------------------------------------------
# Area 13: Cheat Skill Overlay (0x07F4D0..0x0826D8)
# ---------------------------------------------------------------------------

def patch_cheat_skill(rom: bytearray, alloc: gl_rom.SpaceAllocator, tr: dict, fonts: Dict[str, vwf.BitmapFont]) -> dict:
    alt_addr, m1_addr, m2_addr, tile_addr, tile_end = 0x07F4D0, 0x07F4D8, 0x07FB18, 0x080158, 0x0826D8
    m1_w = unpack_words(bytes(rom[m1_addr:m2_addr]))
    m2_w = unpack_words(bytes(rom[m2_addr:tile_addr]))
    tiles = gl_rom.decode_tiles_bytes(bytes(rom[tile_addr:tile_end]))

    skip: Set[int] = set()
    # stats c4..8 r0..5; left names c1..9 & left costs c10..11 r8..17; right names c12..20 & costs c21..22 r8..17
    for r in range(0, 6):
        for c in range(4, 9):
            skip.add(r * 32 + c)
    for r in range(8, 18):
        for c in range(1, 23):
            skip.add(r * 32 + c)

    protected = collect_map_tiles(m2_w) | collect_map_tiles(m1_w, skip_indices=skip) | set(range(1, 66))
    free = free_indices_from_protected(len(tiles), protected)
    allocator = vwf.TileBankAllocator(tiles, free, allow_flip=True)

    # Stats: c4..8, r0..1 / r2..3 / r4..5 (5x2 = 40x16 px)
    for st in tr["cheat_skill"]["stats"]:
        r0 = st["rows"][0]
        g = make_blank_grid(40, 16, bg=0)
        m = fit_text_mask(fonts, st["en"], 38, 12, prefer_order=("mini", "body"), tracking=0)
        vwf.stamp_mask_onto(g, m, fg=3, shadow=2, center_rect=(1, 2, 38, 12))
        write_grid_to_region(m1_w, 32, 4, r0, 5, 2, g, allocator, default_pal=0, default_prio=True, zero_word_if_all=0)

    # Left and Right skill rows preserve exact palette ramp (L: 6,8,10,12,14; R: 7,9,11,13,15), costs fg=1
    left_colors = [(6, 8), (8, 10), (10, 12), (12, 14), (14, 1)]
    right_colors = [(7, 9), (9, 11), (11, 13), (13, 15), (15, None)]

    for i, sk in enumerate(tr["cheat_skill"]["left_skills"]):
        r0 = sk["rows"][0]
        fg, sh = left_colors[i]
        # Name in c1..9 (72x16)
        g_name = make_blank_grid(72, 16, bg=0)
        m_n = fit_text_mask(fonts, sk["en"], 70, 13, prefer_order=("mini", "body"), tracking=0)
        vwf.stamp_mask_onto(g_name, m_n, fg=fg, shadow=sh, x_off=2, y_off=max(0, (16 - len(m_n)) // 2))
        write_grid_to_region(m1_w, 32, 1, r0, 9, 2, g_name, allocator, default_pal=0, default_prio=True, zero_word_if_all=0)
        # Cost in c10..11 (16x16)
        g_cost = make_blank_grid(16, 16, bg=0)
        m_c = fit_text_mask(fonts, sk["cost"], 14, 13, prefer_order=("mini", "body"), tracking=0)
        vwf.stamp_mask_onto(g_cost, m_c, fg=1, center_rect=(0, 1, 16, 14))
        write_grid_to_region(m1_w, 32, 10, r0, 2, 2, g_cost, allocator, default_pal=0, default_prio=True, zero_word_if_all=0)

    for i, sk in enumerate(tr["cheat_skill"]["right_skills"]):
        r0 = sk["rows"][0]
        fg, sh = right_colors[i]
        # Name in c12..20 (72x16)
        g_name = make_blank_grid(72, 16, bg=0)
        m_n = fit_text_mask(fonts, sk["en"], 70, 13, prefer_order=("mini", "body"), tracking=0)
        vwf.stamp_mask_onto(g_name, m_n, fg=fg, shadow=sh, x_off=2, y_off=max(0, (16 - len(m_n)) // 2))
        write_grid_to_region(m1_w, 32, 12, r0, 9, 2, g_name, allocator, default_pal=0, default_prio=True, zero_word_if_all=0)
        # Cost in c21..22 (16x16)
        g_cost = make_blank_grid(16, 16, bg=0)
        m_c = fit_text_mask(fonts, sk["cost"], 14, 13, prefer_order=("mini", "body"), tracking=0)
        vwf.stamp_mask_onto(g_cost, m_c, fg=1, center_rect=(0, 1, 16, 14))
        write_grid_to_region(m1_w, 32, 21, r0, 2, 2, g_cost, allocator, default_pal=0, default_prio=True, zero_word_if_all=0)

    # Update alt 2x2 stat at 0x07F4D0 to mirror VITAL's leftmost 2x2 (r0..1, c4..5)
    alt_w = [m1_w[0 * 32 + 4], m1_w[0 * 32 + 5], m1_w[1 * 32 + 4], m1_w[1 * 32 + 5]]
    rom[alt_addr:m1_addr] = pack_words(alt_w)
    rom[m1_addr:m2_addr] = pack_words(m1_w)
    rom[tile_addr:tile_end] = gl_rom.encode_tiles_bytes(allocator.tiles)
    alloc.record_patch(alt_addr, m2_addr, "cheat_skill_maps")
    alloc.record_patch(tile_addr, tile_end, "cheat_skill_tiles")
    return {"allocated": len(allocator.allocated), "capacity": len(free)}


# ---------------------------------------------------------------------------
# Area 14: Leaderboard Screen LB2 (0x087C98..0x089C98)
# ---------------------------------------------------------------------------

def patch_leaderboard(rom: bytearray, alloc: gl_rom.SpaceAllocator, tr: dict, fonts: Dict[str, vwf.BitmapFont]) -> dict:
    map_addr, tile_addr, tile_end = 0x087C98, 0x088C98, 0x089C98
    words = unpack_words(bytes(rom[map_addr:tile_addr]))
    tiles = gl_rom.decode_tiles_bytes(bytes(rom[tile_addr:tile_end]))

    protected = {0} | set(range(0, 18)) | {44} | set(range(103, 128))
    free = free_indices_from_protected(len(tiles), protected)
    allocator = vwf.TileBankAllocator(tiles, free, allow_flip=True)

    # Clear header row r6..7 cols 3..35 (inside borders) and rank labels c3..6 rows 8..15 to solid bg=5
    solid_word = gl_rom.tilemap_word(13, 3)  # tile 13 is solid color 5!
    for r in (6, 7):
        for c in range(3, 36):
            words[r * 64 + c] = solid_word
    for r in range(8, 16):
        for c in range(3, 7):
            words[r * 64 + c] = solid_word

    for h in tr["leaderboard"]["headers"]:
        c0, c1 = h["cols"]
        wt = c1 - c0 + 1
        g = make_blank_grid(wt * 8, 16, bg=5)
        m = fit_text_mask(fonts, h["en"], wt * 8 - 2, 13, prefer_order=("mini", "body"), tracking=0)
        vwf.stamp_mask_onto(g, m, fg=6, center_rect=(0, 1, wt * 8, 14))
        write_grid_to_region(words, 64, c0, 6, wt, 2, g, allocator, default_pal=3, zero_word_if_all=None)

    for rk in tr["leaderboard"]["ranks"]:
        r0 = rk["rows"][0]
        g = make_blank_grid(32, 16, bg=5)
        m = fit_text_mask(fonts, rk["en"], 30, 13, prefer_order=("mini", "body"), tracking=0)
        vwf.stamp_mask_onto(g, m, fg=rk["fg"], center_rect=(0, 1, 32, 14))
        write_grid_to_region(words, 64, 3, r0, 4, 2, g, allocator, default_pal=3, zero_word_if_all=None)

    rom[map_addr:tile_addr] = pack_words(words)
    rom[tile_addr:tile_end] = gl_rom.encode_tiles_bytes(allocator.tiles)
    alloc.record_patch(map_addr, tile_end, "leaderboard_lb2")
    return {"allocated": len(allocator.allocated), "capacity": len(free)}


# ---------------------------------------------------------------------------
# Area 15: Mini-Game Backgrounds (0x011B64..0x01B0C4)
# ---------------------------------------------------------------------------

def patch_minigames_bg(rom: bytearray, alloc: gl_rom.SpaceAllocator, tr: dict, fonts: Dict[str, vwf.BitmapFont]) -> dict:
    specs = [
        ("triple_hit",  0x011B64, 0x012B64, 0x014864),
        ("twin_cannon", 0x014864, 0x015864, 0x017DE4),
        ("blackjack",   0x017DE4, 0x018DE4, 0x01B0C4),
    ]
    stats = {}
    for mg, (mg_id, map_addr, tile_addr, tile_end) in zip(tr["minigames_bg"], specs):
        assert mg["id"] == mg_id
        words = unpack_words(bytes(rom[map_addr:tile_addr]))
        tiles = gl_rom.decode_tiles_bytes(bytes(rom[tile_addr:tile_end]))

        # Protect everything outside signboard interior c14..25, r2..4 (note r5 is signboard bottom border)
        skip = {r * 64 + c for r in range(2, 5) for c in range(14, 26)}
        protected = collect_map_tiles(words, skip_indices=skip)
        # Preserve top row r2 top border and side borders at c14, c25 (keep signboard border tiles safe too? No, we copy canvas from orig!)
        free = free_indices_from_protected(len(tiles), protected)
        allocator = vwf.TileBankAllocator(tiles, free, allow_flip=True)

        canvas = render_region_to_grid(tiles, words, 64, 14, 2, 12, 3, is_sprite=False)
        # Interior of signboard is x=4..91, y=4..23
        fill_rect(canvas, 4, 4, 88, 20, 3)
        m = fit_text_mask(fonts, mg["en"], 84, 15, prefer_order=("display", "banner", "body"), tracking=1)
        vwf.stamp_mask_onto(canvas, m, fg=4, shadow=5, center_rect=(4, 4, 88, 20))
        pal = (words[2 * 64 + 14] >> 12) & 0xF
        write_grid_to_region(words, 64, 14, 2, 12, 3, canvas, allocator, default_pal=pal, zero_word_if_all=None)

        # Clean diagonal Chinese felt watermark pixels cleanly in-place ONLY on non-border felt tiles not used elsewhere
        # Replace colors {6, 7} (MG0/MG1 watermark) on felt-only tiles inside c3..36, r6..24 with checkerboard/dominant felt {10, 11}
        if mg_id in ("triple_hit", "twin_cannon"):
            felt_tiles = {words[r * 64 + c] & 0x3FF for r in range(7, 23) for c in range(3, 36)}
            non_felt_tiles = {words[r * 64 + c] & 0x3FF for r in range(32) for c in range(64)
                              if not (7 <= r <= 22 and 3 <= c <= 35)} | {0}
            cleanable = (felt_tiles - non_felt_tiles) - set(allocator.allocated)
            for ti in cleanable:
                t = allocator.tiles[ti]
                # Only scrub tiles whose pixels are strictly felt {10, 11, 12} + watermark {6, 7} (not card boxes {1,2,3,4,9})
                pix_set = {v for row in t for v in row}
                if pix_set <= {6, 7, 10, 11, 12} and (pix_set & {6, 7}):
                    for py in range(8):
                        for px in range(8):
                            if t[py][px] in (6, 7):
                                t[py][px] = 11 if (py >= 2) else 10

        rom[map_addr:tile_addr] = pack_words(words)
        rom[tile_addr:tile_end] = gl_rom.encode_tiles_bytes(allocator.tiles)
        alloc.record_patch(map_addr, tile_end, f"minigame_{mg_id}")
        stats[mg_id] = {"allocated": len(allocator.allocated), "capacity": len(free)}
    return stats


# ---------------------------------------------------------------------------
# Area 16: Bank 3 Mini-Game Sprites (0x01B0C4..0x01FCE8)
# ---------------------------------------------------------------------------

def patch_bank3(rom: bytearray, alloc: gl_rom.SpaceAllocator, tr: dict, fonts: Dict[str, vwf.BitmapFont]) -> dict:
    ptr_addr, size_addr, tile_addr, tile_end = 0x01B0C4, 0x01B16C, 0x01B8C8, 0x01FCE8
    ptrs, dims, word_lists, tiles, _ = load_sprite_bank(rom, ptr_addr, size_addr, 28, tile_addr, tile_end)

    skip_ids = {4, 5, 6, 9, 10, 13, 14, 15, 16, 17, 19, 20, 21, 26, 27}
    protected = {0} | {w & 0x3FF for i in skip_ids for w in word_lists[i]}
    # Also protect #18 rows r0 and r3..9 (rows r1..r2 cols 2..13 replaced!) and outer borders
    wt18, ht18 = dims[18]
    for r in range(ht18):
        for c in range(wt18):
            if r not in (1, 2) or c < 2 or c > 13:
                protected.add(word_lists[18][r * wt18 + c] & 0x3FF)

    free = free_indices_from_protected(len(tiles), protected)
    orig_tiles = clone_tiles(tiles)
    allocator = vwf.TileBankAllocator(tiles, free, allow_flip=True)
    b3_txt = tr["bank3_sprites"]

    # #0: 16x2 PRESS START KEY (fg=11, shadow=3, bg=0)
    wt, ht = dims[0]
    g0 = make_blank_grid(wt * 8, ht * 8, bg=0)
    m0 = fit_text_mask(fonts, b3_txt["0"], wt * 8 - 4, 14, prefer_order=("display", "body"), tracking=1)
    vwf.stamp_mask_onto(g0, m0, fg=11, shadow=3, center_rect=(0, 0, wt * 8, ht * 8))
    word_lists[0] = vwf.slice_canvas_to_words(g0, pal=(word_lists[0][0] >> 12) & 0xF, allocator=allocator, zero_word_if_all=0, word_fn=gl_rom.sprite_word)

    # #1, #2, #3: 4x7 plaques (actual plaque is x=0..23, y=2..52; clear interior x=2..21, y=4..50 -> bg=9)
    for idx in (1, 2, 3):
        orig = render_region_to_grid(orig_tiles, word_lists[idx], dims[idx][0], 0, 0, dims[idx][0], dims[idx][1], is_sprite=True)
        fill_rect(orig, 2, 4, 20, 47, 9)
        m = fit_text_mask(fonts, b3_txt[str(idx)], 20, 42, prefer_order=("mini",), allow_wrap=True, tracking=0, line_gap=2)
        vwf.stamp_mask_onto(orig, m, fg=11, outline=8, neighbors=4, center_rect=(2, 4, 20, 47))
        word_lists[idx] = vwf.slice_canvas_to_words(orig, pal=(word_lists[idx][0] >> 12) & 0xF, allocator=allocator, zero_word_if_all=0, word_fn=gl_rom.sprite_word)

    # #7, #8 (cols 6..11 blank = x=48..95); #11, #12 (cols 8..13 blank = x=64..111)
    for idx, left_k, right_k, x_l_w, x_r_0 in [
        (7, "7_left", "7_right", 48, 96),
        (8, "8_left", "8_right", 48, 96),
        (11, "11_left", "11_right", 64, 112),
        (12, "12_left", "12_right", 64, 112),
    ]:
        g = make_blank_grid(128, 16, bg=0)
        ml = fit_text_mask(fonts, b3_txt[left_k], x_l_w - 2, 13, prefer_order=("display", "body"), tracking=0)
        mr = fit_text_mask(fonts, b3_txt[right_k], 128 - x_r_0, 13, prefer_order=("mini", "body"), tracking=0)
        vwf.stamp_mask_onto(g, ml, fg=11, center_rect=(0, 1, x_l_w, 14))
        vwf.stamp_mask_onto(g, mr, fg=11, center_rect=(x_r_0, 1, 128 - x_r_0, 14))
        word_lists[idx] = vwf.slice_canvas_to_words(g, pal=(word_lists[idx][0] >> 12) & 0xF, allocator=allocator, zero_word_if_all=0, word_fn=gl_rom.sprite_word)

    # #18: 16x10 Odds board -> replace rows r1..r2, c2..13 (12x2 = 96x16 px)
    g18_words = word_lists[18][wt18 + 2 : wt18 + 14] + word_lists[18][2 * wt18 + 2 : 2 * wt18 + 14]
    g18 = render_region_to_grid(orig_tiles, g18_words, 12, 0, 0, 12, 2, is_sprite=True)
    fill_rect(g18, 0, 0, 96, 11, 11)
    clear_rect_row_mode(g18, 0, 11, 96, 5, keep_colors={1, 2, 3, 4, 5, 6, 11})
    m18 = fit_text_mask(fonts, b3_txt["18_header"], 92, 9, prefer_order=("mini", "body"), tracking=0)
    vwf.stamp_mask_onto(g18, m18, fg=8, center_rect=(0, 0, 96, 11))
    pal18 = (word_lists[18][0] >> 12) & 0xF
    new18 = vwf.slice_canvas_to_words(g18, pal=pal18, allocator=allocator, zero_word_if_all=None, word_fn=gl_rom.sprite_word)
    word_lists[18][wt18 + 2 : wt18 + 14] = new18[:12]
    word_lists[18][2 * wt18 + 2 : 2 * wt18 + 14] = new18[12:24]

    def _clean_oval_btn(grid: List[List[int]], x0: int, w: int) -> None:
        for y in range(len(grid)):
            vals = [grid[y][x] for x in range(x0, x0 + w) if grid[y][x] in (1, 2, 3, 4, 5)]
            if not vals:
                continue
            bg = Counter(vals).most_common(1)[0][0]
            for x in range(x0, x0 + w):
                if grid[y][x] in (12, 15):
                    grid[y][x] = bg

    # #22 (8x3: dual button HIT | STAY), #23 (4x3: HIT), #24 (4x3: STAY)
    g22 = render_region_to_grid(orig_tiles, word_lists[22], 8, 0, 0, 8, 3, is_sprite=True)
    _clean_oval_btn(g22, 0, 32)
    _clean_oval_btn(g22, 32, 32)
    m22l = fit_text_mask(fonts, b3_txt["22_left"], 22, 12, prefer_order=("mini", "body"), tracking=0)
    m22r = fit_text_mask(fonts, b3_txt["22_right"], 22, 12, prefer_order=("mini", "body"), tracking=0)
    vwf.stamp_mask_onto(g22, m22l, fg=15, shadow=8, center_rect=(4, 5, 24, 14))
    vwf.stamp_mask_onto(g22, m22r, fg=15, shadow=8, center_rect=(36, 5, 24, 14))
    word_lists[22] = vwf.slice_canvas_to_words(g22, pal=(word_lists[22][0] >> 12) & 0xF, allocator=allocator, zero_word_if_all=0, word_fn=gl_rom.sprite_word)

    for idx, key in [(23, "23"), (24, "24")]:
        g = render_region_to_grid(orig_tiles, word_lists[idx], 4, 0, 0, 4, 3, is_sprite=True)
        _clean_oval_btn(g, 0, 32)
        m = fit_text_mask(fonts, b3_txt[key], 22, 12, prefer_order=("mini", "body"), tracking=0)
        vwf.stamp_mask_onto(g, m, fg=15, shadow=8, center_rect=(4, 5, 24, 14))
        word_lists[idx] = vwf.slice_canvas_to_words(g, pal=(word_lists[idx][0] >> 12) & 0xF, allocator=allocator, zero_word_if_all=0, word_fn=gl_rom.sprite_word)

    # #25: 16x5 (cols 0..9 active = 80x40 plaque; clear x=3..76, y=3..36 while preserving gold border)
    g25 = render_region_to_grid(orig_tiles, word_lists[25], 16, 0, 0, 16, 5, is_sprite=True)
    clear_rect_row_mode(g25, 3, 3, 74, 34, keep_colors={1, 2, 5, 9})
    m25 = fit_text_mask(fonts, b3_txt["25"], 66, 22, prefer_order=("banner", "display"))
    vwf.stamp_mask_onto(g25, m25, fg=15, outline=8, shadow=14, neighbors=4, center_rect=(4, 4, 72, 31))
    word_lists[25] = vwf.slice_canvas_to_words(g25, pal=(word_lists[25][0] >> 12) & 0xF, allocator=allocator, zero_word_if_all=0, word_fn=gl_rom.sprite_word)

    save_sprite_bank(rom, alloc, ptrs, word_lists, tile_addr, tile_end, allocator.tiles, "bank3")
    return {"allocated": len(allocator.allocated), "capacity": len(free)}


# ---------------------------------------------------------------------------
# Area 17: Ending Credits (0x024CCC map d222, 0x024EB8 tiles d222)
# ---------------------------------------------------------------------------

def patch_ending_credits(rom: bytearray, alloc: gl_rom.SpaceAllocator, tr: dict, fonts: Dict[str, vwf.BitmapFont]) -> dict:
    map_addr, tile_addr = 0x024CCC, 0x024EB8
    raw_map, map_end = d222.decompress_d222(rom, map_addr)
    raw_tiles, tile_end = d222.decompress_d222(rom, tile_addr)
    words = unpack_words(raw_map)  # 32x64
    tiles = gl_rom.decode_tiles_bytes(raw_tiles)

    # Keep rows 57..63 (FUNTECH ENTERTAINMENT CORP. 1995) completely intact!
    protected = collect_map_tiles(words[57 * 32 :])
    # Zero out rows 0..55 first so we rewrite cleanly within <= 240 total tiles!
    for idx in range(56 * 32):
        words[idx] = 0
    free = free_indices_from_protected(len(tiles), protected)
    allocator = vwf.TileBankAllocator(tiles, free, allow_flip=True)

    # Render credit rows compactly using 16px-tall rows centered horizontally in 32-col (256px) viewport
    credits = tr["ending_credits"]
    cur_row = 1
    for entry in credits:
        if "role" in entry:
            g = make_blank_grid(256, 16, bg=0)
            mr = fit_text_mask(fonts, entry["role"], 220, 14, prefer_order=("body", "mini"), tracking=1)
            vwf.stamp_mask_onto(g, mr, fg=8, center_rect=(0, 1, 256, 14))
            write_grid_to_region(words, 32, 0, cur_row, 32, 2, g, allocator, default_pal=7, zero_word_if_all=0)
            cur_row += 3
            for name in entry["names"]:
                gn = make_blank_grid(256, 16, bg=0)
                mn = fit_text_mask(fonts, name, 220, 14, prefer_order=("body", "mini"), tracking=1)
                vwf.stamp_mask_onto(gn, mn, fg=7, center_rect=(0, 1, 256, 14))
                write_grid_to_region(words, 32, 0, cur_row, 32, 2, gn, allocator, default_pal=7, zero_word_if_all=0)
                cur_row += 3
            cur_row += 2
        elif "company_en" in entry:
            # Put DUNHUANG TECHNOLOGY cleanly right above FUNTECH (at row 52..54)
            gc = make_blank_grid(256, 24, bg=0)
            mc = fit_text_mask(fonts, entry["company_en"], 232, 16, prefer_order=("display", "body"), tracking=1)
            vwf.stamp_mask_onto(gc, mc, fg=11, center_rect=(0, 4, 256, 16))
            write_grid_to_region(words, 32, 0, 52, 32, 3, gc, allocator, default_pal=7, zero_word_if_all=0)

    # Ensure strictly <= 240 tiles total
    assert len(allocator.tiles) == 240
    m_out = gl_rom.patch_compressed_block(rom, alloc, map_addr, map_end, pack_words(words), "ending_map")
    t_out = gl_rom.patch_compressed_block(rom, alloc, tile_addr, tile_end, gl_rom.encode_tiles_bytes(allocator.tiles), "ending_tiles")
    return {"allocated": len(allocator.allocated), "capacity": len(free), "addrs": (hex(m_out), hex(t_out))}


# ---------------------------------------------------------------------------
# Static Verification Contact Sheets (read back directly from patched ROM!)
# ---------------------------------------------------------------------------

def _default_palette() -> List[Tuple[int, int, int]]:
    return [
        (24, 24, 34),    # 0: transparent / backdrop dark slate
        (28, 36, 48),    # 1: dark outline / shadow
        (52, 72, 92),    # 2: mid dark
        (78, 108, 128),  # 3: mid blue/green panel
        (110, 152, 165), # 4: mid highlight
        (46, 98, 62),    # 5: felt / panel body
        (215, 70, 58),   # 6: dark crimson / ink
        (246, 242, 224), # 7: cream white text
        (158, 34, 30),   # 8: bold red ink
        (228, 186, 86),  # 9: warm gold
        (206, 198, 168), # 10: parchment / cream fill
        (252, 232, 96),  # 11: bright yellow
        (238, 224, 196), # 12: warm beige
        (86, 212, 192),  # 13: cyan highlight
        (240, 150, 48),  # 14: orange / amber
        (255, 255, 255), # 15: pure white
    ]


def _grid_to_image(grid: Sequence[Sequence[int]], scale: int = 2) -> Image.Image:
    pal = _default_palette()
    h = len(grid)
    w = len(grid[0]) if h else 0
    im = Image.new("RGB", (w, h))
    px = im.load()
    for y in range(h):
        row = grid[y]
        for x in range(w):
            px[x, y] = pal[row[x] & 0xF]
    return im.resize((w * scale, h * scale), Image.NEAREST) if scale != 1 else im


def _make_sheet(items: Sequence[Tuple[str, Sequence[Sequence[int]]]], cols: int, scale: int, out_path: Path) -> None:
    thumbs = [(lbl, _grid_to_image(g, scale=scale)) for lbl, g in items]
    cell_w = max(im.width for _, im in thumbs) + 12
    cell_h = max(im.height for _, im in thumbs) + 22
    rows = (len(thumbs) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cell_w + 8, rows * cell_h + 8), (18, 20, 28))
    draw = ImageDraw.Draw(sheet)
    for idx, (lbl, im) in enumerate(thumbs):
        r, c = divmod(idx, cols)
        x0, y0 = 4 + c * cell_w, 4 + r * cell_h
        draw.rectangle([x0, y0, x0 + cell_w - 4, y0 + cell_h - 4], outline=(60, 70, 90))
        draw.text((x0 + 4, y0 + 2), lbl, fill=(210, 220, 240))
        sheet.paste(im, (x0 + 4, y0 + 16))
    sheet.save(out_path)


def _find_d222_or_orig(rom: bytearray, orig_addr: int, code_scan_end: int = 0x037000) -> int:
    try:
        d222.decompress_d222(rom, orig_addr)
        return orig_addr
    except Exception:
        # Read relocated address from lea patch in code
        # Caller can pass exact addrs from stats if relocated; scan known table not needed when stats passed!
        raise


def generate_verification_sheets(rom: bytearray, stats: dict, out_dir: Path = NOTES_DIR) -> List[Path]:
    """Decode every patched asset back from `rom` and save contact sheets under `notes/`."""
    paths: List[Path] = []

    def _d222_addr(orig: int, hint: Optional[str] = None) -> int:
        if hint:
            return int(hint, 16)
        return orig

    # 1. verify_screens.png
    screen_items: List[Tuple[str, List[List[int]]]] = []

    # Title banner
    tb_w = unpack_words(bytes(rom[0x09FE2E:0x09FED0]))
    tb_t = gl_rom.decode_tiles_bytes(bytes(rom[0x09FED0:0x0A7D50]))
    screen_items.append(("Title Banner", render_region_to_grid(tb_t, tb_w, 27, 0, 0, 27, 3)))

    # Edict
    ed_t = gl_rom.decode_tiles_bytes(d222.decompress_d222(rom, _d222_addr(0x08E294, stats["edict"].get("tile_addr")))[0])
    ed_w = unpack_words(bytes(rom[0x090BBA:0x0913BA]))
    screen_items.append(("Imperial Edict", render_region_to_grid(ed_t, ed_w, 32, 3, 2, 27, 13)))

    # CS Headers
    csh_m = unpack_words(d222.decompress_d222(rom, int(stats["cs_headers"]["addrs"][0], 16))[0])
    csh_t = gl_rom.decode_tiles_bytes(d222.decompress_d222(rom, int(stats["cs_headers"]["addrs"][1], 16))[0])
    screen_items.append(("CS Headers", render_region_to_grid(csh_t, csh_m, 64, 0, 0, 32, 3)))

    # VS Intro crest + 5 diamonds + overlay #1
    vs_m = unpack_words(d222.decompress_d222(rom, int(stats["vs_intro"]["addrs"][0], 16))[0])
    vs_t = gl_rom.decode_tiles_bytes(d222.decompress_d222(rom, int(stats["vs_intro"]["addrs"][1], 16))[0])
    screen_items.append(("VS Header", render_region_to_grid(vs_t, vs_m, 64, 12, 2, 15, 3)))
    ov1_p = struct.unpack(">I", rom[0x095770:0x095774])[0]
    screen_items.append(("VS Ov1", render_region_to_grid(vs_t, unpack_words(bytes(rom[ov1_p : ov1_p + 18])), 3, 0, 0, 3, 3)))
    screen_items.append(("VS Crest", render_region_to_grid(vs_t, vs_m, 64, 15, 7, 10, 21)))

    # Bracket BR1 top + BR2 crest
    br1_m = unpack_words(d222.decompress_d222(rom, int(stats["bracket"]["addrs"][0], 16))[0])
    br_t = gl_rom.decode_tiles_bytes(d222.decompress_d222(rom, int(stats["bracket"]["addrs"][1], 16))[0])
    br2_m = unpack_words(d222.decompress_d222(rom, int(stats["bracket"]["addrs"][2], 16))[0])
    screen_items.append(("BR1 M1", render_region_to_grid(br_t, br1_m, 64, 4, 50, 32, 3)))
    screen_items.append(("BR1 M4", render_region_to_grid(br_t, br1_m, 64, 4, 1, 32, 3)))
    screen_items.append(("BR2 M7", render_region_to_grid(br_t, br2_m, 64, 4, 14, 32, 3)))
    screen_items.append(("BR2 Crest", render_region_to_grid(br_t, br2_m, 64, 11, 4, 18, 9)))

    # Cheat Skill + LB2
    cs_m1 = unpack_words(bytes(rom[0x07F4D8:0x07FB18]))
    cs_t = gl_rom.decode_tiles_bytes(bytes(rom[0x080158:0x0826D8]))
    screen_items.append(("CheatSkill", render_region_to_grid(cs_t, cs_m1, 32, 0, 0, 24, 19)))

    lb_w = unpack_words(bytes(rom[0x087C98:0x088C98]))
    lb_t = gl_rom.decode_tiles_bytes(bytes(rom[0x088C98:0x089C98]))
    screen_items.append(("Leaderboard", render_region_to_grid(lb_t, lb_w, 64, 1, 5, 37, 12)))

    # Jade Emperor Stream 0 Page 0 & Page 1
    _, j_dims, j_ws, j_t, _ = load_sprite_bank(rom, 0x0FC128, 0x0FC2D2, 71, 0x0FC698, 0x0FEFB8)
    s0_p = struct.unpack(">I", rom[0x0FEFB8:0x0FEFBC])[0]
    s0_cnt = struct.unpack(">H", rom[s0_p : s0_p + 2])[0] + 1
    s0_ids = struct.unpack(f">{s0_cnt}H", rom[s0_p + 2 : s0_p + 2 + s0_cnt * 2])
    j_p0 = make_blank_grid(48, 80, bg=0)
    j_p1 = make_blank_grid(48, 80, bg=0)
    for slot, sid in enumerate(s0_ids[:15]):
        r, c = divmod(slot, 3)
        g = render_region_to_grid(j_t, j_ws[sid], 2, 0, 0, 2, 2, is_sprite=True)
        for py in range(16):
            j_p0[r * 16 + py][c * 16 : c * 16 + 16] = g[py]
    for slot, sid in enumerate(s0_ids[15:30]):
        r, c = divmod(slot, 3)
        g = render_region_to_grid(j_t, j_ws[sid], 2, 0, 0, 2, 2, is_sprite=True)
        for py in range(16):
            j_p1[r * 16 + py][c * 16 : c * 16 + 16] = g[py]
    screen_items.append(("Jade S0 P0", j_p0))
    screen_items.append(("Jade S0 P1", j_p1))

    # Ending credits top & bottom
    end_m = unpack_words(d222.decompress_d222(rom, int(stats["ending"]["addrs"][0], 16))[0])
    end_t = gl_rom.decode_tiles_bytes(d222.decompress_d222(rom, int(stats["ending"]["addrs"][1], 16))[0])
    screen_items.append(("Credits Top", render_region_to_grid(end_t, end_m, 32, 0, 0, 32, 30)))
    screen_items.append(("Credits Bot", render_region_to_grid(end_t, end_m, 32, 0, 50, 32, 14)))

    p1 = out_dir / "verify_screens.png"
    _make_sheet(screen_items, cols=2, scale=2, out_path=p1)
    paths.append(p1)

    # 2. verify_nameplates.png (CS 8x3, BN 4x7, NP 9x3)
    np_items: List[Tuple[str, List[List[int]]]] = []
    csn_w = unpack_words(bytes(rom[0x0936F8:0x093C98]))
    csn_t = gl_rom.decode_tiles_bytes(d222.decompress_d222(rom, int(stats["cs_names"]["tile_addr"], 16))[0])
    sel_tbl = struct.unpack(">16H", rom[0x0285DA:0x0285FA])
    bn_w = unpack_words(bytes(rom[0x09AED0:0x09B250]))
    bn_t = gl_rom.decode_tiles_bytes(bytes(rom[0x09B250:0x09D3B0]))
    in_ptrs = [struct.unpack(">I", rom[0x04D956 + i * 4 : 0x04D95A + i * 4])[0] for i in range(16)]
    in_t = gl_rom.decode_tiles_bytes(bytes(rom[0x04DCF6:0x04FB76]))
    for i in range(16):
        cs_g = render_region_to_grid(csn_t, csn_w[i * 24 : (i + 1) * 24], 8, 0, 0, 8, 3)
        v = sel_tbl[i]
        is_pal8 = bool(v & 0x100)
        remap = {v & 0xFF: 12, (6 if is_pal8 else 8): 8, (5 if is_pal8 else 7): 1}
        for ry in range(3, 21):
            for rx in range(3, 53):
                if cs_g[ry][rx] in remap:
                    cs_g[ry][rx] = remap[cs_g[ry][rx]]
        np_items.append((f"CS#{i}", cs_g))
        np_items.append((f"BN#{i}", render_region_to_grid(bn_t, bn_w[i * 28 : (i + 1) * 28], 4, 0, 0, 4, 7)))
        in_w = unpack_words(bytes(rom[in_ptrs[i] : in_ptrs[i] + 54]))
        np_items.append((f"NP#{i}", render_region_to_grid(in_t, in_w, 9, 0, 0, 9, 3)))
    p2 = out_dir / "verify_nameplates.png"
    _make_sheet(np_items, cols=6, scale=2, out_path=p2)
    paths.append(p2)

    # 3. verify_set1.png, verify_set2.png, verify_set3.png
    for fname, addr_info, cols_cnt in [
        ("verify_set1.png", (0x0379EE, 0x037B50, 59, 0x0385AA, 0x03E80A), 6),
        ("verify_set2.png", (0x03E80A, 0x03EA26, 90, 0x03F4E6, 0x043FA6), 6),
        ("verify_set3.png", (0x043FA6, 0x04425E, 116, 0x045CF6, 0x04D956), 6),
    ]:
        _, dims_b, ws_b, ts_b, _ = load_sprite_bank(rom, *addr_info)
        items = [(f"#{i}", render_region_to_grid(ts_b, ws_b[i], dims_b[i][0], 0, 0, dims_b[i][0], dims_b[i][1], is_sprite=True))
                 for i in range(len(ws_b))]
        po = out_dir / fname
        _make_sheet(items, cols=cols_cnt, scale=2, out_path=po)
        paths.append(po)

    # 4. verify_minigames.png (3 signboards + felt sample + all 28 Bank 3 sprites)
    mg_items: List[Tuple[str, List[List[int]]]] = []
    for name, ma, ta, te in [
        ("MG0 Sign", 0x011B64, 0x012B64, 0x014864),
        ("MG1 Sign", 0x014864, 0x015864, 0x017DE4),
        ("MG2 Sign", 0x017DE4, 0x018DE4, 0x01B0C4),
    ]:
        mw = unpack_words(bytes(rom[ma:ta]))
        mt = gl_rom.decode_tiles_bytes(bytes(rom[ta:te]))
        mg_items.append((name, render_region_to_grid(mt, mw, 64, 13, 1, 14, 5)))
        if name != "MG2 Sign":
            mg_items.append((name[:3] + " Felt", render_region_to_grid(mt, mw, 64, 6, 8, 12, 8)))
    _, b3_d, b3_w, b3_t, _ = load_sprite_bank(rom, 0x01B0C4, 0x01B16C, 28, 0x01B8C8, 0x01FCE8)
    for i in range(28):
        mg_items.append((f"B3#{i}", render_region_to_grid(b3_t, b3_w[i], b3_d[i][0], 0, 0, b3_d[i][0], b3_d[i][1], is_sprite=True)))
    p_mg = out_dir / "verify_minigames.png"
    _make_sheet(mg_items, cols=4, scale=2, out_path=p_mg)
    paths.append(p_mg)

    return paths
