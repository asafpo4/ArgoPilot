"""Cells (spec 3.1): a point becomes a 0.1 degree cell by exact decimal rounding.

The cell is the point rounded to the nearest 0.1 degree, `index = floor(value * 10 + 0.5)`, ties
rounding up, computed on the decimal text of the accepted value and never on a float. The provider is
called at the cell's node (the index divided by ten, with one decimal).
"""

from decimal import ROUND_FLOOR, Decimal, localcontext
from typing import NamedTuple

# Enough digits for the longest accepted text: 32 characters with an exponent of up to +-999 needs about
# 1100 digits, so 2100 is safe. Python's default of 28 digits is not enough: with it the text
# 0.049999999999999999999999999999 (just below the tie) lands in cell 1 instead of cell 0.
PRECISION = 2100
HALF = Decimal("0.5")


class Cell(NamedTuple):
    lat_index: int
    lon_index: int


def _index(value: Decimal) -> int:
    if not isinstance(value, Decimal):
        # A float would bring float noise back into the cell, so it is refused, not converted.
        raise TypeError("a cell is computed from a Decimal, never from a float")
    if not value.is_finite():
        raise ValueError("a cell needs a finite value")
    with localcontext() as context:
        context.prec = PRECISION
        return int((value * 10 + HALF).to_integral_value(rounding=ROUND_FLOOR))


def cell_for(lat: Decimal, lon: Decimal) -> Cell:
    return Cell(_index(lat), _index(lon))


def node_for(cell: Cell) -> tuple[Decimal, Decimal]:
    """The cell's node: latitude and longitude with exactly one decimal, such as 31.3 and 34.8."""
    return Decimal(cell.lat_index).scaleb(-1), Decimal(cell.lon_index).scaleb(-1)
