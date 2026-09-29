"""24-bit BMP (as written by the bridge DLL) -> PNG, with optional downscale. Standard library only."""
from __future__ import annotations

import struct
import zlib
from pathlib import Path


def read_bmp(path: Path) -> tuple[int, int, list[bytes]]:
    """Return width, height and top-down rows of RGB bytes."""
    data = Path(path).read_bytes()
    if data[:2] != b"BM":
        raise ValueError("not a BMP file")
    offset = struct.unpack_from("<I", data, 10)[0]
    w, h = struct.unpack_from("<ii", data, 18)
    bpp = struct.unpack_from("<H", data, 28)[0]
    if bpp != 24:
        raise ValueError(f"expected a 24-bit BMP, got {bpp}")
    stride = (w * 3 + 3) & ~3
    rows = []
    bottom_up = h > 0
    h = abs(h)
    for i in range(h):
        r = data[offset + i * stride: offset + i * stride + w * 3]
        rgb = bytearray(r)
        rgb[0::3], rgb[2::3] = r[2::3], r[0::3]  # BGR -> RGB
        rows.append(bytes(rgb))
    if bottom_up:
        rows.reverse()
    return w, h, rows


def downscale(w: int, h: int, rows: list[bytes], factor: int) -> tuple[int, int, list[bytes]]:
    if factor <= 1:
        return w, h, rows
    out = []
    nw = w // factor
    for row in rows[::factor]:
        px = bytearray(nw * 3)
        for c in range(3):
            px[c::3] = row[c::3 * factor][:nw]
        out.append(bytes(px))
    return nw, len(out), out


def crop(w: int, h: int, rows: list[bytes], x1: int, y1: int, x2: int, y2: int):
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(w, x2), min(h, y2)
    return x2 - x1, y2 - y1, [r[x1 * 3:x2 * 3] for r in rows[y1:y2]]


def write_png(path: Path, w: int, h: int, rows: list[bytes]) -> Path:
    raw = b"".join(b"\x00" + r for r in rows)

    def chunk(tag: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) \
        + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)
    return path
