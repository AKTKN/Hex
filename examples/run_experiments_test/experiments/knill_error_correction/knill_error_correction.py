import stim
import pymatching
import numpy as np
from numpy import ndarray
from hex_qec.circuit_generation import get_parity_check_matrices, stabilizer_measurement_circuit, noiseless_unitary_state_prep
from hex_qec.circuit_generation import generate_blocks, create_stabilizers_and_block_template
from hex_qec.modularisation import logical_measurement_module, no_measurement_module, modularised_circuit, detector_module, css_detector_module, measurement_module
from hex_qec.modularisation import generate_logical_measurement_module, generate_state_prep_module, generate_state_prep_module_no_noise
from plotting_lib import threshold_plot_from_function 
from typing import List, Dict, Tuple, Callable, Any
from pprint import pprint
from datetime import datetime
import subprocess
import argparse
import json

def check_branch():
    current_branch = subprocess.run(["git", "branch", "--show-current"],
                                    capture_output=True,
                                    text=True
                                    ).stdout.strip()
    if current_branch != "WIP":
        raise Exception("Not on the work in progress branch")

def log_changes(
        current_datetime : datetime,
):
    commit_message = "Automatic snapshot of code"
    current_datetime_string = current_datetime.strftime("%Y-%m-%d  %H:%M:%S")
    # Commit a snapshot of the code to a work in progress (WIP) branch
    subprocess.run(["git",
                    "commit",
                    "-m",
                    f"{commit_message} ({current_datetime_string})",
                    "--date",
                    current_datetime_string
                    ])

def generate_knill_correction_module(
        physical_error: int,
        code: str,
        distance: int,
        # pauli: str,
        data_block_support: List[int],
        first_bell_block_support: List[int],
        second_bell_block_support: List[int],
        decoder_generator: Callable[[ndarray], Callable[[ndarray], ndarray]],
) -> measurement_module:
    (x_pcm, z_pcm, x_logical, z_logical) = get_parity_check_matrices(code, distance=distance)
    k = x_logical.shape[0]
    num_qubits = x_pcm.shape[1]

    assert len(data_block_support) == num_qubits
    assert len(first_bell_block_support) == num_qubits
    assert len(second_bell_block_support) == num_qubits


    bell_measurement_circuit_error = physical_error
    # Circuit for transversal Bell measurement
    circuit = stim.Circuit()
    circuit.append("I", range(0, 3*num_qubits))
    # Transversal CNOT
    for q_index in range(num_qubits):
        circuit.append("CX", [range(0, num_qubits)[q_index],
                            range(num_qubits, 2*num_qubits)[q_index]]
                    )
        circuit.append("DEPOLARIZE2", [range(0, num_qubits)[q_index],
                                       range(num_qubits, 2*num_qubits)[q_index]],
                       bell_measurement_circuit_error
                    )
    # Measure data block in X basis
    circuit.append("Z_ERROR", range(0, num_qubits), bell_measurement_circuit_error)
    circuit.append("MRX", range(0, num_qubits))
    # Measure data block in Z basis
    circuit.append("X_ERROR", range(num_qubits, 2*num_qubits), bell_measurement_circuit_error)
    circuit.append("MR", range(num_qubits, 2*num_qubits))

    x_decoder = decoder_generator(x_pcm)
    z_decoder = decoder_generator(z_pcm)
    def c_func(measurements):
        # For the moment I am just going to do CSS decoding
        x_measurements = measurements[:, :num_qubits]
        z_measurements = measurements[:, num_qubits:2*num_qubits]
        x_syndromes = (x_measurements @ x_pcm.T) % 2
        z_syndromes = (z_measurements @ z_pcm.T) % 2
        print(np.sum(x_syndromes, axis=0))
        print(np.sum(z_syndromes, axis=0))
        z_errors = x_decoder.decode_batch(x_syndromes)
        x_errors = z_decoder.decode_batch(z_syndromes)
        x_measurements = (x_measurements + z_errors) % 2
        z_measurements = (z_measurements + x_errors) % 2
        x_logical_measurements = (x_measurements @ x_logical.T) % 2
        z_logical_measurements = (z_measurements @ z_logical.T) % 2

        corrections = np.hstack([x_logical_measurements, z_logical_measurements])
        return corrections

    # Create correction array
    # These need to be the logical representatives
    correction_array = []
    for z_logical_representative in z_logical.toarray():
        logical_pauli_correction = []
        for qubit_index, qubit_supported in enumerate(z_logical_representative):
            if qubit_supported:
                logical_pauli_correction.append(f"Z{range(2*num_qubits, 3*num_qubits)[qubit_index]}")
        correction_array.append(("*".join(logical_pauli_correction), len(circuit)))

    for x_logical_representative in x_logical.toarray():
        logical_pauli_correction = []
        for qubit_index, qubit_supported in enumerate(x_logical_representative):
            if qubit_supported:
                logical_pauli_correction.append(f"X{range(2*num_qubits, 3*num_qubits)[qubit_index]}")
        correction_array.append(("*".join(logical_pauli_correction), len(circuit)))

    module = measurement_module(
        circuit,
        c_func,
        correction_array,
        data_block_support + first_bell_block_support + second_bell_block_support,
    )
    #print(module.circuit.diagram())

    return module

def generate_transversal_cnot_module(
        physical_error,
        first_block_support,
        second_block_support,
) -> no_measurement_module:
    # The circuit definition doesn't depend on the block support.
    # The circuit is moved to the support when you initialise the module
    transversal_cnot_circuit = stim.Circuit()
    num_qubits_in_code_block = len(first_block_support)
    for q_index in range(num_qubits_in_code_block):
        transversal_cnot_circuit.append("CX", [range(0, num_qubits_in_code_block)[q_index],
                                               range(num_qubits_in_code_block, 2*num_qubits_in_code_block)[q_index]]
                                        )
        transversal_cnot_circuit.append("DEPOLARIZE2", [range(0, num_qubits_in_code_block)[q_index],
                                                        range(num_qubits_in_code_block, 2*num_qubits_in_code_block)[q_index]],
                                        physical_error, 
                                        )
    transversal_cnot_module = no_measurement_module(
        transversal_cnot_circuit,
        first_block_support + second_block_support,
    )

    return transversal_cnot_module


def knill_error_correction(
        physical_error: int,
        num_shots: int,
        distance: int,
        pauli : str,
        repetitions : int,
        include_corrections : bool,
) -> int:
    code = "surface"
    dem_decoder_generator = pymatching.Matching.from_check_matrix
    channel_decoder_generator = pymatching.Matching.from_check_matrix
    parity_check_tuple = get_parity_check_matrices(code, distance)
    block_template, _, _, _ = create_stabilizers_and_block_template(*parity_check_tuple)
    blocks = generate_blocks(2*repetitions+1, block_template)

    num_qubits_in_code_block = len(blocks[0]["data_qubits"])
    k = parity_check_tuple[2].shape[0]

    # first_block_support = blocks[0]["data_qubits"]
    # second_block_support = blocks[1]["data_qubits"]
    # third_block_support = blocks[2]["data_qubits"]
    # first_block_support_with_ancillas = blocks[0]["data_qubits"]+blocks[0]["x_ancillas"]+blocks[0]["z_ancillas"]
    # second_block_support_with_ancillas = blocks[1]["data_qubits"]+blocks[1]["x_ancillas"]+blocks[1]["z_ancillas"]
    # third_block_support_with_ancillas = blocks[2]["data_qubits"]+blocks[2]["x_ancillas"]+blocks[2]["z_ancillas"]

    # Perfect state preparation circuits
    plus_state_prep_circuit_noiseless = noiseless_unitary_state_prep(code, distance, "x", eigenvalue = 0)
    zero_state_prep_circuit_noiseless = noiseless_unitary_state_prep(code, distance, "z", eigenvalue = 0)

    # Perfect data qubit states
    plus_state_prep_data_qubit = no_measurement_module(plus_state_prep_circuit_noiseless, blocks[0]["data_qubits"])
    zero_state_prep_data_qubit = no_measurement_module(zero_state_prep_circuit_noiseless, blocks[0]["data_qubits"])

    # Knill error correction modules
    modules_for_knill_error_correction = []
    rounds_of_knill_error_correction = repetitions
    # reset_circuit = stim.Circuit()
    # reset_circuit.append("R", range(len(second_block_support_with_ancillas)))
    for round_number in range(rounds_of_knill_error_correction):
        # Prepare logical Bell state
        # modules_for_knill_error_correction.append(no_measurement_module(zero_state_prep_circuit_noiseless, blocks[2*round_number+1]["data_qubits"]))
        modules_for_knill_error_correction.append(generate_state_prep_module(
            code,
            distance,
            "z",
            physical_error,
            blocks[2*round_number+1]["data_qubits"]+blocks[2*round_number+1]["x_ancillas"]+blocks[2*round_number+1]["z_ancillas"],
            dem_decoder_generator,
            matchable=True,
        ))
        modules_for_knill_error_correction.append(no_measurement_module(plus_state_prep_circuit_noiseless, blocks[2*round_number+2]["data_qubits"]))
        modules_for_knill_error_correction.append(generate_state_prep_module(
            code,
            distance,
            "x",
            physical_error,
            blocks[2*round_number+2]["data_qubits"]+blocks[2*round_number+2]["x_ancillas"]+blocks[2*round_number+2]["z_ancillas"],
            dem_decoder_generator,
            matchable=True,
        )
        )
        modules_for_knill_error_correction.append(generate_transversal_cnot_module(physical_error,
                                                                                    blocks[2*round_number+2]["data_qubits"], # control
                                                                                    blocks[2*round_number+1]["data_qubits"], # target
                                                                                   )
                                                   )
        if include_corrections:
            modules_for_knill_error_correction.append(generate_knill_correction_module(
                physical_error,
                code,
                distance,
                blocks[2*(round_number-1)+2]["data_qubits"], # data block (second bell of previous step)
                blocks[2*round_number+1]["data_qubits"], # first bell block
                blocks[2*round_number+2]["data_qubits"], # second bell block
                pymatching.Matching.from_check_matrix
            ))
            # print(modules_for_knill_error_correction[-1].circuit.without_noise().diagram())

    measure_data_qubit_x = generate_logical_measurement_module(
        physical_error,
        code,
        distance,
        pauli = "x",
        new_support = blocks[2*round_number+2]["data_qubits"],
        decoder_generator = channel_decoder_generator,
        expected_logical_values = []
    )
    measure_data_qubit_z = generate_logical_measurement_module(
        physical_error,
        code,
        distance,
        pauli = "z",
        new_support = blocks[2*round_number+2]["data_qubits"],
        decoder_generator = channel_decoder_generator,
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
    logical_errors = mod_circ.simulate(num_shots)

    return logical_errors

def main():
    parser = argparse.ArgumentParser(description="Surface code logical error rate simulation")
    parser.add_argument("--distance", type=int, help="Code distance (odd number)")
    parser.add_argument("--physical_error_rate", type=float, help="Physical error rate")
    parser.add_argument("--num_shots", type=int, help="Number of simulation shots")
    parser.add_argument("--pauli", type=str, help="Basis to prepare logical state and to perform logical measurement")
    parser.add_argument("--repetitions", type=int, help="Number of time to repeat Knill error correction")
    parser.add_argument("--include_corrections", action='store_true', help="Whether to include the Knill correction")
    args = parser.parse_args()

    logical_errors = knill_error_correction(args.physical_error_rate, args.num_shots, args.distance,
                                             pauli = args.pauli,
                                             repetitions = args.repetitions,
                                             include_corrections = args.include_corrections,
                                             )
    logical_error_rate = logical_errors / args.num_shots
    print(f"Logical error rate: {logical_error_rate}")
    print(f"Logical errors: {logical_errors} out of {args.num_shots}")
    results = {
        "logical_error_rate" : logical_error_rate
    }

    # Save results
    with open("results.json", "w") as f:
        json.dump(results, f, indent=2)

if __name__ == "__main__":
    main()
