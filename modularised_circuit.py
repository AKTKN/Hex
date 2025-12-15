import stim
import pymatching
from stimbposd import detector_error_model_to_check_matrices
import numpy as np
from numpy import ndarray
import shutil
np.set_printoptions(linewidth=shutil.get_terminal_size().columns)
import scipy
from scipy.sparse import csc_matrix, csr_matrix
from scipy.io import mmread, mmwrite
from typing import List, Dict, Tuple, Callable, Any
from pprint import pprint
import re
import pandas as pd
from plotting_lib import generate_threshold_plot
import glob

############################################
# ######################################## #
# # Generate syndrome extraction circuit # #
# ######################################## #
############################################

####################
# Helper functions #
####################

def get_parity_check_matrices(code, distance):
    parity_check_directory = f"parity_check_matrices/{code}"
    x_pcm_filename     = glob.glob(f"{parity_check_directory}/{code}_*_{distance}_hx.mtx")[0]
    z_pcm_filename     = glob.glob(f"{parity_check_directory}/{code}_*_{distance}_hz.mtx")[0]
    x_logical_filename = glob.glob(f"{parity_check_directory}/{code}_*_{distance}_lx.mtx")[0]
    z_logical_filename = glob.glob(f"{parity_check_directory}/{code}_*_{distance}_lz.mtx")[0]
    x_pcm = mmread(x_pcm_filename)
    z_pcm = mmread(z_pcm_filename)
    x_logical = mmread(x_logical_filename)
    z_logical = mmread(z_logical_filename)

    parity_check_tuple = (x_pcm, z_pcm, x_logical, z_logical)
    return parity_check_tuple

def generate_blocks(number_of_blocks, block_template):
    size_of_block = len(block_template["data_qubits"] + block_template["x_ancillas"] + block_template["z_ancillas"])
    blocks = []
    for block_number in range(number_of_blocks):
        new_block = {}
        new_block["data_qubits"] = block_template["data_qubits"].copy()
        new_block["x_ancillas"] = block_template["x_ancillas"].copy()
        new_block["z_ancillas"] = block_template["z_ancillas"].copy()
        for qubit_type in ["data_qubits", "x_ancillas", "z_ancillas"]:
            for index, q in enumerate(new_block[qubit_type]):
                new_block[qubit_type][index] = q + (block_number * size_of_block)
        blocks.append(new_block)

    return blocks

# This currently is for CSS codes where there are seperate X and Z pcms
def sparse_binary_array_to_paulistrings(sparse_binary_array, pauli):
    n = sparse_binary_array.shape[1]
    paulistrings = []
    for row_index in range(sparse_binary_array.shape[0]):
        paulistring = stim.PauliString("I") * n
        for i in sparse_binary_array.getrow(row_index).indices:
            paulistring[i] = pauli
        paulistrings.append(paulistring)
    return paulistrings

def create_stabilizers_and_block_template(x_pcm, z_pcm, x_logical_binary, z_logical_binary):
    assert x_pcm.shape[1] == z_pcm.shape[1]
    n = x_pcm.shape[1]
    # There may be redundant stabilizers, Rank(x_pcm) != x_pcm.shape[0], but this is fine
    # x_stab_num = np.linalg.matrix_rank(x_pcm.toarray())
    # z_stab_num = np.linalg.matrix_rank(z_pcm.toarray())

    x_stab_num = x_pcm.shape[0]
    z_stab_num = z_pcm.shape[0]

    # Iterate through the rows of the parity check matrices
    x_stabilizers_redundant = sparse_binary_array_to_paulistrings(x_pcm, "X")
    logical_X = sparse_binary_array_to_paulistrings(x_logical_binary, "X")
    z_stabilizers_redundant = sparse_binary_array_to_paulistrings(z_pcm, "Z")
    logical_Z = sparse_binary_array_to_paulistrings(z_logical_binary, "Z")

    tab_Z = stim.Tableau.from_stabilizers(x_stabilizers_redundant + z_stabilizers_redundant + logical_Z, allow_redundant=True)

    # Template circuit for generating logical 0
    logical_0_prep_template = tab_Z.to_circuit()
    # Template circuit for generating logical +
    tab_X = stim.Tableau.from_stabilizers(x_stabilizers_redundant + z_stabilizers_redundant + logical_X, allow_redundant=True)
    logical_plus_prep_template = tab_X.to_circuit()

    # block template
    data_qubits = list(range(0, n))
    x_ancilla_qubits = list(range(n, n + x_stab_num))
    z_ancilla_qubits = list(range(n + x_stab_num, n + x_stab_num + z_stab_num))
    block_template = {"data_qubits": data_qubits, "x_ancillas": x_ancilla_qubits, "z_ancillas": z_ancilla_qubits}
    assert(len(block_template["x_ancillas"]) == x_stab_num)
    assert(len(block_template["z_ancillas"]) == z_stab_num)

    stabilizer_tuple = (x_stabilizers_redundant, z_stabilizers_redundant, logical_X, logical_Z)

    return block_template, stabilizer_tuple, logical_0_prep_template, logical_plus_prep_template

def qubit_initialisation(circuit, pauli, block, prob):
    state_prep_error = prob
    data_qubits = block["data_qubits"]
    # Prepare all physical qubits in the |0> state
    if pauli.lower() == "z":
        circuit.append("R", block["data_qubits"])
        circuit.append("X_ERROR", block["data_qubits"], state_prep_error)
    # Prepare all physical qubits in the |+> state
    elif pauli.lower() == "x":
        circuit.append("RX", block["data_qubits"])
        circuit.append("Z_ERROR", block["data_qubits"], state_prep_error)

def qubit_measurement(circuit, pauli, block, prob):
    measurement_error = prob
    data_qubits = block["data_qubits"]
    # Prepare all physical qubits in the |0> state
    if pauli.lower() == "z":
        circuit.append("X_ERROR", block["data_qubits"], measurement_error)
        circuit.append("M", block["data_qubits"])
    # Prepare all physical qubits in the |+> state
    elif pauli.lower() == "x":
        circuit.append("Z_ERROR", block["data_qubits"], measurement_error)
        circuit.append("MX", block["data_qubits"])

def measure_X_stabilizers(circuit, x_stabilizers, block, prob):
    two_qubit_error = prob
    ancilla_error = prob
    data_qubits = block["data_qubits"]
    x_ancilla_qubits = block["x_ancillas"]
    # Prepare the ancillas
    circuit.append("R", x_ancilla_qubits)  # |+> State prep
    circuit.append("H", x_ancilla_qubits)
    circuit.append("Z_ERROR", x_ancilla_qubits, ancilla_error)  # State preparation error
    # Iterate over stabilizers and measure them using the corresponding ancilla

    for ancilla_index, ancilla in enumerate(x_ancilla_qubits):
        stabilizer = x_stabilizers[ancilla_index]
        stabilizer_qubit_locations = []
        for q_ind, q_loc in enumerate(data_qubits):
            if stabilizer[q_ind] == 1:
                stabilizer_qubit_locations.append(q_loc)
                circuit.append("CX", [ancilla, q_loc])
                circuit.append("DEPOLARIZE2", [ancilla, q_loc], two_qubit_error)

    circuit.append("Z_ERROR", x_ancilla_qubits, ancilla_error)  # Measurement error
    circuit.append("H", x_ancilla_qubits)  # X measurement
    circuit.append("M", x_ancilla_qubits)

def measure_Z_stabilizers(circuit, z_stabilizers, block, prob):
    two_qubit_error = prob
    ancilla_error = prob
    data_qubits = block["data_qubits"]
    z_ancilla_qubits = block["z_ancillas"]
    # Prepare the ancillas
    circuit.append("R", z_ancilla_qubits)  # |+> State prep
    circuit.append("H", z_ancilla_qubits)
    circuit.append("Z_ERROR", z_ancilla_qubits, ancilla_error)  # State preparation error
    # Iterate over stabilizers and measure them using the corresponding ancilla

    for ancilla_index, ancilla in enumerate(z_ancilla_qubits):
        stabilizer = z_stabilizers[ancilla_index]
        stabilizer_qubit_locations = []
        for q_ind, q_loc in enumerate(data_qubits):
            if stabilizer[q_ind] == 3:
                stabilizer_qubit_locations.append(q_loc)
                circuit.append("CZ", [ancilla, q_loc])
                circuit.append("DEPOLARIZE2", [ancilla, q_loc], two_qubit_error)

    circuit.append("Z_ERROR", z_ancilla_qubits, ancilla_error)  # Measurement error
    circuit.append("H", z_ancilla_qubits)  # Z measurement
    circuit.append("M", z_ancilla_qubits)

def transversal_cnot(circuit, first_block, second_block, prob):
    first_block_data_qubits = first_block["data_qubits"]
    second_block_data_qubits = second_block["data_qubits"]
    # Make sure the number of physical qubits is the same for both logical qubits
    assert len(first_block_data_qubits) == len(second_block_data_qubits)
    # Apply transversal cnot gate
    for q_index in range(len(first_block_data_qubits)):
        circuit.append("CX", [first_block_data_qubits[q_index], second_block_data_qubits[q_index]])
    circuit.append("DEPOLARIZE2", [item for pair in zip(first_block_data_qubits, second_block_data_qubits) for item in pair], prob)

def ideal_preparation_circuit(circuit, block, template):
    data_qubits = block["data_qubits"]
    qubit_relabelling = {}
    for q_ind, q_loc in enumerate(data_qubits):
        qubit_relabelling[str(q_ind)] = str(q_loc)

    def replace_numbers(match):
        num = match.group()
        return qubit_relabelling.get(num, num)

    prep_circ_str = ""
    inside_bracket = False
    current_num = ""
    for char in str(template) + "\n":
        if char == "[":
            inside_bracket = True
            prep_circ_str += char
        elif char == "]":
            inside_bracket = False
            prep_circ_str += char
        else:
            # Only deal with integers outside of brackets
            if inside_bracket is False and char in ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9"]:
                # build new number
                current_num += char
            elif inside_bracket is False and len(current_num) > 0:
                # swap number and add to string
                prep_circ_str += qubit_relabelling[current_num]
                prep_circ_str += char
                current_num = ""
            else:
                prep_circ_str += char

    circuit.append_from_stim_program_text(prep_circ_str)

#####################
# Cicuit generation #
#####################

def generate_basis_state_circuit(
        parity_check_tuple,
        # stabilizer_tuple,
        # block_template,
        pauli,
        syndrome_repetitions,
        prob,
        disable_final_detectors=True,
        debug=False
):
    block_template, stabilizer_tuple, logical_0_prep_template, logical_plus_prep_template = create_stabilizers_and_block_template(*parity_check_tuple)
    x_stabilizers, z_stabilizers, x_logicals, z_logicals = stabilizer_tuple
    blocks = generate_blocks(1, block_template)
    block = blocks[0]
    circ = stim.Circuit()


    n = len(block["data_qubits"])
    num_z_stabilizers = len(block["z_ancillas"])
    num_x_stabilizers = len(block["x_ancillas"])
        

    # Apply a Hadamard to all gates if you want to prepare in the X-basis
    #circ.append("H", block["data_qubits"])

    # Noisey physical qubit state preparation
    qubit_initialisation(circ, pauli, block, prob)

    # First found of stabilizer measurement
    measure_X_stabilizers(circ, x_stabilizers, block, prob)
    measure_Z_stabilizers(circ, z_stabilizers, block, prob)

    # Initial detectors
    if pauli.lower() == "x":
        for stab_num in range(num_x_stabilizers):
            #print(-num_stabilizers + stab_num)
            circ.append("DETECTOR", [stim.target_rec(-(num_z_stabilizers + num_x_stabilizers) + stab_num)])
    elif pauli.lower() == "z":
        for stab_num in range(num_z_stabilizers):
            #print(-num_stabilizers + stab_num)
            circ.append("DETECTOR", [stim.target_rec(-num_z_stabilizers + stab_num)])

    for syndrome_repetition in range(2, syndrome_repetitions+1):
        measure_X_stabilizers(circ, x_stabilizers, block, prob)
        measure_Z_stabilizers(circ, z_stabilizers, block, prob)
        # Add detectors
        if pauli.lower() == "x":
            for stab_num in range(num_x_stabilizers):
                circ.append("DETECTOR", [stim.target_rec(-2*(num_z_stabilizers + num_x_stabilizers) + stab_num), stim.target_rec(-(num_z_stabilizers + num_x_stabilizers) + stab_num)])
        elif pauli.lower() == "z":
            for stab_num in range(num_z_stabilizers):
                circ.append("DETECTOR", [stim.target_rec(-(2*num_z_stabilizers + num_x_stabilizers) + stab_num), stim.target_rec(-num_z_stabilizers + stab_num)])


    # Noisy physical qubit measurement
    qubit_measurement(circ, pauli, block, prob)

    if not disable_final_detectors:
        # Form detectors between directly measured qubits and the previous stabilizer measurements
        for stab_num in range(num_stabilizers):
            circ.append("DETECTOR", [stim.target_rec(-n - num_stabilizers + stab_num)] + [stim.target_rec(-n + i) for i in z_pcm.col[z_pcm.row == stab_num]])

        circ.append("OBSERVABLE_INCLUDE", [stim.target_rec(-n + i) for i in z_logical_binary.nonzero()[1]], 0)

    debug and print(f"Number of detectors: {circ.num_detectors} = {circ.num_detectors / num_stabilizers} * {num_stabilizers}(number of stabilizers)")

    return circ

def generate_bell_state_circuit(
        parity_check_tuple,
        # stabilizer_tuple,
        # block_template,
        pauli,
        syndrome_repetitions,
        prob,
        disable_final_detectors=True,
        debug=False
):
    block_template, stabilizer_tuple, logical_0_prep_template, logical_plus_prep_template = create_stabilizers_and_block_template(*parity_check_tuple)
    x_stabilizers, z_stabilizers, x_logicals, z_logicals = stabilizer_tuple
    blocks = generate_blocks(2, block_template)
    block_0 = blocks[0]
    block_1 = blocks[1]
    circ = stim.Circuit()


    n = len(block_template["data_qubits"])
    num_z_stabilizers = len(block_template["z_ancillas"])
    num_x_stabilizers = len(block_template["x_ancillas"])

    ####################################
    # Prepare block 0 in the |+> state #
    ####################################

    ideal_preparation_circuit(circ, block_0, logical_plus_prep_template)

    # # Noisey physical qubit state preparation
    # qubit_initialisation(circ, "X", block_0, prob)
    # # Measure the Z stabilzers
    # measure_Z_stabilizers(circ, z_stabilizers, block_0, 0.0)

    # # There are no initial detectors because the physical qubit stabilizers are different to the first rounds of stabilizer measurement
    
    # # Perform multiple rounds of syndrome measurement
    # for syndrome_repetition in range(2, syndrome_repetitions+1):
    #     measure_Z_stabilizers(circ, z_stabilizers, block_0, 0.0)
    #     for stab_num in range(num_z_stabilizers):
    #         circ.append("DETECTOR", [stim.target_rec(-2*num_z_stabilizers + stab_num), stim.target_rec(-num_z_stabilizers + stab_num)])


    ####################################
    # Prepare block 1 in the |0> state #
    ####################################


    #ideal_preparation_circuit(circ, block_1, logical_plus_prep_template)

    # Noisey physical qubit state preparation
    qubit_initialisation(circ, "Z", block_1, 0.0)
    # Measure the X stabilzers
    measure_X_stabilizers(circ, x_stabilizers, block_1, 0.0)

    # There are no initial detectors because the physical qubit stabilizers are different to the first rounds of stabilizer measurement
    
    # Perform multiple rounds of syndrome measurement
    for syndrome_repetition in range(2, syndrome_repetitions+1):
        measure_X_stabilizers(circ, x_stabilizers, block_1, 0.0)
        for stab_num in range(num_x_stabilizers):
            circ.append("DETECTOR", [stim.target_rec(-2*num_x_stabilizers + stab_num), stim.target_rec(-num_x_stabilizers + stab_num)])

    ############################################################
    # Perform a transversal CNOT creating a logical bell state #
    ############################################################

    transversal_cnot(circ, block_0, block_1, 0.0)

    ###########################################################
    # Measure all the data qubits in the provided pauli basis #
    ###########################################################

    # Noisy physical qubit measurement
    qubit_measurement(circ, pauli, block_0, 0.0)
    qubit_measurement(circ, pauli, block_1, 0.0)

    # if not disable_final_detectors:
    #     # Form detectors between directly measured qubits and the previous stabilizer measurements
    #     for stab_num in range(num_stabilizers):
    #         circ.append("DETECTOR", [stim.target_rec(-n - num_stabilizers + stab_num)] + [stim.target_rec(-n + i) for i in z_pcm.col[z_pcm.row == stab_num]])

    #     circ.append("OBSERVABLE_INCLUDE", [stim.target_rec(-n + i) for i in z_logical_binary.nonzero()[1]], 0)

    debug and print(f"Number of detectors: {circ.num_detectors} = {circ.num_detectors / num_stabilizers} * {num_stabilizers}(number of stabilizers)")

    return circ


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

            #if isinstance(module, measurement_module):
            else:
                module_measurements = measurement_samples[:, previous_measurements:previous_measurements+module.num_measurements]
                # Detectors need to be recalculated for each modules because the measurements are being updated
                detector_flips, observable_values = m2d_converter.convert(measurements=measurement_samples, separate_observables=True)
                module_detectors = detector_flips[:, previous_detectors:previous_detectors+module.num_detectors]
                print(module_detectors)

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
        print(detector_flips)
        assert np.sum(detector_flips) == 0

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

def get_circuit_with_dem_error():
    def generate_test_dem_circuit(
            distance : int = 3,
            syndrome_repetitions : int = 1
    ):
        code = "surface"
        pauli = "Z"
        prob = 0.05

        parity_check_tuple = get_parity_check_matrices(code, distance=distance)
        block_template, stabilizer_tuple, logical_0_prep_template, logical_plus_prep_template = create_stabilizers_and_block_template(*parity_check_tuple)
        x_stabilizers, z_stabilizers, x_logicals, z_logicals = stabilizer_tuple
        blocks = generate_blocks(1, block_template)
        block = blocks[0]
        circ = stim.Circuit()

        n = len(block["data_qubits"])
        num_z_stabilizers = len(block["z_ancillas"])
        num_x_stabilizers = len(block["x_ancillas"])

        # Noisey physical qubit state preparation
        qubit_initialisation(circ, pauli, block, prob)

        # First found of stabilizer measurement
        measure_X_stabilizers(circ, x_stabilizers, block, prob)
        measure_Z_stabilizers(circ, z_stabilizers, block, prob)

        # Initial detectors
        if pauli.lower() == "x":
            for stab_num in range(num_x_stabilizers):
                #print(-num_stabilizers + stab_num)
                circ.append("DETECTOR", [stim.target_rec(-(num_z_stabilizers + num_x_stabilizers) + stab_num)])
        elif pauli.lower() == "z":
            for stab_num in range(num_z_stabilizers):
                #print(-num_stabilizers + stab_num)
                circ.append("DETECTOR", [stim.target_rec(-num_z_stabilizers + stab_num)])

        for syndrome_repetition in range(2, syndrome_repetitions+1):
            measure_X_stabilizers(circ, x_stabilizers, block, prob)
            measure_Z_stabilizers(circ, z_stabilizers, block, prob)
            # Add detectors
            if pauli.lower() == "x":
                for stab_num in range(num_x_stabilizers):
                    circ.append("DETECTOR", [stim.target_rec(-2*(num_z_stabilizers + num_x_stabilizers) + stab_num), stim.target_rec(-(num_z_stabilizers + num_x_stabilizers) + stab_num)])
            elif pauli.lower() == "z":
                for stab_num in range(num_z_stabilizers):
                    circ.append("DETECTOR", [stim.target_rec(-(2*num_z_stabilizers + num_x_stabilizers) + stab_num), stim.target_rec(-num_z_stabilizers + stab_num)])


        # Noisy physical qubit measurement
        qubit_measurement(circ, pauli, block, prob)

        return circ

    module_list = [
        detector_module(generate_test_dem_circuit(),
                        pymatching.Matching.from_check_matrix,
                        [],
                        # range(3, circuit.num_qubits+3),
                        matchable = True
                        ),
        detector_module(generate_test_dem_circuit(distance = 5, syndrome_repetitions=2),
                        pymatching.Matching.from_check_matrix,
                        [],
                        #range(30, circuit.num_qubits+30),
                        matchable = True
                        ),
    ]
    mod_circ = modularised_circuit(module_list)
    mod_circ.generate_correction_to_measurement_flip_map()
    #print(mod_circ.circuit.diagram())
    
    num_shots = 10
    logical_errors = mod_circ.simulate(num_shots)
    print(logical_errors)

    # fake_det_data = np.random.randint(2, size=(num_shots, det_mod.num_detectors))
    # corrections = det_mod.c_func(fake_det_data)
    # correction_to_detector_flips = mod_circ.circuit_modules[0].correction_to_detector_flips
    # correction_to_measurement_flips = mod_circ.circuit_modules[0].correction_to_measurement_flips
    # print("Fake det data")
    # print(fake_det_data)
    # print("Fault corrections")
    # print(corrections)
    # print("Measurement flips")
    # print((corrections @ mod_circ.circuit_modules[0].correction_to_measurement_flips) % 2)

    # print(mod_circ.circuit_modules[0].correction_to_detector_flips)
    # print(mod_circ.circuit_modules[0].correction_to_measurement_flips)

# [('Z13', 34),
#  ('X4', 12),
#  ('X9', 8),
#  ('X5', 16),
#  ('Z14', 44),
#  ('X3', 10),
#  ('X10', 16),
#  ('Z15', 52),
#  ('Z16', 56)]

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
    test = 2
    if test == 1:
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
    elif test == 2:
     get_circuit_with_dem_error()   
