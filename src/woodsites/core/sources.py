"""Reading chips. Training and prediction use the SAME read() and the same downsampling.

ArchiveSource: the frozen f01 tiles listed in manifest.csv (never mosaic_f01.vrt: QGIS can
overwrite that file). Later NiCogSource (LGLN COG, task T0.10) gets the same read() interface.
"""
from __future__ import annotations

import csv
import os
from collections import OrderedDict
from pathlib import Path

import numpy as np
from osgeo import gdal

from . import grid

gdal.UseExceptions()


class MissingTiles(Exception):
    """A chip needs tiles that are not in the archive. Such a chip is never filled with zeros."""


def downsample2(buf: np.ndarray) -> np.ndarray:
    """0.2 m -> 0.4 m: exact mean of every 2 x 2 block, rounded half up. Deterministic."""
    c, h, w = buf.shape
    s = buf.reshape(c, h // 2, 2, w // 2, 2).astype(np.uint16).sum(axis=(2, 4))
    return ((s + 2) // 4).astype(np.uint8)


def empty_mask(rgb: np.ndarray) -> np.ndarray:
    """Pixels that are white or black in all bands (outside the WMS coverage, gaps)."""
    return (rgb >= 250).all(axis=0) | (rgb <= 5).all(axis=0)


class ArchiveSource:
    name = "archive"

    def __init__(self, archive: Path, cache_tiles: int = 16):
        self.archive = Path(archive)
        self.rows: dict[str, dict] = {}
        self.duplicates: list[str] = []
        self._cache: OrderedDict[str, np.ndarray] = OrderedDict()
        self._cache_n = cache_tiles
        p = self.archive / "manifest.csv"
        if not p.exists():
            raise SystemExit(f"manifest not found: {p}")
        with open(p, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r["tile_id"] in self.rows:
                    self.duplicates.append(r["tile_id"])
                self.rows[r["tile_id"]] = r

    def tile_path(self, tid: str) -> Path | None:
        r = self.rows.get(tid)
        return self.archive / r["file"] if r else None

    def _exists(self, p: Path) -> bool:
        """File check with one directory listing per state folder (instead of one network
        round trip per tile - over the VPN that was the slow part of 'check')."""
        if not hasattr(self, "_listing"):
            self._listing: dict[Path, set] = {}
        d = p.parent
        if d not in self._listing:
            try:
                self._listing[d] = set(os.listdir(d))
            except OSError:
                self._listing[d] = set()
        return p.name in self._listing[d]

    def missing_tiles(self, i: int, j: int) -> list[str]:
        out = []
        for a, b in grid.tiles_for_chip(i, j):
            p = self.tile_path(grid.tile_id(a, b))
            if p is None or not self._exists(p):
                out.append(grid.tile_id(a, b))
        return out

    def _tile(self, a: int, b: int) -> np.ndarray:
        tid = grid.tile_id(a, b)
        if tid in self._cache:
            self._cache.move_to_end(tid)
            return self._cache[tid]
        p = self.tile_path(tid)
        if p is None or not p.exists():
            raise MissingTiles(tid)
        ds = gdal.Open(str(p))
        want = (a * grid.TILE_M, grid.TICK_M, 0.0, (b + 1) * grid.TILE_M, 0.0, -grid.TICK_M)
        gt = ds.GetGeoTransform()
        if any(abs(g - w) > 1e-6 for g, w in zip(gt, want)) or ds.RasterXSize != grid.TILE_T \
                or ds.RasterYSize != grid.TILE_T or ds.RasterCount < 3:
            raise RuntimeError(f"{p}: unexpected georeferencing/size {gt} {ds.RasterXSize}x{ds.RasterYSize}")
        arr = ds.ReadAsArray(band_list=[1, 2, 3]).astype(np.uint8)
        ds = None
        self._cache[tid] = arr
        if len(self._cache) > self._cache_n:
            self._cache.popitem(last=False)
        return arr

    def read(self, i: int, j: int) -> tuple[np.ndarray, dict]:
        """RGB chip (3, 2048, 2048) uint8 at 0.4 m plus metadata. Raises MissingTiles."""
        missing = self.missing_tiles(i, j)
        if missing:
            raise MissingTiles(", ".join(missing))
        x0, y0, x1, y1 = grid.chip_bounds_t(i, j)
        buf = np.zeros((3, grid.CHIP_T, grid.CHIP_T), np.uint8)
        tiles, lands, flights = [], set(), set()
        for a, b in grid.tiles_for_chip(i, j):
            tx0, ty0 = a * grid.TILE_T, b * grid.TILE_T
            ox0, ox1 = max(x0, tx0), min(x1, tx0 + grid.TILE_T)
            oy0, oy1 = max(y0, ty0), min(y1, ty0 + grid.TILE_T)
            if ox0 >= ox1 or oy0 >= oy1:
                continue
            t = self._tile(a, b)
            # rows count from the TOP: row = top edge - y
            tr0, cr0 = (ty0 + grid.TILE_T) - oy1, y1 - oy1
            tc0, cc0 = ox0 - tx0, ox0 - x0
            h, w = oy1 - oy0, ox1 - ox0
            buf[:, cr0:cr0 + h, cc0:cc0 + w] = t[:, tr0:tr0 + h, tc0:tc0 + w]
            tid = grid.tile_id(a, b)
            r = self.rows[tid]
            tiles.append(tid)
            lands.add(r.get("land", ""))
            if r.get("bildflug"):
                flights.add(r["bildflug"])
        return downsample2(buf), {"tiles": tiles, "lands": sorted(lands), "bildflug": sorted(flights)}
