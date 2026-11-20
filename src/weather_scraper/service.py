"""Orchestrates fetching weather for many cities and shaping the results."""

from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

from weather_scraper.models import City, WeatherReading
from weather_scraper.providers.base import ProviderError, WeatherProvider

COLUMNS = [
    "City",
    "Temperature (C)",
    "Temperature (F)",
    "Humidity (%)",
    "Wind Speed (m/s)",
    "Wind Speed (mph)",
]


class WeatherService:
    def __init__(self, provider: WeatherProvider, max_workers: int = 5):
        self._provider = provider
        self._max_workers = max_workers

    def collect(self, cities: list[City]) -> list[WeatherReading]:
        """Fetch weather for every city concurrently.

        Fetching cities in parallel (through the shared rate limiter on the
        provider) is the same pattern needed to ingest many ad network
        sources without serializing on the slowest one. A single city
        failing must not take the whole batch down, so a ProviderError from
        any one future is swallowed here and that city is just dropped from
        the results - any *other* exception (a bug, not an expected provider
        failure) is intentionally left to propagate.
        """
        readings: list[WeatherReading] = []
        with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
            futures = [executor.submit(self._provider.fetch, city) for city in cities]
            for future in as_completed(futures):
                try:
                    readings.append(future.result())
                except ProviderError:
                    # The provider already logged the specific reason (with
                    # more context than we have here) before raising, so we
                    # just drop this city from the batch rather than logging
                    # the same failure a second time.
                    continue
        return readings


def build_dataframe(readings: list[WeatherReading]) -> pd.DataFrame:
    rows = [
        {
            "City": r.city,
            "Temperature (C)": r.temperature_c,
            "Temperature (F)": r.temperature_c * 9 / 5 + 32,
            "Humidity (%)": r.humidity_pct,
            "Wind Speed (m/s)": r.wind_speed_ms,
            "Wind Speed (mph)": r.wind_speed_ms * 2.23694,
        }
        for r in readings
    ]
    df = pd.DataFrame(rows, columns=COLUMNS)
    # Derived columns (F, mph) carry long floating-point tails (e.g.
    # 8.388525000000001) that are just binary floating-point noise, not
    # real precision. Round everything to 2 decimals before it ever reaches
    # the CSV.
    numeric_columns = [c for c in COLUMNS if c != "City"]
    df[numeric_columns] = df[numeric_columns].round(2)
    return df


def rank_and_filter(
    df: pd.DataFrame,
    sort_by: str = "temperature",
    ascending: bool = False,
    max_humidity: float | None = None,
) -> pd.DataFrame:
    if sort_by not in ("temperature", "humidity"):
        raise ValueError(f"Invalid sort_by: {sort_by!r}, expected 'temperature' or 'humidity'")

    result = df
    if max_humidity is not None:
        # .copy() avoids a SettingWithCopyWarning from pandas when we later
        # assign the Rank column onto this filtered slice.
        result = result[result["Humidity (%)"] <= max_humidity].copy()

    sort_column = "Temperature (C)" if sort_by == "temperature" else "Humidity (%)"
    result = result.sort_values(
        by=sort_column, ascending=ascending, kind="stable"
    ).reset_index(drop=True)
    # method="min" gives tied values the same rank (e.g. two cities at the
    # same temperature both rank 1) instead of an arbitrary tie-break from a
    # plain 1..N range.
    result["Rank"] = (
        result[sort_column].rank(ascending=ascending, method="min").astype(int)
    )
    return result
