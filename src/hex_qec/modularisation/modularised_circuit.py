import stim
import pymatching
from stimbposd import detector_error_model_to_check_matrices
import numpy as np
from numpy import ndarray
import shutil
np.set_printoptions(linewidth=shutil.get_terminal_size().columns)
import scipy
from scipy.sparse import csc_matrix, csr_matrix
from typing import List, Dict, Tuple, Callable, Any
from pprint import pprint
import re

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
        self.change_support(new_support)

        # Check that the input and output dimensions of c_func work
        try:
            test_batch_size = 10
            test_c_func_input = np.zeros((test_batch_size, self.num_measurements), dtype=int)
            c_func_output = c_func(test_c_func_input)
            assert c_func_output.shape == (test_batch_size, len(c_func_expected_output))
        except AssertionError as a:
            print(f"The output size of c_func doesn't match the fault array")
            raise
        except Exception as e:
            print(f"Testing c_func resulted in the following error: {e}")
            raise

    def change_support(self,
                       new_support: List[int],
                       ) -> None:
        if len(new_support) == 0:
            new_support = range(self.circuit.num_qubits)
        elif len(new_support) != self.circuit.num_qubits:
            print("Module support not the correct size")
            raise
        # Update the circuit
        assert len(new_support) == self.circuit.num_qubits
        circuit_replacements = {f" {original}" : f" {new}" for original, new in enumerate(new_support)}
        circuit_replace_func = lambda matched: circuit_replacements.get(matched.group(0), matched.group(0))
        circuit_regex_pattern = '|'.join(re.escape(key) for key in circuit_replacements.keys())
        new_circuit_text = re.sub(circuit_regex_pattern, circuit_replace_func, str(self.circuit))
        self.circuit = stim.Circuit(new_circuit_text)

class detector_module():
    def __init__(self,
                 circuit: stim.Circuit,
                 c_func_generator: Callable[[ndarray, List[float]], Callable[[ndarray], ndarray]],
                 new_support: List[int],
                 matchable : bool = False
                 ) -> None:
        self.circuit = circuit
        self.c_func_generator = c_func_generator
        self.num_measurements = circuit.num_measurements
        self.num_detectors = circuit.num_detectors
        assert circuit.num_detectors > 0
        self.matchable = matchable

        self._generate_dem()
        self._generate_correction_array()
        # The input circuit is assumed to be a 'template' that will be placed into a (probably) larger set of qubits
        self._change_support(new_support)
        self._initialise_decoder()
        
    def _initialise_decoder(self):
        # Use the parity check matrix and priors of the detector error model to initialse a decoder (c_func)
        if self.matchable:
            weights = (np.log1p(self.dem_priors) - np.log(self.dem_priors))
        else:
            weights = self.dem_priors
        # The c_func for the detector measurement object should take in a batch of detector flips and return
        # an array of fault correction for each sample
        self.c_func = lambda x : self.c_func_generator(self.dem_check_matrix, weights=weights).decode_batch(x)


    def _generate_dem(self):
        self.dem = self.circuit.detector_error_model()
        self.dem_data = detector_error_model_to_check_matrices(self.dem, allow_undecomposed_hyperedges=True)
        if self.matchable:
            self.dem_check_matrix = self.dem_data.edge_check_matrix
            self.dem_hyperedge_to_edge = self.dem_data.hyperedge_to_edge_matrix
            self.dem_priors = self.dem_hyperedge_to_edge @ self.dem_data.priors
        else:
            self.dem_check_matrix = self.dem_data.check_matrix
            self.dem_priors = self.dem_data.priors

    def _get_pauli_product_from_error_location(self,
                                               circ_err_loc: stim.CircuitErrorLocation,
                                               num_qubits: int):
        # Unpack the circuit_error_location object and get the Pauli correction in a useful form
        targets = [gate_target_with_coords.gate_target for gate_target_with_coords in circ_err_loc.flipped_pauli_product]
        paulis = []
        for target in targets:
            if target.is_x_target:
                paulis.append(f"X{target.qubit_value}")
            elif target.is_z_target:
                paulis.append(f"Z{target.qubit_value}")
            elif target.is_y_target:
                paulis.append(f"Y{target.qubit_value}")
        return "*".join(paulis) 


    def _generate_correction_array(self):
        circuit_explain_errors = self.circuit.explain_detector_error_model_errors(
            dem_filter = self.dem,
            reduce_to_one_representative_error=True,
        )
        self.correction_array = []
        for explained_error in circuit_explain_errors:
            # Get location of fault
            error_location = explained_error.circuit_error_locations[0]
            stack_frame = error_location.stack_frames[0]
            instruction_offset = stack_frame.instruction_offset
            # Get Pauli of fault
            pauli_fault = self._get_pauli_product_from_error_location(error_location, self.circuit.num_qubits)
            self.correction_array.append((pauli_fault, instruction_offset))

    def _change_support(self,
                       new_support: List[int],
                       ) -> None:
        # Update the circuit
        if len(new_support) == 0:
            new_support = range(self.circuit.num_qubits)
        elif len(new_support) != self.circuit.num_qubits:
            print("Module support not the correct size")
            raise
            
        circuit_replacements = {f" {original}" : f" {new}" for original, new in enumerate(new_support)}
        def circuit_replace_func(matched):
            return circuit_replacements.get(matched.group(0), matched.group(0))
            
        circuit_regex_pattern = '|'.join(rf"{key}\b" for key in circuit_replacements.keys())
        new_circuit_text = re.sub(circuit_regex_pattern, circuit_replace_func, str(self.circuit))

        # print(circuit_replacements)
        # print(circuit_regex_pattern)
        # print("Old Circuit")
        # print(str(self.circuit)[:200])
        # print("New Circuit")
        # print(new_circuit_text[:200])

        self.circuit = stim.Circuit(new_circuit_text)

        # Update the Pauli corrections
        new_corrections = []
        pauli_replacements = {f'{original}' : f'{new}' for original, new in enumerate(new_support)}
        def pauli_replace_func(matched):
            pauli = matched.group(0)[0]
            qubit = matched.group(0)[1:]
            return f"{pauli}{pauli_replacements.get(qubit, qubit)}"
        pauli_regex_pattern = '|'.join(rf"\w{key}$" for key in pauli_replacements.keys())
        for correction in self.correction_array:
            new_corrections.append((re.sub(pauli_regex_pattern, pauli_replace_func, correction[0]), correction[1]))
        self.correction_array = new_corrections

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

class no_measurement_module():
    def __init__(self,
               circuit: stim.Circuit,
               new_support: List[int],
               ) -> None:
        self.circuit = circuit
        assert circuit.num_measurements == 0
        assert circuit.num_detectors == 0
        self.num_measurements = 0
        self.num_detectors = 0

        self._change_support(new_support)

    def _change_support(self,
                       new_support: List[int],
                       ) -> None:
        # Update the circuit
        if len(new_support) == 0:
            new_support = range(self.circuit.num_qubits)
        elif len(new_support) != self.circuit.num_qubits:
            print("Module support not the correct size")
            raise
            
        circuit_replacements = {f" {original}" : f" {new}" for original, new in enumerate(new_support)}
        def circuit_replace_func(matched):
            return circuit_replacements.get(matched.group(0), matched.group(0))
            
        circuit_regex_pattern = '|'.join(rf"{key}\b" for key in circuit_replacements.keys())
        new_circuit_text = re.sub(circuit_regex_pattern, circuit_replace_func, str(self.circuit))

        self.circuit = stim.Circuit(new_circuit_text)

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
        previous_measurements = 0
        previous_detectors = 0
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

            elif isinstance(module, detector_module):
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
                # For matchable dem we need to conver this into one where the faults are edges
                if module.matchable:
                    module.correction_to_detector_flips = (module.dem_hyperedge_to_edge @ module.correction_to_detector_flips) % 2
                    module.correction_to_measurement_flips = (module.dem_hyperedge_to_edge @ module.correction_to_measurement_flips) % 2
                # module.dem_check_matrix is the check matrix for the dem in that specific module
                # module.correction_to_detector_flips is how the corrections affect all the detectors in the circuit, even the ones outside this module
                # To compare them I need to splce module.correction_to_detectors_flips to only include the detectors for this specific module
                
                assert (module.dem_check_matrix.toarray().T == module.correction_to_detector_flips[:, previous_detectors:previous_detectors+module.num_detectors].astype(np.int8)
                        ).all()

            previous_measurements += module.num_measurements
            previous_detectors += module.num_detectors

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
            if isinstance(module, logical_measurement_module):
                module_measurements = measurement_samples[:, previous_measurements:previous_measurements+module.num_measurements]

                # logical measurement
                logical_measurement = module.c_func(module_measurements)
                logical_errors += np.all(logical_measurement != module.c_func_expected_output, axis=1).astype(int)

                previous_measurements += module.num_measurements
                previous_detectors += module.num_detectors

            elif isinstance(module, measurement_module) or isinstance(module, detector_module):
                module_measurements = measurement_samples[:, previous_measurements:previous_measurements+module.num_measurements]
                # Detectors need to be recalculated for each modules because the measurements are being updated
                detector_flips, observable_values = m2d_converter.convert(measurements=measurement_samples, separate_observables=True)
                module_detectors = detector_flips[:, previous_detectors:previous_detectors+module.num_detectors]

                # Apply the c_func
                if isinstance(module, detector_module):
                    corrections = csr_matrix(module.c_func(module_detectors))
                elif isinstance(module, measurement_module):
                    corrections = csr_matrix(module.c_func(module_measurements))
                else:
                    print("Unkown module")
                    raise
                measurement_updates = (corrections @ module.correction_to_measurement_flips) % 2
                measurement_samples = ((measurement_samples + measurement_updates) % 2).astype(bool)

                previous_measurements += module.num_measurements
                previous_detectors += module.num_detectors


        # Once all the corrections have been applied, none of the detectors should be flipped
        # A decoder that doesn't converge might not satisfy this criterion but I still want it flagged here
        detector_flips, observable_values = m2d_converter.convert(measurements=measurement_samples, separate_observables=True)
        assert np.sum(detector_flips) == 0

        # 1 or more logical measurements having the wrong values in a given sample means that that samples had a logical error
        logical_errors[logical_errors > 0] = 1

        return np.sum(logical_errors)
