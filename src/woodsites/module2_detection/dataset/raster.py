"""Pixels of one chip: masks, statistics, GeoTIFF output."""
from __future__ import annotations

from pathlib import Path

import numpy as np
from osgeo import gdal, ogr, osr

from woodsites.core import grid
from woodsites.core.sources import empty_mask

gdal.UseExceptions()
ogr.UseExceptions()


def _srs() -> osr.SpatialReference:
    s = osr.SpatialReference()
    s.ImportFromEPSG(grid.EPSG)
    return s


def _mem_vector_driver():
    """'MEM' for vectors since GDAL 3.11 (the old 'Memory' driver prints a deprecation warning)."""
    drv = ogr.GetDriverByName("MEM")
    if drv is not None and drv.GetMetadataItem("DCAP_VECTOR") == "YES":
        return drv
    return ogr.GetDriverByName("Memory")


def rasterize(geoms: list[ogr.Geometry], i: int, j: int) -> np.ndarray:
    """Boolean 2048 x 2048 array: True where a geometry touches a pixel (ALL_TOUCHED)."""
    out = np.zeros((grid.CHIP_PX, grid.CHIP_PX), bool)
    if not geoms:
        return out
    ds = gdal.GetDriverByName("MEM").Create("", grid.CHIP_PX, grid.CHIP_PX, 1, gdal.GDT_Byte)
    ds.SetGeoTransform(grid.geotransform(i, j))
    ds.SetProjection(_srs().ExportToWkt())
    vds = _mem_vector_driver().CreateDataSource("m")
    lyr = vds.CreateLayer("m", _srs(), ogr.wkbUnknown)
    for g in geoms:
        f = ogr.Feature(lyr.GetLayerDefn())
        f.SetGeometry(g)
        lyr.CreateFeature(f)
    gdal.RasterizeLayer(ds, [1], lyr, burn_values=[1], options=["ALL_TOUCHED=TRUE"])
    out = ds.GetRasterBand(1).ReadAsArray().astype(bool)
    ds = vds = None
    return out


def apply_mask(rgb: np.ndarray, m: np.ndarray, value: int) -> float:
    """Grey out the masked pixels in place; returns the masked share."""
    if m.any():
        rgb[:, m] = value
    return float(m.mean())


def gap_share(rgb: np.ndarray, block: int = 32, min_fill: float = 0.99, max_std: float = 2.0) -> float:
    """Share of the chip that is a real gap in the imagery (outside the WMS coverage, missing
    data): whole 32 x 32 px blocks (12.8 m) that are white or black and flat. Bright roofs and
    white timber packages are white only in scattered pixels, so they are not counted
    (a chip with 1 % white roof pixels had no gap at all)."""
    e = empty_mask(rgb)
    c, h, w = rgb.shape
    nb_y, nb_x = h // block, w // block
    fill = e[:nb_y * block, :nb_x * block].reshape(nb_y, block, nb_x, block).mean(axis=(1, 3))
    std = rgb[:, :nb_y * block, :nb_x * block].reshape(c, nb_y, block, nb_x, block).std(axis=(2, 4)).max(axis=0)
    return float(((fill >= min_fill) & (std <= max_std)).mean())


def stats(rgb: np.ndarray) -> dict:
    out = {"empty_share": round(gap_share(rgb), 5),
           "white_black_pixels": round(float(empty_mask(rgb).mean()), 5)}
    for k, band in zip("rgb", rgb):
        out[f"mean_{k}"] = round(float(band.mean()), 2)
        out[f"std_{k}"] = round(float(band.std()), 2)
    return out


def write_geotiff(path: Path, rgb: np.ndarray, i: int, j: int, meta: dict | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    ds = gdal.GetDriverByName("GTiff").Create(
        str(tmp), grid.CHIP_PX, grid.CHIP_PX, 3, gdal.GDT_Byte,
        options=["TILED=YES", "BLOCKXSIZE=512", "BLOCKYSIZE=512", "COMPRESS=DEFLATE", "PREDICTOR=2",
                 "PHOTOMETRIC=RGB", "INTERLEAVE=PIXEL"])
    ds.SetGeoTransform(grid.geotransform(i, j))
    ds.SetProjection(_srs().ExportToWkt())
    for b in range(3):
        ds.GetRasterBand(b + 1).WriteArray(rgb[b])
    ds.SetMetadata({k: str(v) for k, v in (meta or {}).items()})
    ds.FlushCache()
    ds = None
    tmp.replace(path)
