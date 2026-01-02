from pprint import pprint
import stim
import pymatching
import numpy as np
from numpy import ndarray
from hex_qec.circuit_generation import get_parity_check_matrices, stabilizer_measurement_circuit, noiseless_unitary_state_prep, stabilizer_measurement_circuit_both_detectors
from hex_qec.circuit_generation import generate_blocks, create_stabilizers_and_block_template
from hex_qec.modularisation import logical_measurement_module, no_measurement_module, modularised_circuit, detector_module, css_detector_module
from hex_qec.modularisation import generate_logical_measurement_module, generate_state_prep_module
from stimbposd import detector_error_model_to_check_matrices
from plotting_lib import threshold_plot_from_function 
from typing import List, Dict, Tuple, Callable, Any
from datetime import datetime
import subprocess

def css_detector_module_test_error(
        physical_error: int,
        num_shots: int,
        distance: int,
        pauli : str,
) -> int:
    code = "surface"
    matchable = True
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

    module_1 = generate_state_prep_module(
        code,
        distance,
        "X",
        physical_error,
        first_block_support_with_ancillas,
        dem_decoder_generator,
        matchable,
    )
    module_2 = generate_state_prep_module(
        code,
        distance,
        "Z",
        physical_error,
        second_block_support_with_ancillas,
        dem_decoder_generator,
        matchable,
    )


    logical_measurement_module_1 = generate_logical_measurement_module(
        physical_error,
        code,
        distance,
        "X",
        first_block_support,
        channel_decoder_generator,
        [],
    )
    logical_measurement_module_2 = generate_logical_measurement_module(
        physical_error,
        code,
        distance,
        "Z",
        second_block_support,
        channel_decoder_generator,
        [],
    )
    module_list = [
        module_1,
        module_2,
        logical_measurement_module_1,
        logical_measurement_module_2,
    ]

    mod_circ = modularised_circuit(module_list)
    mod_circ.generate_correction_to_measurement_flip_map()
    logical_errors = mod_circ.simulate(num_shots)

    return logical_errors

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


def test_css_detector_module():
    physical_error_range = np.linspace(0.001, 0.003, 4)
    distance_range = [3, 5, 7]
    num_shots = 50_000
    pauli = "z"

    #css_detector_module_test_error(0.01, num_shots, 3, pauli)

    check_branch()
    # Add everything in the directory to the staging area
    subprocess.run(["git", "add", "-A"])
    
    current_datetime = datetime.now()
    current_datetime_string = datetime.now().strftime("%Y_%m_%d__%H_%M_%S")

    threshold_plot_from_function(
        css_detector_module_test_error,
        physical_error_range,
        num_shots,
        [({"distance": distance, "pauli": pauli}, f"Distance = {distance}") for distance in distance_range],
        title = f"CSS Module Experiment, {r'$|0>$' if (pauli.lower() == 'z') else r'$|+>$'}",
        path = f"CSS Module Experiment, {r'$|0>$' if (pauli.lower() == 'z') else r'$|+>$'}, {current_datetime_string}.pdf",
        include_physical_error = True,
    )
    log_changes(current_datetime)


if __name__ == "__main__":
    #split_the_detectors_in_a_dem()
    test_css_detector_module()
