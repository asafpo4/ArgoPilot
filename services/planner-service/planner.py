"""One plan request (spec 4.1): the plot, then the soil, the emitter and the forecast in parallel,
the checks of the answers, the engine, and the rounding into the JSON."""

import asyncio
from collections.abc import Callable
from urllib.parse import quote

import engine
from output import to_plan_json
from upstream import (
    InvalidAnswer,
    NotFound,
    Upstream,
    UpstreamFailure,
    forecast_query,
    parse_emitter,
    parse_forecast,
    parse_plot,
    parse_soil,
)

REGISTRY = "registry-service"
WEATHER = "weather-service"
_INVALID_RETRY_AFTER = 5

__all__ = ["REGISTRY", "WEATHER", "NotFound", "UpstreamFailure", "build_plan"]


def _checked[T](service: str, parse: Callable[..., T], *args: object) -> T:
    """Run one of the checks of 4.4. A bad answer becomes a failure of that service."""
    rule = ""
    try:
        return parse(*args)
    except InvalidAnswer as exc:
        rule = exc.rule
    # Raised after the except block: nothing from the bad answer stays in __context__.
    raise UpstreamFailure(service, f"invalid {rule}", _INVALID_RETRY_AFTER)


def _first_failure(group: BaseExceptionGroup) -> BaseException:
    # The group lists the errors in the order the tasks ended, and a failure cancels the siblings,
    # so the first one is the failure that won.
    return group.exceptions[0]


async def build_plan(plot_id: str, days: int, registry: Upstream, weather: Upstream) -> dict:
    """The plan JSON of spec 2.2. Raises NotFound and UpstreamFailure; any other error is a bug."""
    body = await registry.get_json(f"/v1/plots/{quote(plot_id, safe='')}", not_found_ok=True)
    plot = _checked(REGISTRY, parse_plot, body)

    async def soil() -> float:
        answer = await registry.get_json(f"/v1/soils/{quote(plot.soil_id, safe='')}")
        return _checked(REGISTRY, parse_soil, answer)

    async def emitter() -> float:
        answer = await registry.get_json(f"/v1/emitters/{quote(plot.emitter_id, safe='')}")
        return _checked(REGISTRY, parse_emitter, answer)

    async def forecast():
        answer = await weather.get_json("/v1/forecast", forecast_query(plot.lat, plot.lon, days))
        return _checked(WEATHER, parse_forecast, answer, days)

    failure: BaseException | None = None
    try:
        # The first failure cancels the other two calls, and nothing is planned.
        async with asyncio.TaskGroup() as group:
            soil_task = group.create_task(soil())
            emitter_task = group.create_task(emitter())
            forecast_task = group.create_task(forecast())
    except BaseExceptionGroup as caught:
        failure = _first_failure(caught)
    if failure is not None:
        raise failure

    result = engine.plan(
        engine.PlotInput(
            crop_id=plot.crop_id,
            planting_date=plot.planting_date,
            area_m2=plot.area_m2,
            row_spacing_m=plot.row_spacing_m,
            emitter_spacing_m=plot.emitter_spacing_m,
            emitter_flow_lph=emitter_task.result(),
            soil_mm_per_m=soil_task.result(),
        ),
        forecast_task.result().rows,
    )
    return to_plan_json(plot_id, plot, forecast_task.result(), result, days)
