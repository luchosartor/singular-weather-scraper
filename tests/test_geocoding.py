import responses

from weather_scraper.config import Settings
from weather_scraper.geocoding import resolve_city
from weather_scraper.rate_limiter import RateLimiter

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"


def _settings() -> Settings:
    return Settings(geocoding_base_url=GEOCODING_URL, request_timeout_seconds=5)


def _rate_limiter() -> RateLimiter:
    # High rate so the limiter never actually sleeps during tests.
    return RateLimiter(requests_per_second=1000)


@responses.activate
def test_resolve_city_returns_city_when_results_present():
    responses.add(
        responses.GET,
        GEOCODING_URL,
        json={
            "results": [
                {"name": "Lisbon", "latitude": 38.7223, "longitude": -9.1393},
            ]
        },
        status=200,
    )

    city = resolve_city("Lisbon", _settings(), _rate_limiter())

    assert city is not None
    assert city.name == "Lisbon"
    assert city.latitude == 38.7223
    assert city.longitude == -9.1393


@responses.activate
def test_resolve_city_returns_none_when_no_results():
    responses.add(responses.GET, GEOCODING_URL, json={"results": []}, status=200)

    city = resolve_city("Nowhereville", _settings(), _rate_limiter())

    assert city is None


@responses.activate
def test_resolve_city_returns_none_on_request_failure():
    responses.add(responses.GET, GEOCODING_URL, status=500)

    city = resolve_city("Errorville", _settings(), _rate_limiter())

    assert city is None
