"""Cells (spec 3.1): the nearest 0.1 degree node, by exact decimal arithmetic on the decimal text."""

from decimal import Decimal

import pytest

from grid import Cell, cell_for, node_for


def d(text: str) -> Decimal:
    return Decimal(text)


def lat_index(text: str) -> int:
    return cell_for(d(text), d("0")).lat_index


def lon_index(text: str) -> int:
    return cell_for(d("0"), d(text)).lon_index


# The tie and the precision.


def test_the_32_character_value_just_below_the_tie_is_index_0() -> None:
    # Python's default Decimal precision (28 digits) puts this value in cell 1. Exact arithmetic: 0.
    below_tie = "0.049999999999999999999999999999"
    assert len(below_tie) == 32
    assert lat_index(below_tie) == 0
    assert lon_index(below_tie) == 0
    assert lat_index("0.05") == 1
    assert lon_index("0.05") == 1


def test_a_tiny_exponent_is_index_0() -> None:
    for text in ("1e-999", "-1e-999", "0e-999"):
        assert lat_index(text) == 0
        assert lon_index(text) == 0


# Values where float arithmetic gives another cell than the decimal text does (found by comparing both).
FLOAT_TRAPS = [
    ("0.04999999999999999999", 0),
    ("0.0499999999999999999999", 0),
    ("-0.050000000000000000000001", -1),
    ("89.949999999999999999999999", 899),
    ("-89.950000000000000000000001", -900),
]
LON_FLOAT_TRAPS = [
    ("179.94999999999999999999999", 1799),
    ("-179.95000000000000000000001", -1800),
]


@pytest.mark.parametrize("text, expected", FLOAT_TRAPS)
def test_latitude_is_computed_from_the_text_not_from_a_float(text: str, expected: int) -> None:
    assert lat_index(text) == expected


@pytest.mark.parametrize("text, expected", FLOAT_TRAPS + LON_FLOAT_TRAPS)
def test_longitude_is_computed_from_the_text_not_from_a_float(text: str, expected: int) -> None:
    assert lon_index(text) == expected


# The rounding rule: nearest node, ties round up.


@pytest.mark.parametrize(
    "text, expected",
    [
        ("31.25", 313),  # a tie rounds up
        ("31.2499999", 312),
        ("31.26", 313),
        ("31.34", 313),
        ("31.35", 314),
        ("0", 0),
        ("0.04", 0),
        ("0.05", 1),
        ("-0.04", 0),
        ("-0.05", 0),  # a tie rounds up, toward positive
        ("-0.051", -1),
        ("-31.25", -312),
        ("-31.26", -313),
    ],
)
def test_rounding_to_the_nearest_node_with_ties_up(text: str, expected: int) -> None:
    assert lat_index(text) == expected
    assert lon_index(text) == expected


@pytest.mark.parametrize(
    "text, expected",
    [("0.3", 3), ("0.7", 7), ("0.30000000000000004", 3), ("1.1", 11), ("0.6", 6), ("1e-05", 0), ("9e0", 90), ("1.8e2", 1800)],
)
def test_values_that_are_awkward_as_floats(text: str, expected: int) -> None:
    assert lat_index(text) == expected
    assert lon_index(text) == expected


def test_a_decimal_sum_is_exact() -> None:
    assert lat_index(str(d("0.1") + d("0.2"))) == 3


def test_neighbours_share_a_cell() -> None:
    assert cell_for(d("31.26"), d("34.76")) == cell_for(d("31.34"), d("34.84"))


def test_points_across_a_boundary_do_not() -> None:
    assert cell_for(d("31.2499999"), d("34.79")) != cell_for(d("31.25"), d("34.79"))
    assert cell_for(d("31.26"), d("34.7499999")) != cell_for(d("31.26"), d("34.75"))


# The edges: indexes stay inside +-900 and +-1800, so no cell is outside the valid range.


@pytest.mark.parametrize(
    "text, expected",
    [("90", 900), ("-90", -900), ("89.96", 900), ("-89.96", -900), ("90.0", 900), ("89.95", 900), ("89.949", 899)],
)
def test_latitude_edges(text: str, expected: int) -> None:
    assert lat_index(text) == expected


@pytest.mark.parametrize(
    "text, expected",
    [("180", 1800), ("-180", -1800), ("179.96", 1800), ("-179.96", -1800), ("179.95", 1800), ("179.949", 1799)],
)
def test_longitude_edges(text: str, expected: int) -> None:
    assert lon_index(text) == expected


def test_both_sides_of_the_date_line_are_different_cells() -> None:
    assert cell_for(d("10"), d("179.99")).lon_index == 1800
    assert cell_for(d("10"), d("-179.99")).lon_index == -1800
    assert cell_for(d("10"), d("179.99")) != cell_for(d("10"), d("-179.99"))


def test_180_and_minus_180_are_different_cells() -> None:
    assert cell_for(d("0"), d("180")) != cell_for(d("0"), d("-180"))


# Nodes.


def test_the_example_point_falls_in_the_node_31_3_and_34_8() -> None:
    lat, lon = node_for(cell_for(d("31.25"), d("34.79")))
    assert (str(lat), str(lon)) == ("31.3", "34.8")


@pytest.mark.parametrize(
    "cell, expected",
    [
        (Cell(0, 0), ("0.0", "0.0")),
        (Cell(-1, 1), ("-0.1", "0.1")),
        (Cell(313, 348), ("31.3", "34.8")),
        (Cell(900, 1800), ("90.0", "180.0")),
        (Cell(-900, -1800), ("-90.0", "-180.0")),
    ],
)
def test_a_node_has_exactly_one_decimal(cell: Cell, expected: tuple[str, str]) -> None:
    lat, lon = node_for(cell)
    assert (str(lat), str(lon)) == expected


NODE_POINTS = ["0", "0.05", "-0.05", "31.25", "34.79", "-31.25", "89.96", "-89.96", "179.96", "-179.96", "12.34", "-56.78"]


@pytest.mark.parametrize("text", NODE_POINTS)
def test_the_node_is_within_half_a_step_and_maps_back_to_its_cell(text: str) -> None:
    cell = cell_for(d(text), d(text))
    lat, lon = node_for(cell)
    assert abs(lat - d(text)) <= d("0.05")
    assert abs(lon - d(text)) <= d("0.05")
    assert cell_for(lat, lon) == cell


def test_a_cell_is_a_hashable_pair() -> None:
    cell = cell_for(d("31.25"), d("34.79"))
    assert cell == Cell(313, 348)
    assert tuple(cell) == (313, 348)
    assert {cell: "forecast"}[Cell(313, 348)] == "forecast"


# Inputs that would bring float noise or garbage back.


def test_a_float_is_refused_and_not_converted() -> None:
    with pytest.raises(TypeError):
        cell_for(31.25, Decimal("34.79"))  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        cell_for(Decimal("31.25"), 34.79)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity"])
def test_a_value_that_is_not_finite_is_refused(bad: str) -> None:
    with pytest.raises(ValueError):
        cell_for(Decimal(bad), Decimal("0"))
