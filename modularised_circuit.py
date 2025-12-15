import stim
import numpy as np
from numpy import ndarray
import shutil
np.set_printoptions(linewidth=shutil.get_terminal_size().columns)
import scipy
from scipy.sparse import csc_matrix, csr_matrix
from typing import List, Dict, Tuple, Callable, Any
from pprint import pprint
import re
import pandas as pd
from plotting_lib import generate_threshold_plot

class logical_measurement_module():
    def __init__(self,
                 circuit: stim.Circuit,
                 c_func: Callable[[ndarray], ndarray],
                 c_func_expected_output: ndarray,
                 new_support: List[int] = None
                 ) -> None:
        self.circuit = circuit
        self.num_measurements = circuit.num_measurements
        self.num_detectors = circuit.num_detectors
        self.c_func = c_func
        self.support_set = False
        self.c_func_expected_output = c_func_expected_output

        # Check that the input and output dimensions of c_func work
        try:
            test_batch_size = 10
            test_c_func_input = np.zeros((test_batch_size, self.num_measurements), dtype=int)
            c_func_output = c_func(test_c_func_input)
            assert c_func_output.shape == (test_batch_size, len(c_func_expected_output))
        except AssertionError as a:
            print(f"The output size of c_func doesn't match the fault array")
        except Exception as e:
            print(f"Testing c_func resulted in the following error: {e}")

        if new_support != None:
            self.change_support(new_support)

    def change_support(self,
                       new_support: List[int],
                       ) -> None:
        if self.support_set:
            print("Support already set")
            raise
        else:
            # Update the circuit
            assert len(new_support) == self.circuit.num_qubits
            circuit_replacements = {f" {original}" : f" {new}" for original, new in enumerate(new_support)}
            circuit_replace_func = lambda matched: circuit_replacements.get(matched.group(0), matched.group(0))
            circuit_regex_pattern = '|'.join(re.escape(key) for key in circuit_replacements.keys())
            new_circuit_text = re.sub(circuit_regex_pattern, circuit_replace_func, str(self.circuit))
            self.circuit = stim.Circuit(new_circuit_text)

            self.support_set = True

class measurement_module():
    # c_func should work on a batch of inputs
    def __init__(self,
                 circuit: stim.Circuit,
                 c_func: Callable[[ndarray], ndarray],
                 correction_array: List[Tuple[str, int]],
                 new_support: List[int] = None
                 ) -> None:
        self.circuit = circuit
        self.num_measurements = circuit.num_measurements
        self.num_detectors = circuit.num_detectors
        self.c_func = c_func
        self.correction_array = correction_array
        self.support_set = False
        # Check that the input and output dimensions of c_func work
        try:
            test_batch_size = 10
            test_c_func_input = np.zeros((test_batch_size, self.num_measurements), dtype=int)
            c_func_output = c_func(test_c_func_input)
            assert c_func_output.shape == (test_batch_size, len(correction_array))
        except AssertionError as a:
            print(f"The output size of c_func doesn't match the fault array")
        except Exception as e:
            print(f"Testing c_func resulted in the following error: {e}")

        if new_support != None:
            self.change_support(new_support)

    def change_support(self,
                       new_support: List[int],
                       ) -> None:
        if self.support_set:
            print("Support already set")
            raise
        else:
            # Update the circuit
            assert len(new_support) == self.circuit.num_qubits
            circuit_replacements = {f" {original}" : f" {new}" for original, new in enumerate(new_support)}
            circuit_replace_func = lambda matched: circuit_replacements.get(matched.group(0), matched.group(0))
            circuit_regex_pattern = '|'.join(re.escape(key) for key in circuit_replacements.keys())
            new_circuit_text = re.sub(circuit_regex_pattern, circuit_replace_func, str(self.circuit))
            self.circuit = stim.Circuit(new_circuit_text)


            # Update the Pauli corrections
            new_corrections = []
            pauli_replacements = {f'{original}' : f'{new}' for original, new in enumerate(new_support)}
            def pauli_replace_func(matched):
                pauli = matched.group(0)[0]
                qubit = matched.group(0)[1:]
                return f"{pauli}{pauli_replacements.get(qubit, qubit)}"
            pauli_regex_pattern = '|'.join(rf"\w{key}" for key in pauli_replacements.keys())
            for correction in self.correction_array:
                new_corrections.append((re.sub(pauli_regex_pattern, pauli_replace_func, correction[0]), correction[1]))
            self.correction_array = new_corrections

            self.support_set = True

def convert_pauli_to_error(pauli_string):
    error_circuit = stim.Circuit()
    for location, pauli in enumerate(pauli_string):
        if pauli == 1:
            error_circuit.append(stim.Circuit(f"X_ERROR(1) {location}"))
        elif pauli == 2:
            error_circuit.append(stim.Circuit(f"Y_ERROR(1) {location}"))
        elif pauli == 3:
            error_circuit.append(stim.Circuit(f"Z_ERROR(1) {location}"))
    return error_circuit

class modularised_circuit():
    def __init__(self,
                 circuit_modules: List[measurement_module]
                 ) -> None:
        self.circuit_modules = []
        self.logical_measurement_modules = []
        self.circuit = stim.Circuit()
        for module in circuit_modules:
            self.circuit += module.circuit
            if isinstance(module, logical_measurement_module):
                self.logical_measurement_modules.append(module)
            self.circuit_modules.append(module)


    def generate_correction_to_measurement_flip_map(self):
        flip_sim = stim.FlipSimulator(batch_size=1, disable_stabilizer_randomization=True)
        for module_number, module in enumerate(self.circuit_modules):
            if isinstance(module, measurement_module):
                circuit_before_module = stim.Circuit()
                for module_before in self.circuit_modules[:module_number]:
                    circuit_before_module += module_before.circuit.without_noise()
                circuit_after_module = stim.Circuit()
                for module_after in self.circuit_modules[module_number+1:]:
                    circuit_after_module += module_after.circuit.without_noise()
                detector_flips = []
                measurement_flips = []
                for pauli_correction, location in module.correction_array:
                    # Construct circuit with the pauli correction inserted
                    circuit_before_correction = module.circuit[:location].without_noise()
                    circuit_after_correction = module.circuit[location+1:].without_noise()
                    flip_circuit = circuit_before_module + circuit_before_correction + convert_pauli_to_error(stim.PauliString(pauli_correction)) + circuit_after_correction + circuit_after_module
                    # Use the flip simulator to find what measurements and detectors are flipped by this correction
                    flip_sim.do(flip_circuit)
                    measurements_flipped = flip_sim.get_measurement_flips().T
                    detectors_flipped = flip_sim.get_detector_flips().T
                    detector_flips.append(detectors_flipped)
                    measurement_flips.append(measurements_flipped)
                    flip_sim.clear()
                    #print(flip_circuit.diagram())
                module.correction_to_detector_flips = np.vstack(detector_flips)
                module.correction_to_measurement_flips = np.vstack(measurement_flips)

    def simulate(self,
                 num_shots: int
                 ) -> int:
        # Sample
        m2d_converter = self.circuit.compile_m2d_converter()
        measurement_sampler = self.circuit.compile_sampler()
        measurement_samples = measurement_sampler.sample(shots=num_shots)
        
        # Iterate over the modules and perform their corrections
        previous_measurements = 0
        previous_detectors = 0
        logical_errors = np.zeros((num_shots), dtype=int)
        for module in self.circuit_modules:
            if isinstance(module, measurement_module):
                module_measurements = measurement_samples[:, previous_measurements:previous_measurements+module.num_measurements]
                # Detectors need to be recalculated for each modules because the measurements are being updated
                detector_flips, observable_values = m2d_converter.convert(measurements=measurement_samples, separate_observables=True)
                module_detectors = detector_flips[:, previous_detectors:previous_detectors+module.num_detectors]

                # Apply the c_func
                corrections = csr_matrix(module.c_func(module_measurements))
                measurement_updates = (corrections @ module.correction_to_measurement_flips) % 2
                measurement_samples = ((measurement_samples + measurement_updates) % 2).astype(bool)

                previous_measurements += module.num_measurements
                previous_detectors += module.num_detectors
            elif isinstance(module, logical_measurement_module):
                module_measurements = measurement_samples[:, previous_measurements:previous_measurements+module.num_measurements]

                # logical measurement
                logical_measurement = module.c_func(module_measurements)
                logical_errors += np.all(logical_measurement != module.c_func_expected_output, axis=1).astype(int)

                previous_measurements += module.num_measurements
                previous_detectors += module.num_detectors

        # 1 or more logical measurements having the wrong values in a given sample means that that samples had a logical error
        logical_errors[logical_errors > 0] = 1

        return np.sum(logical_errors)

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
    #print(mod_circ.circuit.diagram())
    mod_circ.generate_correction_to_measurement_flip_map()
    logical_errors = mod_circ.simulate(num_shots)
    print(logical_errors)
    return logical_errors


def generate_plot(
        logical_error_function: Callable[[int, int], int],
        physical_error_range: ndarray,
        num_shots: int,
        kwargs_with_labels: Tuple[Dict[str, Any], str],
        title : str = None,
):

    labeled_df_list = []
    for labelled_kwargs in kwargs_with_labels:
        label = labelled_kwargs[1]
        kwargs = labelled_kwargs[0]
        labeled_df = pd.DataFrame(columns=["physical error", "logical error", "logical error interval above", "logical error interval below", "label"])
        labeled_df["physical error"] =  physical_error_range
        labeled_df["label"] = label
        labeled_df["logical error interval above"] = 0
        labeled_df["logical error interval below"] = 0
        print(label)
        logical_errors = []
        for physical_error in physical_error_range:
            logical_flips = get_bell_logical_error(physical_error, num_shots, **kwargs)
            logical_errors.append(logical_flips / num_shots)
        labeled_df["logical error"] = logical_errors
        labeled_df_list.append(labeled_df)
    plot_df = pd.concat(labeled_df_list, ignore_index=True)

    if title == None:
        title = "Temp Plot"
    plot_df.to_csv(f"{title}.csv", index=False)
    generate_threshold_plot(
        f"{title}.csv",
        title,
        output_path=f"{title}.pdf"
    )
    

if __name__ == "__main__":
    # Plot the data
    physical_error_range = np.linspace(0.01, 0.05, 5)
    bell_repetition_range = [20, 30, 40]
    num_shots = 50_000

    generate_plot(
        get_bell_logical_error,
        physical_error_range,
        num_shots,
        [({"number_of_bell_teleportations": bell_rep}, f"Teleportations = {bell_rep}") for bell_rep in bell_repetition_range],
        title = "Noisy Teleportations"
    )
