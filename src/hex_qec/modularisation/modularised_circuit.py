import sys
import copy
import stim
from stimbposd import detector_error_model_to_check_matrices
import numpy as np
np.set_printoptions(linewidth=200)
from numpy import ndarray
import shutil
np.set_printoptions(linewidth=shutil.get_terminal_size().columns)
import scipy
from scipy.sparse import csc_matrix, csr_matrix
from typing import List, Dict, Tuple, Callable, Any
from pprint import pprint
import re
import time
from collections import defaultdict
import json
import logging
from hex_qec.decoders import (
    CSSInnerDecodeResults,
    DecodeResult,
    LegacyDecoderAdapter,
    LegacyDecoderGeneratorAdapter,
)
from .results import (
    SimulationDetailLevel,
    SimulationResult,
    normalize_module_decode_output,
    validate_simulation_detail_level,
    ModuleDecodeResult,
)
# Just get a logger - don't configure it!
logger = logging.getLogger(__name__)


# Helper funtion for multiplying sparse binary matrices
def gf2_matmul_csc(A: csc_matrix, B: csc_matrix) -> csc_matrix:
    # Ensure CSC
    A = A.tocsc()
    B = B.tocsc()

    # Multiply in integer arithmetic (counts overlaps)
    C = (A @ B).tocsc()

    # Reduce counts mod 2
    C.data = (C.data & 1).astype(np.int8)   # bitwise mod 2, faster than % 2

    # Drop zeros created by mod
    C.eliminate_zeros()

    # Ensure stored values are 1s (already true after &1)
    return C

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
                 parity_check_tuple : Tuple[ndarray],
                 x_detectors : List[int],
                 z_detectors : List[int],
                 new_support : List[int] = [],
                 matchable : bool = True,
                 confidence_aggregator: Callable[[CSSInnerDecodeResults], ndarray | None] | None = None,
                 ) -> None:
        self.circuit = circuit
        self.num_measurements = circuit.num_measurements
        self.num_detectors = circuit.num_detectors
        self.matchable = matchable
        self.decoder_generator = decoder_generator
        self.parity_check_tuple = parity_check_tuple
        self.x_detectors = x_detectors
        self.z_detectors = z_detectors
        self.confidence_aggregator = confidence_aggregator

        self.x_pcm = self.parity_check_tuple[0]
        self.z_pcm = self.parity_check_tuple[1]
        self.num_x_stabilizers = self.x_pcm.shape[0]
        self.num_z_stabilizers = self.z_pcm.shape[0]
        self.num_data_qubits = self.x_pcm.shape[1]

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

        self._generate_dem()
        self._generate_c_func()

        if len(new_support) > 0:
            self.set_support(new_support)

    def __deepcopy__(self, memo):
        """Copy circuit metadata without copying third-party decoder handles.

        PyMatching and some LDPC decoders own non-pickleable native objects.
        Decoder instances are immutable in their construction parameters and
        are only used synchronously by the module callbacks, so sharing the
        adapted handles preserves the historical template-copy behavior.
        """
        clone = object.__new__(type(self))
        memo[id(self)] = clone
        shared = {
            "x_dem_decoder",
            "z_dem_decoder",
            "x_decoder",
            "z_decoder",
            "x_dem_decode_batch",
            "z_dem_decode_batch",
            "x_decode_batch",
            "z_decode_batch",
            "c_func",
            "c_func_rich",
            "_legacy_c_func",
        }
        for name, value in self.__dict__.items():
            if name in shared:
                setattr(clone, name, value)
            else:
                setattr(clone, name, copy.deepcopy(value, memo))
        return clone

    def _generate_dem(self):
        # Build seperate circuits with the x and z detectors
        count_det = 0
        self.x_det_circuit = stim.Circuit()
        self.z_det_circuit = stim.Circuit()
        for instruction in self.circuit:
            if instruction.name == "DETECTOR":
                if count_det in self.x_detectors:
                    self.x_det_circuit.append(instruction)
                elif count_det in self.z_detectors:
                    self.z_det_circuit.append(instruction)
                else:
                    raise
                count_det += 1
            else:
                self.x_det_circuit.append(instruction)
                self.z_det_circuit.append(instruction)

        # self.dem = self.circuit.detector_error_model()
        # self.x_dem = stim.DetectorErrorModel("\n".join(list(map(
        #     lambda dem_instr: str(dem_instr),
        #     list(filter(self.x_det_filter_function, self.dem))
        # ))))
        # self.z_dem = stim.DetectorErrorModel("\n".join(list(map(
        #     lambda dem_instr: str(dem_instr),
        #     list(filter(self.z_det_filter_function, self.dem))
        # ))))
        self.x_dem = self.x_det_circuit.detector_error_model()
        self.z_dem = self.z_det_circuit.detector_error_model()
        self.x_dem_data = detector_error_model_to_check_matrices(self.x_dem, allow_undecomposed_hyperedges=True)
        self.z_dem_data = detector_error_model_to_check_matrices(self.z_dem, allow_undecomposed_hyperedges=True)

        # Convert DEMs to check matrices
        if self.matchable:
            # # X dem
            self.x_dem_check_matrix = self.x_dem_data.edge_check_matrix
            self.x_dem_hyperedge_to_edge = self.x_dem_data.hyperedge_to_edge_matrix
            self.x_dem_priors = self.x_dem_hyperedge_to_edge @ self.x_dem_data.priors
            self.x_weights = (np.log1p(self.x_dem_priors) - np.log(self.x_dem_priors))
            # Z dem
            self.z_dem_check_matrix = self.z_dem_data.edge_check_matrix
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
        legacy_factory = LegacyDecoderGeneratorAdapter(
            self.decoder_generator,
            # These casts are part of the historical css_detector_module
            # behavior and are retained for numerical compatibility.
            cast_batch_to_uint8=True,
            cast_scalar_to_uint8=True,
        )

        self.x_dem_decoder = legacy_factory.create(
            self.x_dem_check_matrix, weights=self.x_weights
        )
        self.z_dem_decoder = legacy_factory.create(
            self.z_dem_check_matrix, weights=self.z_weights
        )
        # These decoders are used move the state back into the all zero syndromes code space.
        # Using a decoder for this may be overkill and just performing the destabilizer corrections may be sufficient.
        # Additionally if the decoder you are using doesn't always perform the destabilizer correction
        # (e.g. in the case of belief propagation not converging) then this will likely be problematic
        self.x_decoder = legacy_factory.create(self.x_pcm)
        self.z_decoder = legacy_factory.create(self.z_pcm)

        def get_batch_decode(decoder: LegacyDecoderAdapter):
            # Keep this private callable's legacy ndarray return type.  The
            # richer DecodeResult is available at the adapter boundary.
            return lambda syndromes: decoder.decode_batch(syndromes).correction

        self.x_dem_decode_batch = get_batch_decode(self.x_dem_decoder)
        self.z_dem_decode_batch = get_batch_decode(self.z_dem_decoder)
        self.x_decode_batch = get_batch_decode(self.x_decoder)
        self.z_decode_batch = get_batch_decode(self.z_decoder)


        # Generate correction arrays using the template circuit, as the eventual support with not affect the c_func
        x_correction_array = []
        z_correction_array = []
        for pauli_dem, circuit in [(self.x_dem, self.x_det_circuit), (self.z_dem, self.z_det_circuit)]:
            circuit_explain_errors = circuit.explain_detector_error_model_errors(
                dem_filter = pauli_dem,
                reduce_to_one_representative_error=True,
            )
            for explained_error in circuit_explain_errors:
                # Get location of fault
                error_location = explained_error.circuit_error_locations[0]
                stack_frame = error_location.stack_frames[0]
                instruction_offset = stack_frame.instruction_offset
                # Get Pauli of fault
                pauli_fault = self._get_pauli_product_from_error_location(error_location, circuit.num_qubits)
                if pauli_dem == self.x_dem:
                    x_correction_array.append((pauli_fault, instruction_offset))
                else:
                    z_correction_array.append((pauli_fault, instruction_offset))


        # Calculate correction maps for just the measurements in this module
        flip_sim = stim.FlipSimulator(batch_size=1, disable_stabilizer_randomization=True)
        #####################
        # X dem corrections #
        #####################
        detector_flips = []
        measurement_flips = []
        correction_array = x_correction_array
        circuit = self.x_det_circuit


        # New way to generate the measurement flips more efficiently
        new_flip_start = time.time()
        num_faults = len(correction_array)
        logger.info(f"##Number of faults for X detectors: {num_faults}")
        corrections_at_location = defaultdict(list)
        for index, correction in enumerate(correction_array):
            corrections_at_location[correction[1]].append((index, correction[0]))
            assert "*" not in correction[0] # for the moment assume the fault are only weight 1 paulis
        flip_sim_all_faults = stim.FlipSimulator(batch_size=num_faults, disable_stabilizer_randomization=True)
        for instruction_location, instruction in enumerate(circuit):
            gate_data = stim.gate_data(instruction.name)
            if not (gate_data.is_noisy_gate and not gate_data.produces_measurements):
                flip_sim_all_faults.do(instruction)
            for index, correction in corrections_at_location[instruction_location]:
                # print(f"Instruction location: {instruction_location}")
                # print(f"Index: {index}")
                pauli = correction[0]
                qubit = int(correction[1:])
                # print(f"Pauli: {pauli}, Qubit: {qubit}")
                flip_sim_all_faults.set_pauli_flip(
                    pauli,
                    qubit_index=qubit,
                    instance_index=index
                )
        self.x_dem_correction_to_local_detector_flips = csc_matrix(flip_sim_all_faults.get_detector_flips().T)
        self.x_dem_correction_to_local_measurement_flips = csc_matrix(flip_sim_all_faults.get_measurement_flips().T)
        new_flip_end = time.time()
        logger.info(f"##New flips method: {new_flip_end - new_flip_start}")

        # For matchable dem we need to conver this into one where the faults are edges
        if self.matchable:
            self.x_dem_correction_to_local_detector_flips = gf2_matmul_csc(self.x_dem_hyperedge_to_edge, self.x_dem_correction_to_local_detector_flips)
            self.x_dem_correction_to_local_measurement_flips = gf2_matmul_csc(self.x_dem_hyperedge_to_edge, self.x_dem_correction_to_local_measurement_flips)

        #####################
        # Z dem corrections #
        #####################
        detector_flips = []
        measurement_flips = []
        correction_array = z_correction_array
        circuit = self.z_det_circuit

        # New way to generate the measurement flips more efficiently
        new_flip_start = time.time()
        num_faults = len(correction_array)
        logger.info(f"##Number of faults for Z detectors: {num_faults}")
        corrections_at_location = defaultdict(list)
        for index, correction in enumerate(correction_array):
            corrections_at_location[correction[1]].append((index, correction[0]))
            assert "*" not in correction[0] # for the moment assume the fault are only weight 1 paulis
        flip_sim_all_faults = stim.FlipSimulator(batch_size=num_faults, disable_stabilizer_randomization=True)
        for instruction_location, instruction in enumerate(circuit):
            gate_data = stim.gate_data(instruction.name)
            if not (gate_data.is_noisy_gate and not gate_data.produces_measurements):
                flip_sim_all_faults.do(instruction)
            for index, correction in corrections_at_location[instruction_location]:
                # logger.info(f"Instruction location: {instruction_location}")
                # logger.info(f"Index: {index}")
                pauli = correction[0]
                qubit = int(correction[1:])
                # logger.info(f"Pauli: {pauli}, Qubit: {qubit}")
                flip_sim_all_faults.set_pauli_flip(
                    pauli,
                    qubit_index=qubit,
                    instance_index=index
                )
        self.z_dem_correction_to_local_detector_flips = csc_matrix(flip_sim_all_faults.get_detector_flips().T)
        self.z_dem_correction_to_local_measurement_flips = csc_matrix(flip_sim_all_faults.get_measurement_flips().T)
        new_flip_end = time.time()
        logger.info(f"##New flips method: {new_flip_end - new_flip_start}")

        logger.info(f"##z_dem_correction_to_local_detector_flips : {self.z_dem_correction_to_local_detector_flips.shape}")
        logger.info(f"##z_dem_correction_to_local_measurement_flips : {self.z_dem_correction_to_local_measurement_flips.shape}")
        logger.info(f"##z_dem_correction_to_local_detector_flips : {sys.getsizeof(self.z_dem_correction_to_local_detector_flips)}")
        logger.info(f"##z_dem_correction_to_local_measurement_flips : {sys.getsizeof(self.z_dem_correction_to_local_measurement_flips)}")

        # self.z_dem_correction_to_local_detector_flips = np.vstack(detector_flips)
        # self.z_dem_correction_to_local_measurement_flips = np.vstack(measurement_flips)
        # For matchable dem we need to conver this into one where the faults are edges
        if self.matchable:
            self.z_dem_correction_to_local_detector_flips = gf2_matmul_csc(self.z_dem_hyperedge_to_edge, self.z_dem_correction_to_local_detector_flips)
            self.z_dem_correction_to_local_measurement_flips = gf2_matmul_csc(self.z_dem_hyperedge_to_edge, self.z_dem_correction_to_local_measurement_flips)

        def decode_impl(measurement_samples: ndarray) -> tuple[ndarray, CSSInnerDecodeResults]:

            x_m2d_converter = self.x_det_circuit.compile_m2d_converter()
            x_detector_flips, x_observable_values = x_m2d_converter.convert(measurements=measurement_samples, separate_observables=True)
            z_m2d_converter = self.z_det_circuit.compile_m2d_converter()
            z_detector_flips, z_observable_values = z_m2d_converter.convert(measurements=measurement_samples, separate_observables=True)


            # x_detector_flips = detector_flips[:, self.x_detectors]
            # z_detector_flips = detector_flips[:, self.z_detectors]
            x_dem_result = self.x_dem_decoder.decode_batch(x_detector_flips)
            z_dem_result = self.z_dem_decoder.decode_batch(z_detector_flips)
            corrections_for_x_detectors = x_dem_result.correction
            corrections_for_z_detectors = z_dem_result.correction

            # Need to update the measurements using the detector corrections, before correcting the stabilizers
            measurements_corrections_from_x_detectors = (csr_matrix(corrections_for_x_detectors) @ self.x_dem_correction_to_local_measurement_flips).toarray() % 2
            measurements_corrections_from_z_detectors = (csr_matrix(corrections_for_z_detectors) @ self.z_dem_correction_to_local_measurement_flips).toarray() % 2
            measurement_samples = (measurement_samples + measurements_corrections_from_x_detectors) % 2
            measurement_samples = (measurement_samples + measurements_corrections_from_z_detectors) % 2

            # Assume the circuit is alternating X and Z stabilizer measurements
            last_x_stabilizer_measurements = measurement_samples[:, -(self.num_x_stabilizers + self.num_z_stabilizers):-self.num_z_stabilizers]
            last_z_stabilizer_measurements = measurement_samples[:, -self.num_z_stabilizers:]
            x_result = self.x_decoder.decode_batch(last_x_stabilizer_measurements)
            z_result = self.z_decoder.decode_batch(last_z_stabilizer_measurements)
            correction_for_x_stabilizers = x_result.correction
            correction_for_z_stabilizers = z_result.correction
            # logger.info_array_with_partitions(measurement_samples.astype(int), [0, 4, 8, 12, 16, 20])
            # logger.info(last_x_stabilizer_measurements.astype(int))
            # logger.info(correction_for_x_stabilizers)
            # logger.info(last_z_stabilizer_measurements.astype(int))
            # logger.info(correction_for_z_stabilizers)

            combined_corrections = np.hstack([
                corrections_for_x_detectors,
                corrections_for_z_detectors,
                correction_for_x_stabilizers,
                correction_for_z_stabilizers,
            ])
            # Named so a confidence_aggregator can select DEM-only or
            # code-capacity-only results explicitly rather than relying on
            # positional order (see CSSInnerDecodeResults docstring).
            return combined_corrections, CSSInnerDecodeResults(
                x_dem=x_dem_result,
                z_dem=z_dem_result,
                x_capacity=x_result,
                z_capacity=z_result,
            )

        def c_func(measurement_samples: ndarray) -> ndarray:
            return decode_impl(measurement_samples)[0]

        def c_func_rich(measurement_samples: ndarray) -> ModuleDecodeResult:
            combined_corrections, decoder_results = decode_impl(measurement_samples)
            metrics: dict[str, ndarray] = {}
            for prefix, result in zip(
                ("x_dem", "z_dem", "x_capacity", "z_capacity"),
                decoder_results,
            ):
                for name, value in result.metrics.items():
                    metrics[f"{prefix}.{name}"] = np.asarray(value)

            confidence = None
            if self.confidence_aggregator is not None:
                confidence = self.confidence_aggregator(decoder_results)
                if confidence is not None:
                    confidence = np.asarray(confidence)

            combined_result = DecodeResult(
                correction=combined_corrections,
                confidence=confidence,
                metrics=metrics,
            )
            return ModuleDecodeResult(
                corrections=combined_corrections,
                decode_result=combined_result,
                metrics=metrics,
            )

        self.c_func = c_func
        self._legacy_c_func = c_func
        self.c_func_rich = c_func_rich

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
        start_time = time.time()
        self.x_correction_array = []
        self.z_correction_array = []
        for pauli_dem, circuit in [(self.x_dem, self.x_det_circuit), (self.z_dem, self.z_det_circuit)]:
            circuit_explain_errors = circuit.explain_detector_error_model_errors(
                dem_filter = pauli_dem,
                reduce_to_one_representative_error=True,
            )
            for explained_error in circuit_explain_errors:
                # Get location of fault
                error_location = explained_error.circuit_error_locations[0]
                stack_frame = error_location.stack_frames[0]
                instruction_offset = stack_frame.instruction_offset
                # Get Pauli of fault
                pauli_fault = self._get_pauli_product_from_error_location(error_location, circuit.num_qubits)
                if pauli_dem == self.x_dem:
                    self.x_correction_array.append((pauli_fault, instruction_offset))
                else:
                    self.z_correction_array.append((pauli_fault, instruction_offset))
        logger.info(f"##Correction array : {time.time() - start_time}")

    def set_support(self,
                       new_support: List[int],
                       ) -> None:
        # Update the circuit
        if len(new_support) == 0:
            new_support = list(range(self.circuit.num_qubits))
        elif len(new_support) != self.circuit.num_qubits:
            logger.info("Module support not the correct size")
            raise
        circuit_replacements = {f" {original}" : f" {new}" for original, new in enumerate(new_support)}
        def circuit_replace_func(matched):
            return circuit_replacements.get(matched.group(0), matched.group(0))
            
        circuit_regex_pattern = '|'.join(rf"{key}\b" for key in circuit_replacements.keys())
        new_circuit_text = re.sub(circuit_regex_pattern, circuit_replace_func, str(self.circuit))
        new_x_det_circuit_text = re.sub(circuit_regex_pattern, circuit_replace_func, str(self.x_det_circuit))
        new_z_det_circuit_text = re.sub(circuit_regex_pattern, circuit_replace_func, str(self.z_det_circuit))

        self.circuit = stim.Circuit(new_circuit_text)
        self.x_det_circuit = stim.Circuit(new_x_det_circuit_text)
        self.z_det_circuit = stim.Circuit(new_z_det_circuit_text)

        self.new_support = new_support

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

        self._generate_correction_array()

    def generate_measurement_flip_map(self,
                                      circuit_before_module: stim.Circuit,
                                      circuit_after_module: stim.Circuit,
                                      previous_detectors: int,
                                      ) -> None:
        flip_sim = stim.FlipSimulator(batch_size=1, disable_stabilizer_randomization=True)

        #####################
        # X dem corrections #
        #####################
        correction_array = self.x_correction_array
        circuit = self.x_det_circuit

        # New way to generate the measurement flips more efficiently
        num_faults = len(correction_array)
        logger.info(f"Number of faults: {num_faults}")
        corrections_at_location = defaultdict(list)
        for index, correction in enumerate(correction_array):
            corrections_at_location[correction[1]].append((index, correction[0]))
            assert "*" not in correction[0] # for the moment assume the fault are only weight 1 paulis
        flip_sim_all_faults = stim.FlipSimulator(batch_size=num_faults, disable_stabilizer_randomization=True)
        flip_sim_all_faults.do(circuit_before_module)
        for instruction_location, instruction in enumerate(circuit):
            gate_data = stim.gate_data(instruction.name)
            if not (gate_data.is_noisy_gate and not gate_data.produces_measurements):
                flip_sim_all_faults.do(instruction)
            for index, correction in corrections_at_location[instruction_location]:
                # logger.info(f"Instruction location: {instruction_location}")
                # logger.info(f"Index: {index}")
                pauli = correction[0]
                qubit = int(correction[1:])
                # logger.info(f"Pauli: {pauli}, Qubit: {qubit}")
                flip_sim_all_faults.set_pauli_flip(
                    pauli,
                    qubit_index=qubit,
                    instance_index=index
                )
        flip_sim_all_faults.do(circuit_after_module)
        self.x_dem_correction_to_detector_flips = csc_matrix(flip_sim_all_faults.get_detector_flips().T)
        self.x_dem_correction_to_measurement_flips = csc_matrix(flip_sim_all_faults.get_measurement_flips().T)

        # For matchable dem we need to conver this into one where the faults are edges
        if self.matchable:
            self.x_dem_correction_to_detector_flips = gf2_matmul_csc(self.x_dem_hyperedge_to_edge, self.x_dem_correction_to_detector_flips)
            self.x_dem_correction_to_measurement_flips = gf2_matmul_csc(self.x_dem_hyperedge_to_edge, self.x_dem_correction_to_measurement_flips)

        # self.dem_check_matrix is the check matrix for the dem in that specific module
        # module.dem_correction_to_detector_flips is how the dem_corrections affect all the detectors in the circuit, even the ones outside this module
        # To compare them I need to splce module.dem_correction_to_detectors_flips to only include the detectors for this specific module
        # assert (self.x_dem_check_matrix.T == self.x_dem_correction_to_detector_flips[:, previous_detectors:previous_detectors+len(self.x_detectors)]).all()
        assert (csc_matrix(self.x_dem_check_matrix.T) != self.x_dem_correction_to_detector_flips[:, previous_detectors:previous_detectors+len(self.x_detectors)]).nnz == 0

        ############################
        # X stabilizer corrections #
        ############################
        detector_flips = []
        measurement_flips = []
        # Generate correction map for the Z stabilizer measurements at the end of the circuit
        for qubit in self.new_support[:self.num_data_qubits]: # The circuit, before change of support, is assumed to have the first set of qubits be the data qubits
            flip_circuit = circuit_before_module + self.circuit.without_noise() + convert_pauli_to_error(stim.PauliString(f"Z{qubit}")) + circuit_after_module
            flip_sim.do(flip_circuit)
            measurements_flipped = flip_sim.get_measurement_flips().T
            detectors_flipped = flip_sim.get_detector_flips().T
            detector_flips.append(detectors_flipped)
            measurement_flips.append(measurements_flipped)
            flip_sim.clear()

        self.x_stabalizer_correction_to_detector_flips = csc_matrix(np.vstack(detector_flips))
        self.x_stabilizer_correction_to_measurement_flips = csc_matrix(np.vstack(measurement_flips))

        #####################
        # Z dem corrections #
        #####################
        correction_array = self.z_correction_array
        circuit = self.z_det_circuit

        # New way to generate the measurement flips more efficiently
        num_faults = len(correction_array)
        logger.info(f"Number of faults: {num_faults}")
        corrections_at_location = defaultdict(list)
        for index, correction in enumerate(correction_array):
            corrections_at_location[correction[1]].append((index, correction[0]))
            assert "*" not in correction[0] # for the moment assume the fault are only weight 1 paulis
        flip_sim_all_faults = stim.FlipSimulator(batch_size=num_faults, disable_stabilizer_randomization=True)
        flip_sim_all_faults.do(circuit_before_module)
        for instruction_location, instruction in enumerate(circuit):
            gate_data = stim.gate_data(instruction.name)
            if not (gate_data.is_noisy_gate and not gate_data.produces_measurements):
                flip_sim_all_faults.do(instruction)
            for index, correction in corrections_at_location[instruction_location]:
                # logger.info(f"Instruction location: {instruction_location}")
                # logger.info(f"Index: {index}")
                pauli = correction[0]
                qubit = int(correction[1:])
                # logger.info(f"Pauli: {pauli}, Qubit: {qubit}")
                flip_sim_all_faults.set_pauli_flip(
                    pauli,
                    qubit_index=qubit,
                    instance_index=index
                )
        flip_sim_all_faults.do(circuit_after_module)
        self.z_dem_correction_to_detector_flips = csc_matrix(flip_sim_all_faults.get_detector_flips().T)
        self.z_dem_correction_to_measurement_flips = csc_matrix(flip_sim_all_faults.get_measurement_flips().T)

        # For matchable dem we need to conver this into one where the faults are edges
        if self.matchable:
            self.z_dem_correction_to_detector_flips = gf2_matmul_csc(self.z_dem_hyperedge_to_edge, self.z_dem_correction_to_detector_flips)
            self.z_dem_correction_to_measurement_flips = gf2_matmul_csc(self.z_dem_hyperedge_to_edge, self.z_dem_correction_to_measurement_flips)

        # self.dem_check_matrix is the check matrix for the dem in that specific module
        # module.dem_correction_to_detector_flips is how the dem_corrections affect all the detectors in the circuit, even the ones outside this module
        # To compare them I need to splce module.dem_correction_to_detectors_flips to only include the detectors for this specific module
        assert (csc_matrix(self.z_dem_check_matrix.T) != self.z_dem_correction_to_detector_flips[:, previous_detectors:previous_detectors+len(self.z_detectors)]).nnz == 0

        ############################
        # Z stabilizer corrections #
        ############################
        detector_flips = []
        measurement_flips = []
        # Generate correction map for the Z stabilizer measurements at the end of the circuit
        for qubit in self.new_support[:self.num_data_qubits]: # The circuit, before change of support, is assumed to have the first set of qubits be the data qubits
            flip_circuit = circuit_before_module + self.circuit.without_noise() + convert_pauli_to_error(stim.PauliString(f"X{qubit}")) + circuit_after_module
            flip_sim.do(flip_circuit)
            measurements_flipped = flip_sim.get_measurement_flips().T
            detectors_flipped = flip_sim.get_detector_flips().T
            detector_flips.append(detectors_flipped)
            measurement_flips.append(measurements_flipped)
            flip_sim.clear()

        self.z_stabilizer_correction_to_detector_flips = csc_matrix(np.vstack(detector_flips))
        self.z_stabilizer_correction_to_measurement_flips = csc_matrix(np.vstack(measurement_flips))

        stacked_matrices = scipy.sparse.vstack([self.x_dem_correction_to_measurement_flips,
                                                self.z_dem_correction_to_measurement_flips,
                                                self.x_stabilizer_correction_to_measurement_flips,
                                                self.z_stabilizer_correction_to_measurement_flips,
                                                ])
        self.correction_to_measurement_flips = stacked_matrices

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
        def c_func(x):
            decoder = LegacyDecoderGeneratorAdapter(
                self.c_func_generator
            ).create(self.dem_check_matrix, weights=weights)
            return decoder.decode_batch(x).correction

        self.c_func = c_func

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
            c_func_output = normalize_module_decode_output(c_func(test_c_func_input))
            assert c_func_output.corrections.shape == (test_batch_size, len(correction_array))
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
        pauli_replacements = {str(i): str(new) for i, new in enumerate(new_support)}
        # Match one factor like "Z20" that is followed by "*" or end-of-string
        pauli_pat = re.compile(r'([IXYZ])(\d+)(?=\*|$)')

        def pauli_replace_func(m):
            pauli = m.group(1)   # 'X', 'Y', 'Z', 'I'
            qubit = m.group(2)   # digits only, e.g. '20'
            return pauli + pauli_replacements.get(qubit, qubit)

        for correction in self.correction_array:
            s = correction[0]
            new_s = pauli_pat.sub(pauli_replace_func, s)
            new_corrections.append((new_s, correction[1]))

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
        self.correction_to_measurement_flips = csc_matrix(np.vstack(measurement_flips))


class only_postselection_module():
    # c_func should work on a batch of inputs
    def __init__(self,
                 circuit: stim.Circuit,
                 c_func: Callable[[ndarray], ndarray],
                 new_support: List[int] = None
                 ) -> None:
        self.circuit = circuit
        self.num_measurements = circuit.num_measurements
        self.num_detectors = circuit.num_detectors
        self.c_func = c_func
        self.support_set = False
        # Check that the input and output dimensions of c_func work

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
        pauli_replacements = {str(i): str(new) for i, new in enumerate(new_support)}
        # Match one factor like "Z20" that is followed by "*" or end-of-string
        pauli_pat = re.compile(r'([IXYZ])(\d+)(?=\*|$)')

        def pauli_replace_func(m):
            pauli = m.group(1)   # 'X', 'Y', 'Z', 'I'
            qubit = m.group(2)   # digits only, e.g. '20'
            return pauli + pauli_replacements.get(qubit, qubit)

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
                 max_shots: int,
                 max_errors_before_halting: int,
                 results_path: str = "",
                 seed: int | None = None,
                 ) -> int:

        m2d_converter = self.circuit.compile_m2d_converter()
        measurement_sampler = self.circuit.compile_sampler(seed=seed)

        # Perform the sampling in batches
        total_logical_errors = 0
        total_logical_errors_postselected = 0
        samples_performed = 0
        samples_performed_postselected = 0
        SHOTS_PER_BATCH = 256
        batch_number = 0
        while (total_logical_errors_postselected < max_errors_before_halting) and (SHOTS_PER_BATCH*batch_number < max_shots):
            logger.info(f"Batch number: {batch_number}")
            # Sample
            measurement_samples = measurement_sampler.sample(shots=SHOTS_PER_BATCH)

            # Iterate over the modules and perform their corrections
            previous_measurements = 0
            previous_detectors = 0
            logical_errors = np.zeros((SHOTS_PER_BATCH), dtype=int)
            shots_postselected = np.zeros((SHOTS_PER_BATCH), dtype=int)
            for module in self.circuit_modules:
                if isinstance(module, logical_measurement_module):
                    module_measurements = measurement_samples[:, previous_measurements:previous_measurements+module.num_measurements]

                    # logical measurement
                    logical_measurement = module.c_func(module_measurements)
                    logical_errors += np.sum(logical_measurement != module.c_func_expected_output, axis=1)

                    previous_measurements += module.num_measurements
                    previous_detectors += module.num_detectors

                elif isinstance(module, measurement_module) or isinstance(module, detector_module) or isinstance(module, css_detector_module):
                    module_measurements = measurement_samples[:, previous_measurements:previous_measurements+module.num_measurements]
                    # Detectors need to be recalculated for each modules because the measurements are being updated
                    detector_flips, observable_values = m2d_converter.convert(measurements=measurement_samples, separate_observables=True)
                    module_detectors = detector_flips[:, previous_detectors:previous_detectors+module.num_detectors]

                    # Apply the c_func
                    if isinstance(module, detector_module):
                        c_func_output = module.c_func(module_detectors)
                        module_decode_result = normalize_module_decode_output(c_func_output)
                    elif isinstance(module, measurement_module) or isinstance(module, css_detector_module):
                        c_func_output = module.c_func(module_measurements)
                        module_decode_result = normalize_module_decode_output(c_func_output)
                    else:
                        logger.info("Unkown module")
                        raise
                    corrections = csc_matrix(module_decode_result.corrections)
                    module_postselection = module_decode_result.postselection
                    if module_postselection is None:
                        module_postselection = np.zeros((SHOTS_PER_BATCH), dtype=int)
                    #logger.info(self.measurements_by_module)
                    #logger.info_array_with_partitions(module.correction_to_measurement_flips.astype(int), self.measurements_by_module)
                    # The correction map is stored as a sparse matrix but you need to turn it back to an array to perform the mod 2 addition
                    measurement_updates = (corrections @ module.correction_to_measurement_flips).toarray() % 2
                    measurement_samples = ((measurement_samples + measurement_updates) % 2).astype(bool)

                    previous_measurements += module.num_measurements
                    previous_detectors += module.num_detectors

                    shots_postselected = (shots_postselected + module_postselection) % 2
                elif isinstance(module, only_postselection_module):
                    module_measurements = measurement_samples[:, previous_measurements:previous_measurements+module.num_measurements]

                    c_func_output = module.c_func(module_measurements)
                    module_postselection = c_func_output

                    previous_measurements += module.num_measurements
                    previous_detectors += module.num_detectors

                    shots_postselected = (shots_postselected + module_postselection) % 2
            # Once all the corrections have been applied, none of the detectors should be flipped
            # A decoder that doesn't converge might not satisfy this criterion but I still want it flagged here
            detector_flips, observable_values = m2d_converter.convert(measurements=measurement_samples, separate_observables=True)
            assert np.sum(detector_flips) == 0

            # 1 or more logical measurements having the wrong values in a given sample means that that samples had a logical error
            logical_errors[logical_errors > 0] = 1
            total_logical_errors += np.sum(logical_errors, dtype=int)
            # print(((1 - shots_postselected) * logical_errors))
            total_logical_errors_postselected += np.sum(((1 - shots_postselected) * logical_errors), dtype=int)

            samples_performed += SHOTS_PER_BATCH
            samples_performed_postselected += np.sum((1 - shots_postselected), dtype=int)

            batch_number += 1

            logger.info(f"Logical errors: {np.sum(logical_errors, dtype=int)}")

            if len(results_path) > 0:
                logical_error_rate = total_logical_errors / samples_performed
                results = {
                    "samples_performed" : int(samples_performed), 
                    "logical_errors" : int(total_logical_errors),
                    "logical_error_rate" : logical_error_rate,
                    "logical_errors_postselected" : int(total_logical_errors_postselected),
                    "samples_performed_postselected" : int(samples_performed_postselected), 
                }
                logger.info("Saving results.json")
                with open(results_path, "w") as f:
                    json.dump(results, f, indent=2)
                    

        return samples_performed, total_logical_errors

    def simulate_result(
        self,
        max_shots: int,
        max_errors_before_halting: int,
        results_path: str = "",
        detail_level: SimulationDetailLevel = "summary",
        seed: int | None = None,
    ) -> SimulationResult:
        """Run the existing static simulation and wrap its aggregate result.

        This method deliberately delegates to :meth:`simulate`, preserving
        its sampler, batch size, stopping condition, correction propagation,
        and legacy JSON output.  No adaptive branching or per-shot capture is
        performed here.
        """

        detail_level = validate_simulation_detail_level(detail_level)
        start_time = time.perf_counter()
        samples_performed, logical_errors = self.simulate(
            max_shots=max_shots,
            max_errors_before_halting=max_errors_before_halting,
            results_path=results_path,
            seed=seed,
        )
        runtime_seconds = time.perf_counter() - start_time

        return SimulationResult.from_legacy(
            samples_performed,
            logical_errors,
            runtime_seconds=runtime_seconds,
            detail_level=detail_level,
            metadata={
                "execution_backend": "static_compiled",
                "adaptive": False,
                "num_modules": len(self.circuit_modules),
                "num_measurements": self.circuit.num_measurements,
                "num_detectors": self.circuit.num_detectors,
            },
        )

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
