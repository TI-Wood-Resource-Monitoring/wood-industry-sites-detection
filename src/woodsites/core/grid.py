"""Grid maths for the storage grid f01 and the chip grid g01 (EPSG:25832).

Everything is computed in integer TICKS of 0.2 m, so no float rounding can shift a chip:
  f01 tile (a, b):  lower-left (2000 a, 2000 b) ticks, 2000 x 2000 ticks  (400 m, 0.2 m pixels)
  g01 chip (i, j):  lower-left (3072 i, 3072 j) ticks, 4096 x 4096 ticks  (819.2 m), stride 3072 (614.4 m)
A chip image has 2048 x 2048 pixels of 0.4 m (= 2 ticks).

THE Y AXIS: map y grows upwards, image rows grow downwards. Every function here counts
rows from the chip's TOP edge (y_top = y0 + 819.2 m).
"""
from __future__ import annotations

import math
import re

TICK_M = 0.2                 # one tick = one archive pixel
TILE_T = 2000                # f01 tile edge in ticks (400 m)
CHIP_T = 4096                # g01 chip edge in ticks (819.2 m)
STRIDE_T = 3072              # g01 stride in ticks (614.4 m)
CHIP_PX = 2048               # chip edge in output pixels
PX_T = CHIP_T // CHIP_PX     # ticks per output pixel (2)
PX_M = PX_T * TICK_M         # 0.4 m
CHIP_M = CHIP_T * TICK_M     # 819.2 m
STRIDE_M = STRIDE_T * TICK_M  # 614.4 m
TILE_M = TILE_T * TICK_M     # 400 m
EPSG = 25832

_NEW_ID = re.compile(r"^g01_i(-?\d+)_j(-?\d+)$")
_OLD_ID = re.compile(r"^g01_E(\d+)_N(\d+)$")


def m(t: int) -> float:
    """ticks -> metres (t / 5 is exact for the decimal value, as close as a float gets)."""
    return t / 5


def chip_id(i: int, j: int) -> str:
    return f"g01_i{i:05d}_j{j:05d}"


def old_chip_id(i: int, j: int) -> str:
    """The rounded-metre ID used in plan_f01.gpkg and chip_check (kept for those layers)."""
    return f"g01_E{round(m(i * STRIDE_T)):07d}_N{round(m(j * STRIDE_T)):07d}"


def parse_chip_id(s: str) -> tuple[int, int]:
    """(i, j) from a new (g01_i..._j...) or old (g01_E..._N..., rounded metres) chip ID."""
    s = (s or "").strip()
    mt = _NEW_ID.match(s)
    if mt:
        return int(mt.group(1)), int(mt.group(2))
    mt = _OLD_ID.match(s)
    if mt:
        E, N = int(mt.group(1)), int(mt.group(2))
        i, j = round(E / STRIDE_M), round(N / STRIDE_M)
        if abs(i * STRIDE_M - E) > 0.6 or abs(j * STRIDE_M - N) > 0.6:
            raise ValueError(f"{s}: not on the g01 grid")
        return i, j
    raise ValueError(f"not a g01 chip id: {s!r}")


def tile_id(a: int, b: int) -> str:
    return f"f01_E{a * 400:07d}_N{b * 400:07d}"


def chip_bounds_t(i: int, j: int) -> tuple[int, int, int, int]:
    x0, y0 = i * STRIDE_T, j * STRIDE_T
    return x0, y0, x0 + CHIP_T, y0 + CHIP_T


def chip_bounds(i: int, j: int) -> tuple[float, float, float, float]:
    """(minx, miny, maxx, maxy) in metres."""
    return tuple(m(t) for t in chip_bounds_t(i, j))


def geotransform(i: int, j: int) -> tuple[float, float, float, float, float, float]:
    """GDAL geotransform of the 0.4 m chip image: top-left corner, rows go DOWN."""
    x0, _, _, y1 = chip_bounds(i, j)
    return (x0, PX_M, 0.0, y1, 0.0, -PX_M)


def tiles_for_chip(i: int, j: int) -> list[tuple[int, int]]:
    """f01 tiles (a, b) under a chip, left to right, bottom to top."""
    x0, y0, x1, y1 = chip_bounds_t(i, j)
    return [(a, b) for a in range(x0 // TILE_T, (x1 - 1) // TILE_T + 1)
            for b in range(y0 // TILE_T, (y1 - 1) // TILE_T + 1)]


def chips_touching_envelope(minx: float, miny: float, maxx: float, maxy: float) -> list[tuple[int, int]]:
    """Every chip whose square overlaps the open envelope (same test as fetch_wms_chips plan)."""
    out = []
    for i in range(math.floor((minx - CHIP_M) / STRIDE_M), math.ceil(maxx / STRIDE_M) + 1):
        x0, x1 = chip_bounds(i, 0)[0], chip_bounds(i, 0)[2]
        if not (x0 < maxx and x1 > minx):
            continue
        for j in range(math.floor((miny - CHIP_M) / STRIDE_M), math.ceil(maxy / STRIDE_M) + 1):
            _, y0, _, y1 = chip_bounds(0, j)
            if y0 < maxy and y1 > miny:
                out.append((i, j))
    return out


def chips_overlap(c1: tuple[int, int], c2: tuple[int, int]) -> bool:
    """Two g01 chips share area iff their indices differ by at most 1 in both directions
    (stride 614.4 m < edge 819.2 m < 2 x stride)."""
    return abs(c1[0] - c2[0]) <= 1 and abs(c1[1] - c2[1]) <= 1


# ---- map <-> chip pixel (0.4 m), rows from the TOP ---------------------------------------
def world_to_px(x: float, y: float, i: int, j: int) -> tuple[float, float]:
    x0, _, _, y_top = chip_bounds(i, j)
    return (x - x0) / PX_M, (y_top - y) / PX_M


def px_to_world(col: float, row: float, i: int, j: int) -> tuple[float, float]:
    x0, _, _, y_top = chip_bounds(i, j)
    return x0 + col * PX_M, y_top - row * PX_M


def box_to_yolo(minx: float, miny: float, maxx: float, maxy: float, i: int, j: int) -> tuple[float, float, float, float]:
    """Map box -> YOLO (x_centre, y_centre, width, height), normalised 0..1, y from the TOP."""
    c0, r_bottom = world_to_px(minx, miny, i, j)     # miny = lowest point = LARGEST row
    c1, r_top = world_to_px(maxx, maxy, i, j)        # maxy = highest point = SMALLEST row
    return ((c0 + c1) / 2 / CHIP_PX, (r_top + r_bottom) / 2 / CHIP_PX,
            (c1 - c0) / CHIP_PX, (r_bottom - r_top) / CHIP_PX)


def yolo_to_box(xc: float, yc: float, w: float, h: float, i: int, j: int) -> tuple[float, float, float, float]:
    """Inverse of box_to_yolo -> (minx, miny, maxx, maxy) in metres."""
    c0, c1 = (xc - w / 2) * CHIP_PX, (xc + w / 2) * CHIP_PX
    r_top, r_bottom = (yc - h / 2) * CHIP_PX, (yc + h / 2) * CHIP_PX
    minx, miny = px_to_world(c0, r_bottom, i, j)
    maxx, maxy = px_to_world(c1, r_top, i, j)
    return minx, miny, maxx, maxy
