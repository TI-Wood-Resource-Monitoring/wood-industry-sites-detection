"""Labels of one chip, in MAP coordinates (no framework knowledge).

Rule (decided 2026-10-29 / 2026-11-02): each label polygon is clipped to the chip.
  keep a box  if  visible share >= min_visible (50 %)  OR  visible area >= min_visible_m2 (1 ha)
  otherwise   mask the visible part (grown by mask_grow_px), no label.
holz_klein: positive = exactly like logyard_rough; background = ignored; mask = always masked.
industry_site and triage C: ignored (filtered out before, see Poly.is_label).
"""
from __future__ import annotations

from dataclasses import dataclass

from osgeo import ogr

from woodsites.core import grid
from woodsites.core.polygons import Poly, box

ogr.UseExceptions()


@dataclass
class Box:
    new_id: str
    category: str
    minx: float
    miny: float
    maxx: float
    maxy: float
    visible: float          # share of the polygon area inside the chip
    cut_at_edge: bool


@dataclass
class Mask:
    new_id: str
    category: str
    geom: ogr.Geometry      # area to grey out (already grown and clipped to the chip)
    visible: float
    reason: str             # "below threshold" | "holz_klein mask" | "box too small"


def chip_labels(i: int, j: int, polys: list[Poly], tc: dict) -> tuple[list[Box], list[Mask]]:
    """polys: label polygons (Poly.is_label). Returns boxes and masks for chip (i, j)."""
    bx = grid.chip_bounds(i, j)
    chip = box(*bx)
    boxes, masks = [], []
    grow = tc["mask_grow_px"] * grid.PX_M
    for p in polys:
        e = p.env
        if not (e[0] < bx[2] and bx[0] < e[2] and e[1] < bx[3] and bx[1] < e[3]):
            continue
        mode = "positive" if p.category == "logyard_rough" else tc["holz_klein"]
        if mode == "background":
            continue
        if not p.geom.Intersects(chip):
            continue
        clipped = p.geom.Intersection(chip)
        a_clip, a_poly = clipped.GetArea(), p.geom.GetArea()
        if a_clip <= 0 or a_poly <= 0:
            continue
        vis = a_clip / a_poly

        def mask(reason: str) -> None:
            g = clipped.Buffer(grow).Intersection(chip) if grow > 0 else clipped
            masks.append(Mask(p.new_id, p.category, g, vis, reason))

        if mode == "mask":
            mask("holz_klein mask")
            continue
        if not (vis >= tc["min_visible"] or a_clip >= tc["min_visible_m2"]):
            mask("below threshold")
            continue
        minx, maxx, miny, maxy = clipped.GetEnvelope()
        minx, miny = max(minx, bx[0]), max(miny, bx[1])
        maxx, maxy = min(maxx, bx[2]), min(maxy, bx[3])
        if min(maxx - minx, maxy - miny) / grid.PX_M < tc["min_box_px"]:
            mask("box too small")
            continue
        boxes.append(Box(p.new_id, p.category, minx, miny, maxx, maxy, vis, vis < 1 - 1e-9))
    return boxes, masks


def best_visibility(p: Poly, tc: dict) -> tuple[float, float]:
    """(best share, largest visible area) of a polygon over all chips it touches - a polygon
    that never reaches the threshold anywhere would be masked in every chip (check warns)."""
    best, best_a = 0.0, 0.0
    a_poly = p.geom.GetArea()
    for i, j in grid.chips_touching_envelope(*p.env):
        chip = box(*grid.chip_bounds(i, j))
        if p.geom.Intersects(chip):
            a = p.geom.Intersection(chip).GetArea()
            best, best_a = max(best, a / a_poly if a_poly else 0), max(best_a, a)
    return best, best_a
