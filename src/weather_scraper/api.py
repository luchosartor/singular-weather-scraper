"""FastAPI app exposing the collected weather data.

Run from the project root with: PYTHONPATH=src uvicorn weather_scraper.api:app --reload
"""

import logging
from datetime import datetime, timezone

import pandas as pd
from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel

from weather_scraper.cities import DEFAULT_CITIES
from weather_scraper.config import Settings
from weather_scraper.geocoding import resolve_cities
from weather_scraper.providers.open_meteo import OpenMeteoProvider
from weather_scraper.rate_limiter import RateLimiter
from weather_scraper.service import WeatherService, build_dataframe, rank_and_filter
from weather_scraper.visualize import render_temperature_bar_png

logger = logging.getLogger(__name__)

app = FastAPI(title="Weather Scraper API")


class AppState:
    """In-memory state for the last refresh.

    A singleton for the process' lifetime is enough for this exercise - no
    need for a database just to remember the last run. The CSV/chart bytes
    are kept here too (not written to disk): the API must never overwrite
    the output/weather_data.csv and output/weather_chart.png that the CLI
    run commits to the repo as evidence.
    """

    def __init__(self):
        self.last_run: datetime | None = None
        self.last_success_rate: float | None = None
        self.df: pd.DataFrame | None = None
        self.csv_bytes: bytes | None = None
        self.chart_bytes: bytes | None = None


state = AppState()


class RefreshRequest(BaseModel):
    cities: list[str] | None = None


def _run_pipeline(city_names: list[str] | None) -> dict:
    """Same pipeline the CLI runs: geocode (if needed), collect, shape."""
    settings = Settings()
    rate_limiter = RateLimiter(settings.rate_limit_per_second)

    # Count the number of cities actually *requested*, before any geocoding
    # drop-outs, so a name that fails to geocode still counts as a failure
    # instead of silently shrinking the denominator.
    if city_names:
        cities_requested = len(city_names)
        cities = resolve_cities(city_names, settings, rate_limiter)
    else:
        cities_requested = len(DEFAULT_CITIES)
        cities = DEFAULT_CITIES

    provider = OpenMeteoProvider(settings, rate_limiter)
    service = WeatherService(provider, max_workers=settings.max_concurrent_workers)
    readings = service.collect(cities)

    cities_succeeded = len(readings)
    cities_failed = cities_requested - cities_succeeded

    state.last_run = datetime.now(timezone.utc)
    state.last_success_rate = (
        cities_succeeded / cities_requested if cities_requested else 0.0
    )

    # Only replace the previous good data if this refresh actually produced
    # something. A refresh where every city failed shouldn't wipe out the
    # last known-good dataset - last_run/last_success_rate above still
    # reflect that this (failed) attempt happened.
    if readings:
        df = build_dataframe(readings)
        result_df = rank_and_filter(df)
        state.df = result_df
        state.csv_bytes = result_df.to_csv(index=False).encode("utf-8")
        state.chart_bytes = render_temperature_bar_png(result_df)
    else:
        logger.warning("Refresh fetched 0/%d cities; keeping previous data, if any.", cities_requested)

    return {
        "cities_requested": cities_requested,
        "cities_succeeded": cities_succeeded,
        "cities_failed": cities_failed,
    }


@app.get("/health")
def health() -> dict:
    # Cheap signal of whether the service is both alive and actually
    # producing good data - the kind of check you'd put in front of any
    # ingestion pipeline that depends on flaky upstreams. "ok" only when the
    # last refresh fetched everything it asked for (or no refresh has run
    # yet); anything less is reported as "degraded" rather than papering
    # over partial/total failures with a blanket "ok".
    if state.last_success_rate is None or state.last_success_rate >= 1.0:
        status = "ok"
    else:
        status = "degraded"

    return {
        "status": status,
        "last_run": state.last_run.isoformat() if state.last_run else None,
        "last_success_rate": state.last_success_rate,
    }


@app.get("/weather")
def get_weather() -> list[dict]:
    if state.df is None:
        raise HTTPException(
            status_code=404,
            detail="No data available yet. Call POST /weather/refresh first.",
        )
    return state.df.to_dict(orient="records")


@app.get("/weather/csv")
def get_weather_csv() -> Response:
    if state.csv_bytes is None:
        raise HTTPException(
            status_code=404,
            detail="No data available yet. Call POST /weather/refresh first.",
        )
    return Response(
        content=state.csv_bytes,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=weather_data.csv"},
    )


@app.get("/weather/chart")
def get_weather_chart() -> Response:
    if state.chart_bytes is None:
        raise HTTPException(
            status_code=404,
            detail="No data available yet. Call POST /weather/refresh first.",
        )
    return Response(
        content=state.chart_bytes,
        media_type="image/png",
        headers={"Content-Disposition": "attachment; filename=weather_chart.png"},
    )


@app.post("/weather/refresh")
def refresh_weather(request: RefreshRequest | None = None) -> dict:
    city_names = request.cities if request else None
    return _run_pipeline(city_names)
