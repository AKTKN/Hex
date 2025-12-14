import stim
import numpy as np
from numpy import ndarray
import shutil
np.set_printoptions(linewidth=shutil.get_terminal_size().columns)
import scipy
from scipy.sparse import csc_matrix, csr_matrix
from typing import List, Dict, Tuple, Callable
from pprint import pprint
import re


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
            test_c_func_input = np.zeros((test_batch_size, self.num_measurements), dtype=np.int8)
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
        self.circuit_modules = circuit_modules

    def generate_correction_to_measurement_flip_map(self):
        flip_sim = stim.FlipSimulator(batch_size=1, disable_stabilizer_randomization=True)
        for module_number, module in enumerate(self.circuit_modules):
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
                print(flip_circuit.diagram())
            module.correction_to_detector_flips = np.vstack(detector_flips)
            module.correction_to_measurement_flips = np.vstack(measurement_flips)
            pprint(module.correction_to_detector_flips)
            pprint(module.correction_to_measurement_flips)

if __name__ == "__main__":
    bell_teleportation_circuit = stim.Circuit("""
    RX 1
    R 2
    CX 1 2
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
    for bell_num in range(4):
        bell_modules.append(
            measurement_module(
                bell_teleportation_circuit,
                c_func_bell,
                [("X2", len(bell_teleportation_circuit)),
                ("Z2", len(bell_teleportation_circuit)),
                 ],
                new_support = [2*(bell_num), 2*(bell_num)+1, 2*(bell_num)+2]
            )
        )

    mod_circ = modularised_circuit(bell_modules)
    mod_circ.generate_correction_to_measurement_flip_map()
