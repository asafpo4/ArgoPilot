from datetime import date
from typing import Annotated

from pydantic import AfterValidator, Field


MAX_NAME_LENGTH = 200


class InvalidTextError(Exception):
    """Text that the database cannot store (it contains NUL)."""


def contains_nul(value: str) -> bool:
    return "\x00" in value


def reject_nul(value: str) -> str:
    if contains_nul(value):
        raise InvalidTextError("Text contains invalid characters")
    return value


def strip_and_require_name(value: str) -> str:
    reject_nul(value)
    stripped = value.strip()
    if not stripped:
        raise ValueError("name must not be empty")
    if len(stripped) > MAX_NAME_LENGTH:
        raise ValueError(f"name must be at most {MAX_NAME_LENGTH} characters")
    return stripped


def check_planting_date(value: str) -> str:
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError("planting_date must be YYYY-MM-DD")
    if parsed > date.today():
        raise ValueError("planting_date must not be in the future")
    return value


# Text stored as is (reference ids): only NUL is rejected.
StoredText = Annotated[str, AfterValidator(reject_nul)]

# A name rule shared by farms and plots: spaces at the edges are removed, and empty is rejected.
RequiredName = Annotated[str, AfterValidator(strip_and_require_name)]

# Rejects 0, negatives, and infinity (JSON 1e999 parses to infinity).
PositiveNumber = Annotated[float, Field(gt=0, allow_inf_nan=False, strict=True)]

PlantingDate = Annotated[str, AfterValidator(check_planting_date)]

Latitude = Annotated[float, Field(ge=-90, le=90, strict=True)]

Longitude = Annotated[float, Field(ge=-180, le=180, strict=True)]
