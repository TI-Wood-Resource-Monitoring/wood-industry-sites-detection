"""Grid maths for the stored image tiles (f01) and the planning chips (g01).

Both grids lie in the coordinate system EPSG:25832 and start at the point 0/0.

  Tile (f01): one stored image of 400 m x 400 m = 2000 x 2000 pixels. Tiles do
              not overlap. A tile is named by its column a and its row b,
              counted in 400 m steps from 0/0.
  Chip (g01): a larger square of 819.2 m. A new chip starts every 614.4 m, so
              neighbouring chips overlap. A chip is named by its column i and
              its row j, counted in 614.4 m steps from 0/0.

All maths in this file counts in whole archive pixels of 0.2 m. A tile is 2000
pixels wide, a chip 4096, and a new chip starts every 3072 pixels. Whole
numbers cannot be off by a rounding error; decimal metres can (614.4 cannot be
stored exactly in a computer). Metres only appear where a position enters or
leaves this file.

Pure arithmetic: this file reads no file and asks no server.

How to read the first line of a function: "a: int" says that a is a whole
number, "-> str" says that text comes back. These notes are called type hints.
Python itself does not enforce them; they are for readers and for checking tools.
"""

import math

# ---------------------------------------------------------------------------
# Grid sizes. Changing any of them would make the existing archive invalid,
# because tile names and tile positions are worked out from them. That is why
# they are fixed here and not in the config file.
# ---------------------------------------------------------------------------
EPSG = 25832             # number of the coordinate system both grids are defined in
PIXEL_SIZE_M = 0.2       # one archive pixel covers 0.2 m x 0.2 m on the ground
PIXELS_PER_METRE = 5     # the same fact as a whole number: 5 pixels = 1 m
TILE_SIDE_M = 400        # side of a tile in metres
TILE_SIDE_PX = 2000      # side of a tile in archive pixels (400 m x 5)
CHIP_SIDE_PX = 4096      # side of a chip in archive pixels (819.2 m x 5)
CHIP_STEP_PX = 3072      # from one chip to the next, in archive pixels (614.4 m x 5)


def tile_id(a: int, b: int) -> str:
    """Name of the tile in column a and row b.

    Input:  a, b - whole numbers, not negative.
    Output: text like "f01_E0001200_N0002800" for a = 3, b = 7.

    The two numbers in the name are the lower-left corner of the tile in whole
    metres (east, then north), each written with 7 digits.
    """
    # A negative number would put a minus sign into the name. Such a name does
    # not fit the pattern of the archive, so we stop instead of writing it.
    if a < 0 or b < 0:
        raise ValueError(f"tile column and row must not be negative: a={a}, b={b}")
    easting = a * TILE_SIDE_M
    northing = b * TILE_SIDE_M
    # ":07d" means: a whole number, 7 digits wide, filled with zeros on the left.
    return f"f01_E{easting:07d}_N{northing:07d}"


def tile_bounds(a: int, b: int) -> tuple[int, int, int, int]:
    """Rectangle that the tile in column a and row b covers.

    Input:  a, b - whole numbers.
    Output: (minx, miny, maxx, maxy) in whole metres.
    """
    minx = a * TILE_SIDE_M
    miny = b * TILE_SIDE_M
    return (minx, miny, minx + TILE_SIDE_M, miny + TILE_SIDE_M)


def chip_bounds(i: int, j: int) -> tuple[float, float, float, float]:
    """Rectangle that the chip in column i and row j covers.

    Input:  i, j - whole numbers.
    Output: (minx, miny, maxx, maxy) in metres, e.g. (614.4, 0.0, 1433.6, 819.2)
            for i = 1, j = 0.
    """
    # First work out the four edges in whole pixels ...
    left_px = i * CHIP_STEP_PX
    bottom_px = j * CHIP_STEP_PX
    right_px = left_px + CHIP_SIDE_PX
    top_px = bottom_px + CHIP_SIDE_PX
    # ... and only then turn them into metres. One division of a whole number
    # at the very end gives the closest decimal number the computer can store.
    return (left_px / PIXELS_PER_METRE, bottom_px / PIXELS_PER_METRE,
            right_px / PIXELS_PER_METRE, top_px / PIXELS_PER_METRE)


def tile_indexes_under_chip_index(i: int) -> list[int]:
    """Tile columns that lie under chip column i.

    The grid is the same in both directions, so the same function also gives
    the tile rows under a chip row.

    Input:  i - a chip column (or chip row), whole number.
    Output: list of 3 or 4 tile columns (or rows), smallest first.
    """
    first_px = i * CHIP_STEP_PX
    # The chip covers the pixels first_px ... first_px + 4095. The "- 1" picks
    # the last pixel that still belongs to the chip. Without it, a chip that
    # ends exactly on a tile edge would also get the next tile, which it only
    # touches and does not need.
    last_px = first_px + CHIP_SIDE_PX - 1
    # "//" divides and rounds down to a whole number: pixel 4095 lies in tile 2.
    first_tile = first_px // TILE_SIDE_PX
    last_tile = last_px // TILE_SIDE_PX
    return list(range(first_tile, last_tile + 1))


def tiles_under_chip(i: int, j: int) -> list[tuple[int, int]]:
    """All tiles that lie under the chip in column i and row j.

    Input:  i, j - whole numbers.
    Output: list of (a, b), sorted from left to right and, within one column,
            from bottom to top. Between 9 and 16 tiles.
    """
    tiles = []
    for a in tile_indexes_under_chip_index(i):
        for b in tile_indexes_under_chip_index(j):
            tiles.append((a, b))
    return tiles


def chip_indexes_near_interval(low_m: float, high_m: float) -> list[int]:
    """Chip columns whose square touches a stretch along the east axis.

    The grid is the same in both directions, so the same function also gives
    the chip rows for a stretch along the north axis.

    Input:  low_m, high_m - start and end of the stretch in metres.
    Output: list of chip columns (or rows), smallest first. A chip that only
            shares an edge with the stretch is included.
    """
    if low_m > high_m:
        raise ValueError(f"the stretch ends before it starts: {low_m} > {high_m}")
    # Widen the stretch to whole pixels: the start is rounded down, the end is
    # rounded up. Widening can only add a chip, never lose one. The exact test
    # against the real shape of a polygon happens later, in another file.
    low_px = math.floor(low_m * PIXELS_PER_METRE)
    high_px = math.ceil(high_m * PIXELS_PER_METRE)
    # No chip before first_candidate can reach the stretch and no chip after
    # last_candidate can start inside it. first_candidate itself may be one
    # chip too early, so every candidate is tested below.
    first_candidate = (low_px - CHIP_SIDE_PX) // CHIP_STEP_PX
    last_candidate = high_px // CHIP_STEP_PX
    found = []
    for i in range(first_candidate, last_candidate + 1):
        chip_left_px = i * CHIP_STEP_PX
        chip_right_px = chip_left_px + CHIP_SIDE_PX
        # The chip touches the stretch if it starts before the stretch ends
        # and ends after the stretch starts.
        if chip_left_px <= high_px and chip_right_px >= low_px:
            found.append(i)
    return found


def chips_near_box(minx: float, miny: float, maxx: float, maxy: float) -> list[tuple[int, int]]:
    """All chips whose square touches a rectangle.

    Input:  minx, miny, maxx, maxy - a rectangle in metres.
    Output: list of (i, j), sorted from left to right and, within one column,
            from bottom to top.

    These are the chips that COULD touch a polygon lying inside the rectangle.
    Whether a chip really touches the polygon is decided later with the
    polygon's real shape.
    """
    chips = []
    for i in chip_indexes_near_interval(minx, maxx):
        for j in chip_indexes_near_interval(miny, maxy):
            chips.append((i, j))
    return chips
