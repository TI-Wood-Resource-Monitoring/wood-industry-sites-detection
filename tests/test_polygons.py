# Unit tests for src/woodsites/core/polygons.py.
#
# Run all unit tests from the repository folder:
#     set PYTHONPATH=%CD%\src                      (OSGeo4W Shell on Windows)
#     python -m unittest discover -s tests -v
# The last line must be:  OK
#
# These tests never open a real polygon file. They build small invented ones
# in a temporary folder, which is removed again after every test. All ids and
# positions are invented.

import os
import tempfile
import unittest

from osgeo import ogr, osr

from woodsites.core import polygons

osr.UseExceptions()

# An invented square of 100 m x 100 m, far away from any real place.
SQUARE = "POLYGON((1000 2000,1100 2000,1100 2100,1000 2100,1000 2000))"

ALL_FIELDS = ["new_id", "site_id", "land", "triage", "herkunft"]

# Eight invented rows. A field that is not named in a row stays empty.
GOOD_ROWS = [
    {"new_id": "S9001_L01", "site_id": "S9001", "land": "Niedersachsen", "triage": "A", "wkt": SQUARE},
    {"new_id": "S9001_L02", "site_id": "S9001", "land": "Niedersachsen", "triage": "B", "herkunft": "", "wkt": SQUARE},
    {"new_id": "S9002_L01", "site_id": "S9002", "land": "Hessen", "triage": "C", "wkt": SQUARE},
    {"new_id": "S9002_N01", "site_id": "S9002", "land": "Hessen", "herkunft": "dop20_neu", "wkt": SQUARE},
    {"new_id": "S9002_N02", "site_id": "S9002", "land": "Hessen", "triage": "C", "herkunft": "dop20_neu", "wkt": SQUARE},
    # not wanted, so it is skipped although everything else about it is wrong:
    {"new_id": "", "site_id": "", "land": "Nowhere", "triage": "C"},
    # spaces typed by accident:
    {"new_id": " S9003_L01 ", "site_id": " S9003", "land": "Bayern ", "triage": "A ", "wkt": SQUARE},
    # a small letter is not A:
    {"new_id": "S9003_L02", "site_id": "S9003", "land": "Bayern", "triage": "a", "wkt": SQUARE},
]

# Three wanted polygons with a problem each, and one that is fine.
FAULTY_ROWS = [
    {"new_id": "S9001_L01", "site_id": "", "land": "Niedersachsen", "triage": "A", "wkt": SQUARE},
    {"new_id": "", "site_id": "S9001", "land": "Musterland", "triage": "B", "wkt": SQUARE},
    {"new_id": "S9001_L03", "site_id": "S9001", "land": "Niedersachsen", "triage": "A"},
    {"new_id": "S9001_L04", "site_id": "S9001", "land": "Niedersachsen", "triage": "A", "wkt": SQUARE},
]

TWO_ROWS = [
    {"new_id": "S9001_L01", "site_id": "S9001", "land": "Niedersachsen", "triage": "A", "wkt": SQUARE},
    {"new_id": "S9001_L02", "site_id": "S9001", "land": "Niedersachsen", "triage": "C", "wkt": SQUARE},
]


def make_polygon_file(path, layer_name, epsg, field_names, rows):
    """Write a small GeoPackage with one polygon layer, for a test."""
    system = osr.SpatialReference()
    system.ImportFromEPSG(epsg)
    dataset = ogr.GetDriverByName("GPKG").CreateDataSource(path)
    layer = dataset.CreateLayer(layer_name, system, ogr.wkbPolygon)
    for name in field_names:
        layer.CreateField(ogr.FieldDefn(name, ogr.OFTString))
    for row in rows:
        feature = ogr.Feature(layer.GetLayerDefn())
        for name in field_names:
            if row.get(name) is not None:
                feature.SetField(name, row[name])
        if row.get("wkt") is not None:
            feature.SetGeometry(ogr.CreateGeometryFromWkt(row["wkt"]))
        layer.CreateFeature(feature)
        feature = None
    # Let go of the layer and the file, so that GDAL writes everything and closes it.
    layer = None
    dataset = None


class TestPolygonIsWanted(unittest.TestCase):
    """polygon_is_wanted: the rule which polygons count."""

    def test_triage_a_and_b(self):
        """Triage A and triage B are wanted."""
        self.assertTrue(polygons.polygon_is_wanted("A", ""))
        self.assertTrue(polygons.polygon_is_wanted("B", ""))

    def test_other_triage_values(self):
        """Triage C, an empty triage and a small letter are not wanted."""
        self.assertFalse(polygons.polygon_is_wanted("C", ""))
        self.assertFalse(polygons.polygon_is_wanted("", ""))
        self.assertFalse(polygons.polygon_is_wanted("a", ""))

    def test_herkunft_dop20_neu(self):
        """A polygon drawn new on the images is wanted, whatever its triage."""
        self.assertTrue(polygons.polygon_is_wanted("", "dop20_neu"))
        self.assertTrue(polygons.polygon_is_wanted("C", "dop20_neu"))


class TestCleanText(unittest.TestCase):
    """clean_text: a field value as plain text."""

    def test_clean_text(self):
        """An empty field becomes empty text; spaces at both ends are removed."""
        self.assertEqual(polygons.clean_text(None), "")
        self.assertEqual(polygons.clean_text(" x "), "x")
        self.assertEqual(polygons.clean_text(5), "5")


class TestPolygonProblems(unittest.TestCase):
    """polygon_problems: what is wrong with one wanted polygon."""

    def test_good_polygon_has_no_problems(self):
        """A complete polygon gives an empty list."""
        polygon = {"new_id": "S9001_L01", "site_id": "S9001", "land": "Hessen",
                   "shape": ogr.CreateGeometryFromWkt(SQUARE)}
        self.assertEqual(polygons.polygon_problems(polygon), [])

    def test_each_problem_is_named(self):
        """Empty id, empty site, unknown state and missing shape are all named."""
        polygon = {"new_id": "", "site_id": "", "land": "Musterland", "shape": None}
        problems = polygons.polygon_problems(polygon)
        self.assertEqual(len(problems), 4)
        self.assertIn("new_id is empty", problems)
        self.assertIn("site_id is empty", problems)
        self.assertIn("no shape", problems)


class TestReadPolygons(unittest.TestCase):
    """read_polygons and open_polygon_layer: reading a polygon file."""

    def setUp(self):
        """Runs before every test: a temporary folder for the invented files."""
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)

    def tearDown(self):
        """Runs after every test: remove the temporary folder."""
        self.folder.cleanup()

    def path(self, file_name):
        """Full path of a file in the temporary folder."""
        return os.path.join(self.folder.name, file_name)

    def stop_message(self, gpkg_path):
        """Call read_polygons, expect it to stop, and give back its message."""
        with self.assertRaises(SystemExit) as caught:
            polygons.read_polygons(gpkg_path)
        return str(caught.exception)

    def test_only_wanted_polygons_come_back(self):
        """Of 8 rows, the 5 wanted ones come back, in the order of the file."""
        make_polygon_file(self.path("good.gpkg"), "dop20_polygons", 25832, ALL_FIELDS, GOOD_ROWS)
        ids = []
        for polygon in polygons.read_polygons(self.path("good.gpkg")):
            ids.append(polygon["new_id"])
        self.assertEqual(ids, ["S9001_L01", "S9001_L02", "S9002_N01", "S9002_N02", "S9003_L01"])

    def test_spaces_are_removed(self):
        """Spaces typed by accident around a value do not change the result."""
        make_polygon_file(self.path("good.gpkg"), "dop20_polygons", 25832, ALL_FIELDS, GOOD_ROWS)
        last = polygons.read_polygons(self.path("good.gpkg"))[-1]
        self.assertEqual(last["new_id"], "S9003_L01")
        self.assertEqual(last["site_id"], "S9003")
        self.assertEqual(last["land"], "Bayern")

    def test_shape_comes_back(self):
        """The shape has the size and the place it was written with."""
        make_polygon_file(self.path("good.gpkg"), "dop20_polygons", 25832, ALL_FIELDS, GOOD_ROWS)
        shape = polygons.read_polygons(self.path("good.gpkg"))[0]["shape"]
        self.assertEqual(shape.GetArea(), 10000.0)
        # GDAL gives the surrounding rectangle as (minx, maxx, miny, maxy).
        self.assertEqual(shape.GetEnvelope(), (1000.0, 1100.0, 2000.0, 2100.0))

    def test_file_without_herkunft(self):
        """An older file without the field herkunft is still read."""
        make_polygon_file(self.path("old.gpkg"), "dop20_polygons", 25832,
                          ["new_id", "site_id", "land", "triage"], TWO_ROWS)
        self.assertEqual(len(polygons.read_polygons(self.path("old.gpkg"))), 1)

    def test_faulty_polygons_are_all_named(self):
        """Three faulty wanted polygons stop the run with ONE message naming all three."""
        make_polygon_file(self.path("faulty.gpkg"), "dop20_polygons", 25832, ALL_FIELDS, FAULTY_ROWS)
        message = self.stop_message(self.path("faulty.gpkg"))
        self.assertIn("site_id is empty", message)
        self.assertIn("new_id is empty", message)
        self.assertIn("Musterland", message)
        self.assertIn("no shape", message)
        self.assertEqual(message.count("\n  row "), 3)

    def test_missing_file_stops(self):
        """A file that does not exist stops with a message."""
        self.assertIn("polygon file not found", self.stop_message(self.path("nothing.gpkg")))

    def test_wrong_layer_name_stops(self):
        """A file without the layer dop20_polygons stops with a message."""
        make_polygon_file(self.path("other.gpkg"), "something_else", 25832, ALL_FIELDS, TWO_ROWS)
        self.assertIn("layer dop20_polygons not found", self.stop_message(self.path("other.gpkg")))

    def test_wrong_coordinate_system_stops(self):
        """A layer in another coordinate system stops with a message."""
        make_polygon_file(self.path("utm33.gpkg"), "dop20_polygons", 25833, ALL_FIELDS, TWO_ROWS)
        self.assertIn("must be in EPSG:25832", self.stop_message(self.path("utm33.gpkg")))

    def test_missing_field_stops(self):
        """A layer without the field triage stops with a message."""
        make_polygon_file(self.path("short.gpkg"), "dop20_polygons", 25832,
                          ["new_id", "site_id", "land"], TWO_ROWS)
        self.assertIn("has no field triage", self.stop_message(self.path("short.gpkg")))


if __name__ == "__main__":
    unittest.main()
