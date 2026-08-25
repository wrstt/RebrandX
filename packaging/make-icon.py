#!/usr/bin/env python3
"""Regenerate share/rebrandx.ico (and the PNG) from one master rendering.

    python packaging/make-icon.py

Why this exists: Windows picks the closest size in an .ico and scales it to
whatever the shell asked for. A file that jumps 32 -> 48 has nothing to
offer a 150% taskbar asking for 40, so the shell rescales and the icon goes
soft. This writes every size Windows actually asks for, each one rendered
from a 4x supersample rather than resampled from a neighbour.

Pure stdlib: the mark is drawn here as geometry, so there is no dependency
on an SVG renderer or an imaging library, and it can run in CI.
"""

from __future__ import annotations

import os
import struct
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ICO = ROOT / "share" / "rebrandx.ico"
PNG = ROOT / "share" / "rebrandx.png"

# Every size the Windows shell asks for across 100/125/150/175/200% scaling,
# plus the 256 that Explorer's extra-large view uses.
SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)

SS = 4  # supersample factor; 4x is enough to hide the stair-stepping

# -- palette, matching share/rebrandx.svg -----------------------------------
BODY_TOP = (0x32, 0x30, 0x2A)
BODY_BOT = (0x14, 0x13, 0x10)
# The logo's first stop is near-black, which vanishes against the body.
# Lifted just enough to read as the start of a gradient.
STRIP = ((0x5A, 0x55, 0x4C), (0x8A, 0x85, 0x78), (0xB0, 0x8D, 0x2F))
LETTER = (0xFA, 0xF9, 0xF5)
BRASS = (0xB0, 0x8D, 0x2F)


# --------------------------------------------------------------------------
# geometry
# --------------------------------------------------------------------------

def _rounded(x, y, w, h, r) -> bool:
    """Is (x, y) inside a w*h rounded rectangle with corner radius r?"""
    if x < 0 or y < 0 or x >= w or y >= h:
        return False
    cx = r if x < r else (w - r if x > w - r else x)
    cy = r if y < r else (h - r if y > h - r else y)
    if cx == x or cy == y:
        return True
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r


# The R is built from geometry rather than typeset: a font would have to be
# found, licensed and rasterised, and at 16 pixels a hand-built letter is
# cleaner than any of them. Drawn in an 86 x 100 box.
R_W, R_H = 86.0, 100.0
_STEM = 28.0          # stem width, and the weight of every stroke
_BOWL_B = 56.0        # where the bowl closes and the leg starts
_BOWL_C = (46.0, 28.0)
_BOWL_R = 28.0
_COUNTER_R = _BOWL_R - 19.0


def _letter_r(x, y) -> bool:
    """A capital R in an 86 x 100 box, y measured downwards from the cap."""
    if x < 0.0 or y < 0.0 or x > R_W or y > R_H:
        return False

    if x <= _STEM:                                  # the stem
        return True

    if y <= _BOWL_B:                                # the bowl, minus its counter
        cx, cy = _BOWL_C
        outer = x <= cx or (x - cx) ** 2 + (y - cy) ** 2 <= _BOWL_R ** 2
        counter = ((_STEM <= x <= cx and 19.0 <= y <= 37.0)
                   or (x - cx) ** 2 + (y - cy) ** 2 <= _COUNTER_R ** 2)
        return outer and not counter

    t = (y - _BOWL_B) / (R_H - _BOWL_B)             # the leg
    lx = 40.0 + t * 26.0
    return lx <= x <= lx + 20.0


def _plus(x, y, s) -> bool:
    """The small brass plus, in tile units."""
    arm, half = s * 0.085, s * 0.024
    cx, cy = s * 0.775, s * 0.760
    if cx - arm <= x <= cx + arm and cy - half <= y <= cy + half:
        return True
    return cy - arm <= y <= cy + arm and cx - half <= x <= cx + half


def render(size: int) -> bytearray:
    """Draw the mark at `size` px, supersampled, as straight RGBA bytes."""
    big = size * SS
    inset = big * 0.031                       # matches the 8/128 in the SVG
    tile = big - inset * 2
    radius = tile * 0.232                     # matches rx=26/112

    strip_h = max(1.0, tile * 0.080)

    # The R sits on the same optical centre the SVG uses: a little above
    # middle, with the plus clear to its lower right.
    unit = (tile * 0.445) / R_H
    rx0 = inset + tile * 0.475 - (R_W * unit) / 2.0
    ry0 = inset + tile * 0.545 - (R_H * unit) / 2.0

    want_plus = size >= 32                    # below that it is just noise

    acc = [[0.0, 0.0, 0.0, 0.0] for _ in range(size * size)]

    for py in range(big):
        fy = py - inset
        row_out = (py // SS) * size
        for px in range(big):
            fx = px - inset
            if not _rounded(fx, fy, tile, tile, radius):
                continue

            t = fy / tile
            cr = BODY_TOP[0] + (BODY_BOT[0] - BODY_TOP[0]) * t
            cg = BODY_TOP[1] + (BODY_BOT[1] - BODY_TOP[1]) * t
            cb = BODY_TOP[2] + (BODY_BOT[2] - BODY_TOP[2]) * t

            if fy < strip_h:
                cr, cg, cb = STRIP[min(2, int((fx / tile) * 3))]
            elif _letter_r((px - rx0) / unit, (py - ry0) / unit):
                cr, cg, cb = LETTER
            elif want_plus and _plus(px - inset, py - inset, tile):
                cr, cg, cb = BRASS

            cell = acc[row_out + (px // SS)]
            cell[0] += cr
            cell[1] += cg
            cell[2] += cb
            cell[3] += 255.0

    n = float(SS * SS)
    out = bytearray(size * size * 4)
    for i, (sr, sg, sb, sa) in enumerate(acc):
        if sa <= 0.0:
            continue
        # Colours were summed only over covered samples, so they divide by
        # the covered count; dividing by n would darken every edge pixel.
        cov = sa / 255.0
        out[i * 4 + 0] = min(255, int(sr / cov + 0.5))
        out[i * 4 + 1] = min(255, int(sg / cov + 0.5))
        out[i * 4 + 2] = min(255, int(sb / cov + 0.5))
        out[i * 4 + 3] = min(255, int(sa / n + 0.5))
    return out


# --------------------------------------------------------------------------
# encoding
# --------------------------------------------------------------------------

def png_bytes(size: int, rgba: bytes) -> bytes:
    raw = bytearray()
    stride = size * 4
    for y in range(size):
        raw.append(0)                                  # filter: none
        raw += rgba[y * stride:(y + 1) * stride]

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + chunk(b"IEND", b""))


def bmp_bytes(size: int, rgba: bytes) -> bytes:
    """One icon image in DIB form: the format the shell always understands.

    An .ico may hold PNG-compressed entries, but only the 256 is reliably
    read that way -- several shell code paths refuse PNG below that, skip
    the entry, and fall back to downscaling the 256. That is exactly what a
    blurry taskbar icon looks like. Sizes up to 128 are therefore written
    as plain 32-bit DIBs.

    The header claims double the real height because an icon DIB stores the
    colour bitmap and a legacy 1-bit AND mask stacked together, and rows run
    bottom-up.
    """
    header = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0,
                         0, 0, 0, 0, 0)
    stride = size * 4
    xor = bytearray()
    for y in range(size - 1, -1, -1):                 # bottom-up
        row = rgba[y * stride:(y + 1) * stride]
        for x in range(0, stride, 4):
            xor += bytes((row[x + 2], row[x + 1], row[x], row[x + 3]))  # BGRA

    # The AND mask is unused when there is an alpha channel, but it has to
    # be present and its rows padded to 4 bytes.
    mask_stride = ((size + 31) // 32) * 4
    return bytes(header) + bytes(xor) + bytes(mask_stride * size)


def build_ico(images: list) -> bytes:
    head = struct.pack("<HHH", 0, 1, len(images))
    entries, blobs = b"", b""
    offset = 6 + 16 * len(images)
    for size, data in images:
        entries += struct.pack("<BBBBHHII",
                               0 if size >= 256 else size,
                               0 if size >= 256 else size,
                               0, 0, 1, 32, len(data), offset)
        blobs += data
        offset += len(data)
    return head + entries + blobs


def main() -> int:
    print("Rendering the RebrandX mark at %d sizes (%dx supersample)"
          % (len(SIZES), SS))
    images = []
    for size in SIZES:
        rgba = bytes(render(size))
        # PNG only for the 256; DIB for everything the shell draws small.
        if size >= 256:
            data, kind = png_bytes(size, rgba), "PNG"
        else:
            data, kind = bmp_bytes(size, rgba), "DIB"
        images.append((size, data))
        print("  %3dx%-3d  %-3s  %6d bytes" % (size, size, kind, len(data)))
        if size == 256:
            PNG.write_bytes(data)

    ICO.write_bytes(build_ico(images))
    print("\nwrote %s (%d bytes)" % (ICO, ICO.stat().st_size))
    print("wrote %s" % PNG)
    return 0


if __name__ == "__main__":
    sys.exit(main())
