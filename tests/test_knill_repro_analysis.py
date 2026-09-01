import json
import math
from pathlib import Path

from validation.analyze_knill_repro import analyze_suite
from validation.knill_repro_common import (
    comparison_rows,
    newcombe_risk_difference_interval,
    write_csv_rows,
)


RAW_FIELDS = [
    "workflow", "distance", "physical_error", "replicate", "shots",
    "logical_errors", "config_signature",
]


def _write_raw(path: Path, rows):
    write_csv_rows(path, rows, RAW_FIELDS)


def _pair_rows(legacy_errors, new_errors, *, shots=100_000, signature="sig"):
    return [
        {
            "workflow": "legacy_static", "distance": 3,
            "physical_error": 0.001, "replicate": 0, "shots": shots,
            "logical_errors": legacy_errors, "config_signature": signature,
        },
        {
            "workflow": "stateful_fixed", "distance": 3,
            "physical_error": 0.001, "replicate": 0, "shots": shots,
            "logical_errors": new_errors, "config_signature": signature,
        },
    ]


def test_newcombe_interval_has_new_minus_legacy_sign_and_swap_symmetry():
    interval = newcombe_risk_difference_interval(10, 100, 30, 100)
    swapped = newcombe_risk_difference_interval(30, 100, 10, 100)
    assert interval[0] < 0.2 < interval[1]
    assert interval[0] > 0
    assert math.isclose(interval[0], -swapped[1])
    assert math.isclose(interval[1], -swapped[0])


def test_newcombe_handles_zero_errors_and_unequal_shots():
    low, high = newcombe_risk_difference_interval(0, 10_000, 0, 20_000)
    assert math.isfinite(low) and math.isfinite(high)
    assert low <= 0 <= high
    low, high = newcombe_risk_difference_interval(2, 100, 4, 300)
    assert math.isfinite(low) and math.isfinite(high)


def test_analyzer_equivalence_is_separate_from_fisher_status(tmp_path: Path):
    raw = tmp_path / "fixed_workflow_raw.csv"
    _write_raw(raw, _pair_rows(100, 101))
    result = analyze_suite(
        "fixed", raw_path=raw, output_dir=tmp_path,
        equivalence_margin=0.01, min_total_errors=10,
    )["report"]
    point = result["points"][0]
    assert point["equivalence"]["status"] == "equivalent"
    assert point["validation_status"] == "validated_equivalent"
    assert point["risk_difference"]["estimate"] > 0

    small_raw = tmp_path / "small_fixed_workflow_raw.csv"
    _write_raw(small_raw, _pair_rows(1, 1, shots=10))
    small = analyze_suite(
        "fixed", raw_path=small_raw, output_dir=tmp_path / "small",
        equivalence_margin=0.01, min_total_errors=0,
    )["report"]["points"][0]
    assert small["fisher"]["status"] == "compatible"
    assert small["equivalence"]["status"] == "equivalence_not_demonstrated"
    assert small["validation_status"] == "inconclusive_equivalence_not_demonstrated"


def test_analyzer_difference_and_json_sanitization(tmp_path: Path):
    raw = tmp_path / "fixed_workflow_raw.csv"
    _write_raw(raw, _pair_rows(1, 100, shots=1000))
    result = analyze_suite(
        "fixed", raw_path=raw, output_dir=tmp_path,
        equivalence_margin=0.001, min_total_errors=0,
    )
    report = result["report"]
    assert report["overall_status"] == "difference_detected"
    assert report["points"][0]["validation_status"] == "difference_detected"
    loaded = json.loads(result["json_path"].read_text())
    serialized = result["json_path"].read_text()
    assert loaded["methodology"]["equivalence_margin"] == 0.001
    assert "NaN" not in serialized and "Infinity" not in serialized


def test_analyzer_reuses_existing_fisher_and_reports_files(tmp_path: Path):
    raw = tmp_path / "fixed_workflow_raw.csv"
    rows = _pair_rows(4, 8, shots=256)
    _write_raw(raw, rows)
    expected = comparison_rows(
        rows,
        legacy_workflow="legacy_static",
        new_workflow="stateful_fixed",
        distances=[3], physical_errors=[0.001], alpha=0.05,
        min_total_errors=0,
    )[0]
    result = analyze_suite(
        "fixed", raw_path=raw, output_dir=tmp_path,
        equivalence_margin=0.1, min_total_errors=0,
    )
    point = result["report"]["points"][0]
    assert point["fisher"]["table"] == [[4, 252], [8, 248]]
    assert point["fisher"]["raw_p_value"] == expected["raw_p_value"]
    assert point["fisher"]["holm_adjusted_p_value"] == expected["adjusted_p_value"]
    assert result["json_path"].exists()
    assert result["markdown_path"].exists()
    assert "equivalence margin" in result["markdown_path"].read_text().lower()


def test_analyzer_reports_incomplete_and_rejects_mixed_signatures(tmp_path: Path):
    raw = tmp_path / "fixed_workflow_raw.csv"
    _write_raw(raw, [
        _pair_rows(1, 2, signature="sig-a")[0],
    ])
    report = analyze_suite(
        "fixed", raw_path=raw, output_dir=tmp_path,
        equivalence_margin=0.1, distances=[3], physical_errors=[0.001],
    )["report"]
    assert report["overall_status"] == "incomplete"
    assert report["points"][0]["missing_workflows"] == ["stateful_fixed"]

    mixed = tmp_path / "mixed.csv"
    _write_raw(mixed, _pair_rows(1, 2, signature="sig-a") + _pair_rows(1, 2, signature="sig-b"))
    try:
        analyze_suite(
            "fixed", raw_path=mixed, output_dir=tmp_path / "mixed",
            equivalence_margin=0.1,
        )
    except ValueError as error:
        assert "multiple config signatures" in str(error)
    else:
        raise AssertionError("mixed config signatures must not be pooled silently")

