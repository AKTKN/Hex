import stim
import pymatching
import numpy as np
from numpy import ndarray
from hex_qec.circuit_generation import get_parity_check_matrices, noiseless_unitary_state_prep
from hex_qec.modularisation import logical_measurement_module, no_measurement_module, modularised_circuit
from hex_qec.modularisation import generate_logical_measurement_module
from plotting_lib import threshold_plot_from_function 
from typing import List, Dict, Tuple, Callable, Any

def channel_noise_error(
        physical_error: int,
        num_shots: int,
        distance: int,
        pauli : str,
):
    code = "surface"
    channel_decoder_generator = pymatching.Matching.from_check_matrix
    parity_check_tuple = get_parity_check_matrices(code, distance)

    state_prep_circuit = noiseless_unitary_state_prep(
        code,
        distance,
        pauli,
        eigenvalue = 0,
    )

    state_prep_module = no_measurement_module(
        state_prep_circuit,
        []
    )

    final_measurement = generate_logical_measurement_module(
        physical_error,
        code,
        distance,
        pauli = pauli,
        new_support = [],
        decoder_generator = channel_decoder_generator,
        expected_logical_values = []
    )

    module_list = [
        state_prep_module,
        final_measurement
    ]

    mod_circ = modularised_circuit(module_list)
    mod_circ.generate_correction_to_measurement_flip_map()
    logical_errors = mod_circ.simulate(num_shots)

    return logical_errors

if __name__ == "__main__":
    physical_error_range = np.linspace(0.05, 0.15, 10)
    distance_range = [7, 9, 11]
    num_shots = 50_000
    pauli = "x"

    threshold_plot_from_function(
        channel_noise_error,
        physical_error_range,
        num_shots,
        [({"distance": distance, "pauli": pauli}, f"Distance = {distance}") for distance in distance_range],
        title = f"Modularised Channel Noise Experiment, {r'$|0>$' if (pauli.lower() == 'z') else r'$|+>$'}"
    )
