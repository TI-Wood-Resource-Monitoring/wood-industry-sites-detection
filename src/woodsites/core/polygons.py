"""Module 1 files, read-only: polygons, chip_check, background list, holdout. Checks, snapshot.

GeoPackages are opened through GDAL, so edits that QGIS saved into the -wal file are seen.
Unsaved edits in QGIS are not.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from osgeo import gdal, ogr

from . import grid

ogr.UseExceptions()
gdal.UseExceptions()

POLY_LAYER = "dop20_polygons"
CHIP_LAYER = "chip_check"
BG_LAYER = "background_g01"
CATEGORIES = ("logyard_rough", "industry_site", "holz_klein")
LABEL_CATEGORIES = ("logyard_rough", "holz_klein")
LANDS = ("Niedersachsen", "Nordrhein-Westfalen", "Brandenburg", "Baden-Württemberg", "Rheinland-Pfalz",
         "Sachsen", "Thüringen", "Bayern", "Hessen", "Mecklenburg-Vorpommern", "Saarland", "Sachsen-Anhalt")


@dataclass
class Poly:
    new_id: str
    site_id: str
    land: str
    category: str
    triage: str
    herkunft: str
    geom: ogr.Geometry
    env: tuple = field(default=())          # (minx, miny, maxx, maxy)

    @property
    def in_plan(self) -> bool:
        """Same rule as fetch_wms_chips.py plan: triage A/B or herkunft = dop20_neu."""
        return self.triage in ("A", "B") or self.herkunft == "dop20_neu"

    @property
    def is_label(self) -> bool:
        return self.category in LABEL_CATEGORIES and self.triage != "C" and self.in_plan


def _s(v) -> str:
    return "" if v is None else str(v).strip()


def read_polygons(path: Path) -> list[Poly]:
    if not Path(path).exists():
        raise SystemExit(f"polygon file not found: {path}\n"
                         "Check [paths] polygons_gpkg in configs/config.toml (see data/README.md).")
    ds = ogr.Open(str(path), 0)
    lyr = ds.GetLayerByName(POLY_LAYER)
    if lyr is None:
        raise SystemExit(f"{path}: layer {POLY_LAYER} not found")
    srs = lyr.GetSpatialRef()
    if srs is None or srs.GetAuthorityCode(None) != str(grid.EPSG):
        raise SystemExit(f"{path}: {POLY_LAYER} must be EPSG:{grid.EPSG}")
    names = [f.name for f in lyr.schema]
    out = []
    for f in lyr:
        g = f.GetGeometryRef()
        g = g.Clone() if g is not None else None
        env = ()
        if g is not None and not g.IsEmpty():
            minx, maxx, miny, maxy = g.GetEnvelope()
            env = (minx, miny, maxx, maxy)
        out.append(Poly(_s(f["new_id"]), _s(f["site_id"]), _s(f["land"]), _s(f["category"]),
                        _s(f["triage"]).upper(), _s(f["herkunft"]) if "herkunft" in names else "", g, env))
    ds = None
    return out


def validate(polys: list[Poly]) -> tuple[list[str], list[str]]:
    """(errors, warnings). Errors stop 'train'."""
    errors, warns = [], []
    seen = {}
    for p in polys:
        tag = p.new_id or "(no new_id)"
        if p.new_id in seen:
            errors.append(f"{tag}: new_id used twice")
        seen[p.new_id] = p
        if p.geom is None or p.geom.IsEmpty():
            if p.in_plan:
                errors.append(f"{tag}: empty geometry")
            continue
        if ogr.GT_Flatten(p.geom.GetGeometryType()) not in (ogr.wkbPolygon, ogr.wkbMultiPolygon):
            errors.append(f"{tag}: geometry is {p.geom.GetGeometryName()}, not a polygon")
        if not p.geom.IsValid():
            errors.append(f"{tag}: invalid geometry (self-intersection?) - fix in QGIS (Vector > Geometry Tools > Check Validity)")
        if p.category not in CATEGORIES:
            errors.append(f"{tag}: category {p.category!r} unknown (allowed: {', '.join(CATEGORIES)})")
        if p.in_plan and p.land not in LANDS:
            errors.append(f"{tag}: land {p.land!r} unknown")
        if p.category == "holz_klein" and p.herkunft != "dop20_neu":
            warns.append(f"{tag}: holz_klein without herkunft = dop20_neu")
    labels = [p for p in polys if p.is_label and p.geom is not None and not p.geom.IsEmpty()]
    for k, a in enumerate(labels):
        for b in labels[k + 1:]:
            if a.env[0] < b.env[2] and b.env[0] < a.env[2] and a.env[1] < b.env[3] and b.env[1] < a.env[3]:
                if a.geom.Intersects(b.geom):
                    ov = a.geom.Intersection(b.geom).GetArea()
                    if ov > 1.0:
                        warns.append(f"{a.new_id} and {b.new_id} overlap by {ov:.0f} m2 (nested boxes of the same class)")
    return errors, warns


def plan_chips(polys: list[Poly]) -> dict[tuple[int, int], dict]:
    """Every g01 chip that touches a polygon of the plan (triage A/B or dop20_neu), any category -
    the chips that must be completely labelled (= the rows of chip_check)."""
    chips: dict[tuple[int, int], dict] = {}
    for p in polys:
        if not p.in_plan or p.geom is None or p.geom.IsEmpty():
            continue
        for i, j in grid.chips_touching_envelope(*p.env):
            if not p.geom.Intersects(box(*grid.chip_bounds(i, j))):
                continue
            c = chips.setdefault((i, j), {"sites": set(), "lands": set()})
            c["sites"].add(p.site_id)
            c["lands"].add(p.land)
    return chips


def box(minx, miny, maxx, maxy) -> ogr.Geometry:
    return ogr.CreateGeometryFromWkt(
        f"POLYGON(({minx} {miny},{maxx} {miny},{maxx} {maxy},{minx} {maxy},{minx} {miny}))")


def read_chip_status(path: Path) -> tuple[dict[tuple[int, int], str], list[str]]:
    """chip_check -> {(i, j): status}. Returns also the rows whose id could not be read."""
    ds = ogr.Open(str(path), 0)
    lyr = ds.GetLayerByName(CHIP_LAYER)
    if lyr is None:
        ds = None
        return {}, [f"{path}: layer {CHIP_LAYER} not found"]
    out, bad = {}, []
    for f in lyr:
        try:
            out[grid.parse_chip_id(_s(f["id"]))] = _s(f["status"])
        except ValueError as e:
            bad.append(str(e))
    ds = None
    return out, bad


def read_background(path: Path | None) -> list[dict]:
    if path is None or not Path(path).exists():
        return []
    ds = ogr.Open(str(path), 0)
    lyr = ds.GetLayerByName(BG_LAYER)
    out = [{"i": int(f["i"]), "j": int(f["j"]), "id": _s(f["id"]), "land": _s(f["land"]),
            "status": _s(f["status"])} for f in lyr] if lyr is not None else []
    ds = None
    return out


def read_holdout(path: Path | None) -> list[ogr.Geometry]:
    """All geometries of the first layer of holdout.gpkg (empty list if no holdout yet)."""
    if path is None:
        return []
    if not Path(path).exists():
        raise SystemExit(f"holdout file not found: {path}")
    ds = ogr.Open(str(path), 0)
    lyr = ds.GetLayer(0)
    out = [f.GetGeometryRef().Clone() for f in lyr if f.GetGeometryRef() is not None]
    ds = None
    return out


def append_chip_rows(path: Path, chips: list[tuple[int, int, str, str]]) -> None:
    """Append (i, j, land, site_ids) rows to chip_check with an empty status. Never changes a row."""
    ds = ogr.Open(str(path), 1)
    lyr = ds.GetLayerByName(CHIP_LAYER)
    names = [f.name for f in lyr.schema]
    for need in ("id", "land", "site_ids", "status"):
        if need not in names:
            raise SystemExit(f"{CHIP_LAYER} has no field {need}")
    lyr.StartTransaction()
    for i, j, land, sites in chips:
        f = ogr.Feature(lyr.GetLayerDefn())
        f["id"] = grid.old_chip_id(i, j)          # same id style as the existing rows
        f["land"], f["site_ids"] = land, sites
        f.SetGeometry(box(*grid.chip_bounds(i, j)))
        lyr.CreateFeature(f)
    lyr.CommitTransaction()
    ds = None


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def snapshot_gpkg(src: Path, dst: Path) -> None:
    """Copy all layers through GDAL (includes the -wal edits, unlike a file copy)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    gdal.VectorTranslate(str(dst), str(src), format="GPKG")
