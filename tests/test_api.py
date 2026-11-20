from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from weather_scraper import api
from weather_scraper.cities import DEFAULT_CITIES
from weather_scraper.models import WeatherReading
from weather_scraper.providers.base import ProviderError
from weather_scraper.providers.open_meteo import OpenMeteoProvider


@pytest.fixture(autouse=True)
def reset_state():
    """Each test starts from a clean AppState (it's a module-level singleton)."""
    api.state.last_run = None
    api.state.last_success_rate = None
    api.state.df = None
    api.state.csv_bytes = None
    api.state.chart_bytes = None
    yield
    api.state.last_run = None
    api.state.last_success_rate = None
    api.state.df = None
    api.state.csv_bytes = None
    api.state.chart_bytes = None


def fake_fetch_all_succeed(self, city):
    # Stand-in for OpenMeteoProvider.fetch so these tests never hit the network.
    return WeatherReading(city=city.name, temperature_c=20.0, humidity_pct=50.0, wind_speed_ms=5.0)


def fake_fetch_all_fail(self, city):
    raise ProviderError(f"simulated failure for {city.name}")


def test_health_is_always_200():
    client = TestClient(api.app)
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["last_run"] is None
    assert body["last_success_rate"] is None


def test_weather_before_refresh_is_404():
    client = TestClient(api.app)
    assert client.get("/weather").status_code == 404
    assert client.get("/weather/csv").status_code == 404
    assert client.get("/weather/chart").status_code == 404


def test_refresh_then_weather_returns_data():
    with patch.object(OpenMeteoProvider, "fetch", fake_fetch_all_succeed):
        client = TestClient(api.app)

        # No cities in the body -> falls back to DEFAULT_CITIES, no geocoding call.
        refresh_response = client.post("/weather/refresh", json={})
        assert refresh_response.status_code == 200
        body = refresh_response.json()
        assert body["cities_requested"] == len(DEFAULT_CITIES)
        assert body["cities_succeeded"] == len(DEFAULT_CITIES)
        assert body["cities_failed"] == 0

        weather_response = client.get("/weather")
        assert weather_response.status_code == 200
        data = weather_response.json()
        assert len(data) == len(DEFAULT_CITIES)

        health_response = client.get("/health")
        health_body = health_response.json()
        assert health_body["status"] == "ok"
        assert health_body["last_success_rate"] == 1.0


def test_refresh_then_csv_and_chart_are_served_from_memory():
    with patch.object(OpenMeteoProvider, "fetch", fake_fetch_all_succeed):
        client = TestClient(api.app)
        client.post("/weather/refresh", json={})

        csv_response = client.get("/weather/csv")
        assert csv_response.status_code == 200
        assert csv_response.headers["content-type"].startswith("text/csv")
        assert b"City" in csv_response.content

        chart_response = client.get("/weather/chart")
        assert chart_response.status_code == 200
        assert chart_response.headers["content-type"] == "image/png"
        assert chart_response.content[:8] == b"\x89PNG\r\n\x1a\n"  # PNG magic bytes


def test_refresh_with_total_failure_reports_degraded_and_keeps_previous_data():
    with patch.object(OpenMeteoProvider, "fetch", fake_fetch_all_succeed):
        client = TestClient(api.app)
        client.post("/weather/refresh", json={})
        good_csv = client.get("/weather/csv").content

    with patch.object(OpenMeteoProvider, "fetch", fake_fetch_all_fail):
        refresh_response = client.post("/weather/refresh", json={})
        body = refresh_response.json()
        assert body["cities_succeeded"] == 0
        assert body["cities_failed"] == len(DEFAULT_CITIES)

        health_response = client.get("/health")
        health_body = health_response.json()
        assert health_body["status"] == "degraded"
        assert health_body["last_success_rate"] == 0.0

        # The failed refresh must not have wiped out the good data from before.
        csv_response = client.get("/weather/csv")
        assert csv_response.status_code == 200
        assert csv_response.content == good_csv
