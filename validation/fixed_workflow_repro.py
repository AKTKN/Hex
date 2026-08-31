"""Validation 1: legacy static Knill versus the stateful fixed backend."""

from __future__ import annotations

import argparse
import importlib
import time
import pymatching

from hex_qec.circuit_generation import get_parity_check_matrices
from hex_qec.protocols import knill_online_offline
from hex_qec.simulation import StatefulFlipSimulatorBackend

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
    "validation", "workflow", "distance", "physical_error", "state_prep_rounds",
    "num_teleportations", "pauli", "surface_code", "replicate", "seed", "shots",
    "logical_errors", "logical_error_rate", "wilson_95_low", "wilson_95_high",
    "runtime_seconds", "num_qubits", "num_measurements", "num_detectors", "num_modules",
    "config_signature", "git_sha", "python_version", "stim_version", "pymatching_version",
]
COMPARISON_FIELDS = [
    "distance", "physical_error", "legacy_shots", "legacy_errors", "legacy_ler",
    "legacy_ci_low", "legacy_ci_high", "new_shots", "new_errors", "new_ler", "new_ci_low",
    "new_ci_high", "absolute_ler_difference", "ler_ratio", "raw_p_value",
    "adjusted_p_value", "statistical_status", "total_error_events",
]


def _capture_knill_circuit():
    """Capture the exact modular circuit built by the legacy protocol call."""

    module = importlib.import_module("hex_qec.protocols.knill_online_offline")
    captured = []
    original = module.modularised_circuit

    def capture(modules):
        circuit = original(modules)
        captured.append(circuit)
        return circuit

    module.modularised_circuit = capture
    return module, original, captured


def run_validation(config):
    raw_path = config.output_dir / "fixed_workflow_raw.csv"
    comparison_path = config.output_dir / "fixed_workflow_comparison.csv"
    prepare_output(config, raw_path.name, comparison_path.name)
    write_invocation_metadata(config, "fixed_workflow_repro", __import__("sys").argv[1:])
    rows = read_csv_rows(raw_path)
    signature = configuration_signature("fixed_workflow_repro", config)
    completed = {raw_row_key(row) for row in rows}
    total_points = len(config.distances) * len(config.physical_errors) * config.replicates
    point_number = 0

    for distance in config.distances:
        parity_checks = get_parity_check_matrices("surface", distance)
        for physical_error in config.physical_errors:
            for replicate in range(config.replicates):
                point_number += 1
                if parameter_complete(
                    rows,
                    distance=distance,
                    physical_error=physical_error,
                    replicate=replicate,
                    config_signature=signature,
                    workflows=("legacy_static", "stateful_fixed"),
                ):
                    continue
                seed = stable_seed(
                    config.base_seed, "fixed_workflow_repro", distance, physical_error, replicate
                )
                progress(
                    config,
                    "fixed",
                    f"point {point_number}/{total_points}: d={distance}, p={physical_error}, "
                    f"replicate={replicate + 1}/{config.replicates}, seed={seed}",
                )
                common = dict(
                    syndrome_measurement_rounds=distance,
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
                module, original, captured = _capture_knill_circuit()
                try:
                    static_start = time.perf_counter()
                    static_shots, static_errors = knill_online_offline(parity_checks, **common)
                    static_runtime = time.perf_counter() - static_start
                    progress(
                        config,
                        "fixed",
                        f"  legacy_static complete: shots={static_shots}, errors={static_errors}, "
                        f"runtime={static_runtime:.2f}s",
                    )
                    if not captured:
                        raise RuntimeError("legacy Knill call did not construct a modularised circuit")
                    circuit = captured[-1]
                finally:
                    module.modularised_circuit = original

                stateful_result = StatefulFlipSimulatorBackend(
                    circuit, batch_size=STATIC_BATCH_SIZE, seed=seed
                ).simulate_result(config.shots, NO_EARLY_STOP_ERRORS)
                progress(
                    config,
                    "fixed",
                    f"  stateful_fixed complete: shots={stateful_result.shots}, "
                    f"errors={stateful_result.logical_errors}, "
                    f"runtime={stateful_result.summary.runtime_seconds or 0.0:.2f}s",
                )
                for workflow, shots, errors, runtime in [
                    ("legacy_static", static_shots, static_errors, static_runtime),
                    (
                        "stateful_fixed",
                        stateful_result.shots,
                        stateful_result.logical_errors,
                        stateful_result.summary.runtime_seconds or 0.0,
                    ),
                ]:
                    row = add_common_row_fields(
                        validation="fixed_workflow_repro",
                        workflow=workflow,
                        distance=distance,
                        physical_error=physical_error,
                        replicate=replicate,
                        seed=seed,
                        config=config,
                        shots=shots,
                        logical_errors=errors,
                        runtime_seconds=runtime,
                    )
                    row.update(
                        num_qubits=circuit.circuit.num_qubits,
                        num_measurements=circuit.circuit.num_measurements,
                        num_detectors=circuit.circuit.num_detectors,
                        num_modules=len(circuit.circuit_modules),
                        config_signature=signature,
                    )
                    if raw_row_key(row) not in completed:
                        rows.append(row)
                        completed.add(raw_row_key(row))
                        write_csv_rows(raw_path, rows, RAW_FIELDS)
                progress(config, "fixed", "  checkpoint written")

    current_rows = [row for row in rows if row.get("config_signature") == signature]
    comparisons = comparison_rows(
        current_rows,
        legacy_workflow="legacy_static",
        new_workflow="stateful_fixed",
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
