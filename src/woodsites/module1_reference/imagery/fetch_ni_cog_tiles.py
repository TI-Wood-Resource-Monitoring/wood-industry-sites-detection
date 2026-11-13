"""
fetch_ni_cog_tiles.py - Niedersachsen fallback for fetch_wms_chips.py: write the same
f01 tiles (400 m = 2000 x 2000 px @ 0.2 m, EPSG:25832) into <archive>\\NI\\,
but read the pixels from the LGLN COG (found through the STAC catalogue) instead of the WMS.

Use it when `python fetch_wms_chips.py probe --only Niedersachsen` still shows the
maintenance page.

    cd /d <repo>          (then: python src\\woodsites\\module1_reference\\imagery\\fetch_ni_cog_tiles.py ...)
    python fetch_ni_cog_tiles.py list                 which flights exist at the 3 NI sites (nothing is written)
    python fetch_ni_cog_tiles.py run --limit 1        write ONE tile first, look at it in QGIS
    python fetch_ni_cog_tiles.py run                  write all missing NI tiles (resumable)
    python fetch_ni_cog_tiles.py run --date 2025-04-03   use a specific flight instead of the newest

Reuses plan, GeoTIFF writer and manifest of fetch_wms_chips.py (same folder), so the tiles
look exactly like WMS tiles to the rest of the pipeline. Manifest column `note` says
"source=LGLN COG" and `bildflug` holds the flight date from STAC.
Never overwrites an existing tile. After `run`: remove the mosaic layer in QGIS, then
`python fetch_wms_chips.py mosaic`.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from osgeo import gdal, osr

try:                                 # installed package (pip install -e .)
    from woodsites.module1_reference.imagery import fetch_wms_chips as F
except ImportError:                  # run as a script: same folder
    import fetch_wms_chips as F

gdal.UseExceptions()
osr.UseExceptions()
gdal.SetConfigOption("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
gdal.SetConfigOption("GDAL_HTTP_MAX_RETRY", "4")
gdal.SetConfigOption("GDAL_HTTP_RETRY_DELAY", "3")

LAND = "Niedersachsen"
STAC = "https://dop.stac.lgln.niedersachsen.de"


def get_json(url: str) -> dict:
    last = None
    for attempt in range(6):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": F.USER_AGENT,
                                                       "Accept": "application/geo+json, application/json"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:                      # DNS at the institute answers only sometimes
            last = e
            time.sleep(5)
    raise SystemExit(f"cannot reach {url}: {last}")


def lonlat(x: float, y: float) -> tuple[float, float]:
    s, t = osr.SpatialReference(), osr.SpatialReference()
    s.ImportFromEPSG(25832)
    t.ImportFromEPSG(4326)
    for r in (s, t):
        r.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    lon, lat, _ = osr.CoordinateTransformation(s, t).TransformPoint(x, y)
    return lon, lat


def flights_at(x: float, y: float) -> list[dict]:
    """All STAC items at a point, newest first, each with date and the RGB (not RGBI) tif link."""
    lon, lat = lonlat(x, y)
    d = 0.0005
    q = {"bbox": f"{lon - d},{lat - d},{lon + d},{lat + d}", "limit": 100}
    url, items = STAC + "/search?" + urllib.parse.urlencode(q), []
    while url and len(items) < 500:
        page = get_json(url)
        items += page.get("features", [])
        url = next((l["href"] for l in page.get("links", []) if l.get("rel") == "next"), None)
    out = []
    for it in items:
        p = it.get("properties", {})
        date = p.get("datetime") or p.get("start_datetime") or ""
        tifs = {k: a["href"] for k, a in it.get("assets", {}).items()
                if str(a.get("href", "")).lower().split("?")[0].endswith((".tif", ".tiff"))}
        if not tifs:
            continue
        key = next((k for k in tifs if "rgb" in k.lower() and "rgbi" not in k.lower()), None) \
            or next((k for k in tifs if "rgbi" not in tifs[k].lower()), None)
        if key is None:                              # only RGBI offered -> first three bands are RGB
            key = next(iter(tifs))
        out.append({"date": date[:10], "item": it.get("id", ""), "collection": it.get("collection", ""),
                    "key": key, "href": tifs[key], "props": p})
    out.sort(key=lambda r: r["date"], reverse=True)
    return out


def open_cog(href: str):
    """LGLN serves the same files under its own host name; the raw cloud host resolves only sometimes."""
    cands = [href]
    for bucket in ("dop20-rgbi", "dop20-rgb"):
        raw = f"https://{bucket}.s3.eu-de.cloud-object-storage.appdomain.cloud/"
        if href.startswith(raw):
            cands.insert(0, f"https://{bucket}.opengeodata.lgln.niedersachsen.de/" + href[len(raw):])
            break
    for attempt in range(4):
        for cand in cands:
            try:
                return gdal.Open("/vsicurl/" + cand if cand.startswith("http") else cand), cand
            except RuntimeError:
                gdal.VSICurlClearCache()
        time.sleep(5)
    raise RuntimeError(f"cannot open {href}")


def ni_tiles() -> dict:
    polys = F.load_polygons()
    _, tiles = F.make_plan(polys)
    return {k: t for k, t in tiles.items() if t["land"] == LAND}


def pick_flight(fl: list[dict], date: str | None) -> dict:
    if date:
        m = [f for f in fl if f["date"] == date]
        if not m:
            raise RuntimeError(f"no flight dated {date}; available: {', '.join(f['date'] for f in fl)}")
        return m[0]
    return fl[0]


def cmd_list(tiles: dict) -> None:
    seen = {}
    for t in sorted(tiles.values(), key=lambda t: t["tile_id"]):
        for s in sorted(t["sites"]):
            seen.setdefault(s, t)
    for s, t in sorted(seen.items()):
        fl = flights_at(t["E"] + 200, t["N"] + 200)
        print(f"{s}  ({t['tile_id']})")
        for f in fl:
            print(f"    {f['date']}  {f['collection']:14s} {f['key']:10s} {f['item']}")
        if not fl:
            print("    no flights found")


def cmd_run(tiles: dict, limit: int | None, date: str | None) -> None:
    F.upgrade_manifest()
    done = F.manifest_rows()
    folder = F.archive() / F.CODE[LAND]
    folder.mkdir(exist_ok=True)
    cache: dict[str, tuple] = {}
    n_new = n_skip = n_fail = 0
    t_start = time.monotonic()
    for t in sorted(tiles.values(), key=lambda t: t["tile_id"]):
        tid, E, N = t["tile_id"], t["E"], t["N"]
        final, part = folder / f"{tid}.tif", folder / f"{tid}.tif.part"
        if tid in done and final.exists():
            n_skip += 1
            continue
        if final.exists() and tid not in done:
            print(f"  ! {tid}.tif exists without a manifest row - left alone, check it")
            n_skip += 1
            continue
        if limit is not None and n_new >= limit:
            break
        t0 = time.monotonic()
        try:
            fl = pick_flight(flights_at(E + 200, N + 200), date)
            if fl["href"] not in cache:
                cache[fl["href"]] = open_cog(fl["href"])
            ds, used = cache[fl["href"]]
            gt = ds.GetGeoTransform()
            if abs(gt[1] - F.GSD) > 1e-6 or abs(gt[5] + F.GSD) > 1e-6:
                raise RuntimeError(f"COG pixel size is {gt[1]} m, expected {F.GSD} m")
            col0, row0 = (E - gt[0]) / gt[1], (N + F.TILE_M - gt[3]) / gt[5]
            if abs(col0 - round(col0)) > 1e-3 or abs(row0 - round(row0)) > 1e-3:
                raise RuntimeError(f"tile is not on the COG pixel lattice (col {col0}, row {row0})")
            col0, row0 = int(round(col0)), int(round(row0))
            if not (0 <= col0 and 0 <= row0 and col0 + F.TILE_PX <= ds.RasterXSize
                    and row0 + F.TILE_PX <= ds.RasterYSize):
                raise RuntimeError("tile not fully inside this COG file")
            arr = ds.ReadAsArray(col0, row0, F.TILE_PX, F.TILE_PX)[:3].astype(np.uint8)
            empty = (arr == 255).all(axis=0) | (arr == 0).all(axis=0)
            fetched = F.now_utc()
            meta = {"SOURCE": f"LGLN COG {used}", "FETCHED_UTC": fetched, "FORMAT": "COG RGB (original pixels)",
                    "BILDFLUG": fl["date"], "TILE_ID": tid,
                    "LICENCE_NOTE": "DOP20 Niedersachsen, (c) LGLN, CC BY 4.0; attribution required"}
            part.unlink(missing_ok=True)
            F.write_geotiff(part, arr, E, N, meta)
            digest = F.sha256(part)
            part.rename(final)
            F.append_manifest({
                "tile_id": tid, "land": LAND, "site_ids": ";".join(sorted(t["sites"])),
                "minx": E, "miny": N, "maxx": E + F.TILE_M, "maxy": N + F.TILE_M, "epsg": F.EPSG,
                "native_epsg": F.EPSG, "px": F.TILE_PX, "gsd_m": F.GSD, "wms_url": used,
                "layer": fl["key"], "wms_version": "", "format": "COG",
                "n_requests": 1, "fetched_utc": fetched, "seconds": round(time.monotonic() - t0, 1),
                "file": f"{F.CODE[LAND]}/{tid}.tif", "bytes": final.stat().st_size, "sha256": digest,
                "leer_anteil": round(float(empty.mean()), 4), "info_layer": "STAC",
                "bildflug": fl["date"], "bildflug_feld": "stac datetime",
                "bildflug_raw": json.dumps({"item": fl["item"], "collection": fl["collection"]}),
                "note": "source=LGLN COG (not WMS)" + ("; mostly empty - check" if empty.mean() > 0.5 else ""),
            })
            n_new += 1
            print(f"  [{n_new}] {tid} {fl['date']} ok ({time.monotonic() - t_start:.0f} s)", flush=True)
        except (RuntimeError, OSError) as e:
            n_fail += 1
            F.log_error(tid, LAND, f"cog: {e}")
            print(f"  ! {tid}: {str(e)[:200]}")
    print(f"\nwritten {n_new}, already there {n_skip}, failed {n_fail}"
          + (f"  -> see {F.archive() / 'errors.csv'}" if n_fail else ""))
    if n_new:
        print("next: remove the mosaic layer in QGIS, then  python fetch_wms_chips.py mosaic")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["list", "run"])
    ap.add_argument("--limit", type=int)
    ap.add_argument("--date", help="flight date YYYY-MM-DD (default: newest)")
    a = ap.parse_args()
    tiles = ni_tiles()
    print(f"archive: {F.archive()}\n{len(tiles)} NI tiles planned")
    F.keep_awake(True)
    try:
        cmd_list(tiles) if a.command == "list" else cmd_run(tiles, a.limit, a.date)
    finally:
        F.keep_awake(False)


if __name__ == "__main__":
    main()
