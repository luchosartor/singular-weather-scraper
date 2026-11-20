import pandas as pd
import pytest

from weather_scraper.models import City, WeatherReading
from weather_scraper.providers.base import ProviderError, WeatherProvider
from weather_scraper.service import WeatherService, build_dataframe, rank_and_filter


def test_build_dataframe_converts_units_correctly():
    readings = [
        WeatherReading(city="Testville", temperature_c=20.0, humidity_pct=50.0, wind_speed_ms=10.0),
    ]
    df = build_dataframe(readings)

    row = df.iloc[0]
    assert row["City"] == "Testville"
    assert row["Temperature (C)"] == 20.0
    assert row["Temperature (F)"] == pytest.approx(68.0)
    assert row["Humidity (%)"] == 50.0
    assert row["Wind Speed (m/s)"] == 10.0
    # Derived mph is rounded to 2 decimals to avoid float noise in the CSV.
    assert row["Wind Speed (mph)"] == pytest.approx(22.37)


def _sample_df() -> pd.DataFrame:
    readings = [
        WeatherReading(city="Hot", temperature_c=30.0, humidity_pct=20.0, wind_speed_ms=1.0),
        WeatherReading(city="Mild", temperature_c=15.0, humidity_pct=80.0, wind_speed_ms=2.0),
        WeatherReading(city="Cold", temperature_c=0.0, humidity_pct=50.0, wind_speed_ms=3.0),
    ]
    return build_dataframe(readings)


def test_rank_and_filter_sorts_by_temperature_descending_by_default():
    df = rank_and_filter(_sample_df(), sort_by="temperature")
    assert list(df["City"]) == ["Hot", "Mild", "Cold"]
    assert list(df["Rank"]) == [1, 2, 3]


def test_rank_and_filter_sorts_by_temperature_ascending():
    df = rank_and_filter(_sample_df(), sort_by="temperature", ascending=True)
    assert list(df["City"]) == ["Cold", "Mild", "Hot"]
    assert list(df["Rank"]) == [1, 2, 3]


def test_rank_and_filter_sorts_by_humidity_descending():
    df = rank_and_filter(_sample_df(), sort_by="humidity", ascending=False)
    assert list(df["City"]) == ["Mild", "Cold", "Hot"]


def test_rank_and_filter_sorts_by_humidity_ascending():
    df = rank_and_filter(_sample_df(), sort_by="humidity", ascending=True)
    assert list(df["City"]) == ["Hot", "Cold", "Mild"]


def test_rank_and_filter_applies_max_humidity():
    df = rank_and_filter(_sample_df(), sort_by="temperature", max_humidity=60.0)
    assert list(df["City"]) == ["Hot", "Cold"]
    assert list(df["Rank"]) == [1, 2]


def test_rank_and_filter_rejects_invalid_sort_by():
    with pytest.raises(ValueError):
        rank_and_filter(_sample_df(), sort_by="pressure")


def test_rank_and_filter_gives_tied_values_the_same_rank():
    readings = [
        WeatherReading(city="A", temperature_c=20.0, humidity_pct=50.0, wind_speed_ms=1.0),
        WeatherReading(city="B", temperature_c=20.0, humidity_pct=50.0, wind_speed_ms=1.0),
        WeatherReading(city="C", temperature_c=10.0, humidity_pct=50.0, wind_speed_ms=1.0),
    ]
    df = rank_and_filter(build_dataframe(readings), sort_by="temperature")
    ranks = dict(zip(df["City"], df["Rank"]))
    assert ranks["A"] == 1
    assert ranks["B"] == 1
    assert ranks["C"] == 3


class _FakeProvider(WeatherProvider):
    """Raises ProviderError for one named city, succeeds for everything else."""

    def __init__(self, broken_city_name: str):
        self._broken_city_name = broken_city_name

    def fetch(self, city: City) -> WeatherReading:
        if city.name == self._broken_city_name:
            raise ProviderError(f"simulated malformed response for {city.name}")
        return WeatherReading(city=city.name, temperature_c=20.0, humidity_pct=50.0, wind_speed_ms=1.0)


def test_collect_skips_broken_city_but_keeps_the_healthy_one():
    cities = [
        City(name="Broken", latitude=0.0, longitude=0.0),
        City(name="Healthy", latitude=1.0, longitude=1.0),
    ]
    service = WeatherService(_FakeProvider(broken_city_name="Broken"), max_workers=2)

    readings = service.collect(cities)

    assert len(readings) == 1
    assert readings[0].city == "Healthy"
