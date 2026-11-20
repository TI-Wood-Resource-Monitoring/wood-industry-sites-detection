"""The things Module 1 passes between its parts: polygons and tiles.

These are plain data containers (dataclasses). They hold data and the few rules
that belong to that data, and nothing else: no reading of files, no servers.
Every part of the module (polygon source, tile plan, coordinator, image source,
image store) speaks in these types, so that each part can be exchanged without
the others noticing.

`frozen=True` means an object cannot be changed after it is made. A tile that
was planned stays exactly as planned; a mistake cannot creep in later.

RawImage and GeoTIFF (the picture as it comes from a server, and the finished
georeferenced picture) follow in later build steps (R5, R7).
"""

from dataclasses import dataclass

from osgeo import ogr

from woodsites.acquisition import grid


@dataclass(frozen=True)
class Polygon:
    """One polygon as a polygon source delivers it.

    new_id  - name of the polygon (text, not empty)
    land    - federal state, spelled as in states.py; it decides which server
              the tiles of the polygon come from
    shape   - the outline as a GDAL geometry in EPSG:25832
    site_id - the site the polygon belongs to. Optional: the project's own
              polygon file always has one, other sources (e.g. land-use
              layers) may not. "" means "no site".
    """

    new_id: str
    land: str
    shape: ogr.Geometry
    site_id: str = ""


@dataclass(frozen=True)
class Tile:
    """One planned tile of the grid f01 (400 m x 400 m, 2000 x 2000 pixels).

    a, b     - column and row of the tile, counted in 400 m steps from 0/0
    land     - the federal state the tile is fetched from
    site_ids - the sites the tile is needed for, sorted (a tuple, so that it
               cannot be changed either)
    """

    a: int
    b: int
    land: str
    site_ids: tuple[str, ...]

    @property
    def tile_id(self) -> str:
        """The tile's name, e.g. f01_E0400000_N5600000 (worked out, never stored twice)."""
        return grid.tile_id(self.a, self.b)

    @property
    def bounds(self) -> tuple[int, int, int, int]:
        """(minx, miny, maxx, maxy) of the tile in metres, EPSG:25832."""
        return grid.tile_bounds(self.a, self.b)
