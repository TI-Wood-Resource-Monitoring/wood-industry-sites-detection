"""The agreements for the exchangeable parts of the program.

A protocol is a written agreement. It lists what a part must offer: functions
with their inputs and outputs, and nothing else. The rest of the program uses
only the agreement and does not know which version of the part it works with.
A new version is written next to the old one; the code that uses it stays
untouched.

When the program runs, a protocol does nothing. It is a description that
readers, tests and checking tools can rely on.

All agreements are in this one file, so that the boundaries of the program can
be seen in one place. A part that exists only once (the grid, the table of
states) has no agreement here.

How a class fits an agreement: it has the listed functions with the listed
inputs and outputs. It does not have to mention the agreement.
"""

from typing import Protocol, runtime_checkable


# "runtime_checkable" allows the question  isinstance(thing, PolygonSource)
# while the program runs. It only looks whether the listed functions are
# there, not whether they do the right thing.
@runtime_checkable
class PolygonSource(Protocol):
    """Anything that delivers the polygons that count.

    First version: PolygonFile in core/polygons.py (the hand-drawn polygons).
    Possible other versions: official land-use layers, other polygon data.
    """

    def read_polygons(self) -> list[dict]:
        """Deliver all polygons that count.

        Input:  nothing. A source knows by itself where its polygons are.
        Output: list of dictionaries, one per polygon, each with
                  new_id  - name of the polygon (text, not empty)
                  site_id - the site it belongs to (text, not empty)
                  land    - federal state, spelled as in core/states.py
                  shape   - the outline as a GDAL geometry in EPSG:25832

        A source checks its own data. What it hands over can be used without
        further checks; if it cannot deliver that, it stops with a message.
        """
        # The three dots are the whole body: an agreement only describes.
        ...
