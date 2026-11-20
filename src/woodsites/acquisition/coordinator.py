"""Coordinator of Module 1 (acquisition) and the protocols it uses.

The coordinator controls the order of the steps: read polygons, plan tiles,
fetch, georeference, save. It only knows the protocols below, never the
concrete classes behind them (those are chosen by the factory).

A protocol is a written agreement. It lists what a part must offer: methods
with their inputs and outputs, and nothing else. The coordinator uses only the
agreement and does not know which version of the part it works with. A new
version is written next to the old one; the coordinator stays untouched.

When the program runs, a protocol does nothing. It is a description that
readers, tests and the type checker (mypy) can rely on.

The protocols live here, at the consumer, because only the coordinator uses
them (see docs/oop-roles.md, section 2). A part that exists only once (the
grid, the table of states) has no protocol.

How a class fits a protocol: it has the listed methods with the listed inputs
and outputs. It does not have to mention the protocol.

State of the build (step R1): only PolygonSource exists. The coordinator
class, ImageSource, ImageStore and RunReport follow in step R4.
"""

from typing import Protocol, runtime_checkable

from woodsites.acquisition.domain import Polygon


# "runtime_checkable" allows the question  isinstance(thing, PolygonSource)
# while the program runs. It only looks whether the listed functions are
# there, not whether they do the right thing.
@runtime_checkable
class PolygonSource(Protocol):
    """Anything that delivers the polygons that count.

    First version: PolygonFile in acquisition/polygon_file.py (the hand-drawn polygons).
    Possible other versions: official land-use layers, other polygon data.
    """

    def read_polygons(self) -> list[Polygon]:
        """Deliver all polygons that count.

        Input:  nothing. A source knows by itself where its polygons are.
        Output: list of Polygon (see domain.py: new_id, land, shape, and
                site_id where the source has one).

        A source checks its own data. What it hands over can be used without
        further checks; if it cannot deliver that, it stops with a message.
        """
        # The three dots are the whole body: an agreement only describes.
        ...
