"""Resolve a free-text city name to coordinates via the Open-Meteo geocoding API."""

import logging

import requests

from weather_scraper.config import Settings
from weather_scraper.models import City
from weather_scraper.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)


def resolve_city(name: str, settings: Settings, rate_limiter: RateLimiter) -> City | None:
    """Look up `name` and return a City, or None if it can't be resolved.

    Geocoding is best-effort: a typo'd or unknown city name shouldn't crash
    the whole run, so failures are logged and swallowed here. It hits the
    same Open-Meteo infrastructure as the weather endpoint, so it goes
    through the shared rate limiter too.
    """
    rate_limiter.acquire()
    try:
        response = requests.get(
            settings.geocoding_base_url,
            params={"name": name, "count": 1, "language": "en", "format": "json"},
            timeout=settings.request_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("Geocoding request failed for name=%s: %s", name, exc)
        return None

    results = payload.get("results") if isinstance(payload, dict) else None
    if not results:
        logger.warning("Geocoding returned no results for name=%s", name)
        return None

    result = results[0]
    try:
        return City(
            name=result.get("name", name),
            latitude=result["latitude"],
            longitude=result["longitude"],
        )
    except (KeyError, TypeError) as exc:
        logger.warning("Geocoding result for name=%s missing fields: %s", name, exc)
        return None


def resolve_cities(names: list[str], settings: Settings, rate_limiter: RateLimiter) -> list[City]:
    """Resolve several city names, skipping (and logging) any that fail.

    Shared by the CLI and the API so both build their city list the same way.
    """
    # resolve_city() already logs the specific reason for any failure, so we
    # just skip it here rather than logging the same failure twice.
    cities: list[City] = []
    for name in names:
        city = resolve_city(name, settings, rate_limiter)
        if city is not None:
            cities.append(city)
    return cities
