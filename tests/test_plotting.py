import matplotlib

matplotlib.use("Agg")

from matplotlib import pyplot as plt
import pandas as pd

from hex_qec.plotting import (
    plot_adaptive_knill_ler_vs_error,
    plot_adaptive_knill_ler_vs_mean_rounds,
    plot_fixed_knill_ler,
)


def _tables():
    fixed = pd.DataFrame(
        [
            {"physical_error": 0.001, "distance": 3, "rounds": 1, "decoder": "mwpm", "logical_error_rate": 0.01, "ler_ci_low": 0.0, "ler_ci_high": 0.02},
            {"physical_error": 0.002, "distance": 3, "rounds": 1, "decoder": "mwpm", "logical_error_rate": 0.02, "ler_ci_low": 0.01, "ler_ci_high": 0.03},
            {"physical_error": 0.001, "distance": 5, "rounds": 1, "decoder": "mwpm", "logical_error_rate": 0.005, "ler_ci_low": 0.0, "ler_ci_high": 0.01},
            {"physical_error": 0.002, "distance": 5, "rounds": 1, "decoder": "mwpm", "logical_error_rate": 0.01, "ler_ci_low": 0.002, "ler_ci_high": 0.02},
            {"physical_error": 0.001, "distance": 3, "rounds": 3, "decoder": "mwpm", "logical_error_rate": 0.004, "ler_ci_low": 0.0, "ler_ci_high": 0.01},
            {"physical_error": 0.002, "distance": 3, "rounds": 3, "decoder": "mwpm", "logical_error_rate": 0.008, "ler_ci_low": 0.001, "ler_ci_high": 0.015},
        ]
    )
    adaptive = pd.DataFrame(
        [
            {"physical_error": 0.001, "distance": 3, "short_rounds": 1, "long_rounds": 3, "threshold": 0.001, "mean_effective_rounds": 2.0, "logical_error_rate": 0.01, "ler_ci_low": 0.0, "ler_ci_high": 0.02, "confidence_aggregator": "max_dem_only"},
            {"physical_error": 0.002, "distance": 3, "short_rounds": 1, "long_rounds": 3, "threshold": 0.001, "mean_effective_rounds": 2.2, "logical_error_rate": 0.02, "ler_ci_low": 0.01, "ler_ci_high": 0.03, "confidence_aggregator": "max_dem_only"},
            {"physical_error": 0.001, "distance": 5, "short_rounds": 2, "long_rounds": 5, "threshold": 0.001, "mean_effective_rounds": 3.0, "logical_error_rate": 0.005, "ler_ci_low": 0.0, "ler_ci_high": 0.01, "confidence_aggregator": "max_dem_only"},
            {"physical_error": 0.002, "distance": 5, "short_rounds": 2, "long_rounds": 5, "threshold": 0.001, "mean_effective_rounds": 3.2, "logical_error_rate": 0.01, "ler_ci_low": 0.002, "ler_ci_high": 0.02, "confidence_aggregator": "max_dem_only"},
            {"physical_error": 0.001, "distance": 3, "short_rounds": 1, "long_rounds": 3, "threshold": 0.01, "mean_effective_rounds": 1.5, "logical_error_rate": 0.008, "ler_ci_low": 0.0, "ler_ci_high": 0.015, "confidence_aggregator": "max_dem_only"},
        ]
    )
    return fixed, adaptive


def test_plotting_groups_fixed_results_by_round_and_colors_distance(tmp_path):
    fixed, _ = _tables()
    figures = plot_fixed_knill_ler(fixed, output_dir=tmp_path)
    assert set(figures) == {1, 3}
    assert (tmp_path / "fixed_knill_ler_vs_physical_error_rounds_1.png").exists()
    assert len(figures[1][1].get_legend_handles_labels()[1]) == 2
    excluded = {
        matplotlib.colors.to_rgba(plt.get_cmap("tab10")(index))
        for index in (1, 8)
    }
    assert all(
        matplotlib.colors.to_rgba(line.get_color()) not in excluded
        for line in figures[1][1].lines
    )


def test_plotting_adaptive_error_creates_one_figure_per_threshold(tmp_path):
    _, adaptive = _tables()
    figures = plot_adaptive_knill_ler_vs_error(adaptive, output_dir=tmp_path)
    assert set(figures) == {0.001, 0.01}
    assert (tmp_path / "adaptive_knill_ler_vs_physical_error_threshold_0.001.png").exists()
    assert len(figures[0.001][1].get_legend_handles_labels()[1]) == 2


def test_plotting_adaptive_mean_rounds_can_fix_physical_error(tmp_path):
    _, adaptive = _tables()
    figures = plot_adaptive_knill_ler_vs_mean_rounds(
        adaptive, physical_error=0.001, output_dir=tmp_path
    )
    assert set(figures) == {3, 5}
    assert len(figures[3][1].get_legend_handles_labels()[1]) == 2
    assert all(value == 2.0 for value in figures[3][1].lines[0].get_xdata())
    assert (tmp_path / "adaptive_knill_ler_vs_mean_rounds_distance_3.png").exists()
