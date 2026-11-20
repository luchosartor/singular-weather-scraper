"""Open-Meteo weather provider."""

import logging
import math

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from weather_scraper.config import Settings
from weather_scraper.models import City, WeatherReading
from weather_scraper.providers.base import ProviderError, WeatherProvider
from weather_scraper.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

# Expected units for the fields we read out of `current`. If Open-Meteo ever
# changes its defaults (or someone removes the `wind_speed_unit=ms` param
# above), we want a loud ProviderError instead of silently computing mph
# from a km/h value.
EXPECTED_UNITS = {
    "temperature_2m": "°C",
    "wind_speed_10m": "m/s",
}


def _coerce_float(value: object, field_name: str, city_name: str) -> float:
    """Convert an upstream field to float, rejecting anything that isn't a
    genuine number (bools, "n/a" strings, lists, NaN, ...).

    `float(True)` would silently succeed as 1.0 and `float("n/a")` would
    raise a raw, unwrapped ValueError if we didn't guard for it here -
    exactly the kind of inconsistent-field problem real ad network
    responses produce.
    """
    if isinstance(value, bool):
        logger.warning(
            "Open-Meteo response for city=%s field=%s is a bool, not numeric: %r",
            city_name,
            field_name,
            value,
        )
        raise ProviderError(f"Malformed response for {city_name}: {field_name} is a bool")

    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        logger.warning(
            "Open-Meteo response for city=%s field=%s is not numeric: %r",
            city_name,
            field_name,
            value,
        )
        raise ProviderError(
            f"Malformed response for {city_name}: {field_name} is not numeric ({value!r})"
        ) from exc

    if not math.isfinite(result):
        logger.warning(
            "Open-Meteo response for city=%s field=%s is not finite: %r",
            city_name,
            field_name,
            result,
        )
        raise ProviderError(f"Malformed response for {city_name}: {field_name} is not finite ({result!r})")

    return result


class OpenMeteoProvider(WeatherProvider):
    def __init__(self, settings: Settings, rate_limiter: RateLimiter):
        self._settings = settings
        self._rate_limiter = rate_limiter
        self._session = requests.Session()

        retry = Retry(
            total=settings.max_retries,
            backoff_factor=settings.retry_backoff_factor,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
        )
        adapter = HTTPAdapter(max_retries=retry)
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)

    def fetch(self, city: City) -> WeatherReading:
        # Shared across every worker thread in the pool, so all concurrent
        # fetches collectively stay under the configured rate, not just each
        # thread individually.
        self._rate_limiter.acquire()

        try:
            response = self._session.get(
                self._settings.open_meteo_base_url,
                params={
                    "latitude": city.latitude,
                    "longitude": city.longitude,
                    "current": "temperature_2m,relative_humidity_2m,wind_speed_10m",
                    # The API defaults wind speed to km/h. We need m/s to match
                    # the rest of the pipeline (WeatherReading.wind_speed_ms),
                    # so this must be requested explicitly - easy to miss.
                    "wind_speed_unit": "ms",
                },
                timeout=self._settings.request_timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            # Never let a raw requests/json exception escape the provider -
            # callers (the thread pool in service.py) only know about
            # ProviderError, same as they'd only know about a normalized
            # error from any ad network integration.
            logger.warning("Open-Meteo request failed for city=%s: %s", city.name, exc)
            raise ProviderError(f"Failed to fetch weather for {city.name}") from exc

        current = payload.get("current") if isinstance(payload, dict) else None
        if not isinstance(current, dict):
            logger.warning(
                "Open-Meteo response for city=%s missing 'current' block: %r",
                city.name,
                payload,
            )
            raise ProviderError(f"Malformed response for {city.name}: missing 'current'")

        # Upstream APIs are inconsistent about what fields they actually
        # populate, exactly like real ad network responses. Validate every
        # field we depend on before trusting it, instead of letting a KeyError
        # or TypeError surface deep in the pipeline.
        required_fields = ["temperature_2m", "relative_humidity_2m", "wind_speed_10m"]
        missing = [field for field in required_fields if current.get(field) is None]
        if missing:
            logger.warning(
                "Open-Meteo response for city=%s missing fields %s: %r",
                city.name,
                missing,
                current,
            )
            raise ProviderError(f"Malformed response for {city.name}: missing {missing}")

        # Don't just trust that wind_speed_unit=ms above was honored - check
        # the units Open-Meteo actually reports back. If that param is ever
        # dropped (or the API changes its default), this is what catches it
        # instead of silently treating km/h as m/s.
        units = payload.get("current_units") if isinstance(payload, dict) else None
        if not isinstance(units, dict):
            logger.warning(
                "Open-Meteo response for city=%s missing 'current_units' block: %r",
                city.name,
                payload,
            )
            raise ProviderError(f"Malformed response for {city.name}: missing 'current_units'")

        for field, expected_unit in EXPECTED_UNITS.items():
            actual_unit = units.get(field)
            if actual_unit != expected_unit:
                logger.warning(
                    "Open-Meteo response for city=%s field=%s has unexpected unit %r "
                    "(expected %r)",
                    city.name,
                    field,
                    actual_unit,
                    expected_unit,
                )
                raise ProviderError(
                    f"Malformed response for {city.name}: {field} unit is "
                    f"{actual_unit!r}, expected {expected_unit!r}"
                )

        return WeatherReading(
            city=city.name,
            temperature_c=_coerce_float(current["temperature_2m"], "temperature_2m", city.name),
            humidity_pct=_coerce_float(
                current["relative_humidity_2m"], "relative_humidity_2m", city.name
            ),
            wind_speed_ms=_coerce_float(current["wind_speed_10m"], "wind_speed_10m", city.name),
        )
