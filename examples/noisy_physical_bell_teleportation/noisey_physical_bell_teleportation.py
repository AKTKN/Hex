import stim
import numpy as np
from numpy import ndarray
from hex_qec.modularisation import logical_measurement_module, detector_module, measurement_module, modularised_circuit
from plotting_lib import threshold_plot_from_function 
from typing import List, Dict, Tuple, Callable, Any


def get_bell_logical_error(physical_error, num_shots, number_of_bell_teleportations):
    def generate_noisey_teleportation_circuit(physical_error: int):
        return stim.Circuit(f"""
        RX 1
        R 2
        CX 1 2
        DEPOLARIZE2({physical_error}) 0 1
        CX 0 1
        MX 0
        MZ 1
        """)
    # This will take batch input of the two measurements of the bell circuit
    # and return batch corrections
    def c_func_bell(measurements: ndarray) -> ndarray:
        assert measurements.shape[1] == 2
        return measurements[:, [1, 0]]

    bell_modules = []
    for bell_num in range(number_of_bell_teleportations):
        bell_circ = generate_noisey_teleportation_circuit(physical_error)
        bell_modules.append(
            measurement_module(
                bell_circ,
                c_func_bell,
                [("X2", len(bell_circ)),
                ("Z2", len(bell_circ)),
                ],
                new_support = [2*(bell_num), 2*(bell_num)+1, 2*(bell_num)+2]
            )
        )
    bell_modules.append(
        logical_measurement_module(
            stim.Circuit("M 0"),
            lambda x: x,
            np.array([0]),
            new_support = [2*(bell_num)+2]
        )
    )
    # bell_modules.append(
    #     logical_measurement_module(
    #         stim.Circuit("""
    #         H 0
    #         M 0
    #         """),
    #         lambda x: x,
    #         np.array([0]),
    #         new_support = [11]
    #     )
    # )

    mod_circ = modularised_circuit(bell_modules)
    mod_circ.generate_correction_to_measurement_flip_map()
    logical_errors = mod_circ.simulate(num_shots)
    return logical_errors


if __name__ == "__main__":
    # Plot the data
    physical_error_range = np.linspace(0.01, 0.05, 5)
    bell_repetition_range = [10, 15, 20]
    num_shots = 50_000

    threshold_plot_from_function(
        get_bell_logical_error,
        physical_error_range,
        num_shots,
        [({"number_of_bell_teleportations": bell_rep}, f"Teleportations = {bell_rep}") for bell_rep in bell_repetition_range],
        title = "Noisy Teleportations"
    )
