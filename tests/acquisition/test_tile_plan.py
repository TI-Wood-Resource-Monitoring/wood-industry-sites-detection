# Unit tests for src/woodsites/acquisition/tile_plan.py.
#
# Run all tests from the repository folder:
#     python -m pytest                    (OSGeo4W Shell on Windows)
# The last line must say "passed" and nothing "failed".
#
# All polygons here are invented and lie around chip column 10, chip row 20.
# The numbers the expected results were worked out from, by hand:
#
#   chip column  9 covers 5529.6 - 6348.8 m east      tile columns 13-15
#   chip column 10 covers 6144.0 - 6963.2 m east      tile columns 15-17
#   chip column 11 covers 6758.4 - 7577.6 m east      tile columns 16-18
#   chip row    20 covers 12288.0 - 13107.2 m north   tile rows    30-32
#   chip row    21 covers 12902.4 - 13721.6 m north   tile rows    32-34
#
# Neighbouring chips overlap. Only chip column 10 covers 6348.8 - 6758.4 m,
# only chip column 11 covers 6963.2 - 7372.8 m, only chip row 20 covers
# 12492.8 - 12902.4 m and only chip row 21 covers 13107.2 - 13516.8 m.

import unittest

from osgeo import ogr

from woodsites.acquisition import grid
from woodsites.acquisition import tile_plan
from woodsites.acquisition.domain import Polygon, Tile


def square(minx, miny):
    """An invented polygon shape: a square of 100 m with this lower-left corner."""
    return tile_plan.box_shape(minx, miny, minx + 100.0, miny + 100.0)


def polygon(site_id, land, shape):
    """An invented polygon as a polygon source would deliver it."""
    return Polygon(new_id=site_id + "_L01", site_id=site_id, land=land, shape=shape)


# Shapes that lie where only one chip covers them.
IN_CHIP_10_20 = square(6400.0, 12600.0)
IN_CHIP_11_20 = square(7000.0, 12600.0)
IN_CHIP_10_21 = square(6400.0, 13200.0)

# A shape that reaches from chip column 10 into chip column 11.
ACROSS_BORDER = tile_plan.box_shape(6700.0, 12600.0, 7000.0, 12700.0)


class TestBoxShape(unittest.TestCase):
    """box_shape: a rectangle as a GDAL shape."""

    def test_size_and_place(self):
        """The shape has the size and the place of the rectangle."""
        box = tile_plan.box_shape(1000.0, 2000.0, 1100.0, 2300.0)
        self.assertEqual(box.GetArea(), 30000.0)
        # GDAL gives the surrounding rectangle as (minx, maxx, miny, maxy).
        self.assertEqual(box.GetEnvelope(), (1000.0, 1100.0, 2000.0, 2300.0))


class TestChipsTouching(unittest.TestCase):
    """chips_touching: which chips touch one polygon."""

    def test_polygon_inside_one_chip(self):
        """A polygon where only one chip lies touches exactly that chip."""
        self.assertEqual(tile_plan.chips_touching(IN_CHIP_10_20), [(10, 20)])

    def test_polygon_across_a_chip_border(self):
        """A polygon reaching into the next chip column touches both chips."""
        self.assertEqual(tile_plan.chips_touching(ACROSS_BORDER), [(10, 20), (11, 20)])

    def test_sharing_only_an_edge_counts(self):
        """A polygon that starts exactly where chip column 10 ends still touches it."""
        on_the_edge = tile_plan.box_shape(6963.2, 12600.0, 7000.0, 12700.0)
        self.assertEqual(tile_plan.chips_touching(on_the_edge), [(10, 20), (11, 20)])

    def test_real_shape_decides_not_the_rectangle(self):
        """A triangle whose surrounding rectangle reaches chip (11, 21) but which itself does not."""
        triangle = ogr.CreateGeometryFromWkt("POLYGON((6700 12850,6800 12850,6700 12950,6700 12850))")
        # the rectangle around the triangle touches four chips ...
        self.assertEqual(grid.chips_near_box(6700.0, 12850.0, 6800.0, 12950.0),
                         [(10, 20), (10, 21), (11, 20), (11, 21)])
        # ... the triangle itself only three: its slanted side stays below the
        # corner where chip (11, 21) begins (6758.4 / 12902.4).
        self.assertEqual(tile_plan.chips_touching(triangle), [(10, 20), (10, 21), (11, 20)])


class TestChipsOfPolygons(unittest.TestCase):
    """chips_of_polygons: the chips of several polygons with their sites and states."""

    def test_sites_and_states_are_collected(self):
        """Every chip knows all sites and all states of the polygons that touch it."""
        polygons = [
            polygon("S9001", "Hessen", IN_CHIP_10_20),
            polygon("S9002", "Bayern", IN_CHIP_11_20),
            polygon("S9003", "Hessen", ACROSS_BORDER),
        ]
        chips = tile_plan.chips_of_polygons(polygons)
        self.assertEqual(sorted(chips), [(10, 20), (11, 20)])
        self.assertEqual(chips[(10, 20)], {"site_ids": {"S9001", "S9003"}, "lands": {"Hessen"}})
        self.assertEqual(chips[(11, 20)], {"site_ids": {"S9002", "S9003"}, "lands": {"Bayern", "Hessen"}})


class TestMajorityLand(unittest.TestCase):
    """majority_land: the rule which federal state a tile belongs to."""

    def test_most_chips_win(self):
        """The state with the most chips is chosen."""
        self.assertEqual(tile_plan.majority_land({"Hessen": 3, "Bayern": 1}), "Hessen")
        self.assertEqual(tile_plan.majority_land({"Hessen": 1, "Bayern": 2, "Thüringen": 1}), "Bayern")

    def test_tie_goes_to_first_in_alphabet(self):
        """On a tie the state that comes first in the alphabet is chosen, every time."""
        self.assertEqual(tile_plan.majority_land({"Hessen": 2, "Bayern": 2}), "Bayern")
        self.assertEqual(tile_plan.majority_land({"Sachsen-Anhalt": 1, "Sachsen": 1}), "Sachsen")

    def test_one_state(self):
        """With one state there is nothing to choose."""
        self.assertEqual(tile_plan.majority_land({"Saarland": 4}), "Saarland")

    def test_no_state_stops(self):
        """Without any state the function stops with an error."""
        with self.assertRaises(ValueError):
            tile_plan.majority_land({})


class TestPlanTiles(unittest.TestCase):
    """plan_tiles: from polygons to the tile plan."""

    def test_one_polygon_gives_nine_tiles(self):
        """One polygon in one chip needs the 3 x 3 tiles under that chip."""
        plan = tile_plan.plan_tiles([polygon("S9001", "Hessen", IN_CHIP_10_20)])
        by_hand = [
            "f01_E0006000_N0012000", "f01_E0006000_N0012400", "f01_E0006000_N0012800",
            "f01_E0006400_N0012000", "f01_E0006400_N0012400", "f01_E0006400_N0012800",
            "f01_E0006800_N0012000", "f01_E0006800_N0012400", "f01_E0006800_N0012800",
        ]
        self.assertEqual(list(plan), by_hand)
        self.assertEqual(plan["f01_E0006000_N0012000"],
                         Tile(a=15, b=30, land="Hessen", site_ids=("S9001",)))

    def test_across_border_gives_twelve_tiles(self):
        """A polygon in two chip columns needs tile columns 15-18, rows 30-32."""
        plan = tile_plan.plan_tiles([polygon("S9001", "Hessen", ACROSS_BORDER)])
        positions = []
        for tile_id in plan:
            positions.append((plan[tile_id].a, plan[tile_id].b))
        by_hand = []
        for a in (15, 16, 17, 18):
            for b in (30, 31, 32):
                by_hand.append((a, b))
        self.assertEqual(positions, by_hand)

    def test_two_states_share_tiles(self):
        """Tiles under chips of two states go to the majority; a tie goes to the first in the alphabet."""
        plan = tile_plan.plan_tiles([
            polygon("S9001", "Hessen", IN_CHIP_10_20),
            polygon("S9002", "Bayern", IN_CHIP_11_20),
            polygon("S9001", "Hessen", IN_CHIP_10_21),
        ])
        self.assertEqual(len(plan), 18)
        # only under the Hessen chip (10, 20):
        self.assertEqual(plan["f01_E0006000_N0012000"].land, "Hessen")
        self.assertEqual(plan["f01_E0006000_N0012000"].site_ids, ("S9001",))
        # under one Hessen chip and one Bayern chip: a tie
        self.assertEqual(plan["f01_E0006400_N0012000"].land, "Bayern")
        self.assertEqual(plan["f01_E0006400_N0012000"].site_ids, ("S9001", "S9002"))
        # under two Hessen chips and one Bayern chip: the majority
        self.assertEqual(plan["f01_E0006400_N0012800"].land, "Hessen")
        self.assertEqual(plan["f01_E0006400_N0012800"].site_ids, ("S9001", "S9002"))
        # only under the Bayern chip (11, 20):
        self.assertEqual(plan["f01_E0007200_N0012000"].land, "Bayern")
        self.assertEqual(plan["f01_E0007200_N0012000"].site_ids, ("S9002",))
        # only under the Hessen chip (10, 21):
        self.assertEqual(plan["f01_E0006000_N0013600"].land, "Hessen")

    def test_key_is_the_tile_id(self):
        """Every key of the plan is the id of the tile stored under it."""
        plan = tile_plan.plan_tiles([polygon("S9001", "Hessen", ACROSS_BORDER)])
        for tile_id, tile in plan.items():
            self.assertEqual(tile_id, tile.tile_id)

    def test_polygon_without_site(self):
        """A polygon without a site (other sources) brings its tiles and state, but no site."""
        no_site = Polygon(new_id="X1", land="Hessen", shape=IN_CHIP_10_20)
        plan = tile_plan.plan_tiles([no_site])
        self.assertEqual(len(plan), 9)
        self.assertEqual(plan["f01_E0006000_N0012000"], Tile(a=15, b=30, land="Hessen", site_ids=()))

    def test_no_polygons_gives_empty_plan(self):
        """Without polygons there is nothing to fetch."""
        self.assertEqual(tile_plan.plan_tiles([]), {})


if __name__ == "__main__":
    unittest.main()
