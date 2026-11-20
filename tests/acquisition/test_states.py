# Unit tests for src/woodsites/acquisition/states.py.
#
# Run all unit tests from the repository folder:
#     python -m pytest                    (OSGeo4W Shell on Windows)
# The last line must say "passed" and nothing "failed".

import unittest

from woodsites.acquisition import states


class TestStates(unittest.TestCase):
    """STATES and state_code: the twelve federal states."""

    def test_twelve_states(self):
        """The table has twelve states."""
        self.assertEqual(len(states.STATES), 12)

    def test_codes_are_different(self):
        """No two states share a code, so no two states share an archive folder."""
        codes = []
        for land in states.STATES:
            codes.append(states.STATES[land]["code"])
        self.assertEqual(len(set(codes)), 12)

    def test_codes_are_two_capital_letters(self):
        """Every code has the form of an archive folder name: two capital letters."""
        for land in states.STATES:
            code = states.STATES[land]["code"]
            self.assertEqual(len(code), 2, land)
            self.assertTrue(code.isalpha() and code.isupper(), land)

    def test_native_epsg_values(self):
        """Three states store their images in EPSG:25833, the others in EPSG:25832."""
        in_25833 = []
        for land in states.STATES:
            native = states.STATES[land]["native_epsg"]
            self.assertIn(native, (25832, 25833), land)
            if native == 25833:
                in_25833.append(land)
        self.assertEqual(sorted(in_25833), ["Brandenburg", "Mecklenburg-Vorpommern", "Sachsen"])

    def test_state_code(self):
        """A known name gives its code."""
        self.assertEqual(states.state_code("Niedersachsen"), "NI")
        self.assertEqual(states.state_code("Baden-Württemberg"), "BW")

    def test_unknown_state_stops(self):
        """An unknown name stops with an error that lists the known names."""
        with self.assertRaises(ValueError) as caught:
            states.state_code("Musterland")
        message = str(caught.exception)
        self.assertIn("Musterland", message)
        self.assertIn("Niedersachsen", message)


if __name__ == "__main__":
    unittest.main()
