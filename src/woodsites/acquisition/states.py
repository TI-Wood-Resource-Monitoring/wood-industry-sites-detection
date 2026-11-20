"""The twelve federal states whose images are in the archive.

The state name is the key that joins everything: the field `land` of the
polygons, the column `land` of the manifest and the server table all use
exactly these spellings.
"""

from typing import TypedDict


class StateInfo(TypedDict):
    """What is known about one state. A TypedDict is a normal dictionary whose
    keys and value types are fixed, so that the type checker can check them."""

    code: str
    native_epsg: int


# Per state:
#   code        - two letters. It is the name of the state's folder in the
#                 archive (for example NI/f01_....tif).
#   native_epsg - the coordinate system in which the state stores its images.
#                 Every tile is requested in EPSG:25832. Three states store
#                 their images in EPSG:25833, so their server converts each
#                 image for us, which turns it slightly. The manifest records
#                 this per tile in the column `native_epsg`.
STATES: dict[str, StateInfo] = {
    "Baden-Württemberg":      {"code": "BW", "native_epsg": 25832},
    "Bayern":                 {"code": "BY", "native_epsg": 25832},
    "Brandenburg":            {"code": "BB", "native_epsg": 25833},
    "Hessen":                 {"code": "HE", "native_epsg": 25832},
    "Mecklenburg-Vorpommern": {"code": "MV", "native_epsg": 25833},
    "Niedersachsen":          {"code": "NI", "native_epsg": 25832},
    "Nordrhein-Westfalen":    {"code": "NW", "native_epsg": 25832},
    "Rheinland-Pfalz":        {"code": "RP", "native_epsg": 25832},
    "Saarland":               {"code": "SL", "native_epsg": 25832},
    "Sachsen":                {"code": "SN", "native_epsg": 25833},
    "Sachsen-Anhalt":         {"code": "ST", "native_epsg": 25832},
    "Thüringen":              {"code": "TH", "native_epsg": 25832},
}


def state_code(land: str) -> str:
    """Two-letter code of a federal state.

    Input:  land - the state name, spelled exactly as in STATES.
    Output: the code, for example "NI" for "Niedersachsen".

    Stops with an error if the name is not one of the twelve. A misspelled
    name must never turn into a new folder in the archive.
    """
    if land not in STATES:
        known = ", ".join(sorted(STATES))
        raise ValueError(f"unknown state: '{land}'. Known states: {known}")
    return STATES[land]["code"]
