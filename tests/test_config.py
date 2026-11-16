# Unit tests for src/woodsites/core/config.py.
#
# Run all unit tests from the repository folder:
#     set PYTHONPATH=%CD%\src                      (OSGeo4W Shell on Windows)
#     python -m unittest discover -s tests -v
# The last line must be:  OK
#
# These tests never read a real settings file. They write a small invented one
# into a temporary folder, which is removed again after every test.

import os
import tempfile
import unittest

from woodsites.core import config

# A small settings file, invented for these tests.
SMALL_CONFIG = """
[paths]
polygons_gpkg = 'some\\folder\\polygons.gpkg'
archive       = 'some\\folder\\archive'
not_filled_in = ''

[other]
number = 3
"""


class TestConfigFilePath(unittest.TestCase):
    """config_file_path: which settings file is used."""

    def setUp(self):
        """Runs before every test: remember the variable of the shell and clear it."""
        self.before = os.environ.get("WOODSITES_CONFIG")
        os.environ.pop("WOODSITES_CONFIG", None)

    def tearDown(self):
        """Runs after every test: put the variable back as it was."""
        os.environ.pop("WOODSITES_CONFIG", None)
        if self.before is not None:
            os.environ["WOODSITES_CONFIG"] = self.before

    def test_default_file(self):
        """Without the variable it is configs/config.toml."""
        self.assertEqual(config.config_file_path(), os.path.join("configs", "config.toml"))

    def test_file_from_variable(self):
        """With the variable WOODSITES_CONFIG it is the file named there."""
        os.environ["WOODSITES_CONFIG"] = "elsewhere.toml"
        self.assertEqual(config.config_file_path(), "elsewhere.toml")


class TestReadConfig(unittest.TestCase):
    """read_config: reading the file and stopping with a clear message."""

    def setUp(self):
        """Runs before every test: a temporary folder with the small settings file."""
        self.folder = tempfile.TemporaryDirectory()
        self.good = os.path.join(self.folder.name, "small.toml")
        with open(self.good, "w", encoding="utf-8") as file:
            file.write(SMALL_CONFIG)

    def tearDown(self):
        """Runs after every test: remove the temporary folder."""
        self.folder.cleanup()

    def stop_message(self, path, needed_paths):
        """Call read_config, expect it to stop, and give back its message."""
        with self.assertRaises(SystemExit) as caught:
            config.read_config(path, needed_paths)
        return str(caught.exception)

    def test_reads_paths_and_other_sections(self):
        """A path is read as written (backslashes kept); other sections are read too."""
        result = config.read_config(self.good, ["polygons_gpkg", "archive"])
        self.assertEqual(result["paths"]["archive"], "some\\folder\\archive")
        self.assertEqual(result["other"]["number"], 3)

    def test_no_needed_paths(self):
        """A script that needs no path can still read the file."""
        result = config.read_config(self.good, [])
        self.assertIn("paths", result)

    def test_missing_file_stops(self):
        """A file that does not exist stops with a message that says what to do."""
        nowhere = os.path.join(self.folder.name, "does_not_exist.toml")
        message = self.stop_message(nowhere, ["archive"])
        self.assertIn("settings file not found", message)
        self.assertIn("WOODSITES_CONFIG", message)

    def test_missing_paths_are_all_named(self):
        """Two missing paths are named in one message."""
        message = self.stop_message(self.good, ["archive", "archive_scratch", "holdout_gpkg"])
        self.assertIn("[paths]", message)
        self.assertIn("archive_scratch, holdout_gpkg", message)

    def test_empty_path_counts_as_missing(self):
        """A path that is in the file but empty counts as missing."""
        message = self.stop_message(self.good, ["not_filled_in"])
        self.assertIn("not_filled_in", message)

    def test_writing_mistake_stops(self):
        """A file that is not valid TOML stops with a clear message."""
        broken = os.path.join(self.folder.name, "broken.toml")
        with open(broken, "w", encoding="utf-8") as file:
            file.write("[paths]\narchive = \n")
        message = self.stop_message(broken, ["archive"])
        self.assertIn("not valid TOML", message)


if __name__ == "__main__":
    unittest.main()
