"""Tests for tile_and_chip.py / woodsites with a synthetic archive (no network, no QGIS).

    cd /d <repo>
    python tests\\test_tile_and_chip.py

Every archive pixel encodes its own map position (red = x tick, green = y tick, mod 256),
so a chip that is shifted, flipped upside down or resampled wrongly is detected exactly.
"""
from __future__ import annotations

import csv
import hashlib
import os
import sys
import tempfile
from pathlib import Path

import numpy as np
from osgeo import gdal, ogr, osr

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))                           # woodsites
sys.path.insert(0, str(REPO / "src" / "woodsites" / "module2_detection" / "dataset"))  # tile_and_chip.py
gdal.UseExceptions()
ogr.UseExceptions()

TMP = Path(tempfile.mkdtemp(prefix="tac_test_"))
ARCH, POLY, BG, HOLD, OUT = TMP / "archive", TMP / "poly" / "dop20_polygons.gpkg", \
    TMP / "poly" / "background_g01.gpkg", TMP / "poly" / "holdout.gpkg", TMP / "datasets"
FAILS: list[str] = []


def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def srs():
    s = osr.SpatialReference()
    s.ImportFromEPSG(25832)
    return s


def tile_pattern(a: int, b: int) -> np.ndarray:
    cols = a * 2000 + np.arange(2000)                       # x tick of each column
    rows = (b + 1) * 2000 - np.arange(2000) - 1             # y tick (lower edge) of each row, top row first
    X, Y = np.meshgrid(cols, rows)
    return np.stack([X % 256, Y % 256, ((X + Y) // 7) % 256]).astype(np.uint8)


def expected_chip(i: int, j: int) -> np.ndarray:
    x0, y0 = i * 3072, j * 3072
    cols = x0 + np.arange(4096)
    rows = y0 + 4096 - np.arange(4096) - 1
    X, Y = np.meshgrid(cols, rows)
    full = np.stack([X % 256, Y % 256, ((X + Y) // 7) % 256]).astype(np.uint16)
    s = full.reshape(3, 2048, 2, 2048, 2).sum(axis=(2, 4))
    return ((s + 2) // 4).astype(np.uint8)


def make_archive(tiles: list[tuple[int, int]]):
    from woodsites.core import grid
    ARCH.mkdir(parents=True)
    (ARCH / "XX").mkdir()
    rows = []
    for a, b in tiles:
        tid = grid.tile_id(a, b)
        p = ARCH / "XX" / f"{tid}.tif"
        ds = gdal.GetDriverByName("GTiff").Create(str(p), 2000, 2000, 3, gdal.GDT_Byte,
                                                  options=["TILED=YES", "COMPRESS=DEFLATE"])
        ds.SetGeoTransform((a * 400.0, 0.2, 0.0, (b + 1) * 400.0, 0.0, -0.2))
        ds.SetProjection(srs().ExportToWkt())
        arr = tile_pattern(a, b)
        for k in range(3):
            ds.GetRasterBand(k + 1).WriteArray(arr[k])
        ds = None
        rows.append({"tile_id": tid, "land": "Testland", "file": f"XX/{tid}.tif", "bildflug": "2025-05-01"})
    with open(ARCH / "manifest.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["tile_id", "land", "file", "bildflug"])
        w.writeheader()
        w.writerows(rows)


def make_gpkg(path: Path, layer: str, fields: list[str], rows: list[dict], gtype=ogr.wkbPolygon):
    path.parent.mkdir(parents=True, exist_ok=True)
    ds = ogr.Open(str(path), 1) if path.exists() else ogr.GetDriverByName("GPKG").CreateDataSource(str(path))
    lyr = ds.CreateLayer(layer, srs(), gtype)
    for fn in fields:
        lyr.CreateField(ogr.FieldDefn(fn, ogr.OFTInteger if fn in ("i", "j") else ogr.OFTString))
    for r in rows:
        f = ogr.Feature(lyr.GetLayerDefn())
        for fn in fields:
            if r.get(fn) is not None:
                f[fn] = r[fn]
        f.SetGeometry(ogr.CreateGeometryFromWkt(r["wkt"]))
        lyr.CreateFeature(f)
    ds = None


def rect(x0, y0, x1, y1):
    return f"POLYGON(({x0} {y0},{x1} {y0},{x1} {y1},{x0} {y1},{x0} {y0}))"


def set_status(path: Path, status_by_old_id: dict):
    ds = ogr.Open(str(path), 1)
    lyr = ds.GetLayerByName("chip_check")
    for f in lyr:
        if f["id"] in status_by_old_id:
            f["status"] = status_by_old_id[f["id"]]
            lyr.SetFeature(f)
    ds = None


def files_hash(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted((root / "images").rglob("*.tif")) + sorted((root / "labels").rglob("*.txt")):
        h.update(p.relative_to(root).as_posix().encode())
        if p.suffix == ".tif":
            ds = gdal.Open(str(p))
            h.update(ds.ReadAsArray().tobytes())
            h.update(repr(ds.GetGeoTransform()).encode())
            ds = None
        else:
            h.update(p.read_bytes())
    return h.hexdigest()


def write_config(holdout: str = "") -> Path:
    p = TMP / "config.toml"
    p.write_text(f"[paths]\npolygons_gpkg = '{POLY}'\narchive = '{ARCH}'\nbackground_gpkg = '{BG}'\n"
                 f"dataset_root = '{OUT}'\nholdout_gpkg = '{holdout}'\n"
                 "[tile_and_chip]\nholz_klein = 'positive'\nval_share = 0.15\nseed = 1\n", encoding="utf-8")
    return p


def main():
    from woodsites.core import grid, polygons as P
    from woodsites.core.sources import ArchiveSource, MissingTiles
    from woodsites.module2_detection.dataset import labels as L, split as S
    import tile_and_chip as T

    # ---------------- grid ----------------
    check(grid.parse_chip_id("g01_E0615014_N5530214") == (1001, 9001), "old chip id -> (1001, 9001)")
    check(grid.parse_chip_id("g01_i01001_j09001") == (1001, 9001), "new chip id parsed")
    check(grid.old_chip_id(1001, 9001) == "g01_E0615014_N5530214", "old id rebuilt exactly")
    check(grid.old_chip_id(1002, 9004) == "g01_E0615629_N5532058", "old id rounds .8/.6 up")
    check(grid.parse_chip_id("g01_E0615629_N5532058") == (1002, 9004), "rounded old id parsed back")
    check(grid.chip_bounds(1001, 9001)[0] == 615014.4, "exact corner 615014.4")
    for (i, j) in [(1002, 9003), (0, 0), (1001, 9001)]:
        b = (615100.3, 5530500.1, 615700.7, 5530560.9)
        back = grid.yolo_to_box(*grid.box_to_yolo(*b, i, j), i, j)
        check(max(abs(x - y) for x, y in zip(b, back)) < 1e-6, f"YOLO round trip exact in chip {i},{j}")
    xc, yc, w, h = grid.box_to_yolo(615300, 5530430, 615400, 5530490, 1001, 9001)
    check(abs(xc - 0.409668) < 1e-6 and abs(yc - 0.700195) < 1e-6 and abs(w - 0.122070) < 1e-6
          and abs(h - 0.073242) < 1e-6, f"YOLO numbers by hand (lower half of chip -> yc {yc:.4f} > 0.5)")
    check(grid.chips_overlap((5, 5), (6, 6)) and not grid.chips_overlap((5, 5), (7, 5)), "overlap rule")
    check(len(grid.tiles_for_chip(1001, 9001)) in (9, 12, 16), "3-4 tiles per axis")

    # ---------------- synthetic archive ----------------
    tiles = [(a, b) for a in range(1536, 1543) for b in range(13824, 13831)]
    make_archive(tiles)
    src = ArchiveSource(ARCH)
    for c in [(1001, 9001), (1002, 9003), (1003, 9003)]:
        rgb, meta = src.read(*c)
        check(np.array_equal(rgb, expected_chip(*c)), f"chip {c} read exactly (position, Y axis, 2x2 mean)")
    check(meta["bildflug"] == ["2025-05-01"], "flight date from the manifest")

    # ---------------- gaps vs. bright roofs ----------------
    from woodsites.module2_detection.dataset.raster import gap_share
    rng = np.random.default_rng(0)
    img = rng.integers(60, 200, (3, 2048, 2048)).astype(np.uint8)
    img[:, 100:400, 100:400] = rng.integers(235, 256, (3, 300, 300))        # bright roof: many pixels >= 250
    check(gap_share(img) == 0, "bright roof is not a gap")
    img[:, 1024:1344, :320] = 255                                            # real gap: flat white, 10 x 10 blocks
    check(abs(gap_share(img) - 100 / 4096) < 1e-9, f"flat white area counted as gap ({gap_share(img):.4f})")

    # ---------------- polygons ----------------
    X = lambda v: v                                          # noqa: E731  (readability)
    pol = [  # site S1 in chip (1001, 9001); y 5530419.2-5530828.8 belongs to j = 9001 only
        dict(new_id="S1_L01", site_id="S1", land="Niedersachsen", category="logyard_rough", triage="A",
             wkt=rect(615300, 5530430, 615400, 5530490)),
        dict(new_id="S1_L02", site_id="S1", land="Niedersachsen", category="logyard_rough", triage="B",
             wkt=rect(615150, 5530500, 615700, 5530560)),             # crosses into i=1000 and i=1002
        dict(new_id="S1_L03", site_id="S1", land="Niedersachsen", category="logyard_rough", triage="A",
             wkt=rect(615100, 5530600, 615800, 5530800)),             # big: 1 ha rule in i=1000/1002
        dict(new_id="S1_N01", site_id="S1", land="Niedersachsen", category="holz_klein", herkunft="dop20_neu",
             wkt=rect(615450, 5530440, 615470, 5530460)),
        dict(new_id="S1_I01", site_id="S1", land="Niedersachsen", category="industry_site", triage="A",
             wkt=rect(615050, 5530420, 615850, 5530820)),
        dict(new_id="S1_L04", site_id="S1", land="Niedersachsen", category="logyard_rough", triage="C",
             wkt=rect(615500, 5530440, 615600, 5530490)),
        dict(new_id="S2_L01", site_id="S2", land="Niedersachsen", category="logyard_rough", triage="A",
             wkt=rect(615300, 5531700, 615400, 5531800)),             # chip (1001, 9003) only
    ]
    make_gpkg(POLY, "dop20_polygons", ["new_id", "site_id", "land", "category", "triage", "herkunft"], pol)
    make_gpkg(POLY, "chip_check", ["id", "land", "site_ids", "status"], [])
    polys = P.read_polygons(POLY)
    errors, warns = P.validate(polys)
    check(not errors, f"validate: no errors {errors}")
    check(any("S1_I01" in w for w in warns) is False, "industry_site never in the overlap warning")
    plan = P.plan_chips(polys)
    check(sorted(plan) == [(1000, 9001), (1001, 9001), (1001, 9003), (1002, 9001)], f"plan chips {sorted(plan)}")
    labs = [p for p in polys if p.is_label]
    check(sorted(p.new_id for p in labs) == ["S1_L01", "S1_L02", "S1_L03", "S1_N01", "S2_L01"],
          "labels: logyard_rough A/B + holz_klein dop20_neu; not industry_site, not C")

    # ---------------- 50 % / 1 ha rule ----------------
    tc = dict(T.C.TC_DEFAULTS)
    bx, mk = L.chip_labels(1001, 9001, labs, tc)
    check(sorted(b.new_id for b in bx) == ["S1_L01", "S1_L02", "S1_L03", "S1_N01"] and not mk,
          "chip (1001,9001): 4 whole boxes incl. holz_klein (positive), no mask")
    check(not any(b.cut_at_edge for b in bx), "nothing cut in (1001,9001)")
    bx, mk = L.chip_labels(1002, 9001, labs, tc)
    check([b.new_id for b in bx] == ["S1_L03"] and bx[0].cut_at_edge and bx[0].visible < 0.5,
          f"chip (1002,9001): S1_L03 kept by the 1 ha rule ({bx[0].visible:.0%} visible), cut_at_edge")
    check([m.new_id for m in mk] == ["S1_L02"] and mk[0].reason == "below threshold",
          "chip (1002,9001): S1_L02 (13 %, 0.4 ha) masked")
    tc2 = dict(tc, min_visible_m2=1e12)
    bx, mk = L.chip_labels(1002, 9001, labs, tc2)
    check(not bx and sorted(m.new_id for m in mk) == ["S1_L02", "S1_L03"], "without the 1 ha rule both are masked")
    bx, mk = L.chip_labels(1001, 9001, labs, dict(tc, holz_klein="mask"))
    check("S1_N01" not in [b.new_id for b in bx] and [m.reason for m in mk] == ["holz_klein mask"],
          "holz_klein = mask")
    bx, mk = L.chip_labels(1001, 9001, labs, dict(tc, holz_klein="background"))
    check("S1_N01" not in [b.new_id for b in bx] and not mk, "holz_klein = background")

    # ---------------- split ----------------
    lc = [(i, j) for i in range(10) for j in range(3)] + [(20, 0), (21, 0), (30, 5)]
    sp = S.split(lc, [(50, 50), (60, 60)], 0.15, 1)
    bad = [(a, b) for a in lc for b in lc if sp[a] != sp[b] and grid.chips_overlap(a, b)]
    check(not bad and any(v == "val" for v in sp.values()), "split: no train chip overlaps a val chip")
    check(sp == S.split(lc, [(50, 50), (60, 60)], 0.15, 1), "split is seeded")
    # five sites of 8, 8, 4, 16, 7 chips (like d004): val must be close to 15 % of 43, not 20 chips
    sites, k0 = [], 0
    for size in (8, 8, 4, 16, 7):
        sites += [(k0 + n, 0) for n in range(size)]     # a row of overlapping chips = one group
        k0 += size + 5
    sp = S.split(sites, [], 0.15, 1)
    n_val = sum(1 for v in sp.values() if v == "val")
    check(n_val in (7, 8), f"split close to 15 %: {n_val} of {len(sites)} chips in val (target 6.45)")
    bad = [(a, b) for a in sites for b in sites if sp[a] != sp[b] and grid.chips_overlap(a, b)]
    check(not bad, "split still keeps overlapping chips together")
    check(S.split([(0, 0), (1, 0)], [], 0.15, 1) == {(0, 0): "train", (1, 0): "train"},
          "one group only -> everything in train")

    # ---------------- CLI ----------------
    cfg = write_config()
    os.environ["WOODSITES_CONFIG"] = str(cfg)
    check(T.main(["sync-chipcheck"]) == 0, "sync-chipcheck runs")
    st, _ = P.read_chip_status(POLY)
    check(sorted(st) == sorted(plan), "chip_check now has every plan chip")
    check(T.main(["sync-chipcheck"]) == 0 and len(P.read_chip_status(POLY)[0]) == 4, "second sync adds nothing")
    set_status(POLY, {grid.old_chip_id(1000, 9001): "vollständig", grid.old_chip_id(1001, 9001): "vollständig",
                      grid.old_chip_id(1002, 9001): "unsicher", grid.old_chip_id(1001, 9003): "vollständig"})
    (ARCH / "XX" / f"{grid.tile_id(1536, 13825)}.tif").unlink()     # only chip (1000, 9001) needs it
    try:
        src2 = ArchiveSource(ARCH)
        src2.read(1000, 9001)
        check(False, "missing tile raises")
    except MissingTiles:
        check(True, "missing tile raises MissingTiles (never zero-filled)")
    make_gpkg(BG, "background_g01", ["id", "i", "j", "land", "status"], [
        dict(id="g01_i01003_j09003", i=1003, j=9003, land="Testland", status="ok",
             wkt=rect(*grid.chip_bounds(1003, 9003))),
        dict(id="g01_i01002_j09000", i=1002, j=9000, land="Testland", status="ok",
             wkt=rect(*grid.chip_bounds(1002, 9000))),                 # overlaps plan chip (1002, 9001)
        dict(id="g01_i01003_j09000", i=1003, j=9000, land="Testland", status="",
             wkt=rect(*grid.chip_bounds(1003, 9000)))])
    check(T.main(["check"]) == 0, "check runs without errors")
    check(T.main(["train", "--dry-run"]) == 0 and (not OUT.exists() or not any(OUT.iterdir())),
          "dry run writes nothing")
    check(T.main(["train"]) == 0, "train runs")
    d1 = sorted(OUT.glob("d001_*"))[0]
    from woodsites.module2_detection.dataset import index as I
    chips = {r["id"]: r for r in I.read_layer(d1 / "chip_index.gpkg", "chips")}
    written = sorted(k for k, r in chips.items() if r["written"])
    check(written == ["g01_i01001_j09001", "g01_i01001_j09003", "g01_i01003_j09003"],
          f"written chips {written}")
    check("missing tiles" in chips["g01_i01000_j09001"]["skip_reason"], "chip with a missing tile left out")
    check(chips["g01_i01002_j09001"]["skip_reason"] == "status 'unsicher'", "unsicher left out by default")
    check(chips["g01_i01002_j09000"]["skip_reason"] == "overlaps a plan chip", "background overlapping plan left out")
    check(chips["g01_i01003_j09000"]["skip_reason"] == "status 'empty'", "unchecked background left out")
    check(chips["g01_i01003_j09003"]["kind"] == "background"
          and (d1 / "labels" / chips["g01_i01003_j09003"]["split"] / "g01_i01003_j09003.txt").read_text() == "",
          "background chip has an empty label file")
    lines = (d1 / "labels" / chips["g01_i01001_j09001"]["split"] / "g01_i01001_j09001.txt").read_text().split("\n")
    check("0 0.409668 0.700195 0.122070 0.073242" in lines, "S1_L01 line exactly as computed by hand")
    img = gdal.Open(str(d1 / "images" / chips["g01_i01001_j09001"]["split"] / "g01_i01001_j09001.tif"))
    check(img.GetGeoTransform() == grid.geotransform(1001, 9001), "chip GeoTIFF georeferenced (top-left, -0.4)")
    check(np.array_equal(img.ReadAsArray(), expected_chip(1001, 9001)), "unmasked chip image = exact archive pixels")
    img = None
    check(len({chips[c]["split"] for c in ("g01_i01001_j09001", "g01_i01001_j09003")}) == 2,
          "the two sites ended in different splits (train / val)")
    for f in ("data.yaml", "params.json", "report.txt", "snapshot/dop20_polygons.gpkg", "snapshot/sha256.txt",
              "snapshot/manifest.csv", "snapshot/config.toml", "snapshot/background_g01.gpkg"):
        check((d1 / f).exists(), f"dataset has {f}")
    snap = P.read_chip_status(d1 / "snapshot" / "dop20_polygons.gpkg")[0]
    check(snap.get((1002, 9001)) == "unsicher", "snapshot contains chip_check with the statuses used")
    check(T.main(["roundtrip", d1.name]) == 0, "roundtrip OK")

    # determinism
    check(T.main(["train"]) == 0, "second train run")
    d2 = sorted(OUT.glob("d002_*"))[0]
    check(files_hash(d1) == files_hash(d2), "same inputs -> identical images and labels (d001 = d002)")

    # unsicher included -> masked pixels are grey
    check(T.main(["train", "--include-unsicher"]) == 0, "train --include-unsicher")
    d3 = sorted(OUT.glob("d003_*"))[0]
    ch3 = {r["id"]: r for r in I.read_layer(d3 / "chip_index.gpkg", "chips")}
    r = ch3["g01_i01002_j09001"]
    check(r["written"] == 1 and r["n_labels"] == 1 and r["n_masked"] == 1 and r["n_cut"] == 1,
          "unsicher chip written: 1 box (cut), 1 mask")
    img = gdal.Open(str(d3 / "images" / r["split"] / "g01_i01002_j09001.tif")).ReadAsArray()
    from woodsites.module2_detection.dataset.raster import rasterize
    masks = [m for m in I.read_layer(d3 / "chip_index.gpkg", "masks") if m["chip_id"] == "g01_i01002_j09001"]
    mm = rasterize([m["geom"] for m in masks], 1002, 9001)
    check(mm.sum() > 0 and (img[:, mm] == 114).all(), f"all {mm.sum()} masked pixels are 114 grey")
    exp = expected_chip(1002, 9001)
    check(np.array_equal(img[:, ~mm], exp[:, ~mm]), "all other pixels unchanged")
    # inner part of S1_L02 in this chip: x 615628.8-615700, y 5530500-5530560 -> rows from the top
    c0, r0 = grid.world_to_px(615640, 5530550, 1002, 9001)
    check(mm[int(r0), int(c0)], "a point inside S1_L02 is masked at the right row (Y axis)")
    c1, r1 = grid.world_to_px(615640, 5530300, 1002, 9001)
    check(not mm[int(r1), int(c1)], "a point 250 m lower is not masked")
    check(T.main(["roundtrip", d3.name]) == 0, "roundtrip OK with a cut box")

    # holdout
    make_gpkg(HOLD, "holdout", ["name"], [dict(name="S2", wkt=rect(615250, 5531650, 615450, 5531850))])
    os.environ["WOODSITES_CONFIG"] = str(write_config(str(HOLD)))
    check(T.main(["train"]) == 0, "train with holdout")
    d4 = sorted(OUT.glob("d004_*"))[0]
    ch4 = {r["id"]: r for r in I.read_layer(d4 / "chip_index.gpkg", "chips")}
    check(ch4["g01_i01001_j09003"]["skip_reason"] == "holdout" and not ch4["g01_i01001_j09003"]["written"],
          "holdout chip never written")
    check(not list(d4.rglob("g01_i01001_j09003.*")), "no file of the holdout chip in the dataset")

    # prediction mode
    check(T.main(["chips", "--chips", "g01_i01001_j09001,g01_E0615014_N5530214,g01_i01000_j09001",
                  "--out", str(TMP / "pred")]) == 0, "chips (prediction mode) runs")
    pr = {r["id"]: r for r in I.read_layer(TMP / "pred" / "chip_index.gpkg", "chips")}
    check(len(pr) == 2 and pr["g01_i01001_j09001"]["written"] == 1 and not pr["g01_i01000_j09001"]["written"],
          "old and new ids are the same chip; missing tiles reported")
    a = gdal.Open(str(TMP / "pred" / "images" / "g01_i01001_j09001.tif")).ReadAsArray()
    check(np.array_equal(a, expected_chip(1001, 9001)), "prediction chip = training chip pixels (no mask)")

    print(f"\n{'ALL PASS' if not FAILS else f'{len(FAILS)} FAILED'}   (test files in {TMP})")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
