from __future__ import annotations

import struct
import zlib
from pathlib import Path


def create_png(width: int, height: int, pixels: list[list[tuple[int, int, int, int]]]) -> bytes:
    def chunk(chunk_type: bytes, data: bytes) -> bytes:
        c = chunk_type + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    raw = b""
    for y in range(height):
        raw += b"\x00"
        for x in range(width):
            r, g, b, a = pixels[y][x]
            raw += struct.pack("BBBB", r, g, b, a)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def create_ico(png_data: bytes) -> bytes:
    header = struct.pack("<HHH", 0, 1, 1)
    size = len(png_data)
    offset = 6 + 16
    entry = struct.pack("<BBBBHHII", 0, 0, 0, 0, 1, 32, size, offset)
    return header + entry + png_data


def interpolate(c1: tuple, c2: tuple, t: float) -> tuple:
    return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(4))


def draw_rounded_rect(
    pixels: list, x0: int, y0: int, x1: int, y1: int, r: int, color: tuple
) -> None:
    for y in range(y0, y1):
        for x in range(x0, x1):
            inside = True
            if x < x0 + r and y < y0 + r:
                dx, dy = x0 + r - x, y0 + r - y
                inside = dx * dx + dy * dy <= r * r
            elif x >= x1 - r and y < y0 + r:
                dx, dy = x - (x1 - r - 1), y0 + r - y
                inside = dx * dx + dy * dy <= r * r
            elif x < x0 + r and y >= y1 - r:
                dx, dy = x0 + r - x, y - (y1 - r - 1)
                inside = dx * dx + dy * dy <= r * r
            elif x >= x1 - r and y >= y1 - r:
                dx, dy = x - (x1 - r - 1), y - (y1 - r - 1)
                inside = dx * dx + dy * dy <= r * r
            if inside:
                pixels[y][x] = color


SZ = 256
C1 = (37, 99, 235, 255)
C2 = (29, 78, 216, 255)
BG = (245, 247, 251, 0)
WHITE = (255, 255, 255, 255)

pixels = [[BG for _ in range(SZ)] for _ in range(SZ)]

margin = 24
for y in range(SZ):
    t = y / (SZ - 1)
    color = interpolate(C1, C2, t)
    for x in range(SZ):
        dx = x - SZ / 2
        dy = y - SZ / 2
        dist = (dx * dx + dy * dy) ** 0.5
        outer = SZ / 2 - 4
        inner = SZ / 2 - 18
        if inner <= dist <= outer:
            rr = int(color[0] + 10)
            gg = int(color[1] + 15)
            bb = int(color[2] + 20)
            pixels[y][x] = (min(rr, 255), min(gg, 255), min(bb, 255), 255)

draw_rounded_rect(pixels, 54, 54, 202, 202, 40, C1)

inner_bg = (30, 80, 210, 255)
draw_rounded_rect(pixels, 64, 64, 192, 192, 32, inner_bg)

bar_data = [
    (72, 78, 184, 88),
    (72, 96, 184, 106),
    (72, 114, 140, 124),
    (72, 132, 160, 142),
    (72, 150, 148, 160),
]
for x0, y0, x1, y1 in bar_data:
    draw_rounded_rect(pixels, x0, y0, x1, y1, 4, WHITE)

dot_data = [
    (152, 118, 160, 126),
    (168, 140, 176, 148),
    (148, 154, 156, 162),
]
for x0, y0, x1, y1 in dot_data:
    draw_rounded_rect(pixels, x0, y0, x1, y1, 4, WHITE)

png = create_png(SZ, SZ, pixels)
ico = create_ico(png)

output = Path(__file__).resolve().parent.parent / "assets" / "icon.ico"
output.write_bytes(ico)
print(f"Icon created: {output} ({len(ico)} bytes)")
