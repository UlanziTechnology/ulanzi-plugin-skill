#!/usr/bin/env python3
import argparse
import hashlib
import os
import shutil
import struct
import subprocess
import sys
import zlib
from pathlib import Path

SIZE = 196

FONT = {
    "0": ["111", "101", "101", "101", "111"],
    "1": ["010", "110", "010", "010", "111"],
    "2": ["111", "001", "111", "100", "111"],
    "3": ["111", "001", "111", "001", "111"],
    "4": ["101", "101", "111", "001", "001"],
    "5": ["111", "100", "111", "001", "111"],
    "6": ["111", "100", "111", "101", "111"],
    "7": ["111", "001", "010", "010", "010"],
    "8": ["111", "101", "111", "101", "111"],
    "9": ["111", "101", "111", "001", "111"],
    "A": ["010", "101", "111", "101", "101"],
    "B": ["110", "101", "110", "101", "110"],
    "C": ["111", "100", "100", "100", "111"],
    "D": ["110", "101", "101", "101", "110"],
    "E": ["111", "100", "110", "100", "111"],
    "F": ["111", "100", "110", "100", "100"],
    "G": ["111", "100", "101", "101", "111"],
    "H": ["101", "101", "111", "101", "101"],
    "I": ["111", "010", "010", "010", "111"],
    "J": ["001", "001", "001", "101", "111"],
    "K": ["101", "101", "110", "101", "101"],
    "L": ["100", "100", "100", "100", "111"],
    "M": ["101", "111", "111", "101", "101"],
    "N": ["101", "111", "111", "111", "101"],
    "O": ["111", "101", "101", "101", "111"],
    "P": ["111", "101", "111", "100", "100"],
    "Q": ["111", "101", "101", "111", "001"],
    "R": ["111", "101", "111", "110", "101"],
    "S": ["111", "100", "111", "001", "111"],
    "T": ["111", "010", "010", "010", "010"],
    "U": ["101", "101", "101", "101", "111"],
    "V": ["101", "101", "101", "101", "010"],
    "W": ["101", "101", "111", "111", "101"],
    "X": ["101", "101", "010", "101", "101"],
    "Y": ["101", "101", "010", "010", "010"],
    "Z": ["111", "001", "010", "100", "111"],
}


def write_png(path, width, height, rgba):
    raw = bytearray()
    stride = width * 4
    for y in range(height):
        raw.append(0)
        raw.extend(rgba[y * stride:(y + 1) * stride])

    def chunk(kind, data):
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    data = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(raw), 6))
        + chunk(b"IEND", b"")
    )
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(data)


def hex_to_rgb(value, fallback):
    if not value:
        return fallback
    value = value.strip().lstrip("#")
    if len(value) != 6:
        return fallback
    try:
        return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return fallback


def color_seed(seed):
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    return (
        (32 + digest[0] // 4, 36 + digest[1] // 5, 48 + digest[2] // 4),
        (80 + digest[3] // 3, 88 + digest[4] // 3, 110 + digest[5] // 4),
        (150 + digest[6] // 3, 170 + digest[7] // 4, 180 + digest[8] // 4),
    )


def initials(name):
    words = [part for part in "".join(ch if ch.isalnum() else " " for ch in name.upper()).split() if part]
    if len(words) >= 2:
        return (words[0][0] + words[1][0])[:2]
    if words:
        return words[0][:2].ljust(2, "D")
    return "UD"


def put(px, x, y, color):
    if 0 <= x < SIZE and 0 <= y < SIZE:
        i = (y * SIZE + x) * 4
        px[i:i + 4] = bytes(color)


def rect(px, x0, y0, x1, y1, color):
    for y in range(max(0, y0), min(SIZE, y1)):
        for x in range(max(0, x0), min(SIZE, x1)):
            put(px, x, y, color)


def text(px, value, x, y, scale, color):
    cursor = x
    for char in value:
        glyph = FONT.get(char)
        if not glyph:
            cursor += scale * 2
            continue
        for gy, row in enumerate(glyph):
            for gx, bit in enumerate(row):
                if bit == "1":
                    rect(px, cursor + gx * scale, y + gy * scale, cursor + (gx + 1) * scale - 1, y + (gy + 1) * scale - 1, color)
        cursor += 4 * scale


def fallback_icon(name, kind, out, bg=None, accent=None):
    bg1, bg2, ac = color_seed(f"{name}|{kind}")
    bg1 = hex_to_rgb(bg, bg1)
    ac = hex_to_rgb(accent, ac)

    px = bytearray(SIZE * SIZE * 4)
    for y in range(SIZE):
        for x in range(SIZE):
            t = (x + y) / (SIZE * 2)
            rgb = tuple(int(bg1[i] * (1 - t) + bg2[i] * t) for i in range(3))
            put(px, x, y, rgb + (255,))

    rect(px, 42, 42, 154, 154, (18, 20, 24, 255))
    rect(px, 50, 50, 146, 146, ac + (255,))
    rect(px, 60, 60, 136, 136, (28, 30, 36, 255))

    value = initials(name or kind)
    scale = 13
    width = len(value) * 4 * scale - scale
    text(px, value, (SIZE - width) // 2, 75, scale, (255, 255, 255, 255))
    write_png(out, SIZE, SIZE, px)


def normalize_image(src, out):
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    try:
        from PIL import Image, ImageOps
    except ImportError:
        if not shutil.which("sips"):
            raise RuntimeError("Image normalization needs Pillow (python3 -m pip install Pillow) or macOS sips; omit --from for a dependency-free placeholder")
        subprocess.run(
            ["sips", "-s", "format", "png", "-z", str(SIZE), str(SIZE), src, "--out", out],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        return
    with Image.open(src) as original:
        image = ImageOps.exif_transpose(original).convert("RGBA")
        image.thumbnail((SIZE, SIZE), Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
        canvas.alpha_composite(image, ((SIZE - image.width) // 2, (SIZE - image.height) // 2))
        canvas.save(out, "PNG")


def main():
    parser = argparse.ArgumentParser(description="Create or normalize Ulanzi 196x196 PNG icons.")
    parser.add_argument("--from", dest="src", help="Input image to normalize to 196x196 PNG using Pillow or macOS sips")
    parser.add_argument("--out", required=True, help="Output PNG path")
    parser.add_argument("--name", default="Ulanzi Plugin", help="Plugin/action name for fallback generation")
    parser.add_argument("--kind", default="plugin", help="Icon kind, used as part of the fallback seed")
    parser.add_argument("--bg", help="Fallback background hex color")
    parser.add_argument("--accent", help="Fallback accent hex color")
    args = parser.parse_args()

    if args.src:
        normalize_image(args.src, args.out)
    else:
        fallback_icon(args.name, args.kind, args.out, args.bg, args.accent)

    print(os.path.abspath(args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
