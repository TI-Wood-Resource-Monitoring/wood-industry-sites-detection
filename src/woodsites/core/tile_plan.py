"""The tile plan: from polygons to the list of tiles that are needed.

The way from a polygon to its tiles has two steps:

  1. polygon -> chips.  Every chip whose square touches the real shape of the
     polygon counts. A chip is the square the model will later look at.
  2. chips -> tiles.    Every tile that lies under such a chip is needed,
     because the chip is cut out of these tiles later.

Each tile also gets the federal state it is fetched from and the sites it was
planned for.

This file reads no file and asks no server. It gets a list of polygons and
gives back a plan. Where the polygons come from is decided elsewhere (see
PolygonSource in core/protocols.py).
"""

from osgeo import ogr

from woodsites.core import grid

# Make GDAL stop with an error where a problem happens (see core/polygons.py).
ogr.UseExceptions()


def box_shape(minx: float, miny: float, maxx: float, maxy: float) -> ogr.Geometry:
    """Turn a rectangle into a GDAL shape.

    Input:  minx, miny, maxx, maxy - a rectangle in metres.
    Output: the rectangle as a GDAL polygon, so that GDAL can test whether it
            touches another shape.
    """
    # A polygon is stored as a closed line: the first point is repeated at the end.
    ring = ogr.Geometry(ogr.wkbLinearRing)
    ring.AddPoint_2D(minx, miny)
    ring.AddPoint_2D(maxx, miny)
    ring.AddPoint_2D(maxx, maxy)
    ring.AddPoint_2D(minx, maxy)
    ring.AddPoint_2D(minx, miny)
    box = ogr.Geometry(ogr.wkbPolygon)
    box.AddGeometry(ring)
    return box


def chips_touching(shape: ogr.Geometry) -> list[tuple[int, int]]:
    """All chips whose square touches a polygon.

    Input:  shape - the outline of one polygon as a GDAL geometry.
    Output: list of (i, j), sorted from left to right and, within one column,
            from bottom to top. A chip that only shares an edge or a corner
            with the polygon is included.
    """
    # GDAL gives the surrounding rectangle in the order minx, maxx, miny, maxy.
    minx, maxx, miny, maxy = shape.GetEnvelope()
    touching = []
    # The grid gives the candidates: chips that touch the surrounding
    # rectangle. A polygon can be slanted or bent, so its rectangle may reach
    # a chip that the polygon itself does not. The real shape decides.
    for i, j in grid.chips_near_box(minx, miny, maxx, maxy):
        chip_minx, chip_miny, chip_maxx, chip_maxy = grid.chip_bounds(i, j)
        chip = box_shape(chip_minx, chip_miny, chip_maxx, chip_maxy)
        if shape.Intersects(chip):
            touching.append((i, j))
    return touching


def chips_of_polygons(polygons: list[dict]) -> dict[tuple[int, int], dict]:
    """All chips that touch at least one polygon, with what they were found for.

    Input:  polygons - list of polygons as a polygon source delivers them.
    Output: dictionary chip (i, j) -> dictionary with
              site_ids - set of the sites whose polygons touch the chip
              lands    - set of the federal states of those polygons
            (A set is a collection without duplicates and without order.)
    """
    chips = {}
    for polygon in polygons:
        for chip in chips_touching(polygon["shape"]):
            if chip not in chips:
                chips[chip] = {"site_ids": set(), "lands": set()}
            chips[chip]["site_ids"].add(polygon["site_id"])
            chips[chip]["lands"].add(polygon["land"])
    return chips


def tiles_of_chips(chips: dict[tuple[int, int], dict]) -> dict[tuple[int, int], dict]:
    """All tiles under the chips, with what they are needed for.

    Input:  chips - the dictionary from chips_of_polygons.
    Output: dictionary tile (a, b) -> dictionary with
              site_ids    - set of the sites of all chips above the tile
              land_counts - dictionary federal state -> number of chips above
                            the tile that belong to that state
    """
    tiles = {}
    for (i, j) in chips:
        chip = chips[(i, j)]
        for tile in grid.tiles_under_chip(i, j):
            if tile not in tiles:
                tiles[tile] = {"site_ids": set(), "land_counts": {}}
            tiles[tile]["site_ids"].update(chip["site_ids"])
            # One vote per chip for each state of that chip.
            counts = tiles[tile]["land_counts"]
            for land in chip["lands"]:
                counts[land] = counts.get(land, 0) + 1
    return tiles


def majority_land(counts: dict[str, int]) -> str:
    """THE rule which federal state a tile belongs to.

    Input:  counts - dictionary federal state -> number of chips.
    Output: the state with the most chips. If two states have the same
            number, the one that comes first in the alphabet.

    The rule for a tie must be fixed. If it depended on chance, the same tile
    could be planned for one state today and for another tomorrow.
    """
    if not counts:
        raise ValueError("no federal state to choose from")
    best_land = ""
    best_count = 0
    # Going through the names in alphabetical order and replacing the best
    # only if a count is LARGER keeps the earlier name on a tie.
    for land in sorted(counts):
        if counts[land] > best_count:
            best_land = land
            best_count = counts[land]
    return best_land


def plan_tiles(polygons: list[dict]) -> dict[str, dict]:
    """The tile plan for a list of polygons.

    Input:  polygons - list of polygons as a polygon source delivers them
            (each with site_id, land and shape).
    Output: dictionary tile id -> dictionary with
              a, b     - column and row of the tile
              land     - the federal state the tile is fetched from
              site_ids - sorted list of the sites the tile is needed for
            The tiles are in the order of their column and row.
    """
    tiles = tiles_of_chips(chips_of_polygons(polygons))
    plan = {}
    for (a, b) in sorted(tiles):
        tile = tiles[(a, b)]
        plan[grid.tile_id(a, b)] = {
            "a": a,
            "b": b,
            "land": majority_land(tile["land_counts"]),
            "site_ids": sorted(tile["site_ids"]),
        }
    return plan
