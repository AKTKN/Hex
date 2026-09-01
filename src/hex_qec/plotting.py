"""Plots for fixed-round and two-level adaptive Knill sweep results.

The sweep drivers write one row per simulation point.  This module keeps the
plot layout and filtering rules out of the notebook so the same result tables
can be plotted from a script.  ``pandas`` is intentionally not imported here:
the functions accept a pandas-like table and only import Matplotlib when a
plot is requested, keeping the core package import lightweight.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any


# The default tab10 yellow/olive/orange/pink entries are unnecessarily bright
# on the white notebook background. Keep the darker, easier-to-distinguish
# tab10 entries for both distance and threshold encodings.
_SAFE_TAB10_INDICES = (0, 2, 3, 4, 5, 7, 9)


def _pyplot() -> Any:
    """Import Matplotlib lazily because plotting is an optional capability."""

    import matplotlib.pyplot as plt

    return plt


def _require_columns(table: Any, columns: Iterable[str]) -> None:
    available = set(table.columns)
    missing = sorted(set(columns) - available)
    if missing:
        raise ValueError(f"result table is missing required columns: {missing}")


def _values(table: Any, column: str) -> list[Any]:
    return sorted(table[column].dropna().unique().tolist())


def _selected(values: Iterable[Any] | None, available: list[Any]) -> list[Any]:
    if values is None:
        return available
    wanted = list(values)
    return [value for value in wanted if value in available]


def _filter(table: Any, **filters: Any) -> Any:
    view = table
    for column, value in filters.items():
        if value is None:
            continue
        if isinstance(value, (list, tuple, set, frozenset)):
            view = view[view[column].isin(value)]
        else:
            view = view[view[column] == value]
    return view


def _palette(values: Iterable[Any], cmap_name: str) -> Mapping[Any, Any]:
    plt = _pyplot()
    ordered = list(values)
    cmap = plt.get_cmap(cmap_name)
    if cmap_name == "tab10":
        colors = [cmap(index) for index in _SAFE_TAB10_INDICES]
        return {
            value: colors[index % len(colors)]
            for index, value in enumerate(ordered)
        }
    if len(ordered) == 1:
        positions = [0.5]
    else:
        positions = [index / (len(ordered) - 1) for index in range(len(ordered))]
    return {value: cmap(position) for value, position in zip(ordered, positions)}


def _safe_token(value: Any) -> str:
    token = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value))
    return token.strip("-") or "value"


def _save_figure(figure: Any, output_dir: str | Path | None, filename: str) -> None:
    if output_dir is None:
        return
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    figure.savefig(directory / filename, dpi=300, bbox_inches="tight")


def _plot_ler_curve(
    axis: Any,
    group: Any,
    *,
    x_column: str,
    label: str,
    color: Any,
    linestyle: str = "-",
    marker: str = "o",
) -> None:
    """Plot a sorted curve, using Wilson intervals when they are available."""

    import numpy as np

    group = group.sort_values(x_column)
    x = group[x_column].to_numpy(dtype=float)
    y = group["logical_error_rate"].to_numpy(dtype=float)
    valid = np.isfinite(x) & np.isfinite(y)
    if not np.any(valid):
        return
    x, y = x[valid], y[valid]

    if {"ler_ci_low", "ler_ci_high"}.issubset(group.columns):
        low = group["ler_ci_low"].to_numpy(dtype=float)[valid]
        high = group["ler_ci_high"].to_numpy(dtype=float)[valid]
        interval_valid = np.isfinite(low) & np.isfinite(high)
        if np.all(interval_valid):
            axis.errorbar(
                x,
                y,
                yerr=[np.maximum(0.0, y - low), np.maximum(0.0, high - y)],
                color=color,
                linestyle=linestyle,
                marker=marker,
                label=label,
                capsize=2,
            )
            return
    axis.plot(
        x,
        y,
        color=color,
        linestyle=linestyle,
        marker=marker,
        label=label,
    )


def _finish(axis: Any, *, title: str, xlabel: str) -> None:
    axis.set_title(title)
    axis.set_xlabel(xlabel)
    axis.set_ylabel("logical error rate")
    axis.set_yscale("log")
    axis.grid(True, which="both", alpha=0.25)
    handles, labels = axis.get_legend_handles_labels()
    if handles:
        axis.legend()


def plot_fixed_knill_ler(
    table: Any,
    *,
    rounds: Iterable[Any] | None = None,
    distances: Iterable[Any] | None = None,
    decoder: str | None = None,
    output_dir: str | Path | None = None,
    filename_prefix: str = "fixed_knill_ler_vs_physical_error",
) -> dict[Any, tuple[Any, Any]]:
    """Create one fixed-round figure per SE-round count.

    Distance determines the curve color.  If several decoders are present,
    they share the distance color and are distinguished by line style.
    The returned mapping is keyed by the SE-round count.
    """

    _require_columns(table, {"physical_error", "distance", "rounds", "logical_error_rate"})
    view = _filter(table, decoder=decoder)
    available_distances = _values(view, "distance")
    selected_distances = _selected(distances, available_distances)
    available_rounds = _values(view, "rounds")
    selected_rounds = _selected(rounds, available_rounds)
    view = _filter(view, distance=selected_distances)
    colors = _palette(selected_distances, "tab10")
    decoders = _values(view, "decoder") if "decoder" in view.columns else [None]
    linestyles = ["-", "--", ":", "-."]
    style = {name: linestyles[index % len(linestyles)] for index, name in enumerate(decoders)}
    plt = _pyplot()
    figures: dict[Any, tuple[Any, Any]] = {}

    for round_count in selected_rounds:
        round_view = _filter(view, rounds=round_count)
        figure, axis = plt.subplots(figsize=(7.5, 5.0))
        group_columns = ["distance"] + (["decoder"] if "decoder" in round_view.columns else [])
        for group_key, group in round_view.groupby(group_columns, dropna=False):
            if not isinstance(group_key, tuple):
                group_key = (group_key,)
            distance = group_key[0]
            decoder_name = group_key[1] if len(group_key) > 1 else None
            label = f"d={distance}"
            if len(decoders) > 1 and decoder_name is not None:
                label += f", {decoder_name}"
            _plot_ler_curve(
                axis,
                group,
                x_column="physical_error",
                label=label,
                color=colors[distance],
                linestyle=style.get(decoder_name, "-"),
            )
        _finish(axis, title=f"Fixed Knill: {round_count} SE rounds", xlabel="physical error rate")
        figure.tight_layout()
        _save_figure(
            figure,
            output_dir,
            f"{filename_prefix}_rounds_{_safe_token(round_count)}.png",
        )
        figures[round_count] = (figure, axis)
    return figures


def plot_adaptive_knill_ler_vs_error(
    table: Any,
    *,
    thresholds: Iterable[Any] | None = None,
    distances: Iterable[Any] | None = None,
    confidence_aggregator: str | None = None,
    output_dir: str | Path | None = None,
    filename_prefix: str = "adaptive_knill_ler_vs_physical_error",
) -> dict[Any, tuple[Any, Any]]:
    """Create one adaptive LER-vs-error figure for each threshold.

    Every distance/``(short_rounds, long_rounds)`` schedule is a separate
    curve.  Distance controls color; schedules at the same distance use
    different line styles.
    """

    _require_columns(
        table,
        {
            "physical_error",
            "distance",
            "short_rounds",
            "long_rounds",
            "threshold",
            "logical_error_rate",
        },
    )
    view = _filter(table, confidence_aggregator=confidence_aggregator)
    selected_distances = _selected(distances, _values(view, "distance"))
    selected_thresholds = _selected(thresholds, _values(view, "threshold"))
    view = _filter(view, distance=selected_distances)
    colors = _palette(selected_distances, "tab10")
    pairs = list(view[["short_rounds", "long_rounds"]].drop_duplicates().itertuples(index=False, name=None))
    linestyles = ["-", "--", ":", "-."]
    pair_style = {pair: linestyles[index % len(linestyles)] for index, pair in enumerate(sorted(pairs))}
    plt = _pyplot()
    figures: dict[Any, tuple[Any, Any]] = {}

    for threshold in selected_thresholds:
        threshold_view = _filter(view, threshold=threshold)
        figure, axis = plt.subplots(figsize=(8.5, 5.0))
        group_columns = ["distance", "short_rounds", "long_rounds"]
        for group_key, group in threshold_view.groupby(group_columns, dropna=False):
            distance, short_rounds, long_rounds = group_key
            pair = (short_rounds, long_rounds)
            _plot_ler_curve(
                axis,
                group,
                x_column="physical_error",
                label=f"d={distance}, ({short_rounds}, {long_rounds})",
                color=colors[distance],
                linestyle=pair_style[pair],
            )
        _finish(
            axis,
            title=f"Adaptive Knill: threshold={threshold:g}",
            xlabel="physical error rate",
        )
        figure.tight_layout()
        _save_figure(
            figure,
            output_dir,
            f"{filename_prefix}_threshold_{_safe_token(threshold)}.png",
        )
        figures[threshold] = (figure, axis)
    return figures


def plot_adaptive_knill_ler_vs_mean_rounds(
    table: Any,
    *,
    physical_error: float | None = None,
    thresholds: Iterable[Any] | None = None,
    distances: Iterable[Any] | None = None,
    confidence_aggregator: str | None = None,
    output_dir: str | Path | None = None,
    filename_prefix: str = "adaptive_knill_ler_vs_mean_rounds",
) -> dict[Any, tuple[Any, Any]]:
    """Create one adaptive LER-vs-mean-rounds figure for each distance.

    ``physical_error`` may pin the plot to one noise rate.  If it is omitted,
    all rates are shown with the same threshold color and a distinct line
    style/label for each physical error rate.
    """

    _require_columns(
        table,
        {
            "physical_error",
            "distance",
            "threshold",
            "mean_effective_rounds",
            "logical_error_rate",
        },
    )
    view = _filter(table, physical_error=physical_error, confidence_aggregator=confidence_aggregator)
    selected_distances = _selected(distances, _values(view, "distance"))
    selected_thresholds = _selected(thresholds, _values(view, "threshold"))
    view = _filter(view, distance=selected_distances, threshold=selected_thresholds)
    colors = _palette(selected_thresholds, "tab10")
    physical_errors = _values(view, "physical_error")
    linestyles = ["-", "--", ":", "-."]
    error_style = {
        value: linestyles[index % len(linestyles)]
        for index, value in enumerate(physical_errors)
    }
    plt = _pyplot()
    figures: dict[Any, tuple[Any, Any]] = {}

    for distance in selected_distances:
        distance_view = _filter(view, distance=distance)
        figure, axis = plt.subplots(figsize=(7.5, 5.0))
        group_columns = ["threshold"]
        if physical_error is None and len(physical_errors) > 1:
            group_columns.append("physical_error")
        for group_key, group in distance_view.groupby(group_columns, dropna=False):
            if not isinstance(group_key, tuple):
                group_key = (group_key,)
            threshold = group_key[0]
            label = f"threshold={threshold:g}"
            if len(group_key) > 1:
                label += f", p={group_key[1]:g}"
            _plot_ler_curve(
                axis,
                group,
                x_column="mean_effective_rounds",
                label=label,
                color=colors[threshold],
                linestyle=error_style.get(group_key[1], "-") if len(group_key) > 1 else "-",
            )
        error_label = "all physical error rates" if physical_error is None else f"p={physical_error:g}"
        _finish(
            axis,
            title=f"Adaptive Knill: d={distance}, {error_label}",
            xlabel="mean effective SE rounds",
        )
        figure.tight_layout()
        _save_figure(
            figure,
            output_dir,
            f"{filename_prefix}_distance_{_safe_token(distance)}.png",
        )
        figures[distance] = (figure, axis)
    return figures


__all__ = [
    "plot_fixed_knill_ler",
    "plot_adaptive_knill_ler_vs_error",
    "plot_adaptive_knill_ler_vs_mean_rounds",
]
