"""Variable-width bitmap font loader, text styling effects, and 8x8 tile deduplicator for Gambling Lord."""

import json
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from PIL import Image

from gl_rom import TileGrid, TileKey, flip_tile_grid, tilemap_word

Grid2D = List[List[int]]

# Crisp 5x7 proportional pixel glyphs (used for tight 32x16 / 64x16 / 32x48 labels)
_MINI_5X7: Dict[str, List[str]] = {
    "A": ["01110", "10001", "10001", "11111", "10001", "10001", "10001"],
    "B": ["11110", "10001", "10001", "11110", "10001", "10001", "11110"],
    "C": ["01111", "10000", "10000", "10000", "10000", "10000", "01111"],
    "D": ["11110", "10001", "10001", "10001", "10001", "10001", "11110"],
    "E": ["11111", "10000", "10000", "11110", "10000", "10000", "11111"],
    "F": ["11111", "10000", "10000", "11110", "10000", "10000", "10000"],
    "G": ["01111", "10000", "10000", "10111", "10001", "10001", "01111"],
    "H": ["10001", "10001", "10001", "11111", "10001", "10001", "10001"],
    "I": ["111", "010", "010", "010", "010", "010", "111"],
    "J": ["00111", "00010", "00010", "00010", "10010", "10010", "01100"],
    "K": ["10001", "10010", "10100", "11000", "10100", "10010", "10001"],
    "L": ["10000", "10000", "10000", "10000", "10000", "10000", "11111"],
    "M": ["10001", "11011", "10101", "10101", "10001", "10001", "10001"],
    "N": ["10001", "11001", "10101", "10011", "10001", "10001", "10001"],
    "O": ["01110", "10001", "10001", "10001", "10001", "10001", "01110"],
    "P": ["11110", "10001", "10001", "11110", "10000", "10000", "10000"],
    "Q": ["01110", "10001", "10001", "10001", "10101", "10010", "01101"],
    "R": ["11110", "10001", "10001", "11110", "10100", "10010", "10001"],
    "S": ["01111", "10000", "10000", "01110", "00001", "00001", "11110"],
    "T": ["11111", "00100", "00100", "00100", "00100", "00100", "00100"],
    "U": ["10001", "10001", "10001", "10001", "10001", "10001", "01110"],
    "V": ["10001", "10001", "10001", "10001", "01010", "01010", "00100"],
    "W": ["10001", "10001", "10001", "10101", "10101", "11011", "10001"],
    "X": ["10001", "10001", "01010", "00100", "01010", "10001", "10001"],
    "Y": ["10001", "10001", "01010", "00100", "00100", "00100", "00100"],
    "Z": ["11111", "00001", "00010", "00100", "01000", "10000", "11111"],
    "0": ["01110", "10001", "10011", "10101", "11001", "10001", "01110"],
    "1": ["010", "110", "010", "010", "010", "010", "111"],
    "2": ["01110", "10001", "00001", "00110", "01000", "10000", "11111"],
    "3": ["11110", "00001", "00001", "01110", "00001", "00001", "11110"],
    "4": ["00110", "01010", "10010", "11111", "00010", "00010", "00010"],
    "5": ["11111", "10000", "11110", "00001", "00001", "10001", "01110"],
    "6": ["01110", "10000", "11110", "10001", "10001", "10001", "01110"],
    "7": ["11111", "00001", "00010", "00100", "01000", "01000", "01000"],
    "8": ["01110", "10001", "10001", "01110", "10001", "10001", "01110"],
    "9": ["01110", "10001", "10001", "01111", "00001", "00001", "01110"],
    "!": ["1", "1", "1", "1", "1", "0", "1"],
    "?": ["01110", "10001", "00010", "00100", "00100", "00000", "00100"],
    ".": ["0", "0", "0", "0", "0", "0", "1"],
    ",": ["00", "00", "00", "00", "00", "01", "10"],
    ":": ["0", "1", "0", "0", "0", "1", "0"],
    "-": ["000", "000", "000", "111", "000", "000", "000"],
    "'": ["1", "1", "0", "0", "0", "0", "0"],
    "/": ["0001", "0001", "0010", "0010", "0100", "1000", "1000"],
    "+": ["000", "010", "010", "111", "010", "010", "000"],
    "*": ["000", "101", "010", "111", "010", "101", "000"],
    "&": ["01100", "10010", "10100", "01000", "10101", "10010", "01101"],
    "a": ["0000", "0000", "0111", "0001", "0111", "1001", "0111"],
    "b": ["1000", "1000", "1110", "1001", "1001", "1001", "1110"],
    "c": ["0000", "0000", "0111", "1000", "1000", "1000", "0111"],
    "d": ["0001", "0001", "0111", "1001", "1001", "1001", "0111"],
    "e": ["0000", "0000", "0110", "1001", "1111", "1000", "0111"],
    "f": ["0011", "0100", "1110", "0100", "0100", "0100", "0100"],
    "g": ["0000", "0111", "1001", "1001", "0111", "0001", "0110"],
    "h": ["1000", "1000", "1110", "1001", "1001", "1001", "1001"],
    "i": ["1", "0", "1", "1", "1", "1", "1"],
    "j": ["001", "000", "001", "001", "001", "101", "010"],
    "k": ["1000", "1000", "1010", "1100", "1100", "1010", "1001"],
    "l": ["1", "1", "1", "1", "1", "1", "1"],
    "m": ["00000", "00000", "11010", "10101", "10101", "10001", "10001"],
    "n": ["0000", "0000", "1110", "1001", "1001", "1001", "1001"],
    "o": ["0000", "0000", "0110", "1001", "1001", "1001", "0110"],
    "p": ["0000", "1110", "1001", "1001", "1110", "1000", "1000"],
    "q": ["0000", "0111", "1001", "1001", "0111", "0001", "0001"],
    "r": ["0000", "0000", "0111", "1000", "1000", "1000", "1000"],
    "s": ["0000", "0000", "0111", "1000", "0110", "0001", "1110"],
    "t": ["010", "010", "111", "010", "010", "010", "001"],
    "u": ["0000", "0000", "1001", "1001", "1001", "1001", "0111"],
    "v": ["0000", "0000", "1001", "1001", "1001", "0110", "0110"],
    "w": ["00000", "00000", "10001", "10001", "10101", "10101", "01010"],
    "x": ["0000", "0000", "1001", "0110", "0110", "1001", "1001"],
    "y": ["0000", "1001", "1001", "0111", "0001", "1001", "0110"],
    "z": ["0000", "0000", "1111", "0010", "0100", "1000", "1111"],
}


class BitmapFont:
    """Grid-packed monochrome bitmap font with per-glyph tight horizontal bounds."""

    def __init__(self, png_path: Optional[Path] = None, json_path: Optional[Path] = None) -> None:
        self.glyphs: Dict[str, Tuple[int, Grid2D]] = {}
        self.advances: Dict[str, int] = {}
        if png_path is None or json_path is None:
            self.cell_w = 5
            self.cell_h = 7
            self.pad = 0
            self.ascii_start = 32
            for ch, rows in _MINI_5X7.items():
                grid = [[int(c) for c in r] for r in rows]
                self.glyphs[ch] = (len(rows[0]), grid)
            self.glyphs[" "] = (2, [[0] * 2 for _ in range(7)])
            return

        meta = json.loads(json_path.read_text(encoding="utf-8"))
        self.cell_w = int(meta["cell_w"])
        self.cell_h = int(meta["cell_h"])
        self.pad = int(meta.get("pad", 1))
        self.ascii_start = int(meta.get("ascii_start", 0))
        self.advances = dict(meta.get("advances", {}))

        im = Image.open(png_path).convert("RGB")
        cols = (im.width - self.pad) // (self.cell_w + self.pad)
        px = im.load()

        for code in range(self.ascii_start, 128):
            ch = chr(code)
            idx = code - self.ascii_start
            row_i, col_i = divmod(idx, cols)
            x0 = self.pad + col_i * (self.cell_w + self.pad)
            y0 = self.pad + row_i * (self.cell_h + self.pad)
            if y0 + self.cell_h > im.height or x0 + self.cell_w > im.width:
                continue

            raw: Grid2D = []
            xs: List[int] = []
            for y in range(self.cell_h):
                r: List[int] = []
                for x in range(self.cell_w):
                    rgb = px[x0 + x, y0 + y]
                    on = 1 if (rgb[0] + rgb[1] + rgb[2]) < 380 else 0
                    r.append(on)
                    if on:
                        xs.append(x)
                raw.append(r)

            if xs:
                xmin, xmax = min(xs), max(xs)
                trimmed = [r[xmin : xmax + 1] for r in raw]
                self.glyphs[ch] = (xmax - xmin + 1, trimmed)

        sp_w = int(self.advances.get(" ", max(3, self.cell_w // 3)))
        self.glyphs[" "] = (sp_w, [[0] * sp_w for _ in range(self.cell_h)])

    def get_glyph(self, ch: str, scale_x: float = 1.0, space_w: Optional[int] = None) -> Tuple[int, Grid2D]:
        """Return (width, 2D mask) for character `ch`, optionally stretched horizontally."""
        if ch == "·":
            ch = "*" if "*" in self.glyphs else "."
        if ch == " ":
            w = space_w if space_w is not None else self.glyphs[" "][0]
            if scale_x != 1.0 and space_w is None:
                w = max(1, int(round(w * scale_x)))
            return w, [[0] * w for _ in range(self.cell_h)]

        if ch not in self.glyphs and ch.upper() in self.glyphs:
            ch = ch.upper()
        if ch not in self.glyphs:
            raise KeyError(f"Character {ch!r} (0x{ord(ch):02X}) missing from font")
        w, raw = self.glyphs[ch]
        if scale_x == 1.0:
            return w, [list(r) for r in raw]

        nw = max(1, int(round(w * scale_x)))
        scaled: Grid2D = []
        for y in range(self.cell_h):
            r = raw[y]
            scaled.append([r[min(w - 1, int(x / scale_x))] for x in range(nw)])
        return nw, scaled


def load_fonts(notes_dir: Path) -> Dict[str, BitmapFont]:
    """Load `banner`, `display`, `body`, and built-in `mini` VWF bitmap fonts."""
    fonts = {
        name: BitmapFont(notes_dir / f"font_vwf_{name}.png", notes_dir / f"font_vwf_{name}.json")
        for name in ("banner", "display", "body")
    }
    fonts["mini"] = BitmapFont(None, None)
    return fonts


def render_text_mask(
    font: BitmapFont,
    text: str,
    tracking: int = 1,
    space_w: Optional[int] = None,
    scale_x: float = 1.0,
) -> Grid2D:
    """Render `text` into a tightly bounded 2D binary mask (`0/1`) of height `font.cell_h`."""
    pieces = [font.get_glyph(ch, scale_x=scale_x, space_w=space_w) for ch in text]
    if not pieces:
        return [[0] for _ in range(font.cell_h)]

    total_w = sum(w for w, _ in pieces) + tracking * (len(pieces) - 1)
    mask: Grid2D = [[0] * max(1, total_w) for _ in range(font.cell_h)]
    cx = 0
    for idx, (gw, g) in enumerate(pieces):
        for y in range(font.cell_h):
            row_dst = mask[y]
            row_src = g[y]
            for x in range(gw):
                if row_src[x]:
                    row_dst[cx + x] = 1
        cx += gw + (tracking if idx + 1 < len(pieces) else 0)
    return mask


def render_multiline_mask(
    font: BitmapFont,
    lines: Sequence[str],
    tracking: int = 1,
    line_gap: int = 1,
    space_w: Optional[int] = None,
    align: str = "center",
) -> Grid2D:
    """Stack multiple lines centered (or left/right aligned) into one tight 2D mask."""
    rendered = [render_text_mask(font, ln, tracking=tracking, space_w=space_w) for ln in lines]
    max_w = max((len(m[0]) if m else 0) for m in rendered)
    total_h = sum(len(m) for m in rendered) + line_gap * max(0, len(rendered) - 1)
    out: Grid2D = [[0] * max(1, max_w) for _ in range(max(1, total_h))]
    cy = 0
    for m in rendered:
        mw = len(m[0]) if m else 0
        ox = (max_w - mw) // 2 if align == "center" else (max_w - mw if align == "right" else 0)
        for y, row in enumerate(m):
            for x, v in enumerate(row):
                if v:
                    out[cy + y][ox + x] = 1
        cy += len(m) + line_gap
    return out


def wrap_words(font: BitmapFont, text: str, max_w: int, tracking: int = 1, space_w: int = 2) -> List[str]:
    """Greedy word wrapper measured in exact pixels using `font`."""
    words = text.split()
    if not words:
        return [""]
    lines: List[str] = []
    cur = words[0]
    for w in words[1:]:
        cand = cur + " " + w
        cw = len(render_text_mask(font, cand, tracking=tracking, space_w=space_w)[0])
        if cw <= max_w:
            cur = cand
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    return lines


def render_fitted_mask(
    fonts: Dict[str, BitmapFont],
    text: str,
    max_w: int,
    max_h: int,
    prefer_order: Sequence[str] = ("display", "body", "mini"),
    allow_wrap: bool = True,
) -> Grid2D:
    """Choose the best crisp font (single or 2-line wrapped) that fits within `max_w x max_h`."""
    # Single-line fit first across preferred fonts and tracking 1 -> 0
    for fname in prefer_order:
        f = fonts[fname]
        for tr in (1, 0):
            sp = 3 if fname != "mini" else 2
            m = render_text_mask(f, text, tracking=tr, space_w=sp if tr == 0 else None)
            ymin, ymax = _ink_y_bounds(m)
            ih = ymax - ymin + 1
            iw = len(m[0]) if m else 0
            if iw <= max_w and ih <= max_h:
                return m

    # Multi-line word wrap on body -> mini
    if allow_wrap:
        for fname in [fn for fn in prefer_order if fn in ("body", "mini")]:
            f = fonts[fname]
            for tr in (1, 0):
                sp = 2 if fname == "mini" else 3
                lines = wrap_words(f, text, max_w, tracking=tr, space_w=sp)
                m = render_multiline_mask(f, lines, tracking=tr, line_gap=1, space_w=sp)
                ymin, ymax = _ink_y_bounds(m)
                ih = ymax - ymin + 1
                iw = len(m[0]) if m else 0
                if iw <= max_w and ih <= max_h:
                    return m

    # Last resort: condensed mini with tracking=0, trimmed/scaled horizontally only if necessary
    f = fonts["mini"]
    m = render_text_mask(f, text, tracking=0, space_w=1)
    if len(m[0]) > max_w:
        sx = max_w / float(len(m[0]))
        m = scale_mask(m, sx=sx, sy=1.0)
    return m


def _ink_y_bounds(mask: Sequence[Sequence[int]]) -> Tuple[int, int]:
    ys = [y for y, row in enumerate(mask) if any(row)]
    if not ys:
        return 0, max(0, len(mask) - 1)
    return min(ys), max(ys)


def place_mask_centered(
    mask: Sequence[Sequence[int]],
    width: int,
    height: int,
    x_off: Optional[int] = None,
    y_off: Optional[int] = None,
) -> Grid2D:
    """Place binary mask onto a `width x height` canvas (center ink vertically if y_off is None)."""
    mw = len(mask[0]) if mask else 0
    mh = len(mask)
    if x_off is None:
        x_off = (width - mw) // 2
    if y_off is None:
        ymin, ymax = _ink_y_bounds(mask)
        ink_h = ymax - ymin + 1
        y_off = ((height - ink_h) // 2) - ymin

    placed: Grid2D = [[0] * width for _ in range(height)]
    for y in range(mh):
        dy = y_off + y
        if not (0 <= dy < height):
            continue
        dst_row = placed[dy]
        src_row = mask[y]
        for x in range(mw):
            if src_row[x]:
                dx = x_off + x
                if 0 <= dx < width:
                    dst_row[dx] = 1
    return placed


def stamp_mask_onto(
    canvas: Grid2D,
    mask: Sequence[Sequence[int]],
    fg: int,
    outline: Optional[int] = None,
    shadow: Optional[int] = None,
    neighbors: int = 4,
    x_off: Optional[int] = None,
    y_off: Optional[int] = None,
    center_rect: Optional[Tuple[int, int, int, int]] = None,
) -> None:
    """Composite a 2D mask onto an existing `canvas` with optional outline and drop shadow."""
    ch = len(canvas)
    cw = len(canvas[0]) if ch else 0
    rx, ry, rw, rh = center_rect if center_rect is not None else (0, 0, cw, ch)
    mw = len(mask[0]) if mask else 0
    ymin, ymax = _ink_y_bounds(mask)
    ink_h = ymax - ymin + 1
    ox = rx + ((rw - mw) // 2) if x_off is None else x_off
    oy = ry + ((rh - ink_h) // 2) - ymin if y_off is None else y_off

    if shadow is not None:
        for my, row in enumerate(mask):
            for mx, v in enumerate(row):
                if v:
                    px, py = ox + mx + 1, oy + my + 1
                    if 0 <= px < cw and 0 <= py < ch:
                        canvas[py][px] = shadow

    if outline is not None:
        deltas = (
            ((-1, 0), (1, 0), (0, -1), (0, 1))
            if neighbors == 4
            else tuple((dx, dy) for dy in (-1, 0, 1) for dx in (-1, 0, 1) if dx or dy)
        )
        for my, row in enumerate(mask):
            for mx, v in enumerate(row):
                if v:
                    for dx, dy in deltas:
                        px, py = ox + mx + dx, oy + my + dy
                        if 0 <= px < cw and 0 <= py < ch:
                            canvas[py][px] = outline

    for my, row in enumerate(mask):
        for mx, v in enumerate(row):
            if v:
                px, py = ox + mx, oy + my
                if 0 <= px < cw and 0 <= py < ch:
                    canvas[py][px] = fg


def style_bevel_banner(
    mask: Sequence[Sequence[int]],
    width: int,
    height: int,
    outline_col: int,
    top_fill: int,
    bot_fill: int,
    bg_col: int = 0,
    x_off: Optional[int] = None,
    y_off: Optional[int] = None,
) -> Grid2D:
    """Two-tone beveled sprite banner."""
    m = place_mask_centered(mask, width, height, x_off, y_off)
    ymin, ymax = _ink_y_bounds(m)
    split_y = ymin + (ymax - ymin + 1) // 2

    canvas: Grid2D = [[bg_col] * width for _ in range(height)]
    for y in range(height):
        for x in range(width):
            if m[y][x]:
                continue
            hit = False
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if (dx or dy) and 0 <= y + dy < height and 0 <= x + dx < width and m[y + dy][x + dx]:
                        hit = True
                        break
                if hit:
                    break
            if not hit and y >= 2 and m[y - 2][x]:
                hit = True
            if hit:
                canvas[y][x] = outline_col

    for y in range(height):
        for x in range(width):
            if m[y][x]:
                canvas[y][x] = top_fill if y < split_y else bot_fill
    return canvas


def scale_mask(mask: Grid2D, sx: float = 1.0, sy: float = 1.0) -> Grid2D:
    """Scale a 2D binary glyph mask horizontally and vertically via nearest-neighbor."""
    sh = len(mask)
    sw = len(mask[0]) if sh else 0
    if sh == 0 or sw == 0:
        return [[0]]
    nw = max(1, int(round(sw * sx)))
    nh = max(1, int(round(sh * sy)))
    return [
        [mask[min(sh - 1, int(y / sy))][min(sw - 1, int(x / sx))] for x in range(nw)]
        for y in range(nh)
    ]


class TileBankAllocator:
    """Fixed-size 4bpp tile bank deduplicator preserving non-target tiles and bank capacity."""

    def __init__(self, tiles: List[TileGrid], free_indices: Iterable[int], allow_flip: bool = True) -> None:
        self.tiles = tiles
        free_list = sorted(set(free_indices))
        self.free_set = set(free_list)
        if 0 in self.free_set:
            raise ValueError("Tile 0 must always remain preserved as blank/transparent")
        self.free_queue: List[int] = list(free_list)
        self.allocated: List[int] = []
        self.allow_flip = allow_flip
        self.lookup: Dict[TileKey, Tuple[int, bool, bool]] = {}

        for idx, grid in enumerate(self.tiles):
            if idx not in self.free_set:
                self._index_tile(idx, grid)

    def _index_tile(self, idx: int, grid: Sequence[Sequence[int]]) -> None:
        if self.allow_flip:
            for fy in (False, True):
                for fx in (False, True):
                    k = flip_tile_grid(grid, hflip=fx, vflip=fy)
                    if k not in self.lookup:
                        self.lookup[k] = (idx, fx, fy)
        else:
            k = tuple(tuple(v & 0xF for v in row) for row in grid)
            if k not in self.lookup:
                self.lookup[k] = (idx, False, False)

    def get_or_alloc_word(
        self,
        cell: Sequence[Sequence[int]],
        pal: int,
        word_fn=tilemap_word,
    ) -> int:
        """Return tilemap word for `cell`, reusing an existing/flipped tile or allocating from free pool."""
        key = tuple(tuple(v & 0xF for v in row) for row in cell)
        if key in self.lookup:
            tidx, fx, fy = self.lookup[key]
            return word_fn(tidx, pal, hflip=fx, vflip=fy)

        if not self.free_queue:
            raise RuntimeError(
                f"Tile bank exhausted! All {len(self.allocated)} free tiles used."
            )
        tidx = self.free_queue.pop(0)
        self.allocated.append(tidx)
        self.tiles[tidx] = [list(r) for r in key]
        self._index_tile(tidx, key)
        return word_fn(tidx, pal, hflip=False, vflip=False)


def slice_canvas_to_words(
    canvas: Sequence[Sequence[int]],
    pal: int,
    allocator: TileBankAllocator,
    zero_word_if_all: Optional[int] = 0,
    word_fn=tilemap_word,
) -> List[int]:
    """Slice a `(H*8) x (W*8)` canvas row-major into PPU tilemap words."""
    h = len(canvas)
    w = len(canvas[0]) if h else 0
    if (h % 8) or (w % 8):
        raise ValueError(f"Canvas {w}x{h} must be multiple of 8x8 tiles")
    rows, cols = h // 8, w // 8
    words: List[int] = []
    for r in range(rows):
        for c in range(cols):
            cell = [canvas[r * 8 + py][c * 8 : c * 8 + 8] for py in range(8)]
            if zero_word_if_all is not None and all(
                v == zero_word_if_all for row in cell for v in row
            ):
                words.append(0 if zero_word_if_all == 0 else word_fn(0, pal))
            else:
                words.append(allocator.get_or_alloc_word(cell, pal, word_fn=word_fn))
    return words
