from __future__ import annotations

import stim
import pymatching
from ldpc import BpDecoder, BpOsdDecoder
import numpy as np
from numpy import ndarray
from hex_qec.circuit_generation import get_parity_check_matrices, stabilizer_measurement_circuit, noiseless_unitary_state_prep
from hex_qec.circuit_generation import generate_blocks, create_stabilizers_and_block_template
from hex_qec.modularisation import logical_measurement_module, no_measurement_module, modularised_circuit, detector_module, css_detector_module, measurement_module
from hex_qec.modularisation import generate_logical_measurement_module, generate_state_prep_modules, generate_state_prep_module_no_noise, generate_bell_measurement_and_correction_module, generate_transversal_cnot_module
from hex_qec.modularisation import (
    AdaptiveSERounds,
    generate_adaptive_state_prep_module,
)

from typing import List, Dict, Tuple, Callable, Any
from pprint import pprint
from datetime import datetime
import subprocess
import argparse
import json
import time
import logging
import sys
from contextlib import nullcontext


def _profile_setup(profiler, name: str):
    if profiler is None:
        return nullcontext()
    return profiler.section(name, absolute=True)

def knill_online_offline(
        parity_check_tuple,
        syndrome_measurement_rounds,
        online_decoder_generator,
        offline_decoder_generator,
        matchable_offline_decoding,
        physical_error,
        max_shots,
        max_errors_before_halting,
        pauli,
        num_teleportations,
        results_path = "",
        surface_code: bool = False,
        seed: int | None = None,
):
    block_template, _, _, _ = create_stabilizers_and_block_template(*parity_check_tuple)
    blocks = generate_blocks(2*num_teleportations+1, block_template)

    (x_pcm, z_pcm, x_logical, z_logical) = parity_check_tuple

    # Perfect state preparation circuits
    plus_state_prep_circuit_noiseless = noiseless_unitary_state_prep(parity_check_tuple, "x", eigenvalue = 0)
    zero_state_prep_circuit_noiseless = noiseless_unitary_state_prep(parity_check_tuple, "z", eigenvalue = 0)
    # Perfect data qubit preparation modules
    plus_state_prep_data_qubit = no_measurement_module(plus_state_prep_circuit_noiseless, blocks[0]["data_qubits"])
    zero_state_prep_data_qubit = no_measurement_module(zero_state_prep_circuit_noiseless, blocks[0]["data_qubits"])

    # Knill error correction modules
    modules_for_knill_error_correction = []
    # Generate state prep modules
    zero_state_prep_modules = generate_state_prep_modules(
            parity_check_tuple,
            syndrome_measurement_rounds,
            "z",
            physical_error,
            [blocks[2*teleportation_index+1]["data_qubits"]+blocks[2*teleportation_index+1]["x_ancillas"]+blocks[2*teleportation_index+1]["z_ancillas"] for teleportation_index in range(num_teleportations)],
            offline_decoder_generator,
            matchable=matchable_offline_decoding,
            surface_code=surface_code,
    )
    plus_state_prep_modules = generate_state_prep_modules(
            parity_check_tuple,
            syndrome_measurement_rounds,
            "x",
            physical_error,
            [blocks[2*teleportation_index+2]["data_qubits"]+blocks[2*teleportation_index+2]["x_ancillas"]+blocks[2*teleportation_index+2]["z_ancillas"] for teleportation_index in range(num_teleportations)],
            offline_decoder_generator,
            matchable=matchable_offline_decoding,
            surface_code=surface_code,
    )
    for teleportation_index in range(num_teleportations):
        # Prepare logical Bell state
        modules_for_knill_error_correction.append(zero_state_prep_modules[teleportation_index])
        modules_for_knill_error_correction.append(plus_state_prep_modules[teleportation_index])
        modules_for_knill_error_correction.append(generate_transversal_cnot_module(physical_error,
                                                                                    blocks[2*teleportation_index+2]["data_qubits"], # control
                                                                                    blocks[2*teleportation_index+1]["data_qubits"], # target
                                                                                   )
                                                   )
        modules_for_knill_error_correction.append(generate_bell_measurement_and_correction_module(
            parity_check_tuple,
            physical_error,
            blocks[2*(teleportation_index-1)+2]["data_qubits"], # data block (second bell of previous step)
            blocks[2*teleportation_index+1]["data_qubits"], # first bell block
            blocks[2*teleportation_index+2]["data_qubits"], # second bell block
            decoder_generator = online_decoder_generator,
        ))
    measure_data_qubit_x = generate_logical_measurement_module(
        parity_check_tuple,
        physical_error,
        pauli = "x",
        new_support = blocks[2*num_teleportations]["data_qubits"],
        decoder_generator = online_decoder_generator,
        expected_logical_values = []
    )
    measure_data_qubit_z = generate_logical_measurement_module(
        parity_check_tuple,
        physical_error,
        pauli = "z",
        new_support = blocks[2*num_teleportations]["data_qubits"],
        decoder_generator = online_decoder_generator,
        expected_logical_values = []
    )
        
    module_list = []

    if pauli.lower() == "x":
        module_list.append(plus_state_prep_data_qubit)
    elif pauli.lower() == "z":
        module_list.append(zero_state_prep_data_qubit)

    module_list.extend(modules_for_knill_error_correction)

    if pauli.lower() == "x":
        module_list.append(measure_data_qubit_x)
    elif pauli.lower() == "z":
        module_list.append(measure_data_qubit_z)

    mod_circ = modularised_circuit(module_list)
    mod_circ.generate_correction_to_measurement_flip_map()

    samples_performed, logical_errors = mod_circ.simulate(
        max_shots,
        max_errors_before_halting,
        results_path=results_path,
        seed=seed,
    )
    return samples_performed, logical_errors


def _build_knill_online_offline_adaptive_executor(
        parity_check_tuple,
        adaptive_schedule: AdaptiveSERounds,
        online_decoder_generator,
        offline_decoder_generator,
        matchable_offline_decoding,
        physical_error,
        pauli,
        num_teleportations,
        confidence_aggregator=None,
        batch_size=256,
        seed=None,
        surface_code: bool = False,
        profiler=None,
):
    """Build the shared adaptive Knill executor used by serial and parallel paths.

    The legacy ``knill_online_offline`` function remains the static compiled
    backend.  This separate entry point uses the stateful reference executor
    and accepts a policy through ``adaptive_schedule``.

    ``confidence_aggregator`` receives one ``CSSInnerDecodeResults`` (the
    four inner ``x_dem``/``z_dem``/``x_capacity``/``z_capacity`` decode
    results) per state-preparation patch and must return one confidence
    value per shot; it is required for policies such as ``ClusterLLRPolicy``
    that read ``DecodeResult.confidence``.  ``hex_qec.decoders`` provides
    ``dem_only_max_confidence`` as the current, theoretically-justified
    default (DEM-only) and ``all_components_max_confidence`` as a
    diagnostic-only alternative that also folds in code-capacity confidence;
    see ``FUTURE.md``, "Code-capacity confidence for adaptive state
    preparation", for why the latter is not the default.

    Each teleportation's ``|0_L>`` and ``|+_L>`` patches are decoded and
    policy-evaluated independently; the synchronized pair decision is the
    boolean OR of their individual ``policy.should_extend(...)`` results,
    never a raw max/min comparison of their confidence values.  That OR is
    the generic pair-level control rule for every policy/metric.
    """
    from hex_qec.simulation import StatefulAdaptiveKnillExecutor

    with _profile_setup(profiler, "setup.block_layout"):
        block_template, _, _, _ = create_stabilizers_and_block_template(*parity_check_tuple)
        blocks = generate_blocks(2 * num_teleportations + 1, block_template)

    with _profile_setup(profiler, "setup.initial_state_module"):
        plus_state_prep_circuit_noiseless = noiseless_unitary_state_prep(
            parity_check_tuple, "x", eigenvalue=0
        )
        zero_state_prep_circuit_noiseless = noiseless_unitary_state_prep(
            parity_check_tuple, "z", eigenvalue=0
        )
        plus_state_prep_data_qubit = no_measurement_module(
            plus_state_prep_circuit_noiseless, blocks[0]["data_qubits"]
        )
        zero_state_prep_data_qubit = no_measurement_module(
            zero_state_prep_circuit_noiseless, blocks[0]["data_qubits"]
        )

    modules = []
    if pauli.lower() == "x":
        modules.append(plus_state_prep_data_qubit)
    elif pauli.lower() == "z":
        modules.append(zero_state_prep_data_qubit)
    else:
        raise ValueError("pauli must be 'x' or 'z'")
    modules[0]._profile_role = "initial_preparation"

    for teleportation_index in range(num_teleportations):
        zero_support = (
            blocks[2 * teleportation_index + 1]["data_qubits"]
            + blocks[2 * teleportation_index + 1]["x_ancillas"]
            + blocks[2 * teleportation_index + 1]["z_ancillas"]
        )
        plus_support = (
            blocks[2 * teleportation_index + 2]["data_qubits"]
            + blocks[2 * teleportation_index + 2]["x_ancillas"]
            + blocks[2 * teleportation_index + 2]["z_ancillas"]
        )
        with _profile_setup(profiler, "setup.adaptive_state_prep.zero"):
            zero_module = generate_adaptive_state_prep_module(
                parity_check_tuple,
                adaptive_schedule,
                "z",
                physical_error,
                zero_support,
                offline_decoder_generator,
                matchable_offline_decoding,
                event_id=f"teleportation={teleportation_index},state=z",
                teleportation_index=teleportation_index,
                confidence_aggregator=confidence_aggregator,
                surface_code=surface_code,
                profiler=profiler,
            )
        with _profile_setup(profiler, "setup.adaptive_state_prep.plus"):
            plus_module = generate_adaptive_state_prep_module(
                parity_check_tuple,
                adaptive_schedule,
                "x",
                physical_error,
                plus_support,
                offline_decoder_generator,
                matchable_offline_decoding,
                event_id=f"teleportation={teleportation_index},state=x",
                teleportation_index=teleportation_index,
                confidence_aggregator=confidence_aggregator,
                surface_code=surface_code,
                profiler=profiler,
            )
        modules.extend([zero_module, plus_module])
        with _profile_setup(profiler, "setup.transversal_cnot"):
            cnot_module = generate_transversal_cnot_module(
                physical_error,
                blocks[2 * teleportation_index + 2]["data_qubits"],
                blocks[2 * teleportation_index + 1]["data_qubits"],
            )
        cnot_module._profile_role = "cnot"
        modules.append(cnot_module)
        with _profile_setup(profiler, "setup.bell_measurement"):
            bell_module = generate_bell_measurement_and_correction_module(
                parity_check_tuple,
                physical_error,
                blocks[2 * (teleportation_index - 1) + 2]["data_qubits"],
                blocks[2 * teleportation_index + 1]["data_qubits"],
                blocks[2 * teleportation_index + 2]["data_qubits"],
                decoder_generator=online_decoder_generator,
            )
        bell_module._profile_role = "bell_measurement"
        modules.append(bell_module)

    with _profile_setup(profiler, "setup.final_logical_module"):
        measure_data_qubit_x = generate_logical_measurement_module(
            parity_check_tuple,
            physical_error,
            pauli="x",
            new_support=blocks[2 * num_teleportations]["data_qubits"],
            decoder_generator=online_decoder_generator,
            expected_logical_values=[],
        )
        measure_data_qubit_z = generate_logical_measurement_module(
            parity_check_tuple,
            physical_error,
            pauli="z",
            new_support=blocks[2 * num_teleportations]["data_qubits"],
            decoder_generator=online_decoder_generator,
            expected_logical_values=[],
        )
    final_module = measure_data_qubit_x if pauli.lower() == "x" else measure_data_qubit_z
    final_module._profile_role = "final_logical_measurement"
    modules.append(final_module)

    with _profile_setup(profiler, "setup.executor_construction"):
        executor = StatefulAdaptiveKnillExecutor(
            modules,
            batch_size=batch_size,
            seed=seed,
        )
    return executor


def knill_online_offline_adaptive(
        parity_check_tuple,
        adaptive_schedule: AdaptiveSERounds,
        online_decoder_generator,
        offline_decoder_generator,
        matchable_offline_decoding,
        physical_error,
        max_shots,
        max_errors_before_halting,
        pauli,
        num_teleportations,
        results_path="",
        confidence_aggregator=None,
        detail_level="summary",
        batch_size=256,
        seed=None,
        surface_code: bool = False,
        profiler=None,
        warmup_shots: int = 0,
        parallel_options=None,
):
    """Run Knill with two-level adaptive state preparation.

    ``parallel_options=None`` preserves the established serial adaptive
    executor path.  Parallel execution is an opt-in summary-only adapter;
    workers build and retain their own executor and return additive counts.
    """
    if parallel_options is not None:
        if profiler is not None:
            raise ValueError(
                "parallel adaptive execution does not support profiler aggregation"
            )
        if detail_level != "summary":
            raise NotImplementedError(
                "parallel adaptive execution currently supports detail_level='summary' only"
            )
        if warmup_shots:
            raise ValueError("warmup_shots is unsupported in parallel adaptive execution")
        from .parallel_adapters import (
            AdaptiveKnillParallelJobFactory,
            merge_adaptive_parallel_result,
        )
        from hex_qec.parallel import ParallelJobSpec, ParallelManager

        factory = AdaptiveKnillParallelJobFactory(
            parity_check_tuple=parity_check_tuple,
            adaptive_schedule=adaptive_schedule,
            online_decoder_generator=online_decoder_generator,
            offline_decoder_generator=offline_decoder_generator,
            matchable_offline_decoding=matchable_offline_decoding,
            physical_error=physical_error,
            pauli=pauli,
            num_teleportations=num_teleportations,
            confidence_aggregator=confidence_aggregator,
            surface_code=surface_code,
        )
        metadata = factory.metadata(seed=seed)
        spec = ParallelJobSpec(
            job_id=factory.job_id_for(seed),
            factory=factory,
            max_shots=max_shots,
            max_errors=max_errors_before_halting,
            seed_base=seed,
            metadata=metadata,
            config_fingerprint=factory.config_fingerprint_for(seed),
        )
        parallel_result = ParallelManager(parallel_options).run([spec])
        result = merge_adaptive_parallel_result(parallel_result, spec)
    else:
        executor = _build_knill_online_offline_adaptive_executor(
            parity_check_tuple,
            adaptive_schedule,
            online_decoder_generator,
            offline_decoder_generator,
            matchable_offline_decoding,
            physical_error,
            pauli,
            num_teleportations,
            confidence_aggregator=confidence_aggregator,
            batch_size=batch_size,
            seed=seed,
            surface_code=surface_code,
            profiler=profiler,
        )
        if profiler is not None and warmup_shots:
            executor.simulate_result(
                max_shots=warmup_shots,
                max_errors_before_halting=max_errors_before_halting,
                detail_level=detail_level,
                profiler=profiler,
                profile_phase="warmup",
            )
        result = executor.simulate_result(
            max_shots=max_shots,
            max_errors_before_halting=max_errors_before_halting,
            detail_level=detail_level,
            profiler=profiler,
            profile_phase="measured",
        )
    if results_path:
        with open(results_path, "w") as result_file:
            json.dump({
                "samples_performed": result.samples_performed,
                "logical_errors": result.logical_errors,
                "logical_error_rate": result.logical_error_rate,
            }, result_file, indent=2)
    return result
