"""Chip index GeoPackage: layers chips, labels, masks. Built locally in one transaction per layer,
then copied (writing feature by feature onto a network drive over the VPN is very slow)."""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from osgeo import ogr, osr

from woodsites.core import grid
from woodsites.core.polygons import box

ogr.UseExceptions()

CHIP_FIELDS = [("id", ogr.OFTString), ("i", ogr.OFTInteger), ("j", ogr.OFTInteger),
               ("old_id", ogr.OFTString), ("kind", ogr.OFTString), ("split", ogr.OFTString),
               ("status", ogr.OFTString), ("n_labels", ogr.OFTInteger), ("n_cut", ogr.OFTInteger),
               ("n_masked", ogr.OFTInteger), ("mask_share", ogr.OFTReal), ("empty_share", ogr.OFTReal), ("white_black_pixels", ogr.OFTReal),
               ("mean_r", ogr.OFTReal), ("mean_g", ogr.OFTReal), ("mean_b", ogr.OFTReal),
               ("std_r", ogr.OFTReal), ("std_g", ogr.OFTReal), ("std_b", ogr.OFTReal),
               ("tiles", ogr.OFTString), ("lands", ogr.OFTString), ("sites", ogr.OFTString),
               ("bildflug", ogr.OFTString), ("written", ogr.OFTInteger), ("skip_reason", ogr.OFTString)]
LABEL_FIELDS = [("chip_id", ogr.OFTString), ("split", ogr.OFTString), ("line", ogr.OFTInteger),
                ("new_id", ogr.OFTString),
                ("category", ogr.OFTString), ("class_id", ogr.OFTInteger), ("visible", ogr.OFTReal),
                ("cut_at_edge", ogr.OFTInteger)]
MASK_FIELDS = [("chip_id", ogr.OFTString), ("new_id", ogr.OFTString), ("category", ogr.OFTString),
               ("visible", ogr.OFTReal), ("reason", ogr.OFTString)]


def write_index(path: Path, chips: list[dict], labels: list[dict], masks: list[dict]) -> None:
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(grid.EPSG)
    with tempfile.TemporaryDirectory() as tmp:
        local = Path(tmp) / path.name
        ds = ogr.GetDriverByName("GPKG").CreateDataSource(str(local))
        for name, rows, fields, gtype in (("chips", chips, CHIP_FIELDS, ogr.wkbPolygon),
                                          ("labels", labels, LABEL_FIELDS, ogr.wkbPolygon),
                                          ("masks", masks, MASK_FIELDS, ogr.wkbMultiPolygon)):
            lyr = ds.CreateLayer(name, srs, gtype)
            for fn, ft in fields:
                lyr.CreateField(ogr.FieldDefn(fn, ft))
            lyr.StartTransaction()
            for r in rows:
                f = ogr.Feature(lyr.GetLayerDefn())
                for fn, _ in fields:
                    v = r.get(fn)
                    if v is not None:
                        f[fn] = v
                g = r["geom"]
                if gtype == ogr.wkbMultiPolygon:
                    g = ogr.ForceToMultiPolygon(g)
                f.SetGeometry(g)
                lyr.CreateFeature(f)
            lyr.CommitTransaction()
        ds = None
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(local, path)


def chip_geom(i: int, j: int) -> ogr.Geometry:
    return box(*grid.chip_bounds(i, j))


def read_layer(path: Path, layer: str) -> list[dict]:
    ds = ogr.Open(str(path), 0)
    lyr = ds.GetLayerByName(layer)
    names = [f.name for f in lyr.schema]
    out = []
    for f in lyr:
        r = {n: f[n] for n in names}
        r["geom"] = f.GetGeometryRef().Clone()
        out.append(r)
    ds = None
    return out
