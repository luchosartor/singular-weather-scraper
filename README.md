# Weather Scraper

A small Python service that fetches current weather for a set of cities from
the [Open-Meteo](https://open-meteo.com/) API, processes it with pandas, and
exports it as a CSV and a bar chart. It also exposes the same pipeline through
a small FastAPI service.

## Overview

- Fetches current temperature, humidity, and wind speed for a configurable
  list of cities (10 default cities, or any city name resolved through
  geocoding).
- Fetches concurrently with a client-side rate limiter so the API isn't
  hammered.
- Retries transient upstream failures (429/5xx) with backoff.
- Normalizes/validates the upstream response defensively before trusting it.
- Produces `output/weather_data.csv` and `output/weather_chart.png`.
- Exposes the same pipeline via a FastAPI app (`/health`, `/weather`,
  `/weather/csv`, `/weather/chart`, `/weather/refresh`).

## Setup

Requires **Python 3.10+** (the codebase uses `X | None` union type hints).
From the project root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# Running the tests also needs responses/pytest/httpx:
pip install -r requirements-dev.txt
cp .env.example .env   # optional, defaults work out of the box
```

The package lives under `src/weather_scraper`. Rather than installing it in
editable mode, every command below is run with `PYTHONPATH=src` from the
project root - that's the convention used throughout this README.

## Running the CLI

```bash
# Default: the 10 built-in cities, sorted by temperature descending.
PYTHONPATH=src python -m weather_scraper.cli

# Specific cities (geocoded by name), sorted by humidity ascending.
PYTHONPATH=src python -m weather_scraper.cli --cities "Lisbon,Oslo,Nairobi" --sort-by humidity --ascending

# Drop anything with humidity above 70%, write CSV elsewhere, skip the chart.
PYTHONPATH=src python -m weather_scraper.cli --max-humidity 70 --output output/dry_cities.csv --no-chart
```

If `--cities` is omitted and the CLI is run in an interactive terminal, it
will prompt for a comma-separated list of city names (press Enter to use the
10 defaults). When run non-interactively (e.g. in CI) without `--cities`, it
uses the defaults directly.

## Running the API

Run from the **project root** (not `src/`) - `output_dir` and `.env` are
resolved relative to the current working directory, and `PYTHONPATH=src` is
how `weather_scraper` gets found either way:

```bash
PYTHONPATH=src uvicorn weather_scraper.api:app --reload
```

```bash
curl http://127.0.0.1:8000/health

curl -X POST http://127.0.0.1:8000/weather/refresh \
  -H "Content-Type: application/json" \
  -d '{"cities": ["Lisbon", "Oslo"]}'

# Or omit the body (or send {}) to refresh with the 10 default cities:
curl -X POST http://127.0.0.1:8000/weather/refresh

curl http://127.0.0.1:8000/weather
curl http://127.0.0.1:8000/weather/csv -o weather_data.csv
curl http://127.0.0.1:8000/weather/chart -o weather_chart.png
```

`/weather`, `/weather/csv` and `/weather/chart` all 404 until
`/weather/refresh` has been called at least once in the running process.
State (the dataframe, and the CSV/PNG bytes for the two endpoints above) is
kept **in memory only** - it is never written to disk, and a refresh never
touches the repo's own `output/weather_data.csv` / `output/weather_chart.png`
(those are the CLI's evidence files, generated separately; see "Running the
CLI" above). If a refresh fetches 0 cities successfully, the previous
in-memory data (if any) is kept rather than being wiped by an empty result,
and `/health` reports `"status": "degraded"` instead of `"ok"`.

## Running tests

```bash
pytest
```

(`pyproject.toml` sets `pythonpath = ["src"]` for pytest, so plain `pytest`
works; `PYTHONPATH=src pytest` also works if you prefer being explicit.)

No test makes a real network call - `requests` is mocked with the
`responses` library (or `unittest.mock.patch`) throughout.

## Output interpretation

`weather_data.csv` columns:

| Column | Meaning |
|---|---|
| `City` | City name as resolved (default list or geocoded). |
| `Temperature (C)` / `Temperature (F)` | Current temperature, Celsius and the derived Fahrenheit. |
| `Humidity (%)` | Current relative humidity. |
| `Wind Speed (m/s)` / `Wind Speed (mph)` | Current wind speed, m/s and the derived mph. |
| `Rank` | Position after sorting/filtering (per `--sort-by`/`--ascending`/`--max-humidity`); ties share the same rank. |

All numeric columns are rounded to 2 decimals before export (the raw
derived values, e.g. mph, otherwise carry long floating-point noise like
`8.388525000000001`).

`weather_chart.png` is a bar chart of `Temperature (C)` by city, sorted
descending, with the value labeled above each bar.

## Design notes

This is a small exercise, but a few choices were made to mirror problems
that show up when ingesting data from many external sources (which is the
actual shape of Singular's problem with 1200+ ad networks), without
over-engineering a weather script:

- **Provider abstraction** (`providers/base.py`, `providers/open_meteo.py`):
  the rest of the pipeline only knows about `WeatherProvider.fetch()`, never
  about Open-Meteo's specific request/response shape. Swapping or adding a
  second weather source wouldn't touch `service.py`, `cli.py`, or `api.py`.
- **Defensive normalization**: the Open-Meteo response is validated field by
  field before being trusted (missing fields raise a typed `ProviderError`
  instead of a raw `KeyError`/`TypeError` surfacing somewhere unrelated).
  External APIs - weather or ad networks alike - don't always return what
  their docs promise.
- **Rate limiting + concurrency**: cities are fetched concurrently (a thread
  pool) for latency, but every outbound call (weather fetches *and*
  geocoding lookups, both against Open-Meteo) acquires one shared
  `RateLimiter` instance before it goes out, so concurrency doesn't turn
  into a burst that gets throttled or blocked upstream. One caveat worth
  being upfront about: that's the *initial* request per call - the
  automatic retries that `urllib3`'s `Retry` adapter fires on a 429/5xx are
  handled below our code and don't individually re-acquire the limiter
  (they do get their own inter-attempt backoff from `retry_backoff_factor`,
  just not a cross-thread shared one). A single city's `ProviderError`
  doesn't fail the whole batch - but a bug (anything other than the
  provider's own typed error) is intentionally left to propagate rather
  than being silently swallowed.
- **Health endpoint**: `/health` reports the last run time, the last
  success rate, and a `status` of `"ok"`/`"degraded"` derived from it - a
  minimal signal for anyone (or anything) watching whether the ingestion
  pipeline is actually producing fresh, complete data, not just "the
  process is up."

None of this is meant to look more sophisticated than it is - it's a direct,
small-scale analogy to the real problem, not a proposal for how Singular's
actual ingestion system should work.

## Development process

This was built with Claude Code, splitting the work into two cooperating
roles instead of one long freeform session: a planner that wrote a precise
implementation brief, a `coder` agent that implemented it, and a `leader`
agent that reviewed the result adversarially - reading the code, running the
tests itself, and actually exercising the CLI and the API, not just skimming
the diff - before anything was accepted.

Two review rounds happened before this was considered done. The first one
caught real bugs, not style nits: a malformed field in the upstream response
(e.g. a non-numeric value) crashed the *entire* batch instead of just that
one city; the FastAPI layer was overwriting the same CSV/PNG files kept in
this repo as evidence, and serving stale data as a 200 where a 404 was
expected; the documented command for running the API wrote output to the
wrong directory; and a run where every city failed still exited successfully
after silently wiping the previous output. All four were fixed and
re-verified by a second review pass - including re-running the tests, the
CLI, and the API by hand - before this was submitted.

The agent configurations themselves aren't included in this repo (they're
personal tooling, not part of the solution), but this section exists so the
process stays transparent to whoever reviews it.

## Possible next steps

Out of scope for this exercise, but worth naming as what a real system would
need next:

- **Deduplication** of readings if the same city is requested/fetched more
  than once in overlapping runs.
- **Incremental loading** - persisting historical readings (e.g. to a
  database) instead of overwriting the single CSV/chart on every run, so
  trends over time could be queried.
