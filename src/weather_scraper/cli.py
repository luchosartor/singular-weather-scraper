"""Command-line entrypoint.

Run as: python -m weather_scraper.cli [options]
"""

import argparse
import logging
import sys
from pathlib import Path

from weather_scraper.cities import DEFAULT_CITIES
from weather_scraper.config import Settings
from weather_scraper.export import save_csv
from weather_scraper.geocoding import resolve_cities as geocode_names
from weather_scraper.models import City
from weather_scraper.providers.open_meteo import OpenMeteoProvider
from weather_scraper.rate_limiter import RateLimiter
from weather_scraper.service import WeatherService, build_dataframe, rank_and_filter
from weather_scraper.visualize import plot_temperature_bar

logger = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect and rank current weather by city.")
    parser.add_argument(
        "--cities",
        type=str,
        default=None,
        help="Comma-separated city names to geocode. Defaults to a built-in list of 10 cities.",
    )
    parser.add_argument(
        "--sort-by",
        choices=["temperature", "humidity"],
        default="temperature",
        help="Column to sort results by.",
    )
    parser.add_argument(
        "--ascending",
        action="store_true",
        help="Sort ascending instead of the default descending.",
    )
    parser.add_argument(
        "--max-humidity",
        type=float,
        default=None,
        help="Drop cities with humidity above this percentage.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Path to write the CSV output (default: <output_dir>/weather_data.csv, "
        "where output_dir comes from Settings/WEATHER_OUTPUT_DIR).",
    )
    parser.add_argument(
        "--chart",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Generate a weather_chart.png next to the CSV output (default: on). "
        "Use --no-chart to skip it.",
    )
    return parser.parse_args(argv)


def resolve_cities(
    cities_arg: str | None, settings: Settings, rate_limiter: RateLimiter
) -> tuple[list[City], int]:
    """Return (cities, cities_requested).

    cities_requested counts what was actually asked for (the default list,
    or every name typed/passed in), even if some of those names later fail
    geocoding - so callers can report an honest X/Y success count.
    """
    # No --cities given and we're attached to a real terminal: ask
    # interactively rather than silently assuming the defaults.
    if cities_arg is None and sys.stdin.isatty():
        user_input = input(
            "Enter city names separated by commas (or press Enter to use the 10 default cities): "
        )
        if user_input.strip():
            cities_arg = user_input

    if not cities_arg:
        return DEFAULT_CITIES, len(DEFAULT_CITIES)

    names = [name.strip() for name in cities_arg.split(",") if name.strip()]
    cities = geocode_names(names, settings, rate_limiter)
    return cities, len(names)


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    args = parse_args(argv)
    settings = Settings()

    # Shared across geocoding and weather fetches: both hit Open-Meteo's
    # infrastructure, so both go through the same limiter.
    rate_limiter = RateLimiter(settings.rate_limit_per_second)

    cities, cities_requested = resolve_cities(args.cities, settings, rate_limiter)

    provider = OpenMeteoProvider(settings, rate_limiter)
    service = WeatherService(provider, max_workers=settings.max_concurrent_workers)

    readings = service.collect(cities)
    logger.info("Fetched weather for %d/%d requested cities", len(readings), cities_requested)

    if not readings:
        # Every city failed (API down, bad geocoding, etc.) - don't write an
        # empty CSV/chart over whatever good output/ evidence already exists.
        logger.error(
            "All %d requested cities failed; not writing output.", cities_requested
        )
        sys.exit(1)

    df = build_dataframe(readings)
    result_df = rank_and_filter(
        df,
        sort_by=args.sort_by,
        ascending=args.ascending,
        max_humidity=args.max_humidity,
    )

    print(result_df.to_string(index=False))

    output_path = Path(args.output) if args.output else Path(settings.output_dir) / "weather_data.csv"
    save_csv(result_df, output_path)

    if args.chart:
        # Chart lives next to wherever the CSV actually landed, so --output
        # and the chart location can never silently disagree.
        chart_path = output_path.parent / "weather_chart.png"
        plot_temperature_bar(result_df, chart_path)


if __name__ == "__main__":
    main()
