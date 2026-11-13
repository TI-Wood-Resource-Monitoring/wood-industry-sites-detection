"""
check_lgln_cog.py - can we read the original LGLN DOP20 files directly over the network?

Runs in the OSGeo4W Shell (GDAL + numpy), takes about a minute, downloads only a few MB:

    python check_lgln_cog.py <E> <N>     (a point in Lower Saxony, EPSG:25832)

What it checks
  1. The LGLN tile index (GeoJSON) is reachable and lists the tile under the test point.
  2. That tile's GeoTIFF is really a Cloud Optimized GeoTIFF (internal tiles + overviews).
  3. A window can be read straight from the URL, how long that takes, at 0.2 m and at 0.4 m.
  4. It saves the window as GeoTIFF next to the WMS archive (_cogtest/), so it can later be
     compared pixel by pixel with the same area fetched from the NI WMS (feasibility test).

Source of the index URL: the LGLN's own example notebook
https://github.com/BostelmannLGLN/LGLN-OpenData-Notebooks (DOP.ipynb)
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from osgeo import gdal, ogr, osr

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
ogr.UseExceptions()

INDEX = ("https://single-datasets.s3.eu-de.cloud-object-storage.appdomain.cloud/"
         "pro-download-indices/dop/lgln-opengeodata-dop20.geojson")
OUT, X, Y = _settings()
WIN_M = 400.0                        # same size as one archive tile

# GDAL network settings: read only the bytes we need, no directory listings.
# If the institute needs a proxy, set it here, e.g. "http://proxy.example:8080"
PROXY = ""
gdal.SetConfigOption("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
gdal.SetConfigOption("CPL_VSIL_CURL_ALLOWED_EXTENSIONS", ".tif,.tiff,.geojson,.json")
gdal.SetConfigOption("GDAL_HTTP_MAX_RETRY", "3")
gdal.SetConfigOption("GDAL_HTTP_TIMEOUT", "60")
def windows_proxy() -> str:
    """The proxy Windows is set to use (what Python's urllib - and so fetch_wms_chips.py -
    picks up automatically, but GDAL/curl does not)."""
    import urllib.request
    p = urllib.request.getproxies()
    return p.get("https") or p.get("http") or ""


def diagnose() -> None:
    """Tell 'proxy needed' apart from 'address gone'."""
    import socket
    import urllib.request
    host = INDEX.split("/")[2]
    print(f"  Windows proxy setting: {windows_proxy() or '(none)'}")
    try:
        print(f"  DNS lookup {host}: {socket.gethostbyname(host)}")
    except OSError as e:
        print(f"  DNS lookup {host}: FAILED ({e})")
    try:
        req = urllib.request.Request(INDEX, method="HEAD", headers={"User-Agent": "Thuenen-Institut"})
        with urllib.request.urlopen(req, timeout=30) as r:
            print(f"  Python/urllib (uses the Windows proxy): HTTP {r.status}, "
                  f"{int(r.headers.get('Content-Length') or 0) / 1e6:.1f} MB")
    except Exception as e:
        print(f"  Python/urllib (uses the Windows proxy): FAILED ({e})")


if not PROXY:
    PROXY = windows_proxy()
if PROXY:
    gdal.SetConfigOption("GDAL_HTTP_PROXY", PROXY)
    print(f"using proxy {PROXY}")


def step(n: int, text: str) -> None:
    print(f"\n[{n}] {text}", flush=True)


def main() -> None:
    _point_from_args()
    step(1, "tile index (42 MB, downloaded once and kept)")
    OUT.mkdir(parents=True, exist_ok=True)
    local = OUT / "lgln-opengeodata-dop20.geojson"
    if not local.exists():
        import urllib.request
        for attempt in range(6):          # the institute DNS answers this host only sometimes
            try:
                t0 = time.monotonic()
                req = urllib.request.Request(INDEX, headers={"User-Agent": "Thuenen-Institut"})
                with urllib.request.urlopen(req, timeout=120) as r:
                    data, modified = r.read(), r.headers.get("Last-Modified", "?")
                local.with_suffix(".part").write_bytes(data)
                local.with_suffix(".part").replace(local)
                (OUT / "index_last_modified.txt").write_text(modified)
                print(f"  downloaded {len(data) / 1e6:.1f} MB in {time.monotonic() - t0:.0f} s "
                      f"(server says last modified: {modified})")
                break
            except Exception as e:
                print(f"  try {attempt + 1}: {e}")
                time.sleep(10)
        else:
            diagnose()
            sys.exit("  could not download the index. Send me this output.")
    else:
        mod = (OUT / "index_last_modified.txt")
        print(f"  using kept copy {local} (last modified: "
              f"{mod.read_text() if mod.exists() else '?'})")
    t0 = time.monotonic()
    ds = ogr.Open(str(local))
    lyr = ds.GetLayer(0)
    srs = lyr.GetSpatialRef()
    print(f"  ok, {lyr.GetFeatureCount()} tiles, {time.monotonic() - t0:.1f} s, "
          f"CRS {srs.GetAuthorityCode(None) if srs else '?'}")
    print(f"  fields: {[f.name for f in lyr.schema]}")
    # how current is the index? newest date found in the image URLs / date fields
    import re
    from collections import Counter
    years = Counter()
    for f in lyr:
        txt = " ".join(str(f[k.name]) for k in lyr.schema)
        m = re.search(r"(20\d\d)[-/]?(\d\d)[-/]?(\d\d)", txt)
        if m:
            years[m.group(1)] += 1
    lyr.ResetReading()
    print(f"  tiles per year in the index: {dict(sorted(years.items()))}")

    pt = ogr.Geometry(ogr.wkbPoint)
    pt.AddPoint(X, Y)
    if srs is not None and srs.GetAuthorityCode(None) != "25832":
        src = osr.SpatialReference(); src.ImportFromEPSG(25832)
        src.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        pt.Transform(osr.CoordinateTransformation(src, srs))
    lyr.SetSpatialFilter(pt)
    feat = lyr.GetNextFeature()
    if feat is None:
        sys.exit("  no index tile covers the test point")
    attrs = {f.name: feat[f.name] for f in lyr.schema}
    print("  tile under the test point:")
    for k, v in attrs.items():
        print(f"    {k} = {v}")
    url = attrs.get("rgb") or next((v for v in attrs.values()
                                     if isinstance(v, str) and v.lower().endswith((".tif", ".tiff"))), None)
    if not url:
        sys.exit("  no RGB url in the index attributes")

    step(2, "is it a Cloud Optimized GeoTIFF?")
    print(f"  url: {url}")
    t0 = time.monotonic()
    src_ds = None
    for attempt in range(6):
        try:
            src_ds = gdal.Open("/vsicurl/" + url)
            break
        except RuntimeError as e:
            print(f"  try {attempt + 1}: {str(e)[:150]}")
            gdal.VSICurlClearCache()
            time.sleep(10)
    if src_ds is None:
        sys.exit("  could not open the image file over the network. Send me this output.")
    b = src_ds.GetRasterBand(1)
    layout = src_ds.GetMetadataItem("LAYOUT", "IMAGE_STRUCTURE") or "-"
    comp = src_ds.GetMetadataItem("COMPRESSION", "IMAGE_STRUCTURE") or "-"
    gt = src_ds.GetGeoTransform()
    print(f"  opened in {time.monotonic() - t0:.1f} s")
    print(f"  size {src_ds.RasterXSize} x {src_ds.RasterYSize} px, {src_ds.RasterCount} bands, "
          f"pixel {gt[1]:.3f} m, origin ({gt[0]:.1f}, {gt[3]:.1f})")
    print(f"  LAYOUT={layout}  compression={comp}  internal blocks {b.GetBlockSize()}  "
          f"overviews {b.GetOverviewCount()}")
    is_cog = (layout == "COG") or (b.GetBlockSize()[1] > 1 and b.GetOverviewCount() > 0)
    print("  -> " + ("COG-style: windows can be read without the whole file" if is_cog
                     else "NOT tiled/overviewed: every read pulls large parts of the file"))

    step(3, f"read a {WIN_M:.0f} m window directly from the URL")
    x0, y1 = X - WIN_M / 2, Y + WIN_M / 2
    col, row = int(round((x0 - gt[0]) / gt[1])), int(round((y1 - gt[3]) / gt[5]))
    n = int(round(WIN_M / gt[1]))
    for label, out_n in (("native", n), ("0.4 m", int(round(WIN_M / 0.4)))):
        t0 = time.monotonic()
        arr = src_ds.ReadAsArray(col, row, n, n, buf_xsize=out_n, buf_ysize=out_n,
                                 resample_alg=gdal.GRIORA_Average)
        print(f"  {label:6s}: {out_n} x {out_n} px in {time.monotonic() - t0:.1f} s  "
              f"(mean grey {arr.mean():.0f})")

    step(4, f"save the native window to {OUT}")
    OUT.mkdir(parents=True, exist_ok=True)
    name = OUT / f"lgln_cog_E{int(x0)}_N{int(y1 - WIN_M)}.tif"
    gdal.Translate(str(name), src_ds, srcWin=[col, row, n, n],
                   creationOptions=["TILED=YES", "COMPRESS=DEFLATE", "PREDICTOR=2"])
    print(f"  {name}  ({name.stat().st_size / 1e6:.1f} MB)")
    print("\nDone. Send me this output.")


if __name__ == "__main__":
    main()
