# Tests that need the project's own data on this computer.
#
# Run all tests from the repository folder:
#     python -m pytest                    (OSGeo4W Shell on Windows)
# The last line must say "passed" and nothing "failed".
#
# Unlike the other test files, this one reads real files: the settings file
# and the polygon file it points to. Both are private and not part of the
# repository. On a computer without them every test here is SKIPPED (shown as
# "skipped" in the output), so the one command above works everywhere.
#
# Everything is opened read-only. This file contains no path and no data: the
# paths come from the settings file.

import os
import unittest

from woodsites.acquisition import config
from woodsites.acquisition import polygon_file
from woodsites.acquisition import states

# The paths the image fetch needs in the section [paths] of the settings file.
FETCH_PATHS = ["polygons_gpkg", "archive", "archive_scratch"]


class TestLocalData(unittest.TestCase):
    """The settings file and the polygon file of this computer are usable."""

    def setUp(self):
        """Runs before every test: skip the test if there is no settings file."""
        self.settings_file = config.config_file_path()
        if not os.path.isfile(self.settings_file):
            self.skipTest("no settings file on this computer")

    def read_settings(self, needed_paths):
        """Read the settings file; a stop becomes a failed test that shows the message."""
        try:
            return config.read_config(self.settings_file, needed_paths)
        except SystemExit as stop:
            self.fail(str(stop))

    def test_settings_have_the_paths_of_the_image_fetch(self):
        """The settings file names the polygon file, the archive and the scratch archive."""
        settings = self.read_settings(FETCH_PATHS)
        for name in FETCH_PATHS:
            self.assertNotEqual(settings["paths"][name], "", name)

    def test_polygon_file_is_read_without_stopping(self):
        """Every wanted polygon in the real file has an ID, a site, a known state and a shape."""
        gpkg_path = self.read_settings(["polygons_gpkg"])["paths"]["polygons_gpkg"]
        if not os.path.isfile(gpkg_path):
            self.skipTest("the polygon file is not on this computer")
        try:
            wanted = polygon_file.read_polygons(gpkg_path)
        except SystemExit as stop:
            # The message lists every faulty polygon, so it says what to correct in QGIS.
            self.fail(str(stop))
        self.assertGreater(len(wanted), 0, "the polygon file has no wanted polygon")
        for polygon in wanted:
            self.assertIn(polygon.land, states.STATES)


if __name__ == "__main__":
    unittest.main()
