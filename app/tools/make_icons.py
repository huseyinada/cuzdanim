"""Generate PWA icons (PNG) with the standard library only — no Pillow needed.

    python -m app.tools.make_icons

Draws a green coin: dark ring, lighter face, and a bold "₺"-like glyph made
of simple strokes. Output: app/static/icons/icon-{192,512}.png (+ maskable).
"""
import struct
import zlib
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parents[1] / "static" / "icons"

BG = (16, 24, 32)          # page background (maskable safe zone)
RING = (22, 163, 74)       # green ring
FACE = (34, 197, 94)       # lighter green face
GLYPH = (255, 255, 255)    # white symbol


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(kind + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)


def png_bytes(size: int, pixels: list[list[tuple[int, int, int]]]) -> bytes:
    raw = bytearray()
    for row in pixels:
        raw.append(0)  # filter type 0 (None)
        for r, g, b in row:
            raw += bytes((r, g, b))
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)  # 8-bit RGB
    png = b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IHDR", ihdr)
    return png + _png_chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + _png_chunk(b"IEND", b"")


def write_png(path: Path, size: int, pixels: list[list[tuple[int, int, int]]]) -> None:
    path.write_bytes(png_bytes(size, pixels))


def write_ico(path: Path, images: list[tuple[int, bytes]]) -> None:
    """Windows .ico containing PNG-compressed frames (supported since Vista)."""
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    directory, payload = b"", b""
    for size, png in images:
        dim = 0 if size >= 256 else size  # 0 means 256 in the ICO directory
        directory += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(png), offset)
        payload += png
        offset += len(png)
    path.write_bytes(header + directory + payload)


def render(size: int, *, maskable: bool) -> list[list[tuple[int, int, int]]]:
    cx = cy = size / 2
    # Maskable icons must keep content within the inner 80% "safe zone".
    radius = size * (0.40 if maskable else 0.47)
    ring_w = size * 0.06

    # "₺" glyph geometry (relative to size): a vertical stem, two slanted bars.
    stem_x = cx - size * 0.06
    stem_w = size * 0.075
    stem_top, stem_bottom = cy - size * 0.24, cy + size * 0.20
    bar_thick = size * 0.055

    def in_bar(x: float, y: float, y0: float) -> bool:
        # Slanted bar rising to the right, centered vertically at y0 on the stem.
        rel = (x - (stem_x - size * 0.10)) / (size * 0.30)
        if rel < 0 or rel > 1:
            return False
        y_center = y0 - rel * size * 0.09
        return abs(y - y_center) <= bar_thick / 2

    rows: list[list[tuple[int, int, int]]] = []
    for py in range(size):
        row: list[tuple[int, int, int]] = []
        for px in range(size):
            x, y = px + 0.5, py + 0.5
            d = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
            if d > radius:
                row.append(BG)
                continue
            if d > radius - ring_w:
                row.append(RING)
                continue
            # Glyph: stem + curved foot + two bars
            on_stem = stem_x <= x <= stem_x + stem_w and stem_top <= y <= stem_bottom
            foot = False
            if y > stem_bottom - size * 0.02:
                # quarter-arc foot sweeping right from the stem bottom
                fx, fy = x - (stem_x + stem_w / 2), y - (stem_bottom - size * 0.02)
                r_out, r_in = size * 0.18, size * 0.18 - stem_w
                dist = (fx ** 2 + fy ** 2) ** 0.5
                foot = r_in <= dist <= r_out and fx >= -stem_w / 2 and fy >= 0 and fx <= r_out and fy <= r_out * 0.9
            bars = in_bar(x, y, cy - size * 0.04) or in_bar(x, y, cy + size * 0.06)
            row.append(GLYPH if (on_stem or foot or bars) else FACE)
        rows.append(row)
    return rows


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for size in (192, 512):
        write_png(OUT_DIR / f"icon-{size}.png", size, render(size, maskable=False))
        write_png(OUT_DIR / f"icon-maskable-{size}.png", size, render(size, maskable=True))
    # Windows EXE icon: several sizes so Explorer/taskbar pick a crisp one.
    write_ico(OUT_DIR / "cuzdanim.ico", [(s, png_bytes(s, render(s, maskable=False))) for s in (16, 32, 48, 64, 128, 256)])
    print(f"Icons written to {OUT_DIR}")


if __name__ == "__main__":
    main()
