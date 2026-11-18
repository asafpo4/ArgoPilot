"""Checks of the raw request: the `days` query parameter and the plot id."""

import re
from urllib.parse import parse_qsl

DEFAULT_DAYS = 7
MAX_PLOT_ID_LENGTH = 64
DAYS_DETAIL = "days: must be one digit from 1 to 7"

# Exactly one ASCII digit from 1 to 7. fullmatch (not match or $) so a
# trailing newline is rejected, and re.ASCII keeps non-ASCII digits out.
_DAYS_PATTERN = re.compile(r"[1-7]", re.ASCII)


class RequestError(Exception):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


def parse_days(raw_query: bytes) -> int:
    """Return the number of days from the raw query string; absent means 7.

    The text is checked against a pattern, never converted with int(), which
    would accept signs, spaces, underscores and non-ASCII digits.
    """
    # latin-1 maps every byte to a character, so decoding cannot fail.
    pairs = parse_qsl(raw_query.decode("latin-1"), keep_blank_values=True)
    values = [value for key, value in pairs if key == "days"]
    if not values:
        return DEFAULT_DAYS
    if len(values) != 1 or not _DAYS_PATTERN.fullmatch(values[0]):
        raise RequestError(DAYS_DETAIL)
    return ord(values[0]) - ord("0")


def plot_id_is_possible(plot_id: str) -> bool:
    """False for an id the registry cannot hold: over 64 characters or a NUL."""
    return len(plot_id) <= MAX_PLOT_ID_LENGTH and "\x00" not in plot_id
