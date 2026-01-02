import stim
import pymatching
import relay_bp
import numpy as np
from scipy.sparse import csc_matrix, csr_matrix
from numpy import ndarray
from hex_qec.circuit_generation import get_parity_check_matrices, noiseless_unitary_state_prep
from hex_qec.modularisation import logical_measurement_module, no_measurement_module, modularised_circuit
from hex_qec.modularisation import generate_logical_measurement_module
from plotting_lib import threshold_plot_from_function 
from typing import List, Dict, Tuple, Callable, Any

def channel_noise_error(
        physical_error: int,
        num_shots: int,
        code : str,
        channel_decoder_generator : Callable[[ndarray], Callable[[ndarray], ndarray]],
        distance: int,
        pauli : str,
):
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
    physical_error_range = [0] + np.linspace(0.001, 0.003, 3)
    distance_range = [3]
    num_shots = 100_000
    pauli = "x"
    code = "color_triangular"
    channel_decoder_generator = lambda check_matrix : relay_bp.RelayDecoderF32(
        csr_matrix(check_matrix),
        error_priors=np.ones(check_matrix.shape[1], dtype=np.float64) * 0.0001, # Set the priors probability for each error
        gamma0=0.65, # Uniform memory weight for the first ensemble
        pre_iter=10, # Max BP iterations for the first ensemble
        num_sets=100, # Number of relay ensemble elements
        set_max_iter=60, # Max BP iterations per relay ensemble
        gamma_dist_interval=(-0.24, 0.66), # Set the uniform distribution range for disordered memory weight selection
        stop_nconv=5, # Number of relay solutions to find before stopping (the best will be selected)
    )

    threshold_plot_from_function(
        channel_noise_error,
        physical_error_range,
        num_shots,
        [({"channel_decoder_generator" : channel_decoder_generator,
           "code": code,
           "distance": distance,
           "pauli": pauli}, f"Distance = {distance}") for distance in distance_range],
        title = f"Steane Code Channel Noise Experiment, {r'$|0>$' if (pauli.lower() == 'z') else r'$|+>$'}"
    )
