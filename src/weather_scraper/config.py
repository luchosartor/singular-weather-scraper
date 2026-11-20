"""Application settings, loaded from environment variables / a .env file.

Centralizing these knobs (timeouts, retry policy, rate limit, concurrency) is
what lets the same code be pointed at a different weather provider, or tuned
for a stricter upstream rate limit, without touching any other module -
exactly the kind of config surface you'd want when onboarding a new ad
network with its own quirks.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="WEATHER_",
        extra="ignore",
    )

    open_meteo_base_url: str = "https://api.open-meteo.com/v1/forecast"
    geocoding_base_url: str = "https://geocoding-api.open-meteo.com/v1/search"
    request_timeout_seconds: int = 10
    max_retries: int = 3
    retry_backoff_factor: float = 0.5
    rate_limit_per_second: float = 5
    max_concurrent_workers: int = 5
    output_dir: str = "output"
