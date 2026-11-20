# Unit tests for src/woodsites/acquisition/coordinator.py.
#
# Run all tests from the repository folder:
#     python -m pytest                    (OSGeo4W Shell on Windows)
# The last line must say "passed" and nothing "failed".
#
# An agreement does nothing by itself, so these tests show what it is for:
# the real polygon file and an invented stand-in both fit it, and code that
# is written against the agreement works with either.

import unittest

from woodsites.acquisition import polygon_file
from woodsites.acquisition import coordinator


class StandInPolygons:
    """An invented polygon source: no file, the polygons are handed in by the test."""

    def __init__(self, invented_polygons):
        self.invented_polygons = invented_polygons

    def read_polygons(self):
        return self.invented_polygons


class NotASource:
    """Something that does not offer read_polygons."""


def count_polygons(source: coordinator.PolygonSource) -> int:
    """A small function written against the agreement: it works with any polygon source."""
    return len(source.read_polygons())


class TestPolygonSource(unittest.TestCase):
    """PolygonSource: the agreement for everything that delivers polygons."""

    def test_polygon_file_fits(self):
        """The class for the hand-drawn polygons offers what the agreement lists."""
        source = polygon_file.PolygonFile("any_file.gpkg")      # the file is not opened here
        self.assertIsInstance(source, coordinator.PolygonSource)

    def test_stand_in_fits_and_can_be_used(self):
        """An invented source fits too, and code written against the agreement uses it."""
        source = StandInPolygons([{"new_id": "S9001_L01"}, {"new_id": "S9001_L02"}])
        self.assertIsInstance(source, coordinator.PolygonSource)
        self.assertEqual(count_polygons(source), 2)

    def test_something_else_does_not_fit(self):
        """A thing without read_polygons does not fit the agreement."""
        self.assertNotIsInstance(NotASource(), coordinator.PolygonSource)


if __name__ == "__main__":
    unittest.main()
