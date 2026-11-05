from datetime import date
from typing import Annotated

from pydantic import AfterValidator, Field


def strip_and_require_name(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError("name must not be empty")
    return stripped


def check_planting_date(value: str) -> str:
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError("planting_date must be YYYY-MM-DD")
    if parsed > date.today():
        raise ValueError("planting_date must not be in the future")
    return value


# A name rule shared by farms and plots: spaces at the edges are removed, and empty is rejected.
RequiredName = Annotated[str, AfterValidator(strip_and_require_name)]

# Rejects 0, negatives, and infinity (JSON 1e999 parses to infinity).
PositiveNumber = Annotated[float, Field(gt=0, allow_inf_nan=False)]

PlantingDate = Annotated[str, AfterValidator(check_planting_date)]

Latitude = Annotated[float, Field(ge=-90, le=90)]

Longitude = Annotated[float, Field(ge=-180, le=180)]
