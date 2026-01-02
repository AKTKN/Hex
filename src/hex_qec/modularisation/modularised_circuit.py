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
            print(f"The output size of c_func doesn't match the size of the expected output")
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
        def circuit_replace_func(matched):
            return circuit_replacements.get(matched.group(0), matched.group(0))
            
        circuit_regex_pattern = '|'.join(rf"{key}\b" for key in circuit_replacements.keys())
        new_circuit_text = re.sub(circuit_regex_pattern, circuit_replace_func, str(self.circuit))

        self.circuit = stim.Circuit(new_circuit_text)

class css_detector_module():
    def __init__(self,
                 circuit: stim.Circuit,
                 decoder_generator:  Callable[[ndarray, List[float]], Callable[[ndarray], ndarray]],
                 x_detectors : List[int],
                 z_detectors : List[int],
                 new_support: List[int],
                 matchable : bool = True,
                 ) -> None:
        self.circuit = circuit
        self.num_measurements = circuit.num_measurements
        self.num_detectors = circuit.num_detectors
        self.matchable = matchable
        self.decoder_generator = decoder_generator
        self.x_detectors = x_detectors
        self.z_detectors = z_detectors

        assert circuit.num_detectors > 0
        assert set(x_detectors).intersection(set(z_detectors)) == set()
        assert set(x_detectors).union(set(z_detectors)) == set(range(self.num_detectors))


        def x_det_filter_function(dem_instruction):
            targets = []
            for target_group in dem_instruction.target_groups():
                targets.extend(target_group)
            targets_int = list(map(lambda target: int(str(target)[1:]), targets))
            return not any([det_index in targets_int for det_index in z_detectors])
        def z_det_filter_function(dem_instruction):
            targets = []
            for target_group in dem_instruction.target_groups():
                targets.extend(target_group)
            targets_int = list(map(lambda target: int(str(target)[1:]), targets))
            return not any([det_index in targets_int for det_index in x_detectors])
        self.x_det_filter_function = x_det_filter_function
        self.z_det_filter_function = z_det_filter_function

        self._change_support(new_support)
        self._generate_dem()
        self._generate_correction_array()
        self._generate_c_func()

    def _generate_dem(self):
        self.dem = self.circuit.detector_error_model()
        self.x_dem = stim.DetectorErrorModel("\n".join(list(map(
            lambda dem_instr: str(dem_instr),
            list(filter(self.x_det_filter_function, self.dem))
        ))))
        self.z_dem = stim.DetectorErrorModel("\n".join(list(map(
            lambda dem_instr: str(dem_instr),
            list(filter(self.z_det_filter_function, self.dem))
        ))))
        self.x_dem_data = detector_error_model_to_check_matrices(self.x_dem, allow_undecomposed_hyperedges=True)
        self.z_dem_data = detector_error_model_to_check_matrices(self.z_dem, allow_undecomposed_hyperedges=True)

        # Conver DEMs to check matrices
        if self.matchable:
            # # X dem
            self.x_dem_check_matrix = self.x_dem_data.edge_check_matrix[self.x_detectors, :]
            self.x_dem_hyperedge_to_edge = self.x_dem_data.hyperedge_to_edge_matrix
            self.x_dem_priors = self.x_dem_hyperedge_to_edge @ self.x_dem_data.priors
            self.x_weights = (np.log1p(self.x_dem_priors) - np.log(self.x_dem_priors))
            # Z dem
            self.z_dem_check_matrix = self.z_dem_data.edge_check_matrix[self.z_detectors, :]
            self.z_dem_hyperedge_to_edge = self.z_dem_data.hyperedge_to_edge_matrix
            self.z_dem_priors = self.z_dem_hyperedge_to_edge @ self.z_dem_data.priors
            self.z_weights = (np.log1p(self.z_dem_priors) - np.log(self.z_dem_priors))
        else:
            # # X dem
            self.x_dem_check_matrix = self.x_dem_data.check_matrix
            self.x_dem_priors = self.x_dem_data.priors
            self.x_weights = self.x_dem_priors
            # Z dem
            self.z_dem_check_matrix = self.z_dem_data.check_matrix
            self.z_dem_priors = self.z_dem_data.priors
            self.z_weights = self.z_dem_priors

    def _generate_c_func(self) -> None:
        self.x_decoder = self.decoder_generator(self.x_dem_check_matrix)
        self.z_decoder = self.decoder_generator(self.z_dem_check_matrix)
        def c_func(detector_flips: ndarray
                   ) -> ndarray:
            x_detector_flips = detector_flips[:, self.x_detectors]
            z_detector_flips = detector_flips[:, self.z_detectors]
            corrections_for_x_detectors = self.x_decoder.decode_batch(x_detector_flips)
            corrections_for_z_detectors = self.z_decoder.decode_batch(z_detector_flips)
            combined_corrections = np.hstack([corrections_for_x_detectors, corrections_for_z_detectors])
            return combined_corrections

        self.c_func = c_func

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
        self.x_correction_array = []
        self.z_correction_array = []
        for pauli_dem in [self.x_dem, self.z_dem]:
            circuit_explain_errors = self.circuit.explain_detector_error_model_errors(
                dem_filter = pauli_dem,
                reduce_to_one_representative_error=True,
            )
            for explained_error in circuit_explain_errors:
                # Get location of fault
                error_location = explained_error.circuit_error_locations[0]
                stack_frame = error_location.stack_frames[0]
                instruction_offset = stack_frame.instruction_offset
                # Get Pauli of fault
                pauli_fault = self._get_pauli_product_from_error_location(error_location, self.circuit.num_qubits)
                if pauli_dem == self.x_dem:
                    self.x_correction_array.append((pauli_fault, instruction_offset))
                else:
                    self.z_correction_array.append((pauli_fault, instruction_offset))

    def _change_support(self,
                       new_support: List[int],
                       ) -> None:
        # Update the circuit
        if len(new_support) == 0:
            new_support = list(range(self.circuit.num_qubits))
        elif len(new_support) != self.circuit.num_qubits:
            print("Module support not the correct size")
            raise
        circuit_replacements = {f" {original}" : f" {new}" for original, new in enumerate(new_support)}
        def circuit_replace_func(matched):
            return circuit_replacements.get(matched.group(0), matched.group(0))
            
        circuit_regex_pattern = '|'.join(rf"{key}\b" for key in circuit_replacements.keys())
        new_circuit_text = re.sub(circuit_regex_pattern, circuit_replace_func, str(self.circuit))

        self.circuit = stim.Circuit(new_circuit_text)

        # # Update the Pauli corrections
        # new_corrections = []
        # pauli_replacements = {f'{original}' : f'{new}' for original, new in enumerate(new_support)}
        # def pauli_replace_func(matched):
        #     pauli = matched.group(0)[0]
        #     qubit = matched.group(0)[1:]
        #     return f"{pauli}{pauli_replacements.get(qubit, qubit)}"
        # pauli_regex_pattern = '|'.join(rf"\w{key}$" for key in pauli_replacements.keys())
        # for correction in self.correction_array:
        #     new_corrections.append((re.sub(pauli_regex_pattern, pauli_replace_func, correction[0]), correction[1]))
        # self.correction_array = new_corrections

    def generate_measurement_flip_map(self,
                                      circuit_before_module: stim.Circuit,
                                      circuit_after_module: stim.Circuit,
                                      previous_detectors: int,
                                      ) -> None:
        flip_sim = stim.FlipSimulator(batch_size=1, disable_stabilizer_randomization=True)
        for pauli in ["x", "z"]:
            detector_flips = []
            measurement_flips = []
            if pauli == "x":
                correction_array = self.x_correction_array
            else:
                correction_array = self.z_correction_array
            for pauli_correction, location in correction_array:
                # Construct circuit with the pauli correction inserted
                circuit_before_correction = self.circuit[:location].without_noise()
                circuit_after_correction = self.circuit[location+1:].without_noise()
                flip_circuit = circuit_before_module + circuit_before_correction + convert_pauli_to_error(stim.PauliString(pauli_correction)) + circuit_after_correction + circuit_after_module
                # Use the flip simulator to find what measurements and detectors are flipped by this correction
                flip_sim.do(flip_circuit)
                measurements_flipped = flip_sim.get_measurement_flips().T
                detectors_flipped = flip_sim.get_detector_flips().T
                detector_flips.append(detectors_flipped)
                measurement_flips.append(measurements_flipped)
                flip_sim.clear()

            if pauli == "x":
                self.x_correction_to_detector_flips = np.vstack(detector_flips)
                self.x_correction_to_measurement_flips = np.vstack(measurement_flips)
                # For matchable dem we need to conver this into one where the faults are edges
                if self.matchable:
                    self.x_correction_to_detector_flips = (self.x_dem_hyperedge_to_edge @ self.x_correction_to_detector_flips) % 2
                    self.x_correction_to_measurement_flips = (self.x_dem_hyperedge_to_edge @ self.x_correction_to_measurement_flips) % 2

                # self.dem_check_matrix is the check matrix for the dem in that specific module
                # module.correction_to_detector_flips is how the corrections affect all the detectors in the circuit, even the ones outside this module
                # To compare them I need to splce module.correction_to_detectors_flips to only include the detectors for this specific module
                assert (self.x_dem_check_matrix.T == self.x_correction_to_detector_flips[:, [det + previous_detectors for det in self.x_detectors]]).all()
            else:
                self.z_correction_to_detector_flips = np.vstack(detector_flips)
                self.z_correction_to_measurement_flips = np.vstack(measurement_flips)
                # For matchable dem we need to conver this into one where the faults are edges
                if self.matchable:
                    self.z_correction_to_detector_flips = (self.z_dem_hyperedge_to_edge @ self.z_correction_to_detector_flips) % 2
                    self.z_correction_to_measurement_flips = (self.z_dem_hyperedge_to_edge @ self.z_correction_to_measurement_flips) % 2
                 
                # self.dem_check_matrix is the check matrix for the dem in that specific module
                # module.correction_to_detector_flips is how the corrections affect all the detectors in the circuit, even the ones outside this module
                # To compare them I need to splce module.correction_to_detectors_flips to only include the detectors for this specific module
                assert (self.z_dem_check_matrix.T == self.z_correction_to_detector_flips[:, [det + previous_detectors for det in self.z_detectors]]).all()

        self.correction_to_measurement_flips = np.vstack([self.x_correction_to_measurement_flips, self.z_correction_to_measurement_flips])


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

    def generate_measurement_flip_map(self,
                                      circuit_before_module: stim.Circuit,
                                      circuit_after_module: stim.Circuit,
                                      previous_detectors: int,
                                      ) -> None:
        flip_sim = stim.FlipSimulator(batch_size=1, disable_stabilizer_randomization=True)
        detector_flips = []
        measurement_flips = []
        for pauli_correction, location in self.correction_array:
            # Construct circuit with the pauli correction inserted
            circuit_before_correction = self.circuit[:location].without_noise()
            circuit_after_correction = self.circuit[location+1:].without_noise()
            flip_circuit = circuit_before_module + circuit_before_correction + convert_pauli_to_error(stim.PauliString(pauli_correction)) + circuit_after_correction + circuit_after_module
            # Use the flip simulator to find what measurements and detectors are flipped by this correction
            flip_sim.do(flip_circuit)
            measurements_flipped = flip_sim.get_measurement_flips().T
            detectors_flipped = flip_sim.get_detector_flips().T
            detector_flips.append(detectors_flipped)
            measurement_flips.append(measurements_flipped)
            flip_sim.clear()
            #print(flip_circuit.diagram())
        self.correction_to_detector_flips = np.vstack(detector_flips)
        self.correction_to_measurement_flips = np.vstack(measurement_flips)
        # For matchable dem we need to conver this into one where the faults are edges
        if self.matchable:
            self.correction_to_detector_flips = (self.dem_hyperedge_to_edge @ self.correction_to_detector_flips) % 2
            self.correction_to_measurement_flips = (self.dem_hyperedge_to_edge @ self.correction_to_measurement_flips) % 2

        # self.dem_check_matrix is the check matrix for the dem in that specific module
        # module.correction_to_detector_flips is how the corrections affect all the detectors in the circuit, even the ones outside this module
        # To compare them I need to splce module.correction_to_detectors_flips to only include the detectors for this specific module
        assert (self.dem_check_matrix.toarray().T == self.correction_to_detector_flips[:, previous_detectors:previous_detectors+self.num_detectors].astype(np.int8)
                ).all()

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

    def generate_measurement_flip_map(self,
                                      circuit_before_module: stim.Circuit,
                                      circuit_after_module: stim.Circuit
                                      ) -> None:
        flip_sim = stim.FlipSimulator(batch_size=1, disable_stabilizer_randomization=True)
        detector_flips = []
        measurement_flips = []
        for pauli_correction, location in self.correction_array:
            # Construct circuit with the pauli correction inserted
            circuit_before_correction = self.circuit[:location].without_noise()
            circuit_after_correction = self.circuit[location+1:].without_noise()
            flip_circuit = circuit_before_module + circuit_before_correction + convert_pauli_to_error(stim.PauliString(pauli_correction)) + circuit_after_correction + circuit_after_module
            # Use the flip simulator to find what measurements and detectors are flipped by this correction
            flip_sim.do(flip_circuit)
            measurements_flipped = flip_sim.get_measurement_flips().T
            detectors_flipped = flip_sim.get_detector_flips().T
            detector_flips.append(detectors_flipped)
            measurement_flips.append(measurements_flipped)
            flip_sim.clear()
            #print(flip_circuit.diagram())
        self.correction_to_detector_flips = np.vstack(detector_flips)
        self.correction_to_measurement_flips = np.vstack(measurement_flips)

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
        previous_measurements = 0
        previous_detectors = 0
        # Generate measurement split
        self.measurements_by_module = []
        for module_number, module in enumerate(self.circuit_modules):
            circuit_before_module = stim.Circuit()
            for module_before in self.circuit_modules[:module_number]:
                circuit_before_module += module_before.circuit.without_noise()
            circuit_after_module = stim.Circuit()
            for module_after in self.circuit_modules[module_number+1:]:
                circuit_after_module += module_after.circuit.without_noise()

            if isinstance(module, measurement_module):
                module.generate_measurement_flip_map(circuit_before_module, circuit_after_module)
            elif isinstance(module, detector_module) or isinstance(module, css_detector_module):
                module.generate_measurement_flip_map(circuit_before_module, circuit_after_module, previous_detectors)

            previous_measurements += module.num_measurements
            previous_detectors += module.num_detectors
            self.measurements_by_module.append(previous_measurements)

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

            elif isinstance(module, measurement_module) or isinstance(module, detector_module) or isinstance(module, css_detector_module):
                module_measurements = measurement_samples[:, previous_measurements:previous_measurements+module.num_measurements]
                # Detectors need to be recalculated for each modules because the measurements are being updated
                detector_flips, observable_values = m2d_converter.convert(measurements=measurement_samples, separate_observables=True)
                module_detectors = detector_flips[:, previous_detectors:previous_detectors+module.num_detectors]

                # Apply the c_func
                if isinstance(module, detector_module) or isinstance(module, css_detector_module):
                    corrections = csr_matrix(module.c_func(module_detectors))
                elif isinstance(module, measurement_module):
                    corrections = csr_matrix(module.c_func(module_measurements))
                else:
                    print("Unkown module")
                    raise
                #print(self.measurements_by_module)
                #print_array_with_partitions(module.correction_to_measurement_flips.astype(int), self.measurements_by_module)
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

def print_array_with_partitions(arr, partition_cols):
    """
    Print array with visual partitions between specified column ranges.

    Args:
        arr: 2D array/list
        partition_cols: List of column indices where partitions should be placed
                        e.g., [2, 4] puts partitions after columns 2 and 4
    """
    for row in arr:
        segments = []
        prev = 0

        for col in sorted(set(partition_cols)):
            segments.append(row[prev:col])
            prev = col

        segments.append(row[prev:])

        print(' | '.join(' '.join(str(x) for x in seg) for seg in segments))
