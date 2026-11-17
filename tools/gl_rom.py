"""Gambling Lord (Super A'Can) ROM byte-swap, tilemap/tile codecs, space allocator, and IPS helpers."""

import hashlib
import struct
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from d222 import decompress_d222, encode_d222_best

ORIG_ROM_PATH = Path(__file__).resolve().parent.parent / "Gambling Lord (Taiwan).bin"   # your own dump
ORIG_ROM_SIZE = 0x200000  # 2,097,152 bytes (preserve original 2 MB ROM size)
ORIG_SHA1 = "0fda223817f0b50f0ce9687076d29df3d1b86960"
ORIG_SHA256 = "c789145655bb06f5f896e72060c2c4d814233b995d3889715f2d131a76d77688"

# Contiguous 0xFF trailing free space inside original 2 MB ROM (18,578 bytes)
FREE_SPACE_REGIONS: List[Tuple[int, int]] = [(0x1FB76E, 0x200000)]

TileGrid = List[List[int]]
TileKey = Tuple[Tuple[int, ...], ...]


def swap16(data: bytes) -> bytes:
    """16-bit byte-swap between .bin file order and 68000 big-endian CPU address space."""
    if len(data) & 1:
        raise ValueError(f"Odd ROM length {len(data)}")
    out = bytearray(len(data))
    out[0::2] = data[1::2]
    out[1::2] = data[0::2]
    return bytes(out)


def load_rom(path: Path = ORIG_ROM_PATH, verify_hash: bool = True) -> Tuple[bytearray, bytes]:
    """Return (cpu_be_rom, orig_swapped_bytes)."""
    swapped = path.read_bytes()
    if verify_hash:
        sha1 = hashlib.sha1(swapped).hexdigest()
        sha256 = hashlib.sha256(swapped).hexdigest()
        if sha1 != ORIG_SHA1 or sha256 != ORIG_SHA256:
            raise ValueError(
                f"ROM hash mismatch for {path}: sha1={sha1} sha256={sha256}"
            )
    if len(swapped) != ORIG_ROM_SIZE:
        raise ValueError(f"Unexpected ROM size {len(swapped)} (expected {ORIG_ROM_SIZE})")
    return bytearray(swap16(swapped)), swapped


def save_rom(cpu_rom: bytes, out_path: Path) -> bytes:
    """Byte-swap 68000 big-endian buffer and write `.bin`; return swapped bytes."""
    if len(cpu_rom) != ORIG_ROM_SIZE:
        raise ValueError(f"ROM size changed to {len(cpu_rom)} (expected {ORIG_ROM_SIZE})")
    swapped = swap16(cpu_rom)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(swapped)
    return swapped


def write_ips(orig_swapped: bytes, mod_swapped: bytes, ips_path: Path) -> None:
    """Write a standard IPS patch transforming orig_swapped into mod_swapped."""
    orig_len = len(orig_swapped)
    mod_len = len(mod_swapped)
    if mod_len > 0xFFFFFF:
        raise ValueError(f"ROM size {mod_len:#x} exceeds 24-bit IPS limit")

    out = bytearray(b"PATCH")
    i = 0
    while i < mod_len:
        b_mod = mod_swapped[i]
        b_orig = orig_swapped[i] if i < orig_len else None
        if b_orig == b_mod:
            i += 1
            continue
        start = i
        chunk = bytearray()
        same_run = 0
        while i < mod_len and len(chunk) < 0xFFFF:
            cur_mod = mod_swapped[i]
            cur_orig = orig_swapped[i] if i < orig_len else None
            chunk.append(cur_mod)
            if cur_orig == cur_mod:
                same_run += 1
                if same_run >= 8:
                    del chunk[-same_run:]
                    i -= same_run - 1
                    break
            else:
                same_run = 0
            i += 1
        if start == 0x454F46 and start > 0:
            start -= 1
            chunk.insert(0, mod_swapped[start])
        out.extend(start.to_bytes(3, "big"))
        out.extend(len(chunk).to_bytes(2, "big"))
        out.extend(chunk)
        if i <= start:
            i = start + len(chunk)
    out.extend(b"EOF")
    ips_path.parent.mkdir(parents=True, exist_ok=True)
    ips_path.write_bytes(out)


def apply_ips(orig_swapped: bytes, ips_path: Path) -> bytes:
    """Apply an IPS patch to orig_swapped and return the patched image."""
    patch = ips_path.read_bytes()
    if not patch.startswith(b"PATCH"):
        raise ValueError(f"Invalid IPS header in {ips_path}")
    out = bytearray(orig_swapped)
    pos = 5
    while pos + 3 <= len(patch):
        if patch[pos : pos + 3] == b"EOF":
            break
        off = int.from_bytes(patch[pos : pos + 3], "big")
        pos += 3
        size = struct.unpack_from(">H", patch, pos)[0]
        pos += 2
        if size == 0:
            rle_len = struct.unpack_from(">H", patch, pos)[0]
            val = patch[pos + 2]
            pos += 3
            need = off + rle_len
            if need > len(out):
                out.extend(b"\x00" * (need - len(out)))
            out[off:need] = bytes([val]) * rle_len
        else:
            data = patch[pos : pos + size]
            pos += size
            need = off + size
            if need > len(out):
                out.extend(b"\x00" * (need - len(out)))
            out[off:need] = data
    return bytes(out)


class SpaceAllocator:
    """Tracks free ROM regions and verifies non-overlapping writes."""

    def __init__(self, regions: Optional[Sequence[Tuple[int, int]]] = None) -> None:
        base = list(regions) if regions is not None else list(FREE_SPACE_REGIONS)
        self.free_regions: List[List[int]] = [[s, e] for s, e in sorted(base) if e > s]
        self.allocations: List[Tuple[int, int, str]] = []
        self.fixed_patches: List[Tuple[int, int, str]] = []

    def allocate(self, size: int, label: str, align: int = 2) -> int:
        """Allocate `size` aligned bytes from free regions and record the range."""
        if size <= 0:
            raise ValueError(f"Allocation size must be positive for {label}: {size}")
        for idx, reg in enumerate(self.free_regions):
            s, e = reg
            aligned = (s + (align - 1)) & ~(align - 1)
            if aligned + size <= e:
                end = aligned + size
                if aligned > s:
                    if end < e:
                        self.free_regions[idx] = [s, aligned]
                        self.free_regions.insert(idx + 1, [end, e])
                    else:
                        reg[1] = aligned
                elif end < e:
                    reg[0] = end
                else:
                    self.free_regions.pop(idx)
                self.allocations.append((aligned, end, label))
                return aligned
        raise MemoryError(
            f"Out of free ROM space allocating {size} bytes for {label}; "
            f"remaining={self.remaining_bytes()}"
        )

    def remaining_bytes(self) -> int:
        return sum(e - s for s, e in self.free_regions)

    def record_patch(self, start: int, end: int, label: str) -> None:
        """Record an in-place ROM patch range [start, end) for overlap validation."""
        if end <= start:
            raise ValueError(f"Invalid patch range [{start:#x}, {end:#x}) for {label}")
        self.fixed_patches.append((start, end, label))

    def verify_non_overlapping(self) -> None:
        """Ensure no two recorded allocations or fixed patches overlap."""
        items = sorted(self.allocations + self.fixed_patches, key=lambda x: (x[0], x[1]))
        for (s1, e1, l1), (s2, e2, l2) in zip(items, items[1:]):
            if s2 < e1:
                raise AssertionError(
                    f"Overlapping ROM writes: {l1} [0x{s1:06X}..0x{e1:06X}) "
                    f"vs {l2} [0x{s2:06X}..0x{e2:06X})"
                )


def decode_tile_4bpp(tile32: bytes) -> TileGrid:
    """Decode one 32-byte 4bpp 8x8 tile into an 8x8 list of palette indices [0..15]."""
    if len(tile32) != 32:
        raise ValueError(f"Expected 32 bytes for 4bpp tile, got {len(tile32)}")
    rows: TileGrid = []
    for y in range(8):
        row: List[int] = []
        base = y * 4
        for x in range(4):
            b = tile32[base + x]
            row.append((b >> 4) & 0xF)
            row.append(b & 0xF)
        rows.append(row)
    return rows


def encode_tile_4bpp(grid: Sequence[Sequence[int]]) -> bytes:
    """Encode an 8x8 grid of nibble indices [0..15] into 32 bytes of 4bpp tile data."""
    if len(grid) != 8 or any(len(r) != 8 for r in grid):
        raise ValueError("Tile grid must be 8x8")
    out = bytearray(32)
    for y in range(8):
        row = grid[y]
        base = y * 4
        for x in range(4):
            out[base + x] = ((row[x * 2] & 0xF) << 4) | (row[x * 2 + 1] & 0xF)
    return bytes(out)


def flip_tile_grid(grid: Sequence[Sequence[int]], hflip: bool, vflip: bool) -> TileKey:
    """Return an immutable 8x8 tuple with optional horizontal and vertical flip."""
    ys = range(7, -1, -1) if vflip else range(8)
    xs = range(7, -1, -1) if hflip else range(8)
    return tuple(tuple(grid[y][x] & 0xF for x in xs) for y in ys)


def tilemap_word(
    tile_idx: int,
    pal: int,
    hflip: bool = False,
    vflip: bool = False,
    prio: bool = False,
) -> int:
    """Build a Super A'Can 16-bit tilemap word (0x0400=vflip, 0x0800=hflip, 0x3FF=tile)."""
    return (
        ((1 if prio else 0) << 15)
        | ((pal & 0xF) << 12)
        | ((1 if hflip else 0) << 11)
        | ((1 if vflip else 0) << 10)
        | (tile_idx & 0x3FF)
    )


def sprite_word(tile_idx: int, pal: int, hflip: bool = False, vflip: bool = False) -> int:
    """Build a Gambling Lord $0006BA sprite tilemap word (0x0800=hflip, 0x0400=vflip)."""
    return (
        ((pal & 0xF) << 12)
        | ((1 if hflip else 0) << 11)
        | ((1 if vflip else 0) << 10)
        | (tile_idx & 0x3FF)
    )


def decode_tiles_bytes(raw: bytes) -> List[TileGrid]:
    """Decode raw 32-byte 4bpp tile array into list of 8x8 grids."""
    if len(raw) % 32 != 0:
        raise ValueError(f"Tile byte length {len(raw)} not multiple of 32")
    return [decode_tile_4bpp(raw[i : i + 32]) for i in range(0, len(raw), 32)]


def encode_tiles_bytes(tiles: Sequence[Sequence[Sequence[int]]]) -> bytes:
    """Encode list of 8x8 tile grids into raw 4bpp bytes."""
    return b"".join(encode_tile_4bpp(t) for t in tiles)


def patch_compressed_block(
    rom: bytearray,
    alloc: SpaceAllocator,
    orig_addr: int,
    orig_end: int,
    raw_data: bytes,
    label: str,
    code_scan_end: int = 0x037000,
) -> int:
    """Compress `raw_data`, write in-place if it fits in [orig_addr, orig_end), else relocate + update lea pointers."""
    comp = encode_d222_best(raw_data, verify_rom=rom)
    slot_len = orig_end - orig_addr
    if len(comp) <= slot_len:
        rom[orig_addr : orig_addr + len(comp)] = comp
        if len(comp) < slot_len:
            rom[orig_addr + len(comp) : orig_end] = b"\xFF" * (slot_len - len(comp))
        alloc.record_patch(orig_addr, orig_end, label)
        # Round-trip check at orig_addr
        dec, _ = decompress_d222(bytes(rom), orig_addr)
        if dec != raw_data:
            raise AssertionError(f"In-place verify failed for {label}")
        return orig_addr

    new_addr = alloc.allocate(len(comp), f"{label}_reloc", align=2)
    rom[new_addr : new_addr + len(comp)] = comp

    pat = struct.pack(">I", orig_addr)
    patched = 0
    pos = 0
    while pos < code_scan_end:
        idx = rom.find(pat, pos, code_scan_end)
        if idx == -1:
            break
        # Verify preceding opcode is 0x41F9 (lea imm32, a0)
        if idx >= 2 and rom[idx - 2 : idx] == b"\x41\xF9":
            struct.pack_into(">I", rom, idx, new_addr)
            alloc.record_patch(idx, idx + 4, f"{label}_ptr_{idx:06X}")
            patched += 1
        pos = idx + 2
    if patched == 0:
        raise RuntimeError(f"No 68000 lea.l references found for relocated block 0x{orig_addr:06X} ({label})")

    dec, _ = decompress_d222(bytes(rom), new_addr)
    if dec != raw_data:
        raise AssertionError(f"Relocated verify failed for {label}")
    return new_addr
