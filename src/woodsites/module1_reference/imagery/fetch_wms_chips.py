"""
fetch_wms_chips.py - fetch the triage imagery ONCE from the state WMS and freeze it
as georeferenced GeoTIFFs plus a manifest.csv.

Why: the labels in dop20_polygons.gpkg were drawn on what these WMS showed in
Oct 2026. A WMS silently switches to the next flight when a state re-flies, so
the pixels are secured now, once, and training only ever reads the archive.

Runs WITHOUT QGIS open, in the "OSGeo4W Shell" that comes with QGIS
(it has Python + GDAL + numpy). Nothing else to install.

    cd /d <repo>          (then: python src\\woodsites\\module1_reference\\imagery\\fetch_wms_chips.py ...)
    python fetch_wms_chips.py caps     1. ask every WMS what it allows (max image size, formats, CRS)
    python fetch_wms_chips.py plan     2. work out which tiles are needed -> plan_f01.gpkg (look at it in QGIS)
    python fetch_wms_chips.py test     3. fetch ONE tile per state -> check in QGIS
    python fetch_wms_chips.py run      4. fetch everything (resumable: just start it again after a break)
    python fetch_wms_chips.py mosaic      rebuild mosaic_f01.vrt (remove the mosaic layer in QGIS first!)
    python fetch_wms_chips.py background  random background chips far from every polygon (see below)

Options: --only Niedersachsen (one state), --limit 20 (at most N new tiles),
         --n 15 (background: total number of background chips), --seed 1 (background: random seed)

Paths come from configs/config.toml in the repository (or the file named in the environment
variable WOODSITES_CONFIG), not from this script, so the same code runs on the laptop,
a GPU desktop or a cluster.

What is fetched
  * Fetch grid f01: 400 m x 400 m tiles = 2000 x 2000 px at 0.2 m, EPSG:25832,
    lower-left corners on multiples of 400 m (tile id f01_E<easting>_N<northing>).
    Tiles do NOT overlap; the overlapping 819.2 m training chips (grid g01) are
    cut from these later by tile_and_chip.py. Both grids sit on the same 0.2 m
    pixel lattice, so no pixel is ever shifted or resampled by that step.
  * Area: every g01 chip (819.2 m, stride 614.4 m, lattice origin 0/0) that
    touches a polygon with triage A or B (or herkunft = dop20_neu, once that
    field exists), and every f01 tile under those chips.
  * Request format: image/jpeg, as in the triage, so the archive holds what you
    looked at. Stored losslessly (DEFLATE) - no second lossy step.

Never overwrites an existing tile. Writes go to *.part first and are renamed
only when complete, so an interrupted run leaves no half files.

Background chips ("background")
  * Draws random g01 chips per state, at least BG_MIN_DIST_M away from every polygon
    (all categories, also C), not overlapping any label chip or another background chip.
  * Keeps a chip only if the state's WMS has imagery over the whole chip (one small
    256 x 256 px request first), then fetches its f01 tiles at 0.2 m exactly like label
    tiles - NOT at 0.4 m, so background and label chips are downsampled the same way later.
  * Default number: 10 % of the label chips, at least one per state, the rest in
    proportion to the label chips per state. Same --seed = same chips.
  * The chips are listed in background_g01.gpkg (path in config.toml) with an empty
    field `status`. Check each chip in QGIS and set status = ok (no wood), holz (wood
    found: label it or drop the chip) or verwerfen. tile_and_chip.py only uses "ok".
  * Running it again keeps the existing chips (and your status values), only adds chips
    up to --n and fetches tiles that are still missing.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import random
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from osgeo import gdal, ogr, osr

# Find the repository's src/ folder so that `import woodsites` works without installing it.
for _p in Path(__file__).resolve().parents:
    if (_p / "src" / "woodsites").is_dir():
        sys.path.insert(0, str(_p / "src"))
        break

gdal.UseExceptions()
ogr.UseExceptions()
osr.UseExceptions()

# =========================================================================
# SETTINGS
# =========================================================================
def load_config() -> tuple[dict, Path]:
    """Read configs/config.toml (or the file in WOODSITES_CONFIG)."""
    import tomllib
    from woodsites.core.config import config_path
    p = config_path()
    if not p.exists():
        raise SystemExit(f"config file not found: {p}\n"
                         "Copy configs/config.example.toml to configs/config.toml and fill in the paths, "
                         "or set the environment variable WOODSITES_CONFIG to your config file.")
    with open(p, "rb") as f:
        return tomllib.load(f), p


CONFIG, CONFIG_PATH = load_config()
_PATHS = CONFIG.get("paths", {})
for _key in ("polygons_gpkg", "archive", "background_gpkg"):
    if not _PATHS.get(_key):
        raise SystemExit(f"{CONFIG_PATH}: [paths] {_key} is missing")

GPKG = _PATHS["polygons_gpkg"]            # master polygons (Module 1)
POLY_LAYER = "dop20_polygons"
ARCHIVE = _PATHS["archive"]               # frozen tile archive (institute network)
BACKGROUND_GPKG = _PATHS["background_gpkg"]   # background chip list (Module 1, checked by hand)

EPSG = 25832
GSD = 0.2                    # metres per pixel in the archive
TILE_M = 400                 # f01 tile edge in metres (integer -> exact ids)
TILE_PX = 2000               # = TILE_M / GSD
CHIP_M = 819.2               # g01 chip edge (2048 px at 0.4 m)
STRIDE_M = 614.4             # g01 stride (25 % overlap)

REQUEST_FORMAT = "image/jpeg"   # what the triage displayed; "image/png" for the quality comparison
PAUSE_S = 0.3                # pause between requests (be polite to the servers)
TIMEOUT_S = 120
RETRIES = 4
MAX_FAIL_STREAK = 3          # after this many failed tiles in a row, skip the state for this run
USER_AGENT = "Thuenen-Institut logyard project (WMS archive fetch)"

# States whose certificate fails in Python (QGIS warned for Sachsen). Only add a
# state here if "caps" reports a certificate error for it.
INSECURE_SSL: set[str] = set()

# state -> (WMS url, image layer, flight-date info layer or None)  [from dop20_triage_qgis.py]
WMS = {
    "Niedersachsen":          ("https://opendata.lgln.niedersachsen.de/doorman/noauth/dop_wms", "ni_dop20", "ni_dop20_info"),
    "Nordrhein-Westfalen":    ("https://www.wms.nrw.de/geobasis/wms_nw_dop", "nw_dop_rgb", "nw_dop_utm_info"),
    "Brandenburg":            ("https://isk.geobasis-bb.de/mapproxy/dop20c/service/wms", "bebb_dop20c", "bb_dop_info"),
    "Baden-Württemberg":      ("https://owsproxy.lgl-bw.de/owsproxy/ows/WMS_LGL-BW_ATKIS_DOP_20_C", "IMAGES_DOP_20_RGB", None),
    "Rheinland-Pfalz":        ("https://geo4.service24.rlp.de/wms/rp_dop20.fcgi", "rp_dop20", "rp_dop20_info"),
    "Sachsen":                ("https://geodienste.sachsen.de/wms_geosn_dop-rgb/guest", "sn_dop_020", "sn_dop_020_info"),
    "Thüringen":              ("https://www.geoproxy.geoportal-th.de/geoproxy/services/DOP", "th_dop", "th_dop_info"),
    "Bayern":                 ("https://geoservices.bayern.de/od/wms/dop/v1/dop20", "by_dop20c", None),
    "Hessen":                 ("https://www.gds-srv.hessen.de/cgi-bin/lika-services/ogc-free-images.ows", "he_dop_rgb", None),
    "Mecklenburg-Vorpommern": ("https://www.geodaten-mv.de/dienste/adv_dop", "mv_dop", None),
    "Saarland":               ("https://geoportal.saarland.de/mapbender/php/wms.php?inspire=1&layer_id=46747&withChilds=1", "sl_dop20_rgb", None),
    # Sachsen-Anhalt: the triage service (.../ST_LVermGeo_DOP_WMS_OpenData/guest, layer lsa_lvermgeo_dop20_2)
    # answers "Could not process client request" since 25.10.2026. The INSPIRE service shows the same
    # flight (S0019 polygons checked in QGIS on 26.10.2026) and is used instead.
    "Sachsen-Anhalt":         ("https://www.geodatenportal.sachsen-anhalt.de/wss/service/INSPIRE_LVermGeo_ATKIS_OI/guest", "OI_OrthoimageCoverage", None),
}
CODE = {"Niedersachsen": "NI", "Nordrhein-Westfalen": "NW", "Brandenburg": "BB",
        "Baden-Württemberg": "BW", "Rheinland-Pfalz": "RP", "Sachsen": "SN",
        "Thüringen": "TH", "Bayern": "BY", "Hessen": "HE",
        "Mecklenburg-Vorpommern": "MV", "Saarland": "SL", "Sachsen-Anhalt": "ST"}
# Per-state request tweaks, filled in from what "probe" finds. Keys:
#   "version": "1.1.1"            force a WMS version
#   "max_px": 1000                smaller requests (tile is split into pieces)
#   "extra": {"STYLES": "default"} extra/replaced GetMap parameters
#   "map_url": "https://..."      GetMap address, when the capabilities name a different one
STATE_OPTIONS: dict = {
    # capabilities come through the Mapbender proxy, images from freewms (as QGIS does)
    "Saarland": {"map_url": "https://geoportal.saarland.de/freewms/dop2023"},
}

# States that store their DOP in UTM 33: asking for EPSG:25832 means the
# server reprojects (open point 9 in the code-check doc). Recorded per tile.
NATIVE_EPSG = {"Brandenburg": 25833, "Mecklenburg-Vorpommern": 25833, "Sachsen": 25833}

MANIFEST_FIELDS = [
    "tile_id", "land", "site_ids", "minx", "miny", "maxx", "maxy", "epsg", "native_epsg",
    "px", "gsd_m", "wms_url", "layer", "wms_version", "format", "n_requests",
    "fetched_utc", "seconds", "file", "bytes", "sha256", "leer_anteil",
    "info_layer", "bildflug", "bildflug_feld", "bildflug_raw", "note",
]


# =========================================================================
# small helpers
# =========================================================================
def archive() -> Path:
    p = Path(ARCHIVE)
    if not archive_reachable():
        drive = Path(p.anchor)
        if p.anchor and not drive.exists():       # never try to create a missing network drive
            wait_for_archive()
        else:
            p.mkdir(parents=True, exist_ok=True)
    return p


def keep_awake(on: bool) -> None:
    """Ask Windows not to go to idle standby while the fetch runs (standby drops the
    VPN and with it the network drive). Does not prevent sleep when the lid is closed."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
        ctypes.windll.kernel32.SetThreadExecutionState(
            ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if on else 0))
    except Exception:
        pass


def archive_reachable() -> bool:
    try:
        return Path(ARCHIVE).is_dir()
    except OSError:
        return False


def wait_for_archive(max_wait_s: int = 1800) -> None:
    """Network drives drop out now and then. Wait for it to come back instead of
    crashing; give up after max_wait_s."""
    t0 = time.monotonic()
    print(f"  ~ archive folder {ARCHIVE} not reachable - waiting (up to {max_wait_s // 60} min) ...",
          flush=True)
    while time.monotonic() - t0 < max_wait_s:
        time.sleep(30)
        if archive_reachable():
            print(f"  ~ back after {(time.monotonic() - t0) / 60:.1f} min, continuing", flush=True)
            for p in Path(ARCHIVE).glob("*/*.tif.part"):
                try:
                    p.unlink()
                except OSError:
                    pass
            return
    raise SystemExit(f"archive folder {ARCHIVE} unreachable for {max_wait_s // 60} min - stopped. "
                     "Start the same command again later; finished tiles are kept.")


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_url(base: str, params: dict) -> str:
    q = urllib.parse.urlencode({k: str(v) for k, v in params.items()}, safe=",:/")
    return base + ("&" if "?" in base else "?") + q


class WMSError(Exception):
    pass


def http_get(url: str, land: str) -> tuple[bytes, str, float]:
    ctx = ssl._create_unverified_context() if land in INSECURE_SSL else None
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    last = None
    for attempt in range(RETRIES + 1):
        t0 = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_S, context=ctx) as r:
                data = r.read()
                ctype = r.headers.get("Content-Type", "") or ""
            return data, ctype.lower(), time.monotonic() - t0
        except urllib.error.HTTPError as e:
            last = e
            if e.code not in (429, 500, 502, 503, 504):
                raise WMSError(f"HTTP {e.code}: {e.read()[:300]!r}") from None
        except urllib.error.URLError as e:
            if isinstance(e.reason, ssl.SSLCertVerificationError):
                raise WMSError(f"certificate error ({e.reason}). If you trust this server, "
                               f"add \"{land}\" to INSECURE_SSL in the settings.") from None
            last = e
        except (TimeoutError, ConnectionError, OSError) as e:
            last = e
        if attempt < RETRIES:
            time.sleep(2 ** attempt * 2)
    raise WMSError(f"no answer after {RETRIES + 1} tries: {last}")


def strip_ns(root: ET.Element) -> ET.Element:
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    return root


def looks_like_xml(data: bytes, ctype: str) -> bool:
    head = data[:200].lstrip().lower()
    return "xml" in ctype or head.startswith((b"<?xml", b"<serviceexception", b"<ows:", b"<html"))


# =========================================================================
# 1. caps - what does each WMS allow?
# =========================================================================
def parse_caps(xml: bytes, layer: str, info: str | None) -> dict:
    root = strip_ns(ET.fromstring(xml))
    out = {"version": root.get("version", ""), "max_w": None, "max_h": None,
           "getmap_formats": [], "fi_formats": [], "layer_found": False,
           "layer_crs": [], "info_found": False, "info_queryable": False}
    svc = root.find("Service")
    if svc is not None:
        for tag, key in (("MaxWidth", "max_w"), ("MaxHeight", "max_h")):
            el = svc.find(tag)
            if el is not None and (el.text or "").strip().isdigit():
                out[key] = int(el.text.strip())
    req = root.find("Capability/Request")
    if req is not None:
        out["getmap_formats"] = [f.text.strip() for f in req.findall("GetMap/Format") if f.text]
        out["fi_formats"] = [f.text.strip() for f in req.findall("GetFeatureInfo/Format") if f.text]

    def walk(el: ET.Element, inherited: list[str]):
        crs = inherited + [c.text.strip() for c in el.findall("CRS") + el.findall("SRS") if c.text]
        name = el.findtext("Name")
        if name == layer:
            out["layer_found"] = True
            out["layer_crs"] = sorted(set(" ".join(crs).split()))
        if info and name == info:
            out["info_found"] = True
            out["info_queryable"] = el.get("queryable") == "1"
        for child in el.findall("Layer"):
            walk(child, crs)

    cap = root.find("Capability")
    if cap is not None:
        for top in cap.findall("Layer"):
            walk(top, [])
    return out


def repair_xml(data: bytes) -> bytes:
    """Fix the two usual faults of hand-edited capabilities: bytes that are not
    valid UTF-8 (umlauts saved as Latin-1) and bare '&' in text or URLs."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("cp1252", "replace")
    text = re.sub(r"^\s*<\?xml[^>]*\?>", "", text)
    text = re.sub(r"&(?!(amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)", "&amp;", text)
    return text.encode("utf-8")


def layer_names(xml: bytes) -> list[str]:
    try:
        root = strip_ns(ET.fromstring(repair_xml(xml)))
        return [n.text.strip() for n in root.iter("Name") if n.text and n.text.strip()]
    except ET.ParseError:
        return re.findall(r"<Name>([^<]+)</Name>", xml.decode("utf-8", "replace"))


def caps_for(land: str) -> dict:
    url, layer, info = WMS[land]
    errors = []
    forced = STATE_OPTIONS.get(land, {}).get("version")
    d = archive() / "_caps"
    d.mkdir(exist_ok=True)
    for version in ([forced] if forced else ["1.3.0", "1.1.1"]):
        try:
            data, ctype, secs = http_get(build_url(url, {"SERVICE": "WMS", "REQUEST": "GetCapabilities",
                                                          "VERSION": version}), land)
            (d / f"{CODE[land]}_{version}.xml").write_bytes(data)     # always keep the raw answer
            if data.lstrip()[:200].lower().startswith((b"<html", b"<!doctype html")):
                title = re.search(rb"<title>\s*(.*?)\s*</title>", data, re.S | re.I)
                title = title.group(1).decode("utf-8", "replace") if title else "?"
                raise WMSError(f"server sent a web page instead of capabilities: \"{title}\" "
                               "(maintenance? try again later)")
            try:
                c = parse_caps(data, layer, info)
                note = ""
            except ET.ParseError as e:
                c = parse_caps(repair_xml(data), layer, info)
                note = f"capabilities repaired ({e})"
            if not c["layer_found"]:
                names = [n for n in layer_names(data) if n not in ("WMS",)]
                errors.append(f"{version}: layer {layer} not in capabilities; offered: "
                              + ", ".join(names[:25]))
                continue
            c["version"] = forced or c["version"] or version
            c["seconds"] = round(secs, 2)
            c["note"] = note
            return c
        except (WMSError, ET.ParseError) as e:
            errors.append(f"{version}: {e}")
    return {"error": " | ".join(errors)}


def load_caps(lands: list[str], refresh: bool = False) -> dict:
    path = archive() / "caps.json"
    caps = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    for land in lands:
        current = (WMS[land][0], WMS[land][1])
        cached_for = (caps.get(land, {}).get("url"), caps.get(land, {}).get("layer"))
        if refresh or land not in caps or "error" in caps[land] or cached_for != current:
            print(f"  GetCapabilities {land} ...", flush=True)
            caps[land] = caps_for(land)
            caps[land]["url"], caps[land]["layer"] = current
    path.write_text(json.dumps(caps, indent=2, ensure_ascii=False), encoding="utf-8")
    return caps


def cmd_caps(lands: list[str]) -> None:
    caps = load_caps(lands, refresh=True)
    rows = []
    print(f"\n{'state':24s} {'ver':5s} {'max px':>11s}  {'25832':5s} jpeg png  pieces  info")
    for land in lands:
        c = caps[land]
        if "error" in c:
            print(f"{land:24s} FAILED  {c['error'][:150]}")
            rows.append({"land": land, "error": c["error"]})
            continue
        n = pieces(c, land)
        crs_ok = f"EPSG:{EPSG}" in c["layer_crs"]
        fmts = c["getmap_formats"]
        info = WMS[land][2]
        info_s = "-" if not info else ("ok" if c["info_found"] and c["info_queryable"] else "NOT queryable")
        print(f"{land:24s} {c['version']:5s} {str(c['max_w'] or '?'):>5s}x{str(c['max_h'] or '?'):<5s}  "
              f"{'yes' if crs_ok else 'NO':5s} {'yes' if 'image/jpeg' in fmts else 'no':4s} "
              f"{'yes' if 'image/png' in fmts else 'no':4s} {n}x{n:<5d} {info_s}")
        rows.append({"land": land, "version": c["version"], "max_w": c["max_w"], "max_h": c["max_h"],
                     "epsg25832": crs_ok, "formats": " ".join(fmts), "pieces_per_tile": n * n,
                     "info_layer": info or "", "info_ok": info_s, "fi_formats": " ".join(c["fi_formats"]),
                     "seconds": c.get("seconds")})
    with open(archive() / "caps_report.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=sorted({k for r in rows for k in r}))
        w.writeheader()
        w.writerows(rows)
    print(f"\nwritten: {archive() / 'caps_report.csv'}  (raw capabilities in _caps/)")


def pieces(c: dict, land: str | None = None) -> int:
    """Smallest n so that a tile split into n x n requests fits MaxWidth/MaxHeight
    (and the per-state max_px override, if set)."""
    own = STATE_OPTIONS.get(land, {}).get("max_px") if land else None
    lim = min(x for x in (c.get("max_w"), c.get("max_h"), own, 10 ** 9) if x)
    for n in (1, 2, 4, 5, 8, 10):
        if TILE_PX % n == 0 and TILE_PX // n <= lim:
            return n
    raise WMSError(f"server limit {lim} px is too small")


# =========================================================================
# 2. plan - which tiles?
# =========================================================================
def load_polygons() -> list[dict]:
    if Path(GPKG + "-wal").exists():
        print("  note: dop20_polygons.gpkg-wal exists (QGIS has the file open). "
              "Saved edits are read too; unsaved edits are not.")
    ds = ogr.Open(GPKG)
    lyr = ds.GetLayerByName(POLY_LAYER)
    srs = lyr.GetSpatialRef()
    if srs is None or srs.GetAuthorityCode(None) != str(EPSG):
        raise SystemExit(f"{POLY_LAYER} must be EPSG:{EPSG}")
    fields = [f.name for f in lyr.schema]
    out, bad = [], []
    for f in lyr:
        keep = f["triage"] in ("A", "B") or ("herkunft" in fields and f["herkunft"] == "dop20_neu")
        g = f.GetGeometryRef()
        if not keep or g is None or g.IsEmpty():
            continue
        if f["land"] not in WMS or not f["new_id"] or not f["site_id"]:
            bad.append(f"  fid {f.GetFID()}: new_id={f['new_id']!r} site_id={f['site_id']!r} land={f['land']!r}")
            continue
        out.append({"new_id": f["new_id"], "site_id": f["site_id"], "land": f["land"],
                    "geom": g.Clone()})
    ds = None
    if bad:
        raise SystemExit("These polygons have an empty or unknown new_id / site_id / land "
                         f"(land must be one of: {', '.join(WMS)}):\n" + "\n".join(bad) +
                         "\nFill them in QGIS (fill_new_polygons_qgis.py), save, and run the command again.")
    return out


def box(minx, miny, maxx, maxy) -> ogr.Geometry:
    return ogr.CreateGeometryFromWkt(
        f"POLYGON(({minx} {miny},{maxx} {miny},{maxx} {maxy},{minx} {maxy},{minx} {miny}))")


def make_plan(polys: list[dict]) -> tuple[dict, dict]:
    """g01 chips touching a polygon -> f01 tiles under those chips."""
    chips: dict[tuple[int, int], dict] = {}
    for p in polys:
        minx, maxx, miny, maxy = p["geom"].GetEnvelope()
        for i in range(math.floor((minx - CHIP_M) / STRIDE_M), math.ceil(maxx / STRIDE_M) + 1):
            for j in range(math.floor((miny - CHIP_M) / STRIDE_M), math.ceil(maxy / STRIDE_M) + 1):
                x0, y0 = round(i * STRIDE_M, 1), round(j * STRIDE_M, 1)
                if not p["geom"].Intersects(box(x0, y0, x0 + CHIP_M, y0 + CHIP_M)):
                    continue
                c = chips.setdefault((i, j), {"x0": x0, "y0": y0, "sites": set(), "lands": set()})
                c["sites"].add(p["site_id"])
                c["lands"].add(p["land"])
    tiles: dict[tuple[int, int], dict] = {}
    for c in chips.values():
        for a, b in chip_tiles(c["x0"], c["y0"]):
            t = tiles.setdefault((a, b), {"E": a * TILE_M, "N": b * TILE_M, "sites": set(), "lands": {}})
            t["sites"] |= c["sites"]
            for land in c["lands"]:
                t["lands"][land] = t["lands"].get(land, 0) + 1
    for t in tiles.values():
        t["land"] = max(t["lands"], key=t["lands"].get)
        t["tile_id"] = tile_id(t["E"], t["N"])
    return chips, tiles


def tile_id(E: int, N: int) -> str:
    return f"f01_E{E:07d}_N{N:07d}"


def chip_tiles(x0: float, y0: float) -> list[tuple[int, int]]:
    """Index (a, b) of every f01 tile under the g01 chip with lower-left corner (x0, y0)."""
    return [(a, b)
            for a in range(math.floor(x0 / TILE_M), math.ceil((x0 + CHIP_M) / TILE_M))
            for b in range(math.floor(y0 / TILE_M), math.ceil((y0 + CHIP_M) / TILE_M))]


def chip_id(i: int, j: int) -> str:
    """Chip ID = grid + column/row index. The exact lower-left corner is (i * 614.4, j * 614.4);
    rounded-metre IDs (g01_E..._N...) are ambiguous about that and are no longer used for new chips."""
    return f"g01_i{i:05d}_j{j:05d}"


def write_plan(chips: dict, tiles: dict) -> Path:
    """Build plan_f01.gpkg in a local temp folder in ONE transaction per layer, then copy it to the
    archive. (Writing a GeoPackage feature by feature straight onto a network drive over the VPN took minutes:
    SQLite saves after every feature, and each save is a slow network round trip.)"""
    import shutil
    import tempfile
    path = archive() / "plan_f01.gpkg"
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(EPSG)
    with tempfile.TemporaryDirectory() as tmpdir:
        local = Path(tmpdir) / "plan_f01.gpkg"
        ds = ogr.GetDriverByName("GPKG").CreateDataSource(str(local))
        for name, items, idf in (("chips_g01", chips, None), ("tiles_f01", tiles, "tile_id")):
            lyr = ds.CreateLayer(name, srs, ogr.wkbPolygon)
            for fld in ("id", "land", "site_ids"):
                lyr.CreateField(ogr.FieldDefn(fld, ogr.OFTString))
            lyr.StartTransaction()
            for key, it in sorted(items.items()):
                f = ogr.Feature(lyr.GetLayerDefn())
                if idf:
                    f["id"] = it["tile_id"]
                    f["land"] = it["land"]
                    f.SetGeometry(box(it["E"], it["N"], it["E"] + TILE_M, it["N"] + TILE_M))
                else:
                    # provisional g01 id (rounded metres) - see code-check doc item 1
                    f["id"] = f"g01_E{round(it['x0']):07d}_N{round(it['y0']):07d}"
                    f["land"] = ";".join(sorted(it["lands"]))
                    f.SetGeometry(box(it["x0"], it["y0"], it["x0"] + CHIP_M, it["y0"] + CHIP_M))
                f["site_ids"] = ";".join(sorted(it["sites"]))
                lyr.CreateFeature(f)
            lyr.CommitTransaction()
        add_default_style(ds, "chips_g01", outline_qml("255,0,255,255", 0.6, label_field="id"))
        add_default_style(ds, "tiles_f01", outline_qml("120,120,120,255", 0.2, dash=True))
        ds = None
        for extra in (path, Path(str(path) + "-wal"), Path(str(path) + "-shm")):
            try:
                if extra.exists():
                    extra.unlink()
            except PermissionError:
                sys.exit(f"{extra} is in use - remove plan_f01 from QGIS, then run 'plan' again.")
        shutil.copyfile(local, path)
    return path


def outline_qml(rgba: str, width_mm: float, dash: bool = False, label_field: str | None = None) -> str:
    """QGIS style: no fill, coloured outline (optionally a small label in the chip corner)."""
    labeling = ""
    if label_field:
        labeling = (
            '<labeling type="simple"><settings calloutType="simple">'
            f'<text-style fieldName="{label_field}" fontSize="8" textColor="{rgba}" isExpression="0">'
            '<text-buffer bufferDraw="1" bufferSize="0.7" bufferColor="255,255,255,255"/></text-style>'
            '<placement placement="1" quadOffset="0" dist="0"/>'
            '<rendering scaleVisibility="1" scaleMin="1" scaleMax="25000"/>'
            '</settings></labeling>')
    return (
        "<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>\n"
        '<qgis version="3.40" styleCategories="Symbology|Labeling">'
        '<renderer-v2 type="singleSymbol" symbollevels="0" enableorderby="0" forceraster="0"><symbols>'
        '<symbol type="fill" name="0" alpha="1" clip_to_extent="1" force_rhr="0">'
        '<layer class="SimpleFill" enabled="1" locked="0" pass="0"><Option type="Map">'
        '<Option type="QString" name="color" value="0,0,0,0"/>'
        '<Option type="QString" name="style" value="no"/>'
        f'<Option type="QString" name="outline_color" value="{rgba}"/>'
        f'<Option type="QString" name="outline_style" value="{"dash" if dash else "solid"}"/>'
        f'<Option type="QString" name="outline_width" value="{width_mm}"/>'
        '<Option type="QString" name="outline_width_unit" value="MM"/>'
        '</Option></layer></symbol></symbols></renderer-v2>'
        f'{labeling}<labelsEnabled>{1 if label_field else 0}</labelsEnabled></qgis>')


def add_default_style(ds, layer_name: str, qml: str) -> None:
    """Store a default QGIS style inside the GeoPackage (table layer_styles, as QGIS itself does):
    QGIS then shows the layer with this style as soon as it is added - no manual styling."""
    styles = ds.GetLayerByName("layer_styles")
    if styles is None:
        styles = ds.CreateLayer("layer_styles", geom_type=ogr.wkbNone)
        for name, typ in (("f_table_catalog", ogr.OFTString), ("f_table_schema", ogr.OFTString),
                          ("f_table_name", ogr.OFTString), ("f_geometry_column", ogr.OFTString),
                          ("styleName", ogr.OFTString), ("styleQML", ogr.OFTString),
                          ("styleSLD", ogr.OFTString), ("useAsDefault", ogr.OFTInteger),
                          ("description", ogr.OFTString), ("owner", ogr.OFTString),
                          ("ui", ogr.OFTString), ("update_time", ogr.OFTDateTime)):
            fd = ogr.FieldDefn(name, typ)
            if name == "useAsDefault":
                fd.SetSubType(ogr.OFSTBoolean)
            styles.CreateField(fd)
    lyr = ds.GetLayerByName(layer_name)
    f = ogr.Feature(styles.GetLayerDefn())
    f["f_table_catalog"], f["f_table_schema"] = "", ""
    f["f_table_name"], f["f_geometry_column"] = layer_name, lyr.GetGeometryColumn() or "geom"
    f["styleName"], f["styleQML"], f["styleSLD"] = layer_name, qml, ""
    f["useAsDefault"], f["description"] = 1, "outline only (written by fetch_wms_chips.py)"
    f["owner"], f["ui"] = "", ""
    f.SetField("update_time", *datetime.now(timezone.utc).timetuple()[:6], 0)
    styles.CreateFeature(f)


def cmd_plan() -> dict:
    polys = load_polygons()
    chips, tiles = make_plan(polys)
    path = write_plan(chips, tiles)
    per_land: dict[str, int] = {}
    for t in tiles.values():
        per_land[t["land"]] = per_land.get(t["land"], 0) + 1
    mixed = [t["tile_id"] for t in tiles.values() if len(t["lands"]) > 1]
    print(f"\n{len(polys)} polygons (A/B) at {len({p['site_id'] for p in polys})} sites")
    print(f"{len(chips)} g01 chips touch a polygon -> {len(tiles)} f01 tiles "
          f"= {len(tiles) * TILE_M ** 2 / 1e6:.1f} km2")
    for land, n in sorted(per_land.items()):
        print(f"  {land:24s} {n:5d} tiles")
    print(f"estimated archive size: {len(tiles) * 6 / 1000:.1f}-{len(tiles) * 10 / 1000:.1f} GB "
          f"(DEFLATE, depends on the imagery)")
    if mixed:
        print(f"note: {len(mixed)} tiles are near sites of two states; each is fetched from the majority state")
    print(f"written: {path}  -> open in QGIS over the WMS to check the coverage")
    return tiles


# =========================================================================
# 3./4. fetching
# =========================================================================
def decode_image(data: bytes, w: int, h: int) -> tuple[np.ndarray, np.ndarray | None]:
    name = f"/vsimem/wms_{time.monotonic_ns()}"
    gdal.FileFromMemBuffer(name, data)
    try:
        ds = gdal.Open(name)
        if ds.RasterXSize != w or ds.RasterYSize != h:
            raise WMSError(f"server returned {ds.RasterXSize}x{ds.RasterYSize}, asked {w}x{h}")
        if ds.RasterCount == 1 and ds.GetRasterBand(1).GetColorTable() is not None:
            ds = gdal.Translate(name + "_rgb", ds, rgbExpand="rgba")
        arr = ds.ReadAsArray()
        if arr.ndim == 2:
            arr = np.stack([arr] * 3)
        alpha = arr[3] if arr.shape[0] == 4 else None
        return arr[:3].astype(np.uint8), alpha
    finally:
        ds = None
        for n in (name, name + "_rgb"):
            if gdal.VSIStatL(n) is not None:
                gdal.Unlink(n)


def map_url(land: str) -> str:
    """Address for GetMap/GetFeatureInfo: the per-state override (taken from the
    GetMap OnlineResource in the capabilities, which QGIS follows) or the WMS url."""
    return STATE_OPTIONS.get(land, {}).get("map_url") or WMS[land][0]


def getmap(land: str, c: dict, bbox: tuple, w: int, h: int,
           extra: dict | None = None, fmt: str | None = None,
           version: str | None = None) -> tuple[np.ndarray, np.ndarray | None]:
    _, layer, _ = WMS[land]
    url = map_url(land)
    v = version or c["version"]
    fmt = fmt or REQUEST_FORMAT
    q = {"SERVICE": "WMS", "VERSION": v, "REQUEST": "GetMap", "LAYERS": layer, "STYLES": "",
         "FORMAT": fmt, "WIDTH": w, "HEIGHT": h,
         "BBOX": ",".join(f"{x:.3f}" for x in bbox)}
    q["CRS" if v.startswith("1.3") else "SRS"] = f"EPSG:{EPSG}"   # EPSG:25832 is easting,northing in both
    if fmt == "image/png":
        q["TRANSPARENT"] = "FALSE"
    q.update(STATE_OPTIONS.get(land, {}).get("extra", {}))
    q.update(extra or {})
    data, ctype, _ = http_get(build_url(url, q), land)
    if looks_like_xml(data, ctype):
        txt = data.decode("utf-8", "replace")
        m = re.search(r"<ServiceException[^>]*>(.*?)</ServiceException>", txt, re.S)
        msg = re.sub(r"\s+", " ", (m.group(1) if m else txt[:400])).replace("&quot;", '"')
        msg = msg.replace("<![CDATA[", "").replace("]]>", "").strip()
        raise WMSError("service exception: " + msg[:400])
    return decode_image(data, w, h)


DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b|\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b")
# Field names in the states' info layers, most trustworthy first. Seen so far:
# NW Bildflugdatum, SN Datum, RP erstellung (+ publikation = NOT the flight),
# TH Erstellung (+ Publikation), BB Ersterstellung.
DATE_FIELDS = ["bildflugdatum", "bildflug", "befliegungsdatum", "befliegung", "aufnahmedatum",
               "aufnahme", "datum", "ersterstellung", "erstellung"]
IGNORE_FIELDS = ["publikation", "aktualisierung", "veroeffentlichung", "veröffentlichung"]


def _iso(m: re.Match) -> str:
    if m.group(1):
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return f"{m.group(6)}-{int(m.group(5)):02d}-{int(m.group(4)):02d}"


def parse_date(text: str) -> tuple[str, str]:
    """(ISO date, field it came from). Looks for known field names first;
    only falls back to 'any date' if no field matched, and never uses a
    publication/update date."""
    # split into "key = value" chunks on the separators the states use
    chunks = re.split(r"\$#\$|\||(?<=')\s+(?=[A-Za-zÄÖÜäöü_]+\s*=)", text)
    pairs = []
    for ch in chunks:
        m = re.match(r"\s*(?:.*?\s)?([A-Za-zÄÖÜäöü_\-]+)\s*[=:]\s*(.*)", ch.strip(), re.S)
        if m:
            pairs.append((m.group(1).lower(), m.group(2)))
    for want in DATE_FIELDS:
        for key, val in pairs:
            if key == want or (key.startswith(want) and want not in ("datum",)):
                d = DATE_RE.search(val)
                if d:
                    return _iso(d), key
    for key, val in pairs:
        if any(key.startswith(ig) for ig in IGNORE_FIELDS):
            continue
        d = DATE_RE.search(val)
        if d:
            return _iso(d), key + " (fallback)"
    for d in DATE_RE.finditer(text):      # unstructured text: any date not right after an ignore word
        before = text[max(0, d.start() - 40):d.start()].lower()
        if not any(ig in before for ig in IGNORE_FIELDS):
            return _iso(d), "text (fallback)"
    return "", ""


def flight_info(land: str, c: dict, x: float, y: float) -> tuple[str, str, str]:
    """GetFeatureInfo on the state's info layer at (x, y). Returns (date, field, raw text)."""
    _, _, info = WMS[land]
    url = map_url(land)
    if not info or not c.get("info_found"):
        return "", "", ""
    fmt = next((f for f in ("text/plain", "application/json", "application/geojson", "text/xml",
                            "application/vnd.ogc.gml", "text/html") if f in c["fi_formats"]),
               (c["fi_formats"] or ["text/plain"])[0])
    v = c["version"]
    q = {"SERVICE": "WMS", "VERSION": v, "REQUEST": "GetFeatureInfo", "LAYERS": info,
         "QUERY_LAYERS": info, "STYLES": "", "FORMAT": "image/png", "INFO_FORMAT": fmt,
         "WIDTH": 101, "HEIGHT": 101, "BBOX": f"{x - 10:.3f},{y - 10:.3f},{x + 10:.3f},{y + 10:.3f}",
         "FEATURE_COUNT": 5}
    q["CRS" if v.startswith("1.3") else "SRS"] = f"EPSG:{EPSG}"
    q["I" if v.startswith("1.3") else "X"] = 50
    q["J" if v.startswith("1.3") else "Y"] = 50
    try:
        data, _, _ = http_get(build_url(url, q), land)
    except WMSError as e:
        return "", "", f"error: {e}"[:400]
    text = data.decode("utf-8", "replace")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    date, field = parse_date(text)
    return date, field, text[:400]


def write_geotiff(path: Path, rgb: np.ndarray, E: float, N: float, meta: dict) -> None:
    drv = gdal.GetDriverByName("GTiff")
    ds = drv.Create(str(path), TILE_PX, TILE_PX, 3, gdal.GDT_Byte,
                    options=["TILED=YES", "BLOCKXSIZE=512", "BLOCKYSIZE=512", "COMPRESS=DEFLATE",
                             "PREDICTOR=2", "PHOTOMETRIC=RGB", "INTERLEAVE=PIXEL"])
    ds.SetGeoTransform((E, GSD, 0.0, N + TILE_M, 0.0, -GSD))   # top-left corner, y goes DOWN
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(EPSG)
    ds.SetProjection(srs.ExportToWkt())
    for b in range(3):
        ds.GetRasterBand(b + 1).WriteArray(rgb[b])
    ds.SetMetadata({k: str(v) for k, v in meta.items()})
    ds.BuildOverviews("AVERAGE", [2, 4, 8])
    ds.FlushCache()
    ds = None


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def manifest_rows() -> dict[str, dict]:
    p = archive() / "manifest.csv"
    if not p.exists():
        return {}
    with open(p, newline="", encoding="utf-8") as f:
        return {r["tile_id"]: r for r in csv.DictReader(f)}


def rewrite_manifest(rows: list[dict]) -> None:
    p = archive() / "manifest.csv"
    tmp = p.with_suffix(".csv.tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in MANIFEST_FIELDS})
    tmp.replace(p)


def upgrade_manifest() -> None:
    """Bring an older manifest.csv to the current column set (only metadata, the
    images are never touched)."""
    p = archive() / "manifest.csv"
    if not p.exists():
        return
    with open(p, newline="", encoding="utf-8") as f:
        rd = csv.DictReader(f)
        header, rows = rd.fieldnames or [], list(rd)
    if header != MANIFEST_FIELDS:
        rewrite_manifest(rows)
        print(f"  manifest.csv upgraded to {len(MANIFEST_FIELDS)} columns ({len(rows)} rows kept)")


def cmd_redate() -> None:
    """Re-read the flight date of every manifest row from its stored raw info text."""
    upgrade_manifest()
    rows = list(manifest_rows().values())
    changed = 0
    for r in rows:
        if not r.get("bildflug_raw") or r["bildflug_raw"].startswith("error"):
            continue
        date, field = parse_date(r["bildflug_raw"])
        if (date, field) != (r.get("bildflug", ""), r.get("bildflug_feld", "")):
            print(f"  {r['tile_id']} {CODE.get(r['land'], r['land'])}: "
                  f"{r.get('bildflug') or '-'} -> {date or '-'} ({field})")
            r["bildflug"], r["bildflug_feld"] = date, field
            changed += 1
    if changed:
        rewrite_manifest(rows)
    print(f"{changed} rows corrected. manifest.csv is the authoritative flight date "
          "(the BILDFLUG tag inside older GeoTIFFs may still show the old value).")


def append_manifest(row: dict) -> None:
    p = archive() / "manifest.csv"
    new = not p.exists()
    with open(p, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
        if new:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in MANIFEST_FIELDS})


def log_error(tile_id: str, land: str, msg: str) -> None:
    p = archive() / "errors.csv"
    new = not p.exists()
    with open(p, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["time_utc", "tile_id", "land", "message"])
        w.writerow([now_utc(), tile_id, land, msg[:500]])


def fetch_tile(t: dict, c: dict, done: dict, note: str = "") -> str:
    """note: extra text for the manifest column `note` (e.g. "background g01_i..._j...")."""
    land, E, N, tid = t["land"], t["E"], t["N"], t["tile_id"]
    folder = archive() / CODE[land]
    folder.mkdir(exist_ok=True)
    final = folder / f"{tid}.tif"
    part = folder / f"{tid}.tif.part"
    if final.exists() and tid in done:
        return "skip"
    _, layer, info = WMS[land]
    url = map_url(land)
    base = {"tile_id": tid, "land": land, "site_ids": ";".join(sorted(t["sites"])),
            "minx": E, "miny": N, "maxx": E + TILE_M, "maxy": N + TILE_M, "epsg": EPSG,
            "native_epsg": NATIVE_EPSG.get(land, EPSG), "px": TILE_PX, "gsd_m": GSD,
            "wms_url": url, "layer": layer, "wms_version": c["version"], "format": REQUEST_FORMAT,
            "info_layer": info or "", "file": f"{CODE[land]}/{tid}.tif"}

    if final.exists():   # crashed after rename, before the manifest line: keep the file, add the line
        date, field, raw = flight_info(land, c, E + TILE_M / 2, N + TILE_M / 2)
        append_manifest({**base, "bildflug_feld": field, "fetched_utc": datetime.fromtimestamp(final.stat().st_mtime, timezone.utc)
                         .strftime("%Y-%m-%dT%H:%M:%SZ"), "bytes": final.stat().st_size,
                         "sha256": sha256(final), "bildflug": date, "bildflug_raw": raw,
                         "note": "; ".join(x for x in (note, "manifest line added on resume") if x)})
        return "recovered"

    t0 = time.monotonic()
    n = pieces(c, land)
    step_px, step_m = TILE_PX // n, TILE_M / n
    rgb = np.zeros((3, TILE_PX, TILE_PX), dtype=np.uint8)
    empty = np.zeros((TILE_PX, TILE_PX), dtype=bool)
    for r in range(n):          # r = row of pieces, from the TOP
        for k in range(n):      # k = column of pieces, from the LEFT
            minx = E + k * step_m
            maxy = N + TILE_M - r * step_m
            arr, alpha = getmap(land, c, (minx, maxy - step_m, minx + step_m, maxy), step_px, step_px)
            sl = (slice(r * step_px, (r + 1) * step_px), slice(k * step_px, (k + 1) * step_px))
            rgb[(slice(None),) + sl] = arr
            if alpha is not None:
                empty[sl] |= alpha == 0
            time.sleep(PAUSE_S)
    empty |= (rgb == 255).all(axis=0) | (rgb == 0).all(axis=0)
    leer = float(empty.mean())
    date, field, raw = flight_info(land, c, E + TILE_M / 2, N + TILE_M / 2)
    fetched = now_utc()
    meta = {"SOURCE": f"{url} layer={layer}", "FETCHED_UTC": fetched, "FORMAT": REQUEST_FORMAT,
            "BILDFLUG": date, "TILE_ID": tid,
            "LICENCE_NOTE": f"DOP20 {land}, see state open-data terms; attribution required"}
    part.unlink(missing_ok=True)
    write_geotiff(part, rgb, E, N, meta)
    digest = sha256(part)
    part.rename(final)
    append_manifest({**base, "n_requests": n * n, "fetched_utc": fetched,
                     "seconds": round(time.monotonic() - t0, 1), "bytes": final.stat().st_size,
                     "sha256": digest, "leer_anteil": round(leer, 4), "bildflug": date,
                     "bildflug_feld": field,
                     "bildflug_raw": raw,
                     "note": "; ".join(x for x in (note, "mostly empty - check" if leer > 0.5 else "") if x)})
    return "fetched"


def build_vrt() -> None:
    """Rebuild mosaic_f01.vrt from all tiles on disk.
    Remove the mosaic layer from QGIS FIRST: QGIS writes statistics into an open VRT and
    can overwrite a newer mosaic with the old one it still has in memory."""
    tifs = sorted(str(p) for p in archive().glob("*/f01_*.tif"))
    if tifs:
        out = archive() / "mosaic_f01.vrt"
        tmp = archive() / "mosaic_f01.vrt.tmp"
        ds = gdal.BuildVRT(str(tmp), tifs)
        ds = None
        tmp.replace(out)
        print(f"mosaic for QGIS: {out}  ({len(tifs)} tiles)")
        print("  (in QGIS: remove the old mosaic layer before running this, then add it again)")


def cmd_fetch(tiles: dict, lands: list[str], limit: int | None, test: bool,
              notes: dict[str, str] | None = None) -> None:
    """notes: tile_id -> text for the manifest column `note` (used by "background")."""
    notes = notes or {}
    for p in archive().glob("*/*.tif.part"):
        p.unlink()
    upgrade_manifest()
    todo = [t for t in tiles.values() if t["land"] in lands]
    if test:   # one tile per state: the one under the first logyard polygon's centre
        polys = sorted(load_polygons(), key=lambda p: ("_L" not in p["new_id"], p["new_id"]))
        pick = {}
        for p in polys:
            if p["land"] in lands and p["land"] not in pick:
                pt = p["geom"].Centroid()
                key = (math.floor(pt.GetX() / TILE_M), math.floor(pt.GetY() / TILE_M))
                if key in tiles:
                    pick[p["land"]] = tiles[key]
        todo = list(pick.values())
    todo.sort(key=lambda t: (t["land"], t["tile_id"]))
    caps = load_caps(sorted({t["land"] for t in todo}))
    done = manifest_rows()
    counts = {"fetched": 0, "skip": 0, "recovered": 0, "failed": 0}
    streak: dict[str, int] = {}          # consecutive failures per state
    t_start = time.monotonic()
    for i, t in enumerate(todo, 1):
        land = t["land"]
        site = land + ":" + ";".join(sorted(t["sites"]))
        if "error" in caps[land] or streak.get(site, 0) >= MAX_FAIL_STREAK:
            counts["failed"] += 1
            why = ("capabilities failed: " + caps[land]["error"]) if "error" in caps[land] \
                else f"skipped: {MAX_FAIL_STREAK} tiles in a row failed at this site"
            log_error(t["tile_id"], land, why)
            continue
        if limit is not None and counts["fetched"] >= limit:
            break
        for attempt in range(3):
            try:
                status = fetch_tile(t, caps[land], done, note=notes.get(t["tile_id"], ""))
                break
            except (WMSError, RuntimeError, OSError) as e:
                if not archive_reachable():        # the network drive dropped out, not the WMS
                    wait_for_archive()
                    continue                       # same tile again; its .part is redone
                status = "failed"
                log_error(t["tile_id"], land, str(e))
                print(f"  ! {t['tile_id']} {land}: {str(e)[:160]}")
                break
        else:
            raise SystemExit("archive folder keeps disappearing - stopped. Start again later; "
                             "finished tiles are kept.")
        streak[site] = streak.get(site, 0) + 1 if status == "failed" else 0
        if streak[site] == MAX_FAIL_STREAK:
            print(f"  !! {site}: {MAX_FAIL_STREAK} failures in a row - skipping this site for this run")
        counts[status] += 1
        if status in ("fetched", "recovered") or test:
            el = time.monotonic() - t_start
            print(f"  [{i}/{len(todo)}] {t['tile_id']} {CODE[land]} {status}  "
                  f"({el / 60:.1f} min elapsed)", flush=True)
    print(f"\nfetched {counts['fetched']}, already there {counts['skip']}, "
          f"recovered {counts['recovered']}, failed {counts['failed']}"
          + (f"  -> see {archive() / 'errors.csv'}" if counts["failed"] else ""))
    if test:
        rows = manifest_rows()
        print("\nflight dates found (raw text from the info layer, check the parsing):")
        for t in todo:
            r = rows.get(t["tile_id"])
            if r:
                print(f"  {CODE[r['land']]}  bildflug={r['bildflug'] or '-':10s}  "
                      f"leer={r['leer_anteil']}  {r['seconds']} s  | {r['bildflug_raw'][:110]}")
    build_vrt()


def first_tile(tiles: dict, land: str) -> dict | None:
    polys = sorted(load_polygons(), key=lambda p: ("_L" not in p["new_id"], p["new_id"]))
    for p in polys:
        if p["land"] == land:
            pt = p["geom"].Centroid()
            key = (math.floor(pt.GetX() / TILE_M), math.floor(pt.GetY() / TILE_M))
            if key in tiles:
                return tiles[key]
    return None


def cmd_probe(land: str, tiles: dict) -> None:
    """Try request variants on one tile of one state and say which work."""
    caps = load_caps([land], refresh=True)
    c = caps[land]
    if "error" in c:
        print(f"\n{land}: capabilities failed:\n  {c['error'][:1500]}")
        print(f"raw answer(s) saved in {archive() / '_caps'}")
        return
    if c.get("note"):
        print(f"  {c['note']}")
    t = first_tile(tiles, land)
    E, N = t["E"], t["N"]
    print(f"\nprobing {land} on {t['tile_id']} (version {c['version']}, server max "
          f"{c['max_w']}x{c['max_h']})")
    qgis_like = {"DPI": "96", "MAP_RESOLUTION": "96", "FORMAT_OPTIONS": "dpi:96", "TRANSPARENT": "TRUE"}
    variants = [
        ("as configured, 2000 px @0.2 m", 2000, GSD, {}, None, None),
        ("1000 px @0.2 m", 1000, GSD, {}, None, None),
        ("512 px @0.2 m", 512, GSD, {}, None, None),
        ("coarser: 400 m in 1000 px (0.4 m)", 1000, 0.4, {}, None, None),
        ("STYLES=default", 1000, GSD, {"STYLES": "default"}, None, None),
        ("QGIS-like (DPI, TRANSPARENT)", 1000, GSD, qgis_like, None, None),
        ("image/png", 1000, GSD, {}, "image/png", None),
        ("WMS 1.1.1", 1000, GSD, {}, None, "1.1.1"),
        ("WMS 1.3.0", 1000, GSD, {}, None, "1.3.0"),
    ]
    for name, px, gsd, extra, fmt, ver in variants:
        if ver and ver == c["version"]:
            continue
        span = px * gsd
        bbox = (E, N + TILE_M - span, E + span, N + TILE_M)
        t0 = time.monotonic()
        try:
            arr, _ = getmap(land, c, bbox, px, px, extra=extra, fmt=fmt, version=ver)
            res = f"OK    mean grey {arr.mean():.0f}"
        except (WMSError, RuntimeError) as e:
            res = "FAIL  " + re.sub(r"\s+", " ", str(e))[:170]
        print(f"  {name:36s} {time.monotonic() - t0:5.1f} s  {res}", flush=True)
        time.sleep(PAUSE_S)

    # same configured request (512 px) at one tile of every site in this state:
    # tells a server-wide problem from missing imagery at one place
    by_site: dict[str, dict] = {}
    for tt in sorted(tiles.values(), key=lambda x: x["tile_id"]):
        if tt["land"] == land:
            for s in tt["sites"]:
                by_site.setdefault(s, tt)
    print(f"\none tile per site ({len(by_site)} sites), 512 px @0.2 m:")
    for s, tt in sorted(by_site.items()):
        span = 512 * GSD
        bbox = (tt["E"], tt["N"] + TILE_M - span, tt["E"] + span, tt["N"] + TILE_M)
        try:
            arr, _ = getmap(land, c, bbox, 512, 512)
            res = f"OK    mean grey {arr.mean():.0f}"
        except (WMSError, RuntimeError) as e:
            res = "FAIL  " + re.sub(r"\s+", " ", str(e))[-170:]
        print(f"  {s}  {tt['tile_id']}  {res}", flush=True)
        time.sleep(PAUSE_S)
    print("\nSend me this output; the working variant goes into STATE_OPTIONS.")


# =========================================================================
# 5. background - random chips far from every polygon
# =========================================================================
# Rough lon/lat boxes (west, south, east, north) of the states. Only used to draw candidate
# chips: a candidate is kept only if the state's own WMS shows imagery over the whole chip,
# so a box that also covers a neighbour just costs a few extra small requests.
STATE_BBOX_LONLAT = {
    "Niedersachsen":          (6.65, 51.29, 11.60, 53.89),
    "Nordrhein-Westfalen":    (5.86, 50.32, 9.46, 52.53),
    "Brandenburg":            (11.26, 51.36, 14.77, 53.56),
    "Baden-Württemberg":      (7.51, 47.53, 10.50, 49.79),
    "Rheinland-Pfalz":        (6.11, 48.96, 8.51, 50.94),
    "Sachsen":                (11.87, 50.17, 15.04, 51.69),
    "Thüringen":              (9.87, 50.20, 12.65, 51.65),
    "Bayern":                 (8.97, 47.27, 13.84, 50.56),
    "Hessen":                 (7.77, 49.39, 10.24, 51.66),
    "Mecklenburg-Vorpommern": (10.59, 53.11, 14.41, 54.69),
    "Saarland":               (6.35, 49.11, 7.41, 49.64),
    "Sachsen-Anhalt":         (10.56, 50.94, 13.19, 53.04),
}
_BG = CONFIG.get("background", {})
BG_SHARE = float(_BG.get("share", 0.10))            # background chips per label chip
BG_MIN_DIST_M = float(_BG.get("min_dist_m", 2000))  # gap to every polygon (all categories, also C)
BG_SEED = int(_BG.get("seed", 1))
BG_LAYER = "background_g01"
COVER_PX = 256              # size of the coverage check request (whole chip at ~3.2 m)
COVER_MAX_EMPTY = 0.01      # a background chip may have at most 1 % empty (white/black) pixels
BG_MAX_WMS_TRIES = 40       # coverage requests per wanted chip before giving up on a state
BG_MAX_DRAWS = 50000        # random draws per state (most are rejected without a request)


def load_all_envelopes() -> list[tuple[float, float, float, float]]:
    """(minx, miny, maxx, maxy) of EVERY polygon, whatever its triage or category."""
    ds = ogr.Open(GPKG)
    lyr = ds.GetLayerByName(POLY_LAYER)
    out = []
    for f in lyr:
        g = f.GetGeometryRef()
        if g is not None and not g.IsEmpty():
            minx, maxx, miny, maxy = g.GetEnvelope()
            out.append((minx, miny, maxx, maxy))
    ds = None
    return out


def state_bbox(land: str) -> tuple[float, float, float, float]:
    """STATE_BBOX_LONLAT of one state as (minx, miny, maxx, maxy) in EPSG:25832."""
    w, s, e, n = STATE_BBOX_LONLAT[land]
    src, dst = osr.SpatialReference(), osr.SpatialReference()
    src.ImportFromEPSG(4326)
    dst.ImportFromEPSG(EPSG)
    for r in (src, dst):
        r.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    ct = osr.CoordinateTransformation(src, dst)
    pts = [ct.TransformPoint(lon, lat)[:2] for lon in (w, (w + e) / 2, e) for lat in (s, (s + n) / 2, n)]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def rects_touch(a: tuple, b: tuple, gap: float = 0.0) -> bool:
    """True if rectangle a, grown by gap on every side, overlaps rectangle b."""
    return a[0] - gap < b[2] and b[0] < a[2] + gap and a[1] - gap < b[3] and b[1] < a[3] + gap


def chip_rect(i: int, j: int) -> tuple[float, float, float, float]:
    x0, y0 = round(i * STRIDE_M, 1), round(j * STRIDE_M, 1)
    return x0, y0, round(x0 + CHIP_M, 1), round(y0 + CHIP_M, 1)


def read_background() -> list[dict]:
    p = Path(BACKGROUND_GPKG)
    if not p.exists():
        return []
    ds = ogr.Open(str(p))
    lyr = ds.GetLayerByName(BG_LAYER)
    if lyr is None:
        raise SystemExit(f"{p} has no layer {BG_LAYER}")
    out = [{"id": f["id"], "i": f["i"], "j": f["j"], "land": f["land"], "status": f["status"] or ""}
           for f in lyr]
    ds = None
    return out


def append_background(new: list[dict], seed: int) -> None:
    """Add chips to background_g01.gpkg. Existing rows (and the status you typed) are never touched."""
    if not new:
        return
    p = Path(BACKGROUND_GPKG)
    try:
        if p.exists():
            ds = ogr.Open(str(p), update=1)
            lyr = ds.GetLayerByName(BG_LAYER)
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            srs = osr.SpatialReference()
            srs.ImportFromEPSG(EPSG)
            ds = ogr.GetDriverByName("GPKG").CreateDataSource(str(p))
            lyr = ds.CreateLayer(BG_LAYER, srs, ogr.wkbPolygon)
            for name, typ in (("id", ogr.OFTString), ("i", ogr.OFTInteger), ("j", ogr.OFTInteger),
                              ("x0", ogr.OFTReal), ("y0", ogr.OFTReal), ("land", ogr.OFTString),
                              ("seed", ogr.OFTInteger), ("drawn_utc", ogr.OFTString),
                              ("leer_anteil", ogr.OFTReal), ("status", ogr.OFTString),
                              ("note", ogr.OFTString)):
                lyr.CreateField(ogr.FieldDefn(name, typ))
            add_default_style(ds, BG_LAYER, outline_qml("255,140,0,255", 0.6, label_field="status"))
        lyr.StartTransaction()
        for c in new:
            x0, y0, x1, y1 = chip_rect(c["i"], c["j"])
            f = ogr.Feature(lyr.GetLayerDefn())
            for k in ("id", "i", "j", "land", "leer_anteil"):
                f[k] = c[k]
            f["x0"], f["y0"], f["seed"], f["drawn_utc"] = x0, y0, seed, now_utc()
            f["status"] = ""
            f.SetGeometry(box(x0, y0, x1, y1))
            lyr.CreateFeature(f)
        lyr.CommitTransaction()
        ds = None
    except RuntimeError as e:
        raise SystemExit(f"cannot write {p}: {e}\nIf QGIS has the layer open in edit mode, "
                         "save or stop editing (or remove the layer), then run the same command again.")


def bg_quota(n: int, lands: list[str], label_chips: dict) -> dict[str, int]:
    """At least one chip per state, the rest in proportion to the label chips per state."""
    per = {land: 0.0 for land in lands}
    for c in label_chips.values():
        for land in c["lands"]:
            if land in per:
                per[land] += 1 / len(c["lands"])
    ranked = sorted(lands, key=lambda l: (-per[l], l))
    if n < len(lands):
        return {l: (1 if l in ranked[:n] else 0) for l in lands}
    q = {l: 1 for l in lands}
    rest, total = n - len(lands), sum(per.values()) or 1.0
    raw = {l: rest * per[l] / total for l in lands}
    for l in lands:
        q[l] += int(raw[l])
    left = rest - sum(int(v) for v in raw.values())
    for l in sorted(lands, key=lambda l: (-(raw[l] - int(raw[l])), l))[:left]:
        q[l] += 1
    return q


def draw_background(land: str, need: int, seed: int, caps: dict, envs: list, taken: list) -> list[dict]:
    """Random chips in one state that keep BG_MIN_DIST_M from every polygon, overlap nothing
    in `taken` and have imagery over the whole chip. Appends the accepted rects to `taken`."""
    rng = random.Random(f"{seed}:{land}")       # same seed -> same candidates in the same order
    minx, miny, maxx, maxy = state_bbox(land)
    i_lo, i_hi = math.ceil(minx / STRIDE_M), math.floor((maxx - CHIP_M) / STRIDE_M)
    j_lo, j_hi = math.ceil(miny / STRIDE_M), math.floor((maxy - CHIP_M) / STRIDE_M)
    out, requests, draws = [], 0, 0
    while len(out) < need and requests < BG_MAX_WMS_TRIES * need and draws < BG_MAX_DRAWS:
        draws += 1
        i, j = rng.randint(i_lo, i_hi), rng.randint(j_lo, j_hi)
        rect = chip_rect(i, j)
        if any(rects_touch(rect, e, BG_MIN_DIST_M) for e in envs) or any(rects_touch(rect, r) for r in taken):
            continue
        requests += 1
        try:
            arr, alpha = getmap(land, caps, rect, COVER_PX, COVER_PX)
        except (WMSError, RuntimeError) as e:
            print(f"  ! {land} coverage check failed: {str(e)[:150]}")
            time.sleep(PAUSE_S)
            continue
        empty = (arr >= 250).all(axis=0) | (arr <= 5).all(axis=0)
        if alpha is not None:
            empty |= alpha == 0
        leer = float(empty.mean())
        time.sleep(PAUSE_S)
        if leer > COVER_MAX_EMPTY:
            continue
        out.append({"id": chip_id(i, j), "i": i, "j": j, "land": land, "leer_anteil": round(leer, 4)})
        taken.append(rect)
        print(f"  + {chip_id(i, j)} {CODE[land]}  (E {rect[0]:.1f} N {rect[1]:.1f}, empty {leer:.1%})", flush=True)
    if len(out) < need:
        print(f"  ! {land}: only {len(out)} of {need} background chips found "
              f"({requests} coverage requests, {draws} draws)")
    return out


def cmd_background(only: str | None, n: int | None, seed: int, limit: int | None) -> None:
    polys = load_polygons()
    label_chips, _ = make_plan(polys)
    all_lands = list(WMS)
    default_n = max(len(all_lands), math.ceil(BG_SHARE * len(label_chips)))
    if only:
        quota = {only: n if n is not None else bg_quota(default_n, all_lands, label_chips)[only]}
    else:
        quota = bg_quota(n if n is not None else default_n, all_lands, label_chips)
    existing = read_background()
    have = {land: sum(1 for c in existing if c["land"] == land) for land in quota}
    envs = load_all_envelopes()
    taken = [chip_rect(c["i"], c["j"]) for c in existing] + \
            [(c["x0"], c["y0"], c["x0"] + CHIP_M, c["y0"] + CHIP_M) for c in label_chips.values()]
    print(f"{len(label_chips)} label chips; background chips wanted {sum(quota.values())}, "
          f"already listed {sum(have.values())} ({BACKGROUND_GPKG})")
    caps = load_caps(sorted(quota))
    for land in sorted(quota):
        need = quota[land] - have[land]
        if need <= 0:
            continue
        if "error" in caps[land]:
            print(f"  ! {land}: WMS not usable now ({caps[land]['error'][:120]}) - skipped, run again later")
            continue
        print(f"{land}: drawing {need} chip(s) ...", flush=True)
        new = draw_background(land, need, seed, caps[land], envs, taken)
        append_background(new, seed)          # saved per state, so an interruption keeps them
    # fetch the f01 tiles of every listed chip (except rejected ones) that are still missing
    chips = [c for c in read_background() if c["land"] in quota and c["status"] != "verwerfen"]
    tiles, notes = {}, {}
    for c in chips:
        x0, y0, _, _ = chip_rect(c["i"], c["j"])
        for a, b in chip_tiles(x0, y0):
            t = tiles.setdefault((a, b), {"E": a * TILE_M, "N": b * TILE_M, "sites": set(),
                                          "lands": {c["land"]: 1}, "land": c["land"],
                                          "tile_id": tile_id(a * TILE_M, b * TILE_M)})
            notes[t["tile_id"]] = f"background {c['id']}"
    print(f"\n{len(chips)} background chips -> {len(tiles)} f01 tiles")
    if tiles:
        cmd_fetch(tiles, sorted(quota), limit, test=False, notes=notes)
    print(f"\nnext: open {BACKGROUND_GPKG} in QGIS over the mosaic and set `status` per chip "
          "(ok / holz / verwerfen). tile_and_chip.py only uses status = ok.")


# =========================================================================
def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["caps", "plan", "test", "run", "probe", "redate", "mosaic",
                                        "background"])
    ap.add_argument("--only", help="one state, e.g. Niedersachsen")
    ap.add_argument("--limit", type=int, help="at most N new tiles this time")
    ap.add_argument("--n", type=int, help="background: total number of background chips "
                                          f"(default {round(BG_SHARE * 100)} %% of the label chips, at least one per state)")
    ap.add_argument("--seed", type=int, default=BG_SEED, help="background: random seed")
    ap.add_argument("--url", help="use another WMS address for the --only state (this command only)")
    ap.add_argument("--layer", help="use another image layer for the --only state (this command only)")
    a = ap.parse_args(argv)
    lands = list(WMS) if not a.only else [a.only]
    if a.only and a.only not in WMS:
        raise SystemExit(f"unknown state {a.only!r}; one of: {', '.join(WMS)}")
    if a.url or a.layer:
        if not a.only:
            raise SystemExit("--url/--layer need --only <state>")
        url, layer, info = WMS[a.only]
        WMS[a.only] = (a.url or url, a.layer or layer, None if a.url else info)
        STATE_OPTIONS.pop(a.only, None)       # e.g. Saarland's map_url belongs to the default address
        print(f"override for {a.only}: url={WMS[a.only][0]}  layer={WMS[a.only][1]}")
    print(f"config:  {CONFIG_PATH}")
    print(f"archive: {archive()}")
    if a.command == "background":
        keep_awake(True)
        try:
            cmd_background(a.only, a.n, a.seed, a.limit)
        finally:
            keep_awake(False)
        return
    if a.command == "caps":
        cmd_caps(lands)
    elif a.command == "plan":
        cmd_plan()
    elif a.command == "redate":
        cmd_redate()
    elif a.command == "mosaic":
        build_vrt()
    elif a.command == "probe":
        if not a.only:
            raise SystemExit("probe needs --only <state>, e.g. --only Baden-Württemberg")
        cmd_probe(a.only, make_plan(load_polygons())[1])
    else:
        _, tiles = make_plan(load_polygons())
        keep_awake(True)
        try:
            cmd_fetch({k: t for k, t in tiles.items()}, lands, a.limit, test=a.command == "test")
        finally:
            keep_awake(False)


if __name__ == "__main__":
    main()
