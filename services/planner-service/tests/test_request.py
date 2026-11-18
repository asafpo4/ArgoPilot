from urllib.parse import quote

import pytest

from request import RequestError, parse_days, plot_id_is_possible

DETAIL = "days: must be one digit from 1 to 7"


def query(value: str) -> bytes:
    return b"days=" + quote(value, safe="").encode()


@pytest.mark.parametrize("digit", ["1", "2", "3", "4", "5", "6", "7"])
def test_accepts_one_digit(digit):
    assert parse_days(query(digit)) == int(digit)


@pytest.mark.parametrize("raw", [b"", b"x=1", b"other=5&more=9"])
def test_absent_means_seven(raw):
    assert parse_days(raw) == 7


def test_other_parameters_are_ignored():
    assert parse_days(b"x=9&days=2&y=%00") == 2


@pytest.mark.parametrize(
    "value",
    [
        "0", "8", "9", "10", "07", "+3", "-3", " 3", "3 ",
        "3.0", "3.5", "3e0", "٣", "３", "",
    ],
)
def test_rejects_bad_value(value):
    with pytest.raises(RequestError) as info:
        parse_days(query(value))
    assert info.value.detail == DETAIL


def test_rejects_empty_without_equals_sign():
    with pytest.raises(RequestError) as info:
        parse_days(b"days")
    assert info.value.detail == DETAIL


def test_rejects_repeated_parameter():
    with pytest.raises(RequestError) as info:
        parse_days(b"days=1&days=2")
    assert info.value.detail == DETAIL


def test_rejects_repeated_parameter_with_same_value():
    with pytest.raises(RequestError) as info:
        parse_days(b"days=1&days=1")
    assert info.value.detail == DETAIL


def test_plot_id_length_limit():
    assert plot_id_is_possible("a" * 64)
    assert not plot_id_is_possible("a" * 65)


def test_plot_id_with_nul_is_impossible():
    assert not plot_id_is_possible("abc\x00def")
