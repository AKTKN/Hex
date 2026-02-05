import numpy as np
from scipy.sparse import csc_matrix, csr_matrix
from numpy import ndarray
import stim
from hex_qec.modularisation import logical_measurement_module, detector_module, measurement_module, modularised_circuit, css_detector_module
from hex_qec.circuit_generation import get_parity_check_matrices, stabilizer_measurement_circuit_both_detectors
from typing import List, Dict, Tuple, Callable, Any
import pymatching

def generate_logical_measurement_module(
        physical_error: int,
        code: str,
        distance: int,
        pauli: str,
        new_support: List[int],
        decoder_generator: Callable[[ndarray], Callable[[ndarray], ndarray]],
        expected_logical_values: List[int] = []
):
    (x_pcm, z_pcm, x_logical, z_logical) = get_parity_check_matrices(code, distance=distance)
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
    if callable(hasattr(decoder, "decode_batch")):
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

def generate_state_prep_module(
        code : str,
        distance : int,
        pauli : str,
        physical_error,
        new_support : List[int],
        decoder_generator: Callable[[ndarray], Callable[[ndarray], ndarray]],
        matchable : bool,
):
    parity_check_tuple = get_parity_check_matrices(code, distance)
    syndrome_measurement_rounds = distance
    circuit = stabilizer_measurement_circuit_both_detectors(
        parity_check_tuple,
        pauli,
        syndrome_measurement_rounds,
        physical_error,
    )
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

    module = css_detector_module(
        circuit,
        decoder_generator,
        parity_check_tuple,
        x_detectors,
        z_detectors,
        new_support,
        matchable,
    )

    return module

def generate_state_prep_module_no_noise(
        code : str,
        distance : int,
        pauli : str,
        new_support : List[int],
):
    parity_check_tuple = get_parity_check_matrices(code, distance)
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
