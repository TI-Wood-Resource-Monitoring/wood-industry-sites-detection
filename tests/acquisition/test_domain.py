# Unit tests for src/woodsites/acquisition/domain.py.
#
# Run all unit tests from the repository folder:
#     python -m pytest                    (OSGeo4W Shell on Windows)
# The last line must say "passed" and nothing "failed".

import dataclasses

import pytest
from osgeo import ogr

from woodsites.acquisition.domain import Polygon, Tile


def test_tile_id_comes_from_the_grid():
    """A tile's id is worked out from its column and row (lower-left corner in metres)."""
    tile = Tile(a=1000, b=14000, land="Hessen", site_ids=("S9001",))
    assert tile.tile_id == "f01_E0400000_N5600000"


def test_tile_bounds_are_400_m():
    """A tile covers 400 m x 400 m from its lower-left corner."""
    tile = Tile(a=1000, b=14000, land="Hessen", site_ids=())
    assert tile.bounds == (400000, 5600000, 400400, 5600400)


def test_tile_cannot_be_changed():
    """A planned tile is frozen: changing a field stops with an error."""
    tile = Tile(a=1, b=2, land="Hessen", site_ids=())
    with pytest.raises(dataclasses.FrozenInstanceError):
        tile.land = "Bayern"  # type: ignore[misc]


def test_tiles_with_the_same_values_are_equal():
    """Two tiles with the same values count as the same tile (used in the tests of the plan)."""
    assert Tile(a=1, b=2, land="Hessen", site_ids=("S1",)) == Tile(a=1, b=2, land="Hessen", site_ids=("S1",))
    assert Tile(a=1, b=2, land="Hessen", site_ids=()) != Tile(a=1, b=2, land="Bayern", site_ids=())


def test_polygon_site_is_optional():
    """A polygon without a site gets the empty text as its site."""
    shape = ogr.CreateGeometryFromWkt("POLYGON((0 0,1 0,1 1,0 0))")
    polygon = Polygon(new_id="X1", land="Hessen", shape=shape)
    assert polygon.site_id == ""
