"""Reading the polygon file, and the rule which polygons count.

The polygon file is a GeoPackage with the layer `dop20_polygons`. Each row is
one polygon drawn by hand, with these fields among others:

  new_id   - name of the polygon
  site_id  - the site it belongs to
  land     - federal state, spelled as in acquisition/states.py
  triage   - result of the comparison with the aerial images: A, B or C
  herkunft - where the polygon comes from; "dop20_neu" = drawn new on the images

The rule which polygons count is needed by several scripts (image fetch,
background chips, chipping). It exists once, here.

The file is only ever opened for reading. Nothing in this module changes it.
"""

import os

from osgeo import ogr

from woodsites.acquisition import grid
from woodsites.acquisition import states
from woodsites.acquisition.domain import Polygon

# Without this line GDAL reports many problems only by handing back "nothing",
# and the mistake shows up much later at a different place. With it, GDAL
# stops with an error at the place where the problem happens.
ogr.UseExceptions()

# Name of the layer inside the polygon file.
POLYGON_LAYER = "dop20_polygons"

# Fields the layer must have. `herkunft` is not in this list on purpose: an
# older polygon file without it is still readable.
NEEDED_FIELDS = ["new_id", "site_id", "land", "triage"]


def polygon_is_wanted(triage: str, herkunft: str) -> bool:
    """THE rule which polygons count.

    Input:  triage, herkunft - the two field values as text, already cleaned
            with clean_text.
    Output: True if the polygon counts, False if not.

    A polygon counts if the triage found it on the images (A or B) or if it
    was drawn new on the images (herkunft = dop20_neu). Capital and small
    letters are different: "a" is not "A".
    """
    if triage == "A" or triage == "B":
        return True
    if herkunft == "dop20_neu":
        return True
    return False


def clean_text(value: object) -> str:
    """Turn one field value into plain text.

    Input:  value - a field value as GDAL hands it over. An empty field
            arrives as None, which means "nothing".
    Output: the value as text without spaces at both ends; "" for an empty field.
    """
    if value is None:
        return ""
    # strip() removes spaces at both ends. A space typed by accident in QGIS
    # is invisible there, and "A " must not count as something other than "A".
    return str(value).strip()


def layer_field_names(layer: ogr.Layer) -> list[str]:
    """Names of all fields of a layer.

    Input:  layer - an opened layer.
    Output: list of the field names as text.
    """
    definition = layer.GetLayerDefn()
    names = []
    for number in range(definition.GetFieldCount()):
        names.append(definition.GetFieldDefn(number).GetName())
    return names


def open_polygon_layer(gpkg_path: str) -> tuple[ogr.DataSource, ogr.Layer]:
    """Open the polygon file for reading and hand over its polygon layer.

    Input:  gpkg_path - path of the polygon file.
    Output: (dataset, layer). The dataset is the opened file, the layer is the
            table of polygons in it. Keep both: GDAL closes the file as soon
            as nothing refers to the dataset any more, and the layer is
            useless after that.

    Stops with a short message if the file or the layer is missing, if the
    layer is not in the coordinate system of the grid, or if a needed field
    is missing.
    """
    if not os.path.isfile(gpkg_path):
        raise SystemExit(
            f"polygon file not found: {gpkg_path}\n"
            f"Check polygons_gpkg in the section [paths] of the settings file.")
    # The 0 means: read only. This module never writes into the polygon file.
    dataset = ogr.Open(gpkg_path, 0)
    layer = dataset.GetLayerByName(POLYGON_LAYER)
    if layer is None:
        raise SystemExit(f"{gpkg_path}: layer {POLYGON_LAYER} not found")
    # All grid maths assumes metres in one coordinate system. Polygons in
    # another system would give tiles at wrong places without any error.
    system = layer.GetSpatialRef()
    if system is None or system.GetAuthorityCode(None) != str(grid.EPSG):
        raise SystemExit(f"{gpkg_path}: layer {POLYGON_LAYER} must be in EPSG:{grid.EPSG}")
    names = layer_field_names(layer)
    for name in NEEDED_FIELDS:
        if name not in names:
            raise SystemExit(f"{gpkg_path}: layer {POLYGON_LAYER} has no field {name}")
    return dataset, layer


def polygon_problems(polygon: Polygon) -> list[str]:
    """Say what is wrong with one wanted polygon.

    Input:  polygon - one Polygon read from the file.
    Output: list of short texts, one per problem. An empty list means the
            polygon can be used.

    In the project's own file every polygon must have a site, although a
    Polygon in general may come without one (domain.py).
    """
    problems = []
    if polygon.new_id == "":
        problems.append("new_id is empty")
    if polygon.site_id == "":
        problems.append("site_id is empty")
    if polygon.land not in states.STATES:
        problems.append(f"land '{polygon.land}' is not one of the twelve states")
    if polygon.shape is None or polygon.shape.IsEmpty():
        problems.append("no shape")
    return problems


def read_polygons(gpkg_path: str) -> list[Polygon]:
    """Read all polygons that count.

    Input:  gpkg_path - path of the polygon file.
    Output: list of Polygon, one per wanted polygon, in the order of the file.

    Polygons that do not count are skipped without looking at them further.
    If a wanted polygon has a problem, the run stops with ONE message that
    lists all of them, so that they can be corrected in one go in QGIS.
    """
    dataset, layer = open_polygon_layer(gpkg_path)
    has_herkunft = "herkunft" in layer_field_names(layer)
    wanted = []
    faulty = []
    for feature in layer:                      # a feature is one row of the layer
        triage = clean_text(feature["triage"])
        herkunft = ""
        if has_herkunft:
            herkunft = clean_text(feature["herkunft"])
        if not polygon_is_wanted(triage, herkunft):
            continue
        shape = feature.GetGeometryRef()
        if shape is not None:
            # Take a copy. The original belongs to the row and disappears
            # when the loop moves on to the next row.
            shape = shape.Clone()
        polygon = Polygon(
            new_id=clean_text(feature["new_id"]),
            site_id=clean_text(feature["site_id"]),
            land=clean_text(feature["land"]),
            shape=shape,
        )
        problems = polygon_problems(polygon)
        if problems:
            faulty.append(f"  row {feature.GetFID()} (new_id '{polygon.new_id}'): " + ", ".join(problems))
        else:
            wanted.append(polygon)
    if faulty:
        raise SystemExit(
            f"{gpkg_path}: these wanted polygons cannot be used:\n"
            + "\n".join(faulty)
            + "\nCorrect them in QGIS, save the layer, and start again.")
    # The file is closed by itself when this function ends, because then
    # nothing refers to `dataset` any more.
    return wanted


class PolygonFile:
    """The project's own hand-drawn polygons as a polygon source.

    This class is the first version of the agreement PolygonSource in
    acquisition/coordinator.py. It is only a thin wrapper: it remembers which file to
    read, and the work is done by the function read_polygons above.

    Use:  source = PolygonFile("path/to/polygons.gpkg")
          polygons = source.read_polygons()
    """

    def __init__(self, gpkg_path: str) -> None:
        """Remember the path of the polygon file. The file is not opened yet."""
        self.gpkg_path = gpkg_path

    def read_polygons(self) -> list[Polygon]:
        """Deliver all polygons that count (see PolygonSource for the output)."""
        # Inside a class, a plain name like read_polygons means the function
        # at the top level of this file, not this method of the same name.
        return read_polygons(self.gpkg_path)
