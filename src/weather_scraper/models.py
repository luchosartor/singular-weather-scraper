"""Shared data models for the weather scraper."""

from pydantic import BaseModel


class City(BaseModel):
    name: str
    latitude: float
    longitude: float


class WeatherReading(BaseModel):
    city: str
    temperature_c: float
    humidity_pct: float
    wind_speed_ms: float
