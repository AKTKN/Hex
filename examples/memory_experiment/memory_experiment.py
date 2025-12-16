import stim
import pymatching
import numpy as np
from numpy import ndarray
from hex_qec.circuit_generation import get_parity_check_matrices, stabilizer_measurement_circuit
from hex_qec.modularisation import logical_measurement_module, detector_module, measurement_module, modularised_circuit
from hex_qec.modularisation import generate_logical_measurement_module
from plotting_lib import threshold_plot_from_function 
from typing import List, Dict, Tuple, Callable, Any

def get_circuit_with_dem_error(
        physical_error: int,
        num_shots: int,
        distance: int,
        pauli : str,
):
    code = "surface"
    dem_decoder_generator = pymatching.Matching.from_check_matrix
    channel_decoder_generator = pymatching.Matching.from_check_matrix
    parity_check_tuple = get_parity_check_matrices(code, distance)
    circuit = stabilizer_measurement_circuit(parity_check_tuple,
                                             pauli,
                                             syndrome_repetitions = 1,
                                             prob=physical_error,
                                             )

    module_list = [
        detector_module(circuit,
                        dem_decoder_generator,
                        [],
                        matchable = True
                        ),
        generate_logical_measurement_module(
            physical_error,
            code,
            distance,
            pauli = pauli,
            new_support = [],
            decoder_generator = channel_decoder_generator,
            expected_logical_values = []
        )
    ]

    mod_circ = modularised_circuit(module_list)
    mod_circ.generate_correction_to_measurement_flip_map()
    logical_errors = mod_circ.simulate(num_shots)
    
    return logical_errors

if __name__ == "__main__":
    physical_error_range = np.linspace(0.009, 0.04, 20)
    distance_range = [7, 9, 11]
    num_shots = 50_000
    pauli = "z"

    threshold_plot_from_function(
        get_circuit_with_dem_error,
        physical_error_range,
        num_shots,
        [({"distance": distance, "pauli": pauli}, f"Distance = {distance}") for distance in distance_range],
        title = f"Modularised Memory Experiment, {r'$|0>$' if (pauli.lower() == 'z') else r'$|+>$'}"
    )
