"""Default set of cities used when the caller does not request specific ones."""

from weather_scraper.models import City

DEFAULT_CITIES: list[City] = [
    City(name="New York", latitude=40.7128, longitude=-74.0060),
    City(name="Tokyo", latitude=35.6895, longitude=139.6917),
    City(name="London", latitude=51.5074, longitude=-0.1278),
    City(name="Paris", latitude=48.8566, longitude=2.3522),
    City(name="Berlin", latitude=52.5200, longitude=13.4050),
    City(name="Sydney", latitude=-33.8688, longitude=151.2093),
    City(name="Mumbai", latitude=19.0760, longitude=72.8777),
    City(name="Cape Town", latitude=-33.9249, longitude=18.4241),
    City(name="Moscow", latitude=55.7558, longitude=37.6173),
    City(name="Rio de Janeiro", latitude=-22.9068, longitude=-43.1729),
]
