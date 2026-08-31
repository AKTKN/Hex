"""Profile the current adaptive Knill executor at component boundaries.

This is an opt-in diagnostic runner.  It intentionally uses the existing
stateful execution path with ``batch_size=1`` and a handful of shots; it does
not optimize, batch, or otherwise alter adaptive execution.
"""

from __future__ import annotations

import argparse
import csv
import json
import platform
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import ldpc
import numpy as np
import pymatching
import stim
import stimbposd

from hex_qec.circuit_generation import get_parity_check_matrices
from hex_qec.decoders import (
    dem_only_max_confidence,
    make_bplsd_decoder_generator,
)
from hex_qec.modularisation import AdaptiveSERounds
from hex_qec.protocols import knill_online_offline_adaptive
from hex_qec.simulation import (
    AlwaysLongPolicy,
    AlwaysShortPolicy,
    ClusterLLRPolicy,
    TimingEvent,
    WallTimeProfiler,
)


BPLSD_OPTIONS = {
    "max_iter": 30,
    "bp_method": "minimum_sum",
    "lsd_method": "LSD_0",
    "lsd_order": 0,
    "always_run_lsd": True,
}

RAW_COLUMNS = [
    "shot_index",
    "phase",
    "policy",
    "distance",
    "physical_error",
    "short_rounds",
    "long_rounds",
    "used_long_pair",
    "section",
    "call_count",
    "wall_time_seconds",
    "git_sha",
    "python_version",
    "stim_version",
    "ldpc_version",
    "pymatching_version",
    "decoder_options",
    "seed",
]

SUMMARY_COLUMNS = [
    "phase",
    "section",
    "call_count_total",
    "time_total",
    "time_mean_per_shot",
    "time_mean_per_call",
    "time_min_per_shot",
    "time_max_per_shot",
    "percent_of_e2e",
    "inclusive",
]


def _version(module: Any) -> str:
    return str(getattr(module, "__version__", "unknown"))


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--distance", type=int, default=5)
    parser.add_argument("--physical-error", type=float, default=0.003)
    parser.add_argument("--short-rounds", type=int, default=1)
    parser.add_argument("--long-rounds", type=int, default=None)
    parser.add_argument("--num-shots", type=int, default=5)
    parser.add_argument("--warmup-shots", type=int, default=1)
    parser.add_argument("--seed", type=int, default=1234)
    parser.add_argument(
        "--policy",
        choices=("always-long", "always-short", "cluster-llr"),
        default="always-long",
    )
    parser.add_argument("--pauli", choices=("x", "z"), default="z")
    parser.add_argument("--confidence-threshold", type=float, default=0.01)
    parser.add_argument("--num-teleportations", type=int, default=1)
    parser.add_argument("--output-dir", type=Path, default=REPO_ROOT / "profiling" / "results")
    parser.add_argument(
        "--output-prefix",
        default="adaptive_walltime_shared_map_suffix",
        help="prefix for this optimized profile's output files",
    )
    return parser


def _format_float(value: float) -> str:
    return f"{value:.9g}"


def _event_rows(
    events: Iterable[TimingEvent],
    *,
    args: argparse.Namespace,
    policy_name: str,
    long_rounds: int,
    used_long_by_shot: dict[int, bool] | None = None,
    metadata: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    grouped: dict[tuple[int, str, str], dict[str, Any]] = {}
    for event in events:
        key = (event.shot_index, event.phase, event.section)
        entry = grouped.setdefault(key, {"call_count": 0, "wall_time_seconds": 0.0})
        entry["call_count"] += 1
        entry["wall_time_seconds"] += event.wall_time_seconds

    rows = []
    for (shot_index, phase, section), values in sorted(grouped.items()):
        rows.append({
            "shot_index": shot_index,
            "phase": phase,
            "policy": policy_name,
            "distance": args.distance,
            "physical_error": args.physical_error,
            "short_rounds": args.short_rounds,
            "long_rounds": long_rounds,
            "used_long_pair": (
                str(used_long_by_shot[shot_index]).lower()
                if used_long_by_shot is not None and shot_index in used_long_by_shot
                else "unknown"
            ),
            "section": section,
            "call_count": values["call_count"],
            "wall_time_seconds": _format_float(values["wall_time_seconds"]),
            "git_sha": (metadata or {}).get("git_sha", "unknown"),
            "python_version": (metadata or {}).get("python", "unknown"),
            "stim_version": (metadata or {}).get("stim", "unknown"),
            "ldpc_version": (metadata or {}).get("ldpc", "unknown"),
            "pymatching_version": (metadata or {}).get("pymatching", "unknown"),
            "decoder_options": json.dumps(BPLSD_OPTIONS, sort_keys=True),
            "seed": args.seed,
        })
    return rows


def _write_csv(path: Path, columns: list[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def _section_by_shot(events: Iterable[TimingEvent], phase: str) -> dict[str, dict[int, float]]:
    result: dict[str, dict[int, float]] = defaultdict(lambda: defaultdict(float))
    for event in events:
        if event.phase == phase:
            result[event.section][event.shot_index] += event.wall_time_seconds
    return result


def _summary_rows(
    events: Iterable[TimingEvent],
    *,
    measured_shots: int,
    warmup_shots: int,
) -> list[dict[str, Any]]:
    events = tuple(events)
    rows = []
    for phase, denominator in (("warmup", warmup_shots), ("measured", measured_shots), ("setup", 1)):
        by_section = _section_by_shot(events, phase)
        for section, by_shot in sorted(by_section.items()):
            values = list(by_shot.values())
            total = float(sum(values))
            calls = sum(
                1 for event in events if event.phase == phase and event.section == section
            )
            e2e_total = sum(
                event.wall_time_seconds
                for event in events
                if event.phase == phase and event.section == "shot.total_wall_time"
            )
            rows.append({
                "phase": phase,
                "section": section,
                "call_count_total": calls,
                "time_total": _format_float(total),
                "time_mean_per_shot": _format_float(total / denominator) if denominator else "0",
                "time_mean_per_call": _format_float(total / calls) if calls else "0",
                "time_min_per_shot": _format_float(min(values)) if values else "0",
                "time_max_per_shot": _format_float(max(values)) if values else "0",
                "percent_of_e2e": _format_float(100.0 * total / e2e_total) if e2e_total else "n/a",
                "inclusive": "yes" if section == "shot.total_wall_time" or "." in section else "no",
            })
    return rows


def _measured_totals(events: Iterable[TimingEvent]) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for event in events:
        if event.phase == "measured":
            totals[event.section] += event.wall_time_seconds
    return totals


def _sum_sections(totals: dict[str, float], names: Iterable[str]) -> float:
    return sum(totals.get(name, 0.0) for name in names)


def _top_level_rows(totals: dict[str, float], e2e_total: float) -> list[dict[str, Any]]:
    groups = {
        "physical Stim execution": [
            "shot.physical.short.zero",
            "shot.physical.short.plus",
            "shot.physical.long.zero",
            "shot.physical.long.plus",
        ],
        "measurement/reference/correction processing": [
            "shot.reconstruction.short",
            "shot.reconstruction.long",
        ],
        "decoder work": [
            "shot.decode.short.zero",
            "shot.decode.short.plus",
            "shot.decode.long.zero",
            "shot.decode.long.plus",
        ],
        "policy/control": [
            "shot.policy.zero",
            "shot.policy.plus",
            "shot.policy.synchronized_or",
        ],
        "state-preparation correction commit": [
            "shot.state_prep.correction_commit",
        ],
        "downstream Knill processing": [
            "shot.initial_preparation",
            "shot.downstream.cnot",
            "shot.downstream.bell_measurement",
            "shot.downstream.final_logical_measurement",
            "shot.final.detector_validation",
        ],
        "result/statistics bookkeeping": [
            "shot.result.bookkeeping",
        ],
    }
    rows = []
    for name, sections in groups.items():
        total = _sum_sections(totals, sections)
        rows.append({
            "component": name,
            "time_seconds": total,
            "percent_of_e2e": 100.0 * total / e2e_total if e2e_total else 0.0,
            "sections": ", ".join(sections),
        })
    return sorted(rows, key=lambda row: row["time_seconds"], reverse=True)


def _diagnostic_total(totals: dict[str, float], suffix: str) -> float:
    return sum(value for section, value in totals.items() if section.endswith(suffix))


def _make_report(
    path: Path,
    *,
    args: argparse.Namespace,
    long_rounds: int,
    policy_name: str,
    result: Any,
    events: tuple[TimingEvent, ...],
    metadata: dict[str, Any],
    warmup_shots: int,
) -> None:
    measured_events = tuple(event for event in events if event.phase == "measured")
    totals = _measured_totals(measured_events)
    e2e_total = totals.get("shot.total_wall_time", 0.0)
    e2e_mean = e2e_total / args.num_shots if args.num_shots else 0.0
    top_levels = _top_level_rows(totals, e2e_total)
    accounted = sum(row["time_seconds"] for row in top_levels)
    accounted_fraction = accounted / e2e_total if e2e_total else 0.0

    def timing_table(rows: list[dict[str, Any]]) -> str:
        lines = [
            "| component | seconds | % E2E |",
            "|---|---:|---:|",
        ]
        for row in rows:
            lines.append(
                f"| {row['component']} | {_format_float(row['time_seconds'])} | "
                f"{row['percent_of_e2e']:.2f}% |"
            )
        return "\n".join(lines)

    decoder_sections = [
        section for section in sorted(totals)
        if any(token in section for token in (".x_dem", ".z_dem", ".x_capacity", ".z_capacity"))
    ]
    correction_sections = [
        section for section in sorted(totals)
        if section.startswith("corrected_measurements.")
    ]
    setup_rows = [
        event for event in events
        if event.phase == "setup"
    ]
    setup_totals: dict[str, float] = defaultdict(float)
    for event in setup_rows:
        setup_totals[event.section] += event.wall_time_seconds

    def diagnostic_table(sections: list[str], source: dict[str, float]) -> str:
        lines = ["| section | seconds |", "|---|---:|"]
        for section in sections:
            lines.append(f"| `{section}` | {_format_float(source[section])} |")
        return "\n".join(lines) if len(lines) > 2 else "_No matching sections recorded._"

    total_calls = sum(1 for event in measured_events if event.section == "corrected_measurements.reference_sample")
    reference_time = sum(
        event.wall_time_seconds
        for event in measured_events
        if event.section == "corrected_measurements.reference_sample"
    )
    map_lookups = sum(1 for event in measured_events if event.section == "shot.correction_map.lookup")
    map_misses = sum(1 for event in measured_events if event.section == "shot.correction_map.fallback_miss")
    map_generation = sum(
        event.wall_time_seconds
        for event in measured_events
        if event.section == "shot.correction_map.fallback_generate"
    )
    setup_map_generation = sum(
        event.wall_time_seconds
        for event in events
        if event.phase == "setup" and event.section == "setup.correction_map.generate"
    )
    shot_totals = _section_by_shot(measured_events, "measured").get("shot.total_wall_time", {})
    ordered_shots = [shot_totals[index] for index in sorted(shot_totals)]
    first = ordered_shots[0] if ordered_shots else 0.0
    later = float(np.mean(ordered_shots[1:])) if len(ordered_shots) > 1 else 0.0
    used_long = None
    if result.per_shot is not None and "used_long_pair" in result.per_shot:
        used_long = result.per_shot["used_long_pair"].any(axis=1)
    used_long_text = "not available"
    if used_long is not None:
        states = ", ".join("long" if value else "short" for value in used_long)
        used_long_text = (
            f"{int(np.sum(used_long))}/{len(used_long)} measured pairs "
            f"(per-shot: [{states}])"
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as handle:
        handle.write("# Adaptive Knill wall-time profile\n\n")
        handle.write("This report profiles the correctness-first adaptive executor after executor-lifetime correction-map precomputation. "
                     "It is a few-shot runtime diagnosis, not an LER estimate.\n\n")
        handle.write("## Configuration\n\n")
        handle.write("```json\n")
        handle.write(json.dumps({
            "distance": args.distance,
            "physical_error": args.physical_error,
            "short_rounds": args.short_rounds,
            "long_rounds": long_rounds,
            "num_shots": args.num_shots,
            "warmup_shots": warmup_shots,
            "policy": policy_name,
            "pauli": args.pauli,
            "num_teleportations": args.num_teleportations,
            "seed": args.seed,
            "batch_size": 1,
            "decoder": "BP-LSD",
            "decoder_options": BPLSD_OPTIONS,
            "confidence_workflow": "DEM-only confidence aggregator",
            "surface_code": True,
        }, indent=2))
        handle.write("\n```\n\n")
        handle.write("## Software provenance\n\n")
        for key, value in metadata.items():
            handle.write(f"- `{key}`: `{value}`\n")
        handle.write("\n## End-to-end timing\n\n")
        handle.write(f"- Mean measured shot wall time: **{_format_float(e2e_mean)} s**\n")
        handle.write(f"- First measured shot: {_format_float(first)} s; later measured shots mean: {_format_float(later)} s.\n")
        handle.write(f"- Measured logical errors: {result.logical_errors}/{result.shots}.\n")
        handle.write(f"- Synchronized pair branch: {used_long}.\n\n")
        handle.write("### Non-overlapping major stages\n\n")
        handle.write(timing_table(top_levels))
        handle.write("\n\n")
        handle.write(f"Accounted time: **{accounted_fraction * 100:.2f}%**; unaccounted/other: **{(1 - accounted_fraction) * 100:.2f}%**. "
                     "Nested diagnostic sections are inclusive and are not included in this sum.\n\n")

        bottleneck_candidates = [
            (section, value)
            for section, value in totals.items()
            if section != "shot.total_wall_time"
            and not section.startswith("corrected_measurements.correction_maps")
            and not section.startswith("correction_map.cache_")
        ]
        bottleneck_candidates.sort(key=lambda item: item[1], reverse=True)
        handle.write("## Largest measured diagnostic/major-stage timers\n\n")
        handle.write("These entries are sorted by inclusive wall time and are **not additive**; they intentionally expose nested decoder and measurement diagnostics.\n\n")
        handle.write("| section | seconds | % E2E |\n|---|---:|---:|\n")
        for section, value in bottleneck_candidates[:5]:
            handle.write(f"| `{section}` | {_format_float(value)} | {100 * value / e2e_total if e2e_total else 0:.2f}% |\n")
        handle.write("\n")

        handle.write("## Decoder timing (inclusive diagnostics)\n\n")
        handle.write(diagnostic_table(decoder_sections, totals))
        short_dem = sum(
            value for section, value in totals.items()
            if section.startswith("shot.decode.short.") and (section.endswith(".x_dem") or section.endswith(".z_dem"))
        )
        short_capacity = sum(
            value for section, value in totals.items()
            if section.startswith("shot.decode.short.") and (section.endswith(".x_capacity") or section.endswith(".z_capacity"))
        )
        long_dem = sum(
            value for section, value in totals.items()
            if section.startswith("shot.decode.long.") and (section.endswith(".x_dem") or section.endswith(".z_dem"))
        )
        long_capacity = sum(
            value for section, value in totals.items()
            if section.startswith("shot.decode.long.") and (section.endswith(".x_capacity") or section.endswith(".z_capacity"))
        )
        handle.write(
            f"\nAggregate decoder timers: short DEM **{_format_float(short_dem)} s**, "
            f"short code-capacity **{_format_float(short_capacity)} s**, "
            f"long DEM **{_format_float(long_dem)} s**, "
            f"long code-capacity **{_format_float(long_capacity)} s**.\n"
        )
        handle.write("\n\n")
        handle.write("## `_corrected_measurements` timing (inclusive diagnostics)\n\n")
        handle.write(diagnostic_table(correction_sections, totals))
        handle.write("\n\n")
        handle.write("## Correction-map cache and `reference_sample`\n\n")
        handle.write(f"- `_corrected_measurements` calls observed: **{total_calls}**.\n")
        handle.write(f"- `reference_sample()` calls: **{total_calls}**, total **{_format_float(reference_time)} s**, mean **{_format_float(reference_time / total_calls if total_calls else 0.0)} s/call**.\n")
        handle.write(f"- Measured-shot correction-map lookups: **{map_lookups}**.\n")
        handle.write(f"- Measured-shot fallback misses: **{map_misses}**; fallback generation: **{_format_float(map_generation)} s**.\n")
        handle.write(f"- Offline correction-map generation: **{_format_float(setup_map_generation)} s** across **{sum(event.section == 'setup.correction_map.generate' for event in events if event.phase == 'setup')}** unique path sets.\n\n")
        handle.write("| measured shot | map lookups | fallback misses | fallback-generation seconds | reference-sample calls | reference-sample seconds |\n")
        handle.write("|---:|---:|---:|---:|---:|---:|\n")
        for shot_index in sorted({event.shot_index for event in measured_events if event.shot_index >= 0}):
            shot_events = [event for event in measured_events if event.shot_index == shot_index]
            shot_lookups = sum(event.section == "shot.correction_map.lookup" for event in shot_events)
            shot_misses = sum(event.section == "shot.correction_map.fallback_miss" for event in shot_events)
            shot_generation = sum(
                event.wall_time_seconds
                for event in shot_events
                if event.section == "shot.correction_map.fallback_generate"
            )
            shot_refs = [
                event for event in shot_events
                if event.section == "corrected_measurements.reference_sample"
            ]
            handle.write(
                f"| {shot_index} | {shot_lookups} | {shot_misses} | "
                f"{_format_float(shot_generation)} | {len(shot_refs)} | "
                f"{_format_float(sum(event.wall_time_seconds for event in shot_refs))} |\n"
            )
        handle.write("\n")
        handle.write("## Setup timing\n\n")
        if setup_totals:
            handle.write("| setup section | seconds |\n|---|---:|\n")
            for section, value in sorted(setup_totals.items(), key=lambda item: item[1], reverse=True):
                handle.write(f"| `{section}` | {_format_float(value)} |\n")
        else:
            handle.write("_No setup events recorded._\n")
        suffix_setup = setup_totals.get("setup.suffix_precompute", 0.0)
        suffix_zero = setup_totals.get("setup.suffix_precompute.zero", 0.0)
        suffix_plus = setup_totals.get("setup.suffix_precompute.plus", 0.0)
        runtime_suffix = sum(
            value
            for section, value in totals.items()
            if section.startswith("shot.physical.long.suffix_preparation.")
        )
        handle.write(
            f"\nDetector-stripped suffix setup: **{_format_float(suffix_setup)} s** "
            f"(zero **{_format_float(suffix_zero)} s**, plus **{_format_float(suffix_plus)} s**); "
            f"measured-shot suffix preparation: **{_format_float(runtime_suffix)} s**.\n"
        )
        handle.write("\n")
        handle.write("## Short versus long physical Stim execution\n\n")
        short = totals.get("shot.physical.short.total", 0.0)
        long = totals.get("shot.physical.long.total", 0.0)
        handle.write(f"- Short total: {_format_float(short)} s ({100 * short / e2e_total if e2e_total else 0:.2f}% E2E).\n")
        handle.write(f"- Long continuation total: {_format_float(long)} s ({100 * long / e2e_total if e2e_total else 0:.2f}% E2E).\n")
        handle.write("\n## Likely optimization opportunities\n\n")
        ranked = sorted(
            [row for row in top_levels if row["component"] != "result/statistics bookkeeping"],
            key=lambda row: row["time_seconds"],
            reverse=True,
        )
        suggestions = {
            "correction-map": "If map generation is large, share deterministic correction maps across shots (expected benefit: high when measured; complexity: low/medium; correctness risk: medium).",
            "reference": "If reference sampling is large, cache reference samples per equivalent execution path (expected benefit: high when measured; complexity: low; correctness risk: low/medium).",
            "decoder": "If decoder work is largest, focus on decoder invocation/statistics processing (expected benefit: proportional to measured decoder share; complexity: medium/high; correctness risk: medium).",
            "physical": "If physical Stim execution is largest, investigate execution/branch scheduling only after preserving same-shot semantics (expected benefit: proportional; complexity: medium/high; correctness risk: high).",
            "suffix": "If adaptive suffix preparation is largest, precompute detector-stripped suffix circuits for the fixed workflow (expected benefit: high when measured; complexity: low; correctness risk: low/medium).",
        }
        if map_generation > 0.1 * e2e_total:
            handle.write(f"1. {suggestions['correction-map']}\n")
        if reference_time > 0.1 * e2e_total:
            handle.write(f"2. {suggestions['reference']}\n")
        if ranked and ranked[0]["component"] == "decoder work":
            handle.write(f"3. {suggestions['decoder']}\n")
        if ranked and ranked[0]["component"] == "physical Stim execution":
            handle.write(f"3. {suggestions['physical']}\n")
        if map_generation <= 0.1 * e2e_total and reference_time <= 0.1 * e2e_total and (not ranked or ranked[0]["component"] not in {"decoder work", "physical Stim execution", "adaptive suffix preparation"}):
            handle.write("The few-shot profile does not show a single dominant low-risk candidate beyond the measured largest stages; collect a similarly scoped profile after choosing the next hypothesis.\n")
        handle.write("\nCorrection-map sharing and suffix precomputation are the only optimizations represented by this profile; no further optimization was implemented.\n")


def _write_cache_comparison(
    path: Path,
    *,
    args: argparse.Namespace,
    result: Any,
    events: tuple[TimingEvent, ...],
) -> None:
    """Write a concise comparison across the original and optimized profiles."""

    measured = tuple(event for event in events if event.phase == "measured")
    original_mean = 0.181446721
    shared_map_mean = 0.0599689558
    original_map_generation_total = 0.618240641
    original_map_misses = 30
    shared_map_suffix_total = 0.252468323
    profile_shots = 5
    new_total = sum(
        event.wall_time_seconds
        for event in measured
        if event.section == "shot.total_wall_time"
    )
    new_mean = new_total / args.num_shots if args.num_shots else 0.0
    setup_map_generation = sum(
        event.wall_time_seconds
        for event in events
        if event.phase == "setup" and event.section == "setup.correction_map.generate"
    )
    setup_suffix_generation = sum(
        event.wall_time_seconds
        for event in events
        if event.phase == "setup" and event.section == "setup.suffix_precompute"
    )
    measured_generation = sum(
        event.wall_time_seconds
        for event in measured
        if event.section == "shot.correction_map.fallback_generate"
    )
    measured_misses = sum(
        event.section == "shot.correction_map.fallback_miss" for event in measured
    )
    lookups = sum(event.section == "shot.correction_map.lookup" for event in measured)
    top_levels = _top_level_rows(
        _measured_totals(measured),
        new_total,
    )
    accounted = sum(row["time_seconds"] for row in top_levels)
    suffix_generation_per_shot = shared_map_suffix_total / profile_shots
    speedup_from_suffix = shared_map_mean / new_mean if new_mean else float("inf")
    total_speedup = original_mean / new_mean if new_mean else float("inf")
    saved_per_shot = shared_map_mean - new_mean
    break_even = setup_suffix_generation / saved_per_shot if saved_per_shot > 0 else None
    long_stim = sum(
        event.wall_time_seconds
        for event in measured
        if event.section in {"shot.physical.long.zero", "shot.physical.long.plus"}
    )
    runtime_suffix = sum(
        event.wall_time_seconds
        for event in measured
        if event.section.startswith("shot.physical.long.suffix_preparation.")
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as handle:
        handle.write("# Adaptive wall-time optimization comparison\n\n")
        handle.write("This compares the original implementation, the shared correction-map implementation, and the current shared-map plus precomputed-suffix implementation.\n\n")
        handle.write("| metric | original | shared maps | shared maps + suffixes |\n|---|---:|---:|---:|\n")
        handle.write(f"| mean E2E wall time / shot | {original_mean:.9g} s | {shared_map_mean:.9g} s | {new_mean:.9g} s |\n")
        handle.write(f"| suffix preparation / shot | n/a | {suffix_generation_per_shot:.9g} s | {runtime_suffix / args.num_shots if args.num_shots else 0:.9g} s |\n")
        handle.write(f"| correction-map generation / measured shot | {original_map_generation_total / profile_shots:.9g} s | 0 s measured | {measured_generation / args.num_shots if args.num_shots else 0:.9g} s measured |\n")
        handle.write(f"| measured-shot map misses | {original_map_misses} | 0 | {measured_misses} |\n")
        handle.write(f"| offline correction-map generation | n/a | 0.158809057 s | {setup_map_generation:.9g} s |\n")
        handle.write(f"| suffix-precompute setup | n/a | n/a | {setup_suffix_generation:.9g} s |\n")
        handle.write(f"| actual long Stim execution / shot | n/a | n/a | {long_stim / args.num_shots if args.num_shots else 0:.9g} s |\n")
        handle.write(f"| measured-shot map lookups | n/a | n/a | {lookups} |\n")
        handle.write("\n")
        handle.write(f"- Speedup from suffix precomputation over shared maps: **{speedup_from_suffix:.3f}x**.\n")
        handle.write(f"- Total speedup over the original implementation: **{total_speedup:.3f}x**.\n")
        handle.write(f"- Cold setup map-precomputation cost: **{setup_map_generation:.9g} s**; suffix-precompute cost: **{setup_suffix_generation:.9g} s**.\n")
        handle.write(f"- Steady-state measured-shot mean: **{new_mean:.9g} s/shot**.\n")
        if break_even is not None:
            handle.write(f"- Approximate suffix break-even: **{break_even:.2f} shots**, using the shared-map versus new mean difference and excluding other setup costs.\n")
        handle.write(f"- New largest non-overlapping stage: **{top_levels[0]['component']}** ({top_levels[0]['percent_of_e2e']:.2f}% E2E).\n")
        handle.write(f"- Accounted fraction: **{100 * accounted / new_total if new_total else 0:.2f}%**; unaccounted: **{100 * (1 - accounted / new_total) if new_total else 0:.2f}%**.\n")
        handle.write(f"- Logical errors: **{result.logical_errors}/{result.shots}**.\n")


def _write_plot(path: Path, rows: list[dict[str, Any]]) -> None:
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        return
    drawable = [row for row in rows if row["time_seconds"] > 0]
    if not drawable:
        return
    drawable = list(reversed(drawable))
    figure, axis = plt.subplots(figsize=(9, 4.5))
    axis.barh(
        [row["component"] for row in drawable],
        [row["time_seconds"] for row in drawable],
    )
    axis.set_xlabel("wall time (seconds)")
    axis.set_title("Adaptive Knill wall-time breakdown")
    figure.tight_layout()
    figure.savefig(path, dpi=150)
    plt.close(figure)


def run(args: argparse.Namespace) -> Any:
    if args.num_shots <= 0 or args.warmup_shots < 0:
        raise ValueError("num-shots must be positive and warmup-shots cannot be negative")
    if args.num_teleportations <= 0:
        raise ValueError("num-teleportations must be positive")
    long_rounds = args.distance if args.long_rounds is None else args.long_rounds
    if args.short_rounds < 1 or args.short_rounds >= long_rounds:
        raise ValueError("short-rounds must be at least 1 and strictly less than long-rounds")

    if args.policy == "always-long":
        policy = AlwaysLongPolicy()
    elif args.policy == "always-short":
        policy = AlwaysShortPolicy()
    else:
        policy = ClusterLLRPolicy(threshold=args.confidence_threshold)
    policy_name = args.policy

    metadata = {
        "git_sha": _git_sha(),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "stim": _version(stim),
        "ldpc": _version(ldpc),
        "pymatching": _version(pymatching),
        "stimbposd": _version(stimbposd),
        "seed": args.seed,
    }
    profiler = WallTimeProfiler(metadata=metadata | {"policy": policy_name})
    with profiler.context_scope(phase="setup", shot_index=-1):
        with profiler.section("setup.parity_check_loading", absolute=True):
            parity_checks = get_parity_check_matrices("surface", args.distance)

    with profiler.section("setup.decoder_factory", absolute=True):
        offline_decoder = make_bplsd_decoder_generator(
            args.physical_error,
            alpha=2.0,
            **BPLSD_OPTIONS,
        )
    with profiler.section("setup.adaptive_schedule", absolute=True):
        schedule = AdaptiveSERounds(args.short_rounds, long_rounds, policy)
    result = knill_online_offline_adaptive(
        parity_checks,
        schedule,
        online_decoder_generator=pymatching.Matching.from_check_matrix,
        offline_decoder_generator=offline_decoder,
        matchable_offline_decoding=False,
        physical_error=args.physical_error,
        max_shots=args.num_shots,
        max_errors_before_halting=10**9,
        pauli=args.pauli,
        num_teleportations=args.num_teleportations,
        confidence_aggregator=dem_only_max_confidence,
        detail_level="analysis",
        batch_size=1,
        seed=args.seed,
        surface_code=True,
        profiler=profiler,
        warmup_shots=args.warmup_shots,
    )

    output_dir = args.output_dir
    events = profiler.events
    used_long_by_shot = None
    if result.per_shot is not None and "used_long_pair" in result.per_shot:
        used_long_by_shot = {
            index: bool(value)
            for index, value in enumerate(result.per_shot["used_long_pair"].any(axis=1))
        }
    raw_rows = _event_rows(
        events,
        args=args,
        policy_name=policy_name,
        long_rounds=long_rounds,
        used_long_by_shot=used_long_by_shot,
        metadata=metadata,
    )
    summary_rows = _summary_rows(
        events,
        measured_shots=args.num_shots,
        warmup_shots=args.warmup_shots,
    )
    output_prefix = args.output_prefix
    _write_csv(output_dir / f"{output_prefix}_raw.csv", RAW_COLUMNS, raw_rows)
    _write_csv(output_dir / f"{output_prefix}_summary.csv", SUMMARY_COLUMNS, summary_rows)
    totals = _measured_totals(tuple(event for event in events if event.phase == "measured"))
    e2e_total = totals.get("shot.total_wall_time", 0.0)
    top_levels = _top_level_rows(totals, e2e_total)
    _make_report(
        output_dir / f"{output_prefix}_report.md",
        args=args,
        long_rounds=long_rounds,
        policy_name=policy_name,
        result=result,
        events=events,
        metadata=metadata,
        warmup_shots=args.warmup_shots,
    )
    _write_plot(output_dir / f"{output_prefix}_breakdown.png", top_levels)
    _write_cache_comparison(
        output_dir / "adaptive_walltime_optimization_comparison.md",
        args=args,
        result=result,
        events=events,
    )
    return result


def main() -> None:
    args = _arg_parser().parse_args()
    result = run(args)
    print(f"Profiled {result.shots} measured shots; logical errors={result.logical_errors}")
    print(f"Results: {args.output_dir}")


if __name__ == "__main__":
    main()
