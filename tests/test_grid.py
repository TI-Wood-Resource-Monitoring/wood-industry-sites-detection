# Unit tests for src/woodsites/core/grid.py.
#
# Run all unit tests from the repository folder:
#     set PYTHONPATH=%CD%\src                      (OSGeo4W Shell on Windows)
#     python -m unittest discover -s tests -v
# The last line must be:  OK
#
# How to read this file: every class groups the tests of one topic, and every
# function whose name starts with "test_" is one test. A test calls a function
# of grid.py with a known input and compares the output with a value that was
# written down by hand or worked out in a second, independent way.
#
# All positions in this file are invented. The numbers 2000, 3072, 4096 and 400
# are typed in again here on purpose, so that a changed constant in grid.py is
# noticed.

import math
import unittest

from woodsites.core import grid

# The old-against-new comparison runs over every chip position from 0 to this
# number on one axis. Germany lies well inside this range on both axes.
LAST_POSITION = 12000


# ---------------------------------------------------------------------------
# The old formulas with decimal metres and rounding, as they were used when
# the image archive was planned. They are the reference: grid.py must give the
# same tiles, otherwise new tiles would not fit the existing archive.
# ---------------------------------------------------------------------------
def old_chip_corner_m(i):
    """Old: lower-left corner of chip column i in decimal metres."""
    return round(i * 614.4, 1)


def old_tile_indexes_under_chip_index(i):
    """Old: tile columns under chip column i (same formula for rows)."""
    x0 = old_chip_corner_m(i)
    return list(range(math.floor(x0 / 400), math.ceil((x0 + 819.2) / 400)))


def old_tiles_under_chip(i, j):
    """Old: all tiles (a, b) under the chip in column i and row j."""
    tiles = []
    for a in old_tile_indexes_under_chip_index(i):
        for b in old_tile_indexes_under_chip_index(j):
            tiles.append((a, b))
    return tiles


class TestConstants(unittest.TestCase):
    """The grid sizes must never change: the archive depends on them."""

    def test_sizes_are_those_of_the_archive(self):
        """Coordinate system, tile and chip sizes have the agreed values."""
        self.assertEqual(grid.EPSG, 25832)
        self.assertEqual(grid.TILE_SIDE_M, 400)
        self.assertEqual(grid.TILE_SIDE_PX, 2000)
        self.assertEqual(grid.CHIP_SIDE_PX, 4096)
        self.assertEqual(grid.CHIP_STEP_PX, 3072)
        self.assertEqual(grid.PIXELS_PER_METRE, 5)

    def test_metres_and_pixels_fit_together(self):
        """0.2 m per pixel, 5 pixels per metre and 400 m = 2000 pixels agree."""
        self.assertEqual(grid.PIXEL_SIZE_M * grid.PIXELS_PER_METRE, 1.0)
        self.assertEqual(grid.TILE_SIDE_M * grid.PIXELS_PER_METRE, grid.TILE_SIDE_PX)


class TestTileId(unittest.TestCase):
    """tile_id: the name of a tile."""

    def test_known_names(self):
        """Names for invented positions, written out by hand."""
        self.assertEqual(grid.tile_id(0, 0), "f01_E0000000_N0000000")
        self.assertEqual(grid.tile_id(3, 7), "f01_E0001200_N0002800")

    def test_seven_digits(self):
        """Large numbers fill all seven digits."""
        self.assertEqual(grid.tile_id(24999, 24999), "f01_E9999600_N9999600")

    def test_negative_position_stops(self):
        """A negative column or row stops with an error instead of giving a name."""
        with self.assertRaises(ValueError):
            grid.tile_id(-1, 5)
        with self.assertRaises(ValueError):
            grid.tile_id(5, -1)

    def test_name_is_lower_left_corner(self):
        """The two numbers in the name are the lower-left corner of the tile."""
        for a in range(0, 50):
            for b in range(0, 50):
                minx, miny, maxx, maxy = grid.tile_bounds(a, b)
                self.assertEqual(grid.tile_id(a, b), "f01_E%07d_N%07d" % (minx, miny))


class TestTileBounds(unittest.TestCase):
    """tile_bounds: the rectangle of a tile."""

    def test_known_bounds(self):
        """Rectangles for invented positions, written out by hand."""
        self.assertEqual(grid.tile_bounds(0, 0), (0, 0, 400, 400))
        self.assertEqual(grid.tile_bounds(3, 7), (1200, 2800, 1600, 3200))

    def test_neighbours_share_an_edge(self):
        """Every tile is 400 m wide and high and ends where the next one starts."""
        for a in range(0, 50):
            for b in range(0, 50):
                minx, miny, maxx, maxy = grid.tile_bounds(a, b)
                self.assertEqual(maxx - minx, 400)
                self.assertEqual(maxy - miny, 400)
                self.assertEqual(grid.tile_bounds(a + 1, b)[0], maxx)
                self.assertEqual(grid.tile_bounds(a, b + 1)[1], maxy)


class TestChipBounds(unittest.TestCase):
    """chip_bounds: the rectangle of a chip."""

    def test_known_bounds(self):
        """Rectangles for invented positions, written out by hand."""
        self.assertEqual(grid.chip_bounds(0, 0), (0.0, 0.0, 819.2, 819.2))
        self.assertEqual(grid.chip_bounds(1, 2), (614.4, 1228.8, 1433.6, 2048.0))

    def test_same_edges_as_old_decimal_formula(self):
        """For every position the edges equal the old decimal formula."""
        for i in range(0, LAST_POSITION + 1):
            left = old_chip_corner_m(i)
            right = round(i * 614.4 + 819.2, 1)
            minx, miny, maxx, maxy = grid.chip_bounds(i, 0)
            self.assertEqual((minx, maxx), (left, right), f"chip column {i}")
            minx, miny, maxx, maxy = grid.chip_bounds(0, i)
            self.assertEqual((miny, maxy), (left, right), f"chip row {i}")


class TestTilesUnderChip(unittest.TestCase):
    """tile_indexes_under_chip_index and tiles_under_chip: which tiles a chip needs."""

    def test_one_chip_by_hand(self):
        """Chip (0, 5) covers 0-819.2 m east and 3072-3891.2 m north: 9 tiles."""
        by_hand = [(0, 7), (0, 8), (0, 9), (1, 7), (1, 8), (1, 9), (2, 7), (2, 8), (2, 9)]
        self.assertEqual(grid.tiles_under_chip(0, 5), by_hand)

    def test_same_as_old_formula_on_one_axis(self):
        """Old formula = new formula for every chip position (the archive stays valid)."""
        for i in range(0, LAST_POSITION + 1):
            self.assertEqual(grid.tile_indexes_under_chip_index(i),
                             old_tile_indexes_under_chip_index(i), f"chip position {i}")

    def test_same_as_old_formula_for_whole_chips(self):
        """Same tiles in the same order as the old formula, columns and rows not swapped."""
        for i in range(0, LAST_POSITION + 1):
            # Two lines across the square of all positions, so that every
            # column meets a different row.
            j = LAST_POSITION - i
            self.assertEqual(grid.tiles_under_chip(i, i), old_tiles_under_chip(i, i), f"chip ({i}, {i})")
            self.assertEqual(grid.tiles_under_chip(i, j), old_tiles_under_chip(i, j), f"chip ({i}, {j})")

    def test_same_as_slow_way(self):
        """A tile lies under a chip if the two share more than an edge."""
        for i in range(0, LAST_POSITION + 1):
            new = grid.tile_indexes_under_chip_index(i)
            left_px = i * 3072
            right_px = left_px + 4096
            slow = []
            for a in range(new[0] - 2, new[-1] + 3):
                if a * 2000 < right_px and (a + 1) * 2000 > left_px:
                    slow.append(a)
            self.assertEqual(new, slow, f"chip position {i}")

    def test_three_or_four_tiles_per_direction(self):
        """A chip is a bit wider than two tiles, so it needs 3 or 4 per direction."""
        for i in range(0, LAST_POSITION + 1):
            self.assertIn(len(grid.tile_indexes_under_chip_index(i)), (3, 4), f"chip position {i}")

    def test_193_edge_positions(self):
        """The hard cases exist in the tested range: a chip edge exactly on a tile edge."""
        left_on_edge = 0
        right_on_edge = 0
        for i in range(0, LAST_POSITION + 1):
            if (i * 3072) % 2000 == 0:
                left_on_edge += 1
            if (i * 3072 + 4096) % 2000 == 0:
                right_on_edge += 1
        self.assertEqual((left_on_edge, right_on_edge), (97, 96))


class TestChipsNearBox(unittest.TestCase):
    """chip_indexes_near_interval and chips_near_box: which chips could touch a rectangle."""

    def test_stretches_by_hand(self):
        """Two invented stretches, worked out by hand."""
        self.assertEqual(grid.chip_indexes_near_interval(10000.0, 10010.0), [15, 16])
        self.assertEqual(grid.chip_indexes_near_interval(20000.0, 20010.0), [32])

    def test_touching_an_edge_counts(self):
        """A stretch that only shares an edge with a chip includes that chip."""
        # chip 0 ends at 819.2 m, chip 1 starts at 614.4 m
        self.assertEqual(grid.chip_indexes_near_interval(819.2, 900.0), [0, 1])
        self.assertEqual(grid.chip_indexes_near_interval(500.0, 614.4), [0, 1])

    def test_stretch_ending_before_start_stops(self):
        """A stretch whose end lies before its start stops with an error."""
        with self.assertRaises(ValueError):
            grid.chip_indexes_near_interval(10.0, 5.0)

    def test_same_as_slow_way(self):
        """Many stretches in whole metres: same answer as trying every chip."""
        for low_m in range(0, 4000):
            for length_m in (0, 1, 100, 819, 2000):
                high_m = low_m + length_m
                slow = []
                for i in range(-5, 40):
                    if i * 3072 <= high_m * 5 and i * 3072 + 4096 >= low_m * 5:
                        slow.append(i)
                self.assertEqual(grid.chip_indexes_near_interval(low_m, high_m), slow,
                                 f"stretch {low_m}-{high_m} m")

    def test_one_box_by_hand(self):
        """A small invented box lies in two chips next to each other."""
        self.assertEqual(grid.chips_near_box(10000.0, 20000.0, 10010.0, 20010.0), [(15, 32), (16, 32)])

    def test_chip_is_found_near_its_tiles(self):
        """If a tile lies under a chip, that chip is found near the tile's rectangle."""
        for i in range(0, 40):
            for j in range(0, 40):
                for a, b in grid.tiles_under_chip(i, j):
                    minx, miny, maxx, maxy = grid.tile_bounds(a, b)
                    self.assertIn((i, j), grid.chips_near_box(minx, miny, maxx, maxy),
                                  f"chip ({i}, {j}), tile ({a}, {b})")


if __name__ == "__main__":
    unittest.main()
