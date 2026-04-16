import numpy as np
from scipy.sparse import csc_matrix, csr_matrix
from numpy import ndarray
import stim
from hex_qec.modularisation import logical_measurement_module, detector_module, measurement_module, modularised_circuit, css_detector_module, no_measurement_module
from hex_qec.circuit_generation import get_parity_check_matrices, stabilizer_measurement_circuit_both_detectors
from typing import List, Dict, Tuple, Callable, Any
import pymatching
import time
import copy
import logging

# Just get a logger - don't configure it!
logger = logging.getLogger(__name__)

def generate_logical_measurement_module(
        parity_check_tuple,
        physical_error,
        pauli: str,
        new_support: List[int],
        decoder_generator: Callable[[ndarray], Callable[[ndarray], ndarray]],
        expected_logical_values: List[int] = []
):
    (x_pcm, z_pcm, x_logical, z_logical) = parity_check_tuple
    k = x_logical.shape[0]
    num_qubits = x_pcm.shape[1]
    print(f"Code number qubits: {num_qubits}")
    # k logical values should be provided
    if len(expected_logical_values) == 0:
        # Default the expected logical values to zero
        expected_logical_values = np.zeros(k, dtype=int)
    elif len(expected_logical_values) != k:
        print("Size of expected logical values should the same as k for the code")

    if pauli.lower() == "z":
        circuit = stim.Circuit()
        circuit.append("X_ERROR", [str(i) for i in range(num_qubits)], physical_error)
        circuit.append("M", [str(i) for i in range(num_qubits)])
    elif pauli.lower() == "x":
        circuit = stim.Circuit()
        circuit.append("Z_ERROR", [str(i) for i in range(num_qubits)], physical_error)
        circuit.append("MX", [str(i) for i in range(num_qubits)])
    else:
        print("Invalid pauli")
        raise

    if pauli.lower() == "z":
        pcm = z_pcm
        logicals = z_logical
    elif pauli.lower() == "x":
        pcm = x_pcm
        logicals = x_logical

    # Initialise decoder
    decoder = decoder_generator(pcm)
    if hasattr(decoder, "decode_batch") and callable(decoder.decode_batch):
        decode_batch = decoder.decode_batch
    else:
        def batch_decoder(syndrome_batch):
            errors = np.zeros(
                (syndrome_batch.shape[0], pcm.shape[1]), dtype=np.int8
            )
            for i in range(0, syndrome_batch.shape[0]):
                errors[i, :] = decoder.decode(syndrome_batch[i, :])
            return errors
        decode_batch = batch_decoder
    def c_func(measurements):
        syndromes = (measurements @ pcm.T) % 2
        corrections = decode_batch(syndromes.astype(np.uint8))
        corrected_measurements = (measurements + corrections) % 2
        logical_values = (corrected_measurements @ logicals.T) % 2
        return logical_values

    module = logical_measurement_module(
        circuit,
        c_func,
        expected_logical_values,
        new_support = new_support
    )

    return module

# Generate many of the same state preparation procedure, with different support
def generate_state_prep_modules(
        parity_check_tuple : Tuple[ndarray],
        syndrome_measurement_rounds : int,
        pauli : str,
        physical_error,
        supports: List[List[int]],
        decoder_generator: Callable[[ndarray], Callable[[ndarray], ndarray]],
        matchable : bool,
        surface_code : bool = False,
):
    start_circuit_gen = time.time()
    circuit = stabilizer_measurement_circuit_both_detectors(
        parity_check_tuple,
        pauli,
        syndrome_measurement_rounds,
        physical_error,
        surface_code = surface_code,
    )
    logger.info(f"#Circuit Gen Time: {time.time() - start_circuit_gen}")
    num_x_stab = parity_check_tuple[0].shape[0]
    num_z_stab = parity_check_tuple[1].shape[0]

    detector_count = 0
    x_detectors = []
    z_detectors = []
    for syndrome_round in range(syndrome_measurement_rounds):
        # Depending on the state we are preparing, the first detectors will be different because only type of initial stabilizer measurement will be deterministic
        if syndrome_round == 0:
            if pauli.lower() == "x":
                x_detectors.extend(range(detector_count, detector_count + num_x_stab))
                detector_count += num_x_stab
            elif pauli.lower() == "z":
                z_detectors.extend(range(detector_count, detector_count + num_z_stab))
                detector_count += num_z_stab
            else:
                raise
        else:
            x_detectors.extend(range(detector_count, detector_count + num_x_stab))
            detector_count += num_x_stab
            z_detectors.extend(range(detector_count, detector_count + num_z_stab))
            detector_count += num_z_stab

    start_module = time.time()
    template_module = css_detector_module(
        circuit,
        decoder_generator,
        parity_check_tuple,
        x_detectors,
        z_detectors,
        matchable=matchable,
    )
    logger.info(f"#Create Template : {time.time() - start_module}")
    change_module_support = time.time()
    modules = []
    for support in supports:
        new_module = copy.deepcopy(template_module)
        new_module.set_support(support)
        modules.append(new_module)
        logger.info(f"#Change support : {time.time() - change_module_support}")
    logger.info(f"#Module creation : {time.time() - change_module_support}")

    return modules

def generate_state_prep_module_no_noise(
        parity_check_tuple,
        pauli : str,
        new_support : List[int],
):
    syndrome_measurement_rounds = 1
    circuit = stabilizer_measurement_circuit_both_detectors(
        parity_check_tuple,
        pauli,
        syndrome_measurement_rounds,
        0,
    )
    num_qubits = parity_check_tuple[0].shape[1]
    num_x_stab = parity_check_tuple[0].shape[0]
    num_z_stab = parity_check_tuple[1].shape[0]

    def c_func(measurements):
        x_decoder = pymatching.Matching.from_check_matrix(parity_check_tuple[0])
        z_decoder = pymatching.Matching.from_check_matrix(parity_check_tuple[1])
        x_stabilizer_measurements = measurements[:, 0:num_x_stab]
        z_stabilizer_measurements = measurements[:, num_x_stab:num_x_stab+num_z_stab]
        z_pauli_corrections = x_decoder.decode_batch(x_stabilizer_measurements)
        x_pauli_corrections = z_decoder.decode_batch(z_stabilizer_measurements)
        #print(np.hstack([x_pauli_corrections, z_pauli_corrections]).shape)
        return np.hstack([x_pauli_corrections, z_pauli_corrections])

    # Create correction array
    correction_array = []
    for correction_qubit in range(2*num_qubits):
        if correction_qubit < num_qubits:
            correction_array.append((f"X{correction_qubit}", len(circuit)))
        else:
            correction_array.append((f"Z{correction_qubit-num_qubits}", len(circuit)))
    #print(correction_array) 

    module = measurement_module(
        circuit,
        c_func,
        correction_array,
        new_support,
    )

    return module


def generate_transversal_cnot_module(
        physical_error,
        first_block_support,
        second_block_support,
) -> no_measurement_module:
    # The circuit definition doesn't depend on the block support.
    # The circuit is moved to the support when you initialise the module
    transversal_cnot_circuit = stim.Circuit()
    num_qubits_in_code_block = len(first_block_support)
    for q_index in range(num_qubits_in_code_block):
        transversal_cnot_circuit.append("CX", [range(0, num_qubits_in_code_block)[q_index],
                                               range(num_qubits_in_code_block, 2*num_qubits_in_code_block)[q_index]]
                                        )
        transversal_cnot_circuit.append("DEPOLARIZE2", [range(0, num_qubits_in_code_block)[q_index],
                                                        range(num_qubits_in_code_block, 2*num_qubits_in_code_block)[q_index]],
                                        physical_error, 
                                        )
    transversal_cnot_module = no_measurement_module(
        transversal_cnot_circuit,
        first_block_support + second_block_support,
    )

    return transversal_cnot_module

def generate_bell_measurement_and_correction_module(
        parity_check_tuple: Tuple[ndarray],
        physical_error: int,
        data_block_support: List[int],
        first_bell_block_support: List[int],
        second_bell_block_support: List[int],
        decoder_generator: Callable[[ndarray], Callable[[ndarray], ndarray]],
) -> measurement_module:
    (x_pcm, z_pcm, x_logical, z_logical) = parity_check_tuple
    k = x_logical.shape[0]
    num_qubits = x_pcm.shape[1]

    assert len(data_block_support) == num_qubits
    assert len(first_bell_block_support) == num_qubits
    assert len(second_bell_block_support) == num_qubits


    bell_measurement_circuit_error = physical_error
    # Circuit for transversal Bell measurement
    circuit = stim.Circuit()
    circuit.append("I", range(0, 3*num_qubits))
    # Transversal CNOT
    for q_index in range(num_qubits):
        circuit.append("CX", [range(0, num_qubits)[q_index],
                            range(num_qubits, 2*num_qubits)[q_index]]
                    )
        circuit.append("DEPOLARIZE2", [range(0, num_qubits)[q_index],
                                       range(num_qubits, 2*num_qubits)[q_index]],
                       bell_measurement_circuit_error
                    )
    # Measure data block in X basis
    circuit.append("Z_ERROR", range(0, num_qubits), bell_measurement_circuit_error)
    circuit.append("MRX", range(0, num_qubits))
    # Measure data block in Z basis
    circuit.append("X_ERROR", range(num_qubits, 2*num_qubits), bell_measurement_circuit_error)
    circuit.append("MR", range(num_qubits, 2*num_qubits))

    x_decoder = decoder_generator(x_pcm)
    z_decoder = decoder_generator(z_pcm)
    if hasattr(x_decoder, "decode_batch") and callable(x_decoder.decode_batch):
        x_decode_batch = x_decoder.decode_batch
    else:
        def x_batch_decoder(x_syndrome_batch):
            z_errors = np.zeros(
                (x_syndrome_batch.shape[0], x_pcm.shape[1]), dtype=np.int8
            )
            for i in range(0, x_syndrome_batch.shape[0]):
                z_errors[i, :] = x_decoder.decode(x_syndrome_batch[i, :])
            return z_errors
        x_decode_batch = x_batch_decoder

    if hasattr(z_decoder, "decode_batch") and callable(z_decoder.decode_batch):
        z_decode_batch = z_decoder.decode_batch
    else:
        def z_batch_decoder(z_syndrome_batch):
            x_errors = np.zeros(
                (z_syndrome_batch.shape[0], z_pcm.shape[1]), dtype=np.int8
            )
            for i in range(0, z_syndrome_batch.shape[0]):
                x_errors[i, :] = z_decoder.decode(z_syndrome_batch[i, :])
            return x_errors
        z_decode_batch = z_batch_decoder
        
    def c_func(measurements):
        # For the moment I am just going to do CSS decoding
        x_measurements = measurements[:, :num_qubits]
        z_measurements = measurements[:, num_qubits:2*num_qubits]
        x_syndromes = (x_measurements @ x_pcm.T) % 2
        z_syndromes = (z_measurements @ z_pcm.T) % 2
        z_errors = x_decode_batch(x_syndromes)
        x_errors = z_decode_batch(z_syndromes)
        x_measurements = (x_measurements + z_errors) % 2
        z_measurements = (z_measurements + x_errors) % 2
        x_logical_measurements = (x_measurements @ x_logical.T) % 2
        z_logical_measurements = (z_measurements @ z_logical.T) % 2

        corrections = np.hstack([x_logical_measurements, z_logical_measurements])
        return corrections

    # Create correction array
    # These need to be the logical representatives
    correction_array = []
    for z_logical_representative in z_logical.toarray():
        logical_pauli_correction = []
        for qubit_index, qubit_supported in enumerate(z_logical_representative):
            if qubit_supported:
                logical_pauli_correction.append(f"Z{range(2*num_qubits, 3*num_qubits)[qubit_index]}")
        correction_array.append(("*".join(logical_pauli_correction), len(circuit)))

    for x_logical_representative in x_logical.toarray():
        logical_pauli_correction = []
        for qubit_index, qubit_supported in enumerate(x_logical_representative):
            if qubit_supported:
                logical_pauli_correction.append(f"X{range(2*num_qubits, 3*num_qubits)[qubit_index]}")
        correction_array.append(("*".join(logical_pauli_correction), len(circuit)))

    module = measurement_module(
        circuit,
        c_func,
        correction_array,
        data_block_support + first_bell_block_support + second_bell_block_support,
    )
    #print(module.circuit.diagram())

    return module

def generate_steane_correction_module(
        parity_check_tuple: Tuple[ndarray],
        physical_error: int,
        pauli: str,
        ancilla_block_support: List[int],
        data_block_support: List[int],
        decoder_generator: Callable[[ndarray], Callable[[ndarray], ndarray]],
) -> measurement_module:
    (x_pcm, z_pcm, x_logical, z_logical) = parity_check_tuple
    k = x_logical.shape[0]
    num_qubits = x_pcm.shape[1]

    assert len(ancilla_block_support) == num_qubits
    assert len(data_block_support) == num_qubits

    # Generate measurement circuit
    circuit = stim.Circuit()
    circuit.append("I", range(0, 2*num_qubits))
    if pauli.lower() == "z":
        circuit.append("X_ERROR", range(num_qubits, 2*num_qubits), physical_error)
        circuit.append("MR", range(num_qubits, 2*num_qubits))
    elif pauli.lower() == "x":
        circuit.append("Z_ERROR", range(num_qubits, 2*num_qubits), physical_error)
        circuit.append("MRX", range(num_qubits, 2*num_qubits))
    else:
        print("Invalid pauli")
        raise

    def c_func(measurements):
        if pauli.lower() == "z":
            pcm = z_pcm
            logicals = z_logical
        elif pauli.lower() == "x":
            pcm = x_pcm
            logicals = x_logical
        decoder = decoder_generator(pcm)

        syndromes = (measurements @ pcm.T) % 2
        corrections = decoder.decode_batch(syndromes)
        return corrections

    # Create correction array
    correction_array = []
    for correction_qubit in range(0, num_qubits):
        if pauli.lower() == "z":
            correction_array.append((f"X{correction_qubit}", len(circuit)))
        elif pauli.lower() == "x":
            correction_array.append((f"Z{correction_qubit}", len(circuit)))

    module = measurement_module(
        circuit,
        c_func,
        correction_array,
        data_block_support + ancilla_block_support,
    )

    return module
