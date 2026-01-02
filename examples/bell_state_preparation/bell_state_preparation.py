import stim
import pymatching
import numpy as np
from numpy import ndarray
from hex_qec.circuit_generation import get_parity_check_matrices, stabilizer_measurement_circuit, noiseless_unitary_state_prep
from hex_qec.circuit_generation import generate_blocks, create_stabilizers_and_block_template
from hex_qec.modularisation import logical_measurement_module, no_measurement_module, modularised_circuit, detector_module, css_detector_module
from hex_qec.modularisation import generate_logical_measurement_module, generate_state_prep_module
from plotting_lib import threshold_plot_from_function 
from typing import List, Dict, Tuple, Callable, Any


def generate_joint_logical_measurement_module(
        physical_error: int,
        code: str,
        distance: int,
        pauli_string: str,
        new_support: List[int],
        decoder_generator: Callable[[ndarray], Callable[[ndarray], ndarray]],
        expected_logical_values: List[int] =[]
):
    (x_pcm, z_pcm, x_logical, z_logical) = get_parity_check_matrices(code, distance=distance)
    k = x_logical.shape[0]
    num_qubits = x_pcm.shape[1]
    number_of_blocks = len(pauli_string)
    print(f"Code number qubits: {num_qubits}")
    print(f"Number block in simultaneous measurement: {number_of_blocks}")
    # k logical values should be provided
    if len(expected_logical_values) == 0:
        # Default the expected logical values to zero
        expected_logical_values = np.zeros(k, dtype=int)
    elif len(expected_logical_values) != k:
        print("Size of expected logical values should the same as k * length of the provided Pauli string")

    # Generate measurement circuit
    circuit = stim.Circuit()
    start_of_block_support = 0
    full_support = range(0, num_qubits * number_of_blocks)
    for pauli in pauli_string:
        print(pauli)
        block_support = full_support[start_of_block_support:start_of_block_support + num_qubits]
        if pauli.lower() == "z":
            circuit.append("X_ERROR", block_support, physical_error)
            circuit.append("M", block_support)
        elif pauli.lower() == "x":
            circuit.append("Z_ERROR", block_support, physical_error)
            circuit.append("MX", block_support)
        else:
            print("Invalid pauli")
            raise
        start_of_block_support += num_qubits


    # The c_func should split the measurement data into each block
    # decode each of these blocks measurements data and get the logical values
    #

    # This will return a vector of length k
    # where value i in the vector is the measurement a pauli string between the same logical qubit in multiple blocks
    # E.g. If the pauli string is XX and the block has k=4 logical qubits. You will return the values for the 4 measurements of the
    # logical XX between the two blocks
    x_decoder = decoder_generator(x_pcm)
    z_decoder = decoder_generator(z_pcm)
    def c_func(measurements):
        logical_values = np.zeros((measurements.shape[0], k))
        start_of_block_measurements = 0
        for block_num, pauli in enumerate(pauli_string):
            block_measurements = measurements[:, start_of_block_measurements:start_of_block_measurements+num_qubits]
            if pauli.lower() == "z":
                pcm = z_pcm
                logicals = z_logical
                decoder = z_decoder
            elif pauli.lower() == "x":
                pcm = x_pcm
                logicals = x_logical
                decoder = x_decoder

            # Decode
            syndromes = (block_measurements @ pcm.T) % 2
            corrections = decoder.decode_batch(syndromes)
            corrected_block_measurements = (block_measurements + corrections) % 2
            logical_values += (corrected_block_measurements @ logicals.T) % 2

            start_of_block_measurements += num_qubits

        logical_values = logical_values % 2
        return logical_values

    module = logical_measurement_module(
        circuit,
        c_func,
        expected_logical_values,
        new_support = new_support
    )

    return module

def bell_state_prep(
        physical_error: int,
        num_shots: int,
        distance: int,
        pauli : str,
):
    code = "surface"
    dem_decoder_generator = pymatching.Matching.from_check_matrix
    channel_decoder_generator = pymatching.Matching.from_check_matrix
    parity_check_tuple = get_parity_check_matrices(code, distance)
    block_template, _, _, _ = create_stabilizers_and_block_template(*parity_check_tuple)
    blocks = generate_blocks(2, block_template)

    num_qubits_in_code_block = len(blocks[0]["data_qubits"])
    k = parity_check_tuple[2].shape[0]

    first_block_support = blocks[0]["data_qubits"]
    second_block_support = blocks[1]["data_qubits"]
    first_block_support_with_ancillas = blocks[0]["data_qubits"]+blocks[0]["x_ancillas"]+blocks[0]["z_ancillas"]
    second_block_support_with_ancillas = blocks[1]["data_qubits"]+blocks[1]["x_ancillas"]+blocks[1]["z_ancillas"]

    # # Perfect state preparation
    plus_state_prep_circuit_noiseless = noiseless_unitary_state_prep(code, distance, "x", eigenvalue = 0)
    plus_state_prep_module_noiseless = no_measurement_module(plus_state_prep_circuit_noiseless, first_block_support)
    zero_state_prep_circuit_noiseless = noiseless_unitary_state_prep(code, distance, "z", eigenvalue = 0)
    zero_state_prep_module_noiseless = no_measurement_module(zero_state_prep_circuit_noiseless, second_block_support)

    # # Noisy state preparation
    plus_state_prep_circuit_noisy = stabilizer_measurement_circuit(parity_check_tuple, "x", syndrome_repetitions=distance, prob=physical_error)
    plus_state_prep_module_noisy = detector_module(plus_state_prep_circuit_noisy, dem_decoder_generator, first_block_support_with_ancillas, matchable=True)
    zero_state_prep_circuit_noisy = stabilizer_measurement_circuit(parity_check_tuple, "z", syndrome_repetitions=distance, prob=physical_error)
    zero_state_prep_module_noisy = detector_module(zero_state_prep_circuit_noisy, dem_decoder_generator, second_block_support_with_ancillas, matchable=True)
    
    # # CSS state preparation
    # plus_state_prep_module_noisy = generate_state_prep_module(
    #     code,
    #     distance,
    #     "x",
    #     physical_error,
    #     first_block_support_with_ancillas,
    #     dem_decoder_generator,
    #     matchable=True,
    # )
    # zero_state_prep_module_noisy = generate_state_prep_module(
    #     code,
    #     distance,
    #     "z",
    #     physical_error,
    #     second_block_support_with_ancillas,
    #     dem_decoder_generator,
    #     matchable=True,
    # )

    # Transversal CNOT circuit
    transversal_cnot_circuit = stim.Circuit()
    for q_index in range(len(first_block_support)):
        transversal_cnot_circuit.append("CX", [range(0, num_qubits_in_code_block)[q_index],
                                               range(num_qubits_in_code_block, 2*num_qubits_in_code_block)[q_index]]
                                        )
    # transversal_cnot_circuit.append("DEPOLARIZE2",
    #                                 [item for pair in zip(range(0, num_qubits_in_code_block), range(num_qubits_in_code_block, 2*num_qubits_in_code_block)) for item in pair],
    #                                 physical_error)
    transversal_cnot_module_1 = no_measurement_module(
        transversal_cnot_circuit,
        first_block_support + second_block_support,
    )
    transversal_cnot_module_2 = no_measurement_module(
        transversal_cnot_circuit,
        second_block_support + first_block_support,
    )
    # print(first_block_support + second_block_support)

    # Module for measuring XX or ZZ between the two blocks
    joint_logical_measurement_module = generate_joint_logical_measurement_module(
        physical_error,
        code,
        distance,
        f"{pauli}{pauli}",
        new_support = first_block_support + second_block_support,
        decoder_generator = channel_decoder_generator,
        expected_logical_values = [],
    )

    measure_x_block_module = generate_logical_measurement_module(
        physical_error,
        code,
        distance,
        pauli = "x",
        new_support = second_block_support,
        decoder_generator = channel_decoder_generator,
        expected_logical_values = []
    )
    measure_z_block_module = generate_logical_measurement_module(
        physical_error,
        code,
        distance,
        pauli = "z",
        new_support = first_block_support,
        decoder_generator = channel_decoder_generator,
        expected_logical_values = []
    )

    module_list = [
        #plus_state_prep_module_noiseless,
        #zero_state_prep_module_noiseless,
        plus_state_prep_module_noisy,
        zero_state_prep_module_noisy,
        transversal_cnot_module_1,
        transversal_cnot_module_2,
        #joint_logical_measurement_module,
        measure_x_block_module,
        measure_z_block_module,
    ]

    mod_circ = modularised_circuit(module_list)
    mod_circ.generate_correction_to_measurement_flip_map()
    logical_errors = mod_circ.simulate(num_shots)

    return logical_errors

if __name__ == "__main__":
    physical_error_range = np.linspace(0.001, 0.004, 4)
    distance_range = [5, 7, 9]
    num_shots = 50_000
    pauli = "z"

    threshold_plot_from_function(
        bell_state_prep,
        physical_error_range,
        num_shots,
        [({"distance": distance, "pauli": pauli}, f"Distance = {distance}") for distance in distance_range],
        #title = f"Bell State Preparation Experiment, Measuring logical {'ZZ' if (pauli.lower() == 'z') else 'XX'}"
        title = f"Bell State Preparation and Measurement",
    )
