"""Validation 2: legacy fixed-depth Knill versus adaptive forced-long Knill."""

from __future__ import annotations

import argparse
import time

import pymatching

from hex_qec.circuit_generation import get_parity_check_matrices
from hex_qec.modularisation import AdaptiveSERounds
from hex_qec.parallel import ParallelExecutionOptions
from hex_qec.protocols import knill_online_offline, knill_online_offline_adaptive
from hex_qec.simulation import AlwaysLongPolicy

from .knill_repro_common import (
    NO_EARLY_STOP_ERRORS,
    STATIC_BATCH_SIZE,
    add_common_arguments,
    add_common_row_fields,
    comparison_rows,
    config_from_args,
    configuration_signature,
    prepare_output,
    parameter_complete,
    progress,
    raw_row_key,
    read_csv_rows,
    stable_seed,
    write_csv_rows,
    write_invocation_metadata,
)


RAW_FIELDS = [
    "validation", "workflow", "distance", "physical_error", "baseline_state_prep_rounds",
    "short_rounds", "extra_rounds", "total_long_rounds", "num_teleportations", "pauli",
    "surface_code", "replicate", "seed", "shots", "logical_errors", "logical_error_rate",
    "wilson_95_low", "wilson_95_high", "runtime_seconds", "pair_fallback_rate",
    "mean_effective_rounds", "num_state_prep_events", "config_signature", "git_sha",
    "python_version", "stim_version", "pymatching_version",
]
COMPARISON_FIELDS = [
    "distance", "physical_error", "legacy_shots", "legacy_errors", "legacy_ler",
    "legacy_ci_low", "legacy_ci_high", "new_shots", "new_errors", "new_ler", "new_ci_low",
    "new_ci_high", "absolute_ler_difference", "ler_ratio", "raw_p_value",
    "adjusted_p_value", "statistical_status", "total_error_events",
]


def run_validation(config):
    raw_path = config.output_dir / "adaptive_forced_long_raw.csv"
    comparison_path = config.output_dir / "adaptive_forced_long_comparison.csv"
    prepare_output(config, raw_path.name, comparison_path.name)
    write_invocation_metadata(config, "adaptive_forced_long_repro", __import__("sys").argv[1:])
    rows = read_csv_rows(raw_path)
    signature = configuration_signature("adaptive_forced_long_repro", config)
    completed = {raw_row_key(row) for row in rows}
    total_points = len(config.distances) * len(config.physical_errors) * config.replicates
    point_number = 0

    for distance in config.distances:
        parity_checks = get_parity_check_matrices("surface", distance)
        schedule = AdaptiveSERounds(
            short_rounds=1,
            long_rounds=distance,
            policy=AlwaysLongPolicy(),
        )
        for physical_error in config.physical_errors:
            for replicate in range(config.replicates):
                point_number += 1
                if parameter_complete(
                    rows,
                    distance=distance,
                    physical_error=physical_error,
                    replicate=replicate,
                    config_signature=signature,
                    workflows=("legacy_static_fixed_d", "adaptive_forced_long"),
                ):
                    continue
                seed = stable_seed(
                    config.base_seed,
                    "adaptive_forced_long_repro",
                    distance,
                    physical_error,
                    replicate,
                )
                progress(
                    config,
                    "adaptive",
                    f"point {point_number}/{total_points}: d={distance}, p={physical_error}, "
                    f"replicate={replicate + 1}/{config.replicates}, seed={seed}, "
                    "schedule=short 1 + extra d-1 -> long d",
                )
                common = dict(
                    online_decoder_generator=pymatching.Matching.from_check_matrix,
                    offline_decoder_generator=pymatching.Matching.from_check_matrix,
                    matchable_offline_decoding=True,
                    physical_error=physical_error,
                    max_shots=config.shots,
                    max_errors_before_halting=NO_EARLY_STOP_ERRORS,
                    pauli=config.pauli,
                    num_teleportations=config.num_teleportations,
                    surface_code=True,
                    seed=seed,
                )
                legacy_start = time.perf_counter()
                legacy_shots, legacy_errors = knill_online_offline(
                    parity_checks,
                    syndrome_measurement_rounds=distance,
                    **common,
                )
                legacy_runtime = time.perf_counter() - legacy_start
                progress(
                    config,
                    "adaptive",
                    f"  legacy_static_fixed_d complete: shots={legacy_shots}, "
                    f"errors={legacy_errors}, runtime={legacy_runtime:.2f}s",
                )
                progress(config, "adaptive", "  adaptive_forced_long running...")
                parallel_options = None
                adaptive_detail_level = "analysis"
                adaptive_batch_size = STATIC_BATCH_SIZE
                if config.parallel_num_workers is not None:
                    parallel_options = ParallelExecutionOptions(
                        num_workers=config.parallel_num_workers,
                        target_chunk_seconds=config.parallel_target_chunk_seconds,
                        initial_chunk_shots=config.parallel_initial_chunk_shots,
                        max_chunk_shots=config.parallel_max_chunk_shots,
                        checkpoint_path=config.parallel_checkpoint_path,
                        verbose=config.parallel_verbose,
                    )
                    adaptive_detail_level = "summary"
                    # Worker leases determine their own batch size.  Keep the
                    # serial value above so the default path is unchanged.
                    adaptive_batch_size = 1
                adaptive_start = time.perf_counter()
                adaptive_result = knill_online_offline_adaptive(
                    parity_checks,
                    adaptive_schedule=schedule,
                    detail_level=adaptive_detail_level,
                    batch_size=adaptive_batch_size,
                    parallel_options=parallel_options,
                    **common,
                )
                adaptive_runtime = time.perf_counter() - adaptive_start
                reported_adaptive_runtime = (
                    adaptive_runtime
                    if parallel_options is not None
                    else adaptive_result.summary.runtime_seconds or 0.0
                )
                progress(
                    config,
                    "adaptive",
                    f"  adaptive_forced_long complete: shots={adaptive_result.shots}, "
                    f"errors={adaptive_result.logical_errors}, "
                    f"runtime={reported_adaptive_runtime:.2f}s, "
                    f"pair_fallback_rate={adaptive_result.bell_pair_stats[0].pair_fallback_rate:.3f}, "
                    f"mean_rounds={adaptive_result.bell_pair_stats[0].mean_effective_rounds:.3f}",
                )
                if len(adaptive_result.bell_pair_stats) != config.num_teleportations:
                    raise AssertionError("adaptive result did not report every Bell-pair decision")
                for pair in adaptive_result.bell_pair_stats:
                    if pair.pair_fallback_rate != 1.0:
                        raise AssertionError("AlwaysLongPolicy did not select long for every pair")
                    if pair.mean_effective_rounds != distance:
                        raise AssertionError("forced-long pair did not use total depth distance")
                if any(
                    stat.short_count != 0
                    or stat.long_count != adaptive_result.shots
                    or stat.long_rounds != distance
                    or stat.short_rounds != 1
                    for stat in adaptive_result.state_prep_stats
                ):
                    raise AssertionError("forced-long patch event has unexpected branch/round counts")

                for workflow, shots, errors, runtime, fallback, mean_rounds, event_count in [
                    (
                        "legacy_static_fixed_d", legacy_shots, legacy_errors, legacy_runtime,
                        None, None, None,
                    ),
                    (
                        "adaptive_forced_long",
                        adaptive_result.shots,
                        adaptive_result.logical_errors,
                        reported_adaptive_runtime,
                        adaptive_result.bell_pair_stats[0].pair_fallback_rate,
                        adaptive_result.bell_pair_stats[0].mean_effective_rounds,
                        len(adaptive_result.state_prep_stats),
                    ),
                ]:
                    row = add_common_row_fields(
                        validation="adaptive_forced_long_repro",
                        workflow=workflow,
                        distance=distance,
                        physical_error=physical_error,
                        replicate=replicate,
                        seed=seed,
                        config=config,
                        shots=shots,
                        logical_errors=errors,
                        runtime_seconds=runtime or 0.0,
                    )
                    row.update(
                        baseline_state_prep_rounds=distance,
                        short_rounds=None if workflow.startswith("legacy") else 1,
                        extra_rounds=None if workflow.startswith("legacy") else distance - 1,
                        total_long_rounds=None if workflow.startswith("legacy") else distance,
                        pair_fallback_rate=fallback,
                        mean_effective_rounds=mean_rounds,
                        num_state_prep_events=event_count,
                        config_signature=signature,
                    )
                    # The common helper uses state_prep_rounds; this suite's
                    # schema intentionally names the baseline column instead.
                    row.pop("state_prep_rounds", None)
                    if raw_row_key(row) not in completed:
                        rows.append(row)
                        completed.add(raw_row_key(row))
                        write_csv_rows(raw_path, rows, RAW_FIELDS)
                progress(config, "adaptive", "  checkpoint written")

    current_rows = [row for row in rows if row.get("config_signature") == signature]
    comparisons = comparison_rows(
        current_rows,
        legacy_workflow="legacy_static_fixed_d",
        new_workflow="adaptive_forced_long",
        distances=config.distances,
        physical_errors=config.physical_errors,
        alpha=config.alpha,
        min_total_errors=config.min_total_errors,
    )
    write_csv_rows(comparison_path, comparisons, COMPARISON_FIELDS)
    return rows, comparisons


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    add_common_arguments(parser)
    config = config_from_args(parser.parse_args(argv))
    run_validation(config)


if __name__ == "__main__":
    main()
