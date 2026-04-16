import stim
import numpy as np
from numpy import ndarray
from hex_qec.circuit_generation import get_parity_check_matrices, stabilizer_measurement_circuit, noiseless_unitary_state_prep
from hex_qec.circuit_generation import generate_blocks, create_stabilizers_and_block_template
from hex_qec.modularisation import logical_measurement_module, no_measurement_module, modularised_circuit, detector_module, css_detector_module, measurement_module
from hex_qec.modularisation import generate_logical_measurement_module, generate_state_prep_modules, generate_state_prep_module_no_noise, generate_transversal_cnot_module, generate_steane_correction_module

from typing import List, Dict, Tuple, Callable, Any
from pprint import pprint
from datetime import datetime
import subprocess
import argparse
import json
import time
import logging
import sys

def steane_online_offline(
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

    # Steane error correction modules
    modules_for_steane_error_correction = []
    # Generate state prep modules
    zero_state_prep_modules = generate_state_prep_modules(
            parity_check_tuple,
            syndrome_measurement_rounds,
            "z",
            physical_error,
            [blocks[2*teleportation_index+1]["data_qubits"]+blocks[2*teleportation_index+1]["x_ancillas"]+blocks[2*teleportation_index+1]["z_ancillas"] for teleportation_index in range(num_teleportations)],
            offline_decoder_generator,
            matchable=matchable_offline_decoding,
    )
    plus_state_prep_modules = generate_state_prep_modules(
            parity_check_tuple,
            syndrome_measurement_rounds,
            "x",
            physical_error,
            [blocks[2*teleportation_index+2]["data_qubits"]+blocks[2*teleportation_index+2]["x_ancillas"]+blocks[2*teleportation_index+2]["z_ancillas"] for teleportation_index in range(num_teleportations)],
            offline_decoder_generator,
            matchable=matchable_offline_decoding,
    )


    for teleportation_index in range(num_teleportations):
        # Prepare logical Bell state
        modules_for_steane_error_correction.append(zero_state_prep_modules[teleportation_index])
        modules_for_steane_error_correction.append(generate_transversal_cnot_module(physical_error,
                                                                                    blocks[2*teleportation_index+1]["data_qubits"], # control
                                                                                    blocks[0]["data_qubits"], # target
                                                                                   )
                                                   )
        modules_for_steane_error_correction.append(generate_steane_correction_module(
            parity_check_tuple,
            physical_error,
            "z",
            blocks[2*teleportation_index+1]["data_qubits"],
            blocks[0]["data_qubits"],
            online_decoder_generator,
        ))

        modules_for_steane_error_correction.append(plus_state_prep_modules[teleportation_index])
        modules_for_steane_error_correction.append(generate_transversal_cnot_module(physical_error,
                                                                                    blocks[0]["data_qubits"], # control
                                                                                    blocks[2*teleportation_index+2]["data_qubits"], # target
                                                                                   )
                                                   )
        modules_for_steane_error_correction.append(generate_steane_correction_module(
            parity_check_tuple,
            physical_error,
            "z",
            blocks[2*teleportation_index+2]["data_qubits"],
            blocks[0]["data_qubits"],
            online_decoder_generator,
        ))


    measure_data_qubit_x = generate_logical_measurement_module(
        parity_check_tuple,
        physical_error,
        pauli = "x",
        new_support = blocks[0]["data_qubits"],
        decoder_generator = online_decoder_generator,
        expected_logical_values = []
    )
    measure_data_qubit_z = generate_logical_measurement_module(
        parity_check_tuple,
        physical_error,
        pauli = "z",
        new_support = blocks[0]["data_qubits"],
        decoder_generator = online_decoder_generator,
        expected_logical_values = []
    )
        
    module_list = []

    if pauli.lower() == "x":
        module_list.append(plus_state_prep_data_qubit)
    elif pauli.lower() == "z":
        module_list.append(zero_state_prep_data_qubit)

    module_list.extend(modules_for_steane_error_correction)

    if pauli.lower() == "x":
        module_list.append(measure_data_qubit_x)
    elif pauli.lower() == "z":
        module_list.append(measure_data_qubit_z)

    mod_circ = modularised_circuit(module_list)
    mod_circ.generate_correction_to_measurement_flip_map()

    samples_performed, logical_errors = mod_circ.simulate(
        max_shots,
        max_errors_before_halting,
        results_path=results_path
    )
    return samples_performed, logical_errors
