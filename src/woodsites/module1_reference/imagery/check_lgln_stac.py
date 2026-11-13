"""
check_lgln_stac.py - which LGLN DOP20 flights exist at a place, according to the
official STAC catalogue (current), and read the newest one directly.

    python check_lgln_stac.py <E> <N>          (any point, EPSG:25832)
    python check_lgln_stac.py                  (test point from [checks] in config.toml)

STAC = SpatioTemporal Asset Catalog, a standard JSON catalogue of images. LGLN's
(metadata updated 12.10.2026; the GeoJSON index used in check_lgln_cog.py stops in 2023):
    https://dop.stac.lgln.niedersachsen.de/        API description: .../api.html

Saves the 400 m window of the newest flight to _cogtest/ for the WMS comparison.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from osgeo import gdal, osr

# Find the repository's src/ folder so that `import woodsites` works without installing it.
for _p in Path(__file__).resolve().parents:
    if (_p / "src" / "woodsites").is_dir():
        sys.path.insert(0, str(_p / "src"))
        break


def _settings() -> tuple[Path, float | None, float | None]:
    """Output folder <archive>/_cogtest and the test point, from configs/config.toml.

    The test point (EPSG:25832) is given on the command line (E N) or in the config:
        [checks]
        test_point = [<E>, <N>]
    """
    import tomllib
    from woodsites.core.config import config_path
    p = config_path()
    if not p.exists():
        raise SystemExit(f"config file not found: {p}\n"
                         "Copy configs/config.example.toml to configs/config.toml and fill in the paths.")
    with open(p, "rb") as f:
        cfg = tomllib.load(f)
    archive = (cfg.get("paths", {}).get("archive") or "").strip()
    if not archive:
        raise SystemExit(f"{p}: [paths] archive is missing")
    pt = cfg.get("checks", {}).get("test_point") or [None, None]
    return Path(archive) / "_cogtest", pt[0], pt[1]


def _point_from_args() -> None:
    """Set X, Y from the command line or the config; stop with a hint if neither is given."""
    global X, Y
    if len(sys.argv) == 3:
        X, Y = float(sys.argv[1]), float(sys.argv[2])
    if X is None or Y is None:
        raise SystemExit("no test point: give one as  E N  (EPSG:25832), e.g.\n"
                         f"    python {Path(__file__).name} <E> <N>\n"
                         "or set [checks] test_point = [<E>, <N>] in configs/config.toml")

gdal.UseExceptions()
osr.UseExceptions()

STAC = "https://dop.stac.lgln.niedersachsen.de"
OUT, X, Y = _settings()
WIN_M = 400.0
TILE_LL = (0.0, 0.0)             # lower-left of the 400 m archive tile under the point (set in main)

gdal.SetConfigOption("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
gdal.SetConfigOption("GDAL_HTTP_MAX_RETRY", "3")


def get_json(url: str) -> dict:
    """GET with retries (the institute DNS answers some cloud hosts only sometimes)."""
    last = None
    for attempt in range(6):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Thuenen-Institut",
                                                       "Accept": "application/geo+json, application/json"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            last = e
            print(f"    try {attempt + 1}: {e}")
            time.sleep(5)
    sys.exit(f"  could not reach {url}: {last}")


def lonlat(x: float, y: float) -> tuple[float, float]:
    s, t = osr.SpatialReference(), osr.SpatialReference()
    s.ImportFromEPSG(25832)
    t.ImportFromEPSG(4326)
    for r in (s, t):
        r.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    lon, lat, _ = osr.CoordinateTransformation(s, t).TransformPoint(x, y)
    return lon, lat


def main() -> None:
    global TILE_LL
    _point_from_args()
    TILE_LL = (X // 400 * 400, Y // 400 * 400)

    print("[1] catalogue and its collections")
    root = get_json(STAC + "/")
    print(f"  {root.get('title', '')}  (STAC {root.get('stac_version', '?')})")
    cols = get_json(STAC + "/collections").get("collections", [])
    for c in cols:
        ext = c.get("extent", {}).get("temporal", {}).get("interval", [[None, None]])[0]
        print(f"  collection {c.get('id')!r}: {c.get('title', '')}  time {ext}")

    print(f"\n[2] all flights at E{X:.0f} N{Y:.0f}")
    lon, lat = lonlat(X, Y)
    d = 0.0005
    q = {"bbox": f"{lon - d},{lat - d},{lon + d},{lat + d}", "limit": 100}
    items, url = [], STAC + "/search?" + urllib.parse.urlencode(q)
    while url and len(items) < 500:
        page = get_json(url)
        items += page.get("features", [])
        url = next((l["href"] for l in page.get("links", []) if l.get("rel") == "next"), None)
    if not items:
        sys.exit("  no items found - send me this output")
    rows = []
    for it in items:
        p = it.get("properties", {})
        date = p.get("datetime") or p.get("start_datetime") or ""
        tifs = {k: a["href"] for k, a in it.get("assets", {}).items()
                if str(a.get("href", "")).lower().split("?")[0].endswith((".tif", ".tiff"))}
        rows.append((date, it.get("collection", ""), it.get("id", ""), tifs))
    rows.sort(reverse=True)
    for date, col, iid, tifs in rows:
        print(f"  {date[:10]}  {col:20s} {iid:40s} assets: {', '.join(tifs) or '-'}")
    newest = max(items, key=lambda it: it.get("properties", {}).get("datetime")
                 or it.get("properties", {}).get("start_datetime") or "")
    print(f"  properties of the newest item: "
          f"{json.dumps(newest.get('properties', {}), ensure_ascii=False)[:400]}")

    print("\n[3] read the newest RGB flight directly")
    date, col, iid, tifs = next((r for r in rows if r[3]), (None, None, None, None))
    if not tifs:
        sys.exit("  no GeoTIFF asset in the items - send me this output")
    key = next((k for k in tifs if "rgb" in k.lower() and "rgbi" not in k.lower()), None) \
        or next((k for k in tifs if "rgbi" not in tifs[k].lower()), None) or next(iter(tifs))
    href = tifs[key]
    print(f"  {date[:10]}  asset {key!r}: {href}")
    # The catalogue links the raw cloud-storage host, which the institute DNS resolves only
    # sometimes. LGLN serves the same files under its own name (same folder structure), which
    # resolved fine -> try that first, fall back to the original, with retries.
    candidates = [href]
    for bucket in ("dop20-rgbi", "dop20-rgb"):
        raw = f"https://{bucket}.s3.eu-de.cloud-object-storage.appdomain.cloud/"
        if href.startswith(raw):
            candidates.insert(0, f"https://{bucket}.opengeodata.lgln.niedersachsen.de/" + href[len(raw):])
            break
    ds, t0 = None, time.monotonic()
    for attempt in range(4):
        for cand in candidates:
            path = cand if not cand.startswith("http") else "/vsicurl/" + cand
            try:
                ds = gdal.Open(path)
                print(f"  opened via {cand.split('/')[2]}")
                break
            except RuntimeError as e:
                print(f"    try {attempt + 1} {cand.split('/')[2]}: {str(e)[:120]}")
                gdal.VSICurlClearCache()
        if ds is not None:
            break
        time.sleep(5)
    if ds is None:
        sys.exit("  could not open the image over the network - send me this output")
    gt = ds.GetGeoTransform()
    print(f"  opened in {time.monotonic() - t0:.1f} s, {ds.RasterXSize}x{ds.RasterYSize} px, "
          f"{ds.RasterCount} bands, pixel {gt[1]} m, "
          f"LAYOUT={ds.GetMetadataItem('LAYOUT', 'IMAGE_STRUCTURE')}")
    x0, y1 = TILE_LL[0], TILE_LL[1] + WIN_M
    col0, row0 = int(round((x0 - gt[0]) / gt[1])), int(round((y1 - gt[3]) / gt[5]))
    n = int(round(WIN_M / gt[1]))
    if not (0 <= col0 and 0 <= row0 and col0 + n <= ds.RasterXSize and row0 + n <= ds.RasterYSize):
        sys.exit("  the 400 m window is not fully inside this file (tile edge) - send me this output")
    t0 = time.monotonic()
    arr = ds.ReadAsArray(col0, row0, n, n)
    print(f"  read {n}x{n} px in {time.monotonic() - t0:.1f} s (mean grey {arr.mean():.0f})")
    OUT.mkdir(parents=True, exist_ok=True)
    name = OUT / f"lgln_stac_{date[:10]}_E{int(x0)}_N{int(TILE_LL[1])}.tif"
    gdal.Translate(str(name), ds, srcWin=[col0, row0, n, n], bandList=[1, 2, 3],
                   creationOptions=["TILED=YES", "COMPRESS=DEFLATE", "PREDICTOR=2"])
    print(f"  saved {name}")
    print("\nDone. Send me this output.")


if __name__ == "__main__":
    main()
