import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from validation.knill_repro_common import (
    ValidationConfig,
    comparison_rows,
    fisher_table,
    holm_bonferroni,
    pooled_counts,
    parameter_complete,
    raw_row_key,
    stable_seed,
    wilson_interval,
    write_csv_rows,
    read_csv_rows,
)
from validation.plot_knill_repro import plot_comparison
from hex_qec.modularisation import AdaptiveSERounds
from hex_qec.simulation import AdaptivePolicyContext, AlwaysLongPolicy


def test_stable_seed_is_parameter_derived():
    first = stable_seed(12, "suite", 5, 0.001, 2)
    assert first == stable_seed(12, "suite", 5, 0.001, 2)
    assert first != stable_seed(12, "suite", 5, 0.003, 2)
    assert first != stable_seed(12, "other", 5, 0.001, 2)


def test_wilson_interval_and_fisher_table():
    low, high = wilson_interval(0, 100)
    assert low <= 1e-15
    assert 0 < high < 0.05
    assert fisher_table(2, 100, 3, 120) == [[2, 98], [3, 117]]


def test_pooling_and_holm_adjustment():
    rows = [
        {"workflow": "legacy", "shots": "10", "logical_errors": "1"},
        {"workflow": "legacy", "shots": "20", "logical_errors": "2"},
        {"workflow": "new", "shots": "10", "logical_errors": "3"},
    ]
    assert pooled_counts(rows, "legacy") == (30, 3)
    assert holm_bonferroni([0.01, 0.04, 0.2]) == [0.03, 0.08, 0.2]


def test_comparison_reports_underpowered_and_ratio():
    rows = []
    for workflow, errors in (("legacy", 0), ("new", 1)):
        rows.append({
            "workflow": workflow,
            "distance": "3",
            "physical_error": "0.001",
            "shots": "256",
            "logical_errors": str(errors),
        })
    result = comparison_rows(
        rows,
        legacy_workflow="legacy",
        new_workflow="new",
        distances=[3],
        physical_errors=[0.001],
        alpha=0.05,
        min_total_errors=10,
    )
    assert result[0]["statistical_status"] == "underpowered"
    assert np.isinf(result[0]["ler_ratio"])


def test_checkpoint_round_trip_and_deduplication(tmp_path: Path):
    row = {
        "workflow": "legacy", "distance": 3, "physical_error": 0.0,
        "replicate": 0, "config_signature": "abc", "shots": 256,
        "logical_errors": 0,
    }
    path = tmp_path / "rows.csv"
    write_csv_rows(path, [row], list(row))
    loaded = read_csv_rows(path)
    assert raw_row_key(loaded[0]) == raw_row_key(row)
    assert len({raw_row_key(row), raw_row_key(loaded[0])}) == 1
    assert parameter_complete(
        [row, {**row, "workflow": "new"}],
        distance=3,
        physical_error=0.0,
        replicate=0,
        config_signature="abc",
        workflows=("legacy", "new"),
    )


def test_configuration_uses_distance_rounds_and_surface_ordering(tmp_path: Path):
    config = ValidationConfig(
        distances=(5,), physical_errors=(0.001,), shots=256,
        output_dir=tmp_path,
    )
    assert config.state_prep_rounds_are_distance is True
    assert config.surface_code is True
    assert config.num_teleportations == 1


def test_forced_long_configuration_has_one_short_and_distance_total_rounds():
    schedule = AdaptiveSERounds(1, 5, AlwaysLongPolicy())
    assert schedule.short_rounds == 1
    assert schedule.long_rounds == 5
    assert schedule.long_rounds - schedule.short_rounds == 4
    np.testing.assert_array_equal(
        schedule.policy.should_extend(
            None, context=AdaptivePolicyContext(batch_size=3)
        ),
        np.ones(3, dtype=bool),
    )


def test_plotting_uses_pooled_rows_without_simulation(tmp_path: Path):
    rows = [
        {
            "distance": "3", "physical_error": "0.001",
            "legacy_shots": "256", "legacy_ler": "0.01",
            "legacy_ci_low": "0.002", "legacy_ci_high": "0.03",
            "new_shots": "256", "new_ler": "0.02",
            "new_ci_low": "0.005", "new_ci_high": "0.04",
        }
    ]
    png, pdf = plot_comparison(
        rows,
        tmp_path / "figure",
        legacy_label="legacy",
        new_label="new",
    )
    assert png.exists() and png.stat().st_size > 0
    assert pdf.exists() and pdf.stat().st_size > 0
