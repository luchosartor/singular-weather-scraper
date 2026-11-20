"""Chart generation for the collected weather data."""

import io
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # Headless backend: no display needed to render a PNG.
import matplotlib.pyplot as plt
import pandas as pd


def _build_temperature_bar_figure(df: pd.DataFrame):
    """Shared drawing logic for both the file-based and in-memory renderers."""
    sorted_df = df.sort_values(by="Temperature (C)", ascending=False)

    fig, ax = plt.subplots(figsize=(10, 6))
    bars = ax.bar(sorted_df["City"], sorted_df["Temperature (C)"], color="#4C72B0")

    ax.set_title("Current Temperature by City")
    ax.set_xlabel("City")
    ax.set_ylabel("Temperature (C)")
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right")

    for bar in bars:
        height = bar.get_height()
        ax.annotate(
            f"{height:.1f}",
            xy=(bar.get_x() + bar.get_width() / 2, height),
            xytext=(0, 3),
            textcoords="offset points",
            ha="center",
            va="bottom",
        )

    return fig


def plot_temperature_bar(df: pd.DataFrame, output_path: Path) -> None:
    """Used by the CLI: writes the chart to disk at `output_path`."""
    fig = _build_temperature_bar_figure(df)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def render_temperature_bar_png(df: pd.DataFrame) -> bytes:
    """Used by the API: renders the same chart entirely in memory.

    The API keeps the chart in AppState rather than writing it to disk, so
    it never touches (and never overwrites) the output/ files the CLI run
    commits as evidence.
    """
    fig = _build_temperature_bar_figure(df)
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    return buffer.getvalue()
