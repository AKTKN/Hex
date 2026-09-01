"""Post-process Knill validation CSVs into equivalence reports.

This module never constructs or runs a quantum circuit.  It only consumes raw
CSV output from the existing validation runners.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .knill_repro_common import (
    DEFAULT_MIN_TOTAL_ERRORS_FOR_INFERENCE,
    comparison_rows,
    fisher_table,
    newcombe_risk_difference_interval,
    read_csv_rows,
)


SUITES: dict[str, dict[str, str]] = {
    "fixed": {
        "raw_filename": "fixed_workflow_raw.csv",
        "legacy_workflow": "legacy_static",
        "new_workflow": "stateful_fixed",
        "report_stem": "fixed_workflow",
        "title": "Legacy static vs stateful fixed-round Knill",
    },
    "adaptive-forced-long": {
        "raw_filename": "adaptive_forced_long_raw.csv",
        "legacy_workflow": "legacy_static_fixed_d",
        "new_workflow": "adaptive_forced_long",
        "report_stem": "adaptive_forced_long",
        "title": "Legacy fixed-depth vs adaptive forced-long Knill",
    },
}


def _finite_or_none(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _json_safe(value: Any) -> Any:
    """Recursively convert NumPy/non-finite values to standard JSON values."""

    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "item"):
        return _json_safe(value.item())
    if isinstance(value, float):
        return _finite_or_none(value)
    return value


def _format(value: Any, digits: int = 6) -> str:
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return "—"
    if isinstance(value, float):
        return f"{value:.{digits}g}"
    return str(value)


def _read_raw(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"raw validation CSV not found: {path}")
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def _select_signature(
    rows: Sequence[Mapping[str, str]],
    workflow_names: Sequence[str],
    requested: str | None,
) -> tuple[str, list[dict[str, str]]]:
    relevant = [row for row in rows if row.get("workflow") in workflow_names]
    signatures = sorted({row.get("config_signature", "") for row in relevant})
    if not signatures:
        raise ValueError("raw CSV contains no rows for the selected workflow pair")
    if requested is not None:
        if requested not in signatures:
            raise ValueError(
                f"config signature {requested!r} not found; available signatures: {signatures}"
            )
        selected = requested
    elif len(signatures) != 1:
        raise ValueError(
            "raw CSV contains multiple config signatures; rerun with "
            f"--config-signature one of {signatures}"
        )
    else:
        selected = signatures[0]
    return selected, [row for row in relevant if row.get("config_signature", "") == selected]


def _available_points(rows: Iterable[Mapping[str, str]]) -> list[tuple[int, float]]:
    return sorted({(int(row["distance"]), float(row["physical_error"])) for row in rows})


def _requested_points(
    rows: Sequence[Mapping[str, str]],
    distances: Sequence[int] | None,
    physical_errors: Sequence[float] | None,
) -> list[tuple[int, float]]:
    if distances is None and physical_errors is None:
        return _available_points(rows)
    if distances is None or physical_errors is None:
        raise ValueError("provide both --distances and --physical-errors, or neither")
    return sorted({(int(distance), float(error)) for distance in distances for error in physical_errors})


def _point_rows(
    rows: Sequence[Mapping[str, str]], distance: int, physical_error: float
) -> list[Mapping[str, str]]:
    return [
        row for row in rows
        if int(row["distance"]) == distance
        and math.isclose(float(row["physical_error"]), physical_error)
    ]


def _replicate_count(rows: Sequence[Mapping[str, str]], workflow: str) -> int:
    return len({row.get("replicate", "") for row in rows if row.get("workflow") == workflow})


def _make_point(
    *,
    point: Mapping[str, Any] | None,
    raw_point_rows: Sequence[Mapping[str, str]],
    distance: int,
    physical_error: float,
    suite_config: Mapping[str, str],
    equivalence_margin: float,
    alpha: float,
    descriptive_confidence: float,
) -> dict[str, Any]:
    legacy_workflow = suite_config["legacy_workflow"]
    new_workflow = suite_config["new_workflow"]
    legacy_rows = [row for row in raw_point_rows if row.get("workflow") == legacy_workflow]
    new_rows = [row for row in raw_point_rows if row.get("workflow") == new_workflow]
    missing = []
    if not legacy_rows:
        missing.append(legacy_workflow)
    if not new_rows:
        missing.append(new_workflow)
    if missing:
        return {
            "distance": distance,
            "physical_error": physical_error,
            "missing_workflows": missing,
            "validation_status": "incomplete",
        }

    # comparison_rows is the existing source of truth for Fisher/Holm values.
    assert point is not None
    legacy_shots = int(point["legacy_shots"])
    legacy_errors = int(point["legacy_errors"])
    new_shots = int(point["new_shots"])
    new_errors = int(point["new_errors"])
    legacy_ler = float(point["legacy_ler"])
    new_ler = float(point["new_ler"])
    risk_difference = new_ler - legacy_ler
    descriptive_low, descriptive_high = newcombe_risk_difference_interval(
        legacy_errors,
        legacy_shots,
        new_errors,
        new_shots,
        descriptive_confidence,
    )
    equivalence_confidence = 1 - 2 * alpha
    equivalence_low, equivalence_high = newcombe_risk_difference_interval(
        legacy_errors,
        legacy_shots,
        new_errors,
        new_shots,
        equivalence_confidence,
    )
    equivalence_status = (
        "equivalent"
        if equivalence_low > -equivalence_margin
        and equivalence_high < equivalence_margin
        else "equivalence_not_demonstrated"
    )
    adjusted_p = float(point["adjusted_p_value"])
    old_status = str(point["statistical_status"])
    if adjusted_p < alpha:
        validation_status = "difference_detected"
    elif equivalence_status == "equivalent":
        validation_status = "validated_equivalent"
    elif old_status == "underpowered":
        validation_status = "inconclusive_low_event_count"
    else:
        validation_status = "inconclusive_equivalence_not_demonstrated"
    return {
        "distance": distance,
        "physical_error": physical_error,
        "replicates": {
            "legacy": _replicate_count(legacy_rows, legacy_workflow),
            "new": _replicate_count(new_rows, new_workflow),
        },
        "legacy": {
            "workflow": legacy_workflow,
            "shots": legacy_shots,
            "errors": legacy_errors,
            "ler": legacy_ler,
            "wilson_95_ci": [float(point["legacy_ci_low"]), float(point["legacy_ci_high"])],
        },
        "new": {
            "workflow": new_workflow,
            "shots": new_shots,
            "errors": new_errors,
            "ler": new_ler,
            "wilson_95_ci": [float(point["new_ci_low"]), float(point["new_ci_high"])],
        },
        "fisher": {
            "table": fisher_table(legacy_errors, legacy_shots, new_errors, new_shots),
            "raw_p_value": float(point["raw_p_value"]),
            "holm_adjusted_p_value": adjusted_p,
            "status": old_status,
        },
        "risk_difference": {
            "definition": "new_ler - legacy_ler",
            "estimate": risk_difference,
            "descriptive_confidence": descriptive_confidence,
            "descriptive_ci": [descriptive_low, descriptive_high],
            "equivalence_ci_confidence": equivalence_confidence,
            "equivalence_ci": [equivalence_low, equivalence_high],
        },
        "equivalence": {
            "margin": equivalence_margin,
            "status": equivalence_status,
        },
        "total_error_events": int(point["total_error_events"]),
        "ler_ratio": _finite_or_none(float(point["ler_ratio"])),
        "validation_status": validation_status,
    }


def _overall_status(points: Sequence[Mapping[str, Any]]) -> str:
    statuses = [str(point["validation_status"]) for point in points]
    if "difference_detected" in statuses:
        return "difference_detected"
    if "incomplete" in statuses:
        return "incomplete"
    if statuses and all(status == "validated_equivalent" for status in statuses):
        return "validated_equivalent"
    return "inconclusive"


def _markdown_report(report: Mapping[str, Any]) -> str:
    method = report["methodology"]
    lines = [
        f"# {report['title']}",
        "",
        f"**Overall status:** `{report['overall_status']}`  ",
        f"**Config signature:** `{report['config_signature'] or '(empty)'}`  ",
        f"**Equivalence margin:** ±{_format(method['equivalence_margin'])} absolute LER  ",
        "",
        "## Methodology",
        "",
        f"Difference testing uses {method['difference_test']} with "
        f"{method['multiple_testing']}. Risk difference is defined as "
        f"`{method['risk_difference']}`. Its intervals use the "
        f"{method['risk_difference_interval']}. Equivalence uses a "
        f"{method['equivalence_confidence']:.1%} CI, corresponding to the "
        f"CI-based TOST rule at α={method['alpha']}. Fisher non-significance "
        "does not establish equivalence.",
        "",
        "## Results",
        "",
        "| d | p | legacy errors/shots | new errors/shots | legacy LER | new LER | RD (new−legacy) | RD 95% CI | Fisher Holm p | equivalence CI | status |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|:---|",
    ]
    for point in report["points"]:
        if point["validation_status"] == "incomplete":
            lines.append(
                f"| {point['distance']} | {_format(point['physical_error'])} | — | — | — | — | — | — | — | — | incomplete ({', '.join(point['missing_workflows'])}) |"
            )
            continue
        legacy = point["legacy"]
        new = point["new"]
        risk = point["risk_difference"]
        fisher = point["fisher"]
        equivalence = point["equivalence"]
        lines.append(
            f"| {point['distance']} | {_format(point['physical_error'])} | "
            f"{legacy['errors']}/{legacy['shots']} | {new['errors']}/{new['shots']} | "
            f"{_format(legacy['ler'])} | {_format(new['ler'])} | "
            f"{_format(risk['estimate'])} | [{_format(risk['descriptive_ci'][0])}, {_format(risk['descriptive_ci'][1])}] | "
            f"{_format(fisher['holm_adjusted_p_value'])} | "
            f"[{_format(risk['equivalence_ci'][0])}, {_format(risk['equivalence_ci'][1])}] "
            f"(±{_format(equivalence['margin'])}) | {point['validation_status']} |"
        )
    lines.extend([
        "",
        "## Conclusion",
        "",
        _conclusion(report),
        "",
        "## Caveats",
        "",
        "Replicates are pooled as independent binomial counts. Equal numerical "
        "seeds do not make legacy and stateful/adaptive shots paired, so no "
        "McNemar test is used. `underpowered` is retained as the Fisher event "
        "count status; equivalence is decided separately from the requested "
        "risk-difference confidence interval.",
        "",
    ])
    return "\n".join(lines)


def _conclusion(report: Mapping[str, Any]) -> str:
    status = report["overall_status"]
    margin = report["methodology"]["equivalence_margin"]
    if status == "validated_equivalent":
        return (
            f"No statistically significant difference was detected and "
            f"equivalence within an absolute LER margin of ±{_format(margin)} "
            "was demonstrated at the specified confidence level for every "
            "tested parameter point."
        )
    if status == "difference_detected":
        return "At least one parameter point has a statistically significant difference after Holm correction."
    if status == "incomplete":
        return "The report is incomplete because at least one requested parameter point lacks a workflow result."
    return (
        f"No statistically significant difference was detected at every complete "
        f"point, but equivalence within ±{_format(margin)} was not demonstrated "
        "for every point at the requested confidence level."
    )


def analyze_suite(
    suite: str,
    *,
    raw_path: Path,
    output_dir: Path,
    equivalence_margin: float,
    alpha: float = 0.05,
    descriptive_confidence: float = 0.95,
    min_total_errors: int = DEFAULT_MIN_TOTAL_ERRORS_FOR_INFERENCE,
    config_signature: str | None = None,
    distances: Sequence[int] | None = None,
    physical_errors: Sequence[float] | None = None,
) -> dict[str, Any]:
    """Analyze one existing raw CSV and write JSON and Markdown reports."""

    if suite not in SUITES:
        raise ValueError(f"unknown suite {suite!r}; choose from {sorted(SUITES)}")
    if equivalence_margin <= 0:
        raise ValueError("equivalence_margin must be strictly positive")
    if not 0 < alpha < 0.5:
        raise ValueError("alpha must be strictly between 0 and 0.5")
    if not 0 < descriptive_confidence < 1:
        raise ValueError("descriptive_confidence must be strictly between 0 and 1")
    if min_total_errors < 0:
        raise ValueError("min_total_errors must be non-negative")
    suite_config = SUITES[suite]
    rows = _read_raw(raw_path)
    selected_signature, selected_rows = _select_signature(
        rows,
        (suite_config["legacy_workflow"], suite_config["new_workflow"]),
        config_signature,
    )
    points = _requested_points(selected_rows, distances, physical_errors)
    if not points:
        raise ValueError("no parameter points found in the selected raw CSV")
    complete_rows = [
        row for row in selected_rows
        if row.get("workflow") in (suite_config["legacy_workflow"], suite_config["new_workflow"])
    ]
    comparisons = comparison_rows(
        complete_rows,
        legacy_workflow=suite_config["legacy_workflow"],
        new_workflow=suite_config["new_workflow"],
        distances=[point[0] for point in points],
        physical_errors=[point[1] for point in points],
        alpha=alpha,
        min_total_errors=min_total_errors,
    )
    comparison_by_point = {
        (int(row["distance"]), float(row["physical_error"])): row
        for row in comparisons
    }
    report_points = [
        _make_point(
            point=comparison_by_point.get(point),
            raw_point_rows=_point_rows(selected_rows, *point),
            distance=point[0],
            physical_error=point[1],
            suite_config=suite_config,
            equivalence_margin=equivalence_margin,
            alpha=alpha,
            descriptive_confidence=descriptive_confidence,
        )
        for point in points
    ]
    report: dict[str, Any] = {
        "schema_version": 1,
        "suite": suite,
        "title": suite_config["title"],
        "source_raw_csv": str(raw_path),
        "config_signature": selected_signature,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "methodology": {
            "difference_test": "two-sided Fisher exact",
            "multiple_testing": "Holm-Bonferroni",
            "risk_difference": "new_ler - legacy_ler",
            "risk_difference_interval": "Newcombe hybrid score",
            "equivalence_test": "CI-based TOST-style equivalence",
            "alpha": alpha,
            "descriptive_confidence": descriptive_confidence,
            "equivalence_confidence": 1 - 2 * alpha,
            "equivalence_margin": equivalence_margin,
            "min_total_errors": min_total_errors,
        },
        "overall_status": _overall_status(report_points),
        "points": report_points,
    }
    report = _json_safe(report)
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = suite_config["report_stem"] + "_validation_report"
    json_path = output_dir / f"{stem}.json"
    markdown_path = output_dir / f"{stem}.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n")
    markdown_path.write_text(_markdown_report(report))
    return {
        "report": report,
        "json_path": json_path,
        "markdown_path": markdown_path,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--suite", choices=tuple(SUITES))
    selection.add_argument("--all", action="store_true")
    parser.add_argument("--equivalence-margin", type=float, required=True)
    parser.add_argument("--alpha", type=float, default=0.05)
    parser.add_argument("--descriptive-confidence", type=float, default=0.95)
    parser.add_argument(
        "--min-total-errors",
        type=int,
        default=DEFAULT_MIN_TOTAL_ERRORS_FOR_INFERENCE,
        help="event threshold used for the existing Fisher statistical status",
    )
    parser.add_argument("--config-signature")
    parser.add_argument("--output-dir", type=Path, default=Path("validation/results"))
    parser.add_argument("--input", type=Path, help="raw CSV path; valid only for a single suite")
    parser.add_argument("--distances", nargs="+", type=int)
    parser.add_argument("--physical-errors", nargs="+", type=float)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    suites = tuple(SUITES) if args.all else (args.suite,)
    if args.input is not None and args.all:
        raise SystemExit("--input can only be used with one --suite")
    for suite in suites:
        raw_path = args.input if args.input is not None else args.output_dir / SUITES[suite]["raw_filename"]
        result = analyze_suite(
            suite,
            raw_path=raw_path,
            output_dir=args.output_dir,
            equivalence_margin=args.equivalence_margin,
            alpha=args.alpha,
            descriptive_confidence=args.descriptive_confidence,
            min_total_errors=args.min_total_errors,
            config_signature=args.config_signature,
            distances=args.distances,
            physical_errors=args.physical_errors,
        )
        print(
            f"[{suite}] overall_status={result['report']['overall_status']} "
            f"JSON={result['json_path']} Markdown={result['markdown_path']}",
            flush=True,
        )


if __name__ == "__main__":
    main()
