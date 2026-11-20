"""Provider abstraction.

Today there's only one upstream (Open-Meteo), but modeling weather sources
behind a common interface mirrors how Singular has to treat 1200+ ad
networks: each has its own API shape, but the rest of the system should only
ever talk to the abstraction, not to a specific vendor's quirks.
"""

from abc import ABC, abstractmethod

from weather_scraper.models import City, WeatherReading


class ProviderError(Exception):
    """Raised when a provider cannot produce a valid reading for a city."""


class WeatherProvider(ABC):
    @abstractmethod
    def fetch(self, city: City) -> WeatherReading:
        """Fetch current weather for `city`, or raise ProviderError."""
        raise NotImplementedError
