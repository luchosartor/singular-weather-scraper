import pytest
import responses

from weather_scraper.config import Settings
from weather_scraper.models import City
from weather_scraper.providers.base import ProviderError
from weather_scraper.providers.open_meteo import OpenMeteoProvider
from weather_scraper.rate_limiter import RateLimiter

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

VALID_UNITS = {
    "temperature_2m": "°C",
    "relative_humidity_2m": "%",
    "wind_speed_10m": "m/s",
}


def _settings() -> Settings:
    return Settings(
        open_meteo_base_url=FORECAST_URL,
        max_retries=3,
        retry_backoff_factor=0.01,
        request_timeout_seconds=5,
    )


def _provider() -> OpenMeteoProvider:
    # High rate so the limiter never actually sleeps during tests.
    return OpenMeteoProvider(_settings(), RateLimiter(requests_per_second=1000))


CITY = City(name="Testville", latitude=1.0, longitude=2.0)


@responses.activate
def test_fetch_returns_correct_weather_reading():
    responses.add(
        responses.GET,
        FORECAST_URL,
        json={
            "current_units": VALID_UNITS,
            "current": {
                "temperature_2m": 21.5,
                "relative_humidity_2m": 60.0,
                "wind_speed_10m": 3.2,
            },
        },
        status=200,
    )

    reading = _provider().fetch(CITY)

    assert reading.city == "Testville"
    assert reading.temperature_c == 21.5
    assert reading.humidity_pct == 60.0
    assert reading.wind_speed_ms == 3.2


@responses.activate
def test_fetch_requests_wind_speed_in_meters_per_second():
    # Regression guard for the wind_speed_unit=ms gotcha: Open-Meteo
    # defaults to km/h, so if this param is ever deleted from open_meteo.py,
    # this test should fail rather than silently computing wrong mph values.
    responses.add(
        responses.GET,
        FORECAST_URL,
        json={"current_units": VALID_UNITS, "current": {
            "temperature_2m": 21.5,
            "relative_humidity_2m": 60.0,
            "wind_speed_10m": 3.2,
        }},
        status=200,
    )

    _provider().fetch(CITY)

    request_url = responses.calls[0].request.url
    assert "wind_speed_unit=ms" in request_url


@responses.activate
def test_fetch_raises_provider_error_on_missing_field():
    responses.add(
        responses.GET,
        FORECAST_URL,
        json={
            "current_units": VALID_UNITS,
            "current": {
                "temperature_2m": 21.5,
                "relative_humidity_2m": 60.0,
                # wind_speed_10m missing
            },
        },
        status=200,
    )

    with pytest.raises(ProviderError):
        _provider().fetch(CITY)


@responses.activate
def test_fetch_raises_provider_error_on_non_numeric_field():
    # A field that's present (so it passes the "missing" check) but isn't a
    # real number - e.g. an ad-network-style "n/a" placeholder - must not
    # let a raw ValueError escape from float(...).
    responses.add(
        responses.GET,
        FORECAST_URL,
        json={
            "current_units": VALID_UNITS,
            "current": {
                "temperature_2m": "n/a",
                "relative_humidity_2m": 60.0,
                "wind_speed_10m": 3.2,
            },
        },
        status=200,
    )

    with pytest.raises(ProviderError):
        _provider().fetch(CITY)


@responses.activate
def test_fetch_raises_provider_error_on_boolean_field():
    responses.add(
        responses.GET,
        FORECAST_URL,
        json={
            "current_units": VALID_UNITS,
            "current": {
                "temperature_2m": True,
                "relative_humidity_2m": 60.0,
                "wind_speed_10m": 3.2,
            },
        },
        status=200,
    )

    with pytest.raises(ProviderError):
        _provider().fetch(CITY)


@responses.activate
def test_fetch_raises_provider_error_on_unexpected_wind_speed_unit():
    # Simulates the API silently falling back to its km/h default (e.g. if
    # wind_speed_unit=ms were ever dropped from the request).
    bad_units = {**VALID_UNITS, "wind_speed_10m": "km/h"}
    responses.add(
        responses.GET,
        FORECAST_URL,
        json={
            "current_units": bad_units,
            "current": {
                "temperature_2m": 21.5,
                "relative_humidity_2m": 60.0,
                "wind_speed_10m": 11.5,
            },
        },
        status=200,
    )

    with pytest.raises(ProviderError):
        _provider().fetch(CITY)


@responses.activate
def test_fetch_retries_on_server_error_then_succeeds():
    responses.add(responses.GET, FORECAST_URL, status=500)
    responses.add(responses.GET, FORECAST_URL, status=500)
    responses.add(
        responses.GET,
        FORECAST_URL,
        json={
            "current_units": VALID_UNITS,
            "current": {
                "temperature_2m": 10.0,
                "relative_humidity_2m": 40.0,
                "wind_speed_10m": 5.0,
            },
        },
        status=200,
    )

    reading = _provider().fetch(CITY)

    assert reading.temperature_c == 10.0
    assert reading.humidity_pct == 40.0
    assert reading.wind_speed_ms == 5.0
    assert len(responses.calls) == 3
