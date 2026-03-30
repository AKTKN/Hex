import stim
import pymatching
from ldpc import BpDecoder, BpOsdDecoder
import numpy as np
from numpy import ndarray

from hex_qec.circuit_generation import get_parity_check_matrices
from hex_qec.protocols import knill_online_offline

def knill_error_correction(
        code,
        distance,
        online_decoder,
        offline_decoder,
        physical_error_rate,
        max_shots,
        max_errors_before_halting,
        pauli,
        num_teleportations,
):
    # Define decoders
    BPOSD_args = {
        "max_iter": 100,
        "bp_method": "ms",
        "osd_method": "osd_0",
        "ms_scaling_factor": 0.75,
        "schedule": "serial"
    }
    def generate_bposd_decoder(pcm, weights=[]):
        if len(weights) > 0:
            return BpOsdDecoder(
                pcm,
                error_channel=list(weights),
                **BPOSD_args
            )
        else:
            return BpOsdDecoder(
                pcm,
                error_rate=physical_error_rate,
                **BPOSD_args
            )
    BP_args = {
        "max_iter" : 100,
        "bp_method" : "ms",
        "ms_scaling_factor" : 0.75,
        "schedule" : "serial"
    }
    def generate_bp_decoder(pcm, weights=[]):
        if len(weights) > 0:
            return BpDecoder(
                pcm,
                error_channel=list(weights),
                **BP_args
            )
        else:
            return BpDecoder(
                pcm,
                error_rate=physical_error_rate,
                **BP_args
            )
    decoder_generators = {
        "pymatching": pymatching.Matching.from_check_matrix,
        "bp": generate_bp_decoder,
        "bposd": generate_bposd_decoder,
    }

    parity_check_tuple = get_parity_check_matrices(code, distance)
    online_decoder_generator = decoder_generators[online_decoder]
    offline_decoder_generator = decoder_generators[offline_decoder]
    syndrome_measurement_rounds = distance

    samples_performed, logical_errors = knill_online_offline(
            parity_check_tuple,
            syndrome_measurement_rounds,
            online_decoder_generator,
            offline_decoder_generator,
            physical_error_rate,
            max_shots,
            max_errors_before_halting,
            pauli,
            num_teleportations,
    )

    return samples_performed, logical_errors

def main():
    code = "surface"
    distances = [3, 5, 7]
    online_decoder = "pymatching"
    offline_decoder = "pymatching"
    physical_error_rates = [0.001, 0.002, 0.003, 0.004, 0.005, 0.006, 0.007, 0.008, 0.009, 0.01]
    max_shots = 10_000
    max_errors_before_halting = 500
    pauli = "z"
    num_teleportations = 1

    for distance in distances:
        for physical_error_rate in physical_error_rates:
            samples_performed, logical_errors = knill_error_correction(
                code,
                distance,
                online_decoder,
                offline_decoder,
                physical_error_rate,
                max_shots,
                max_errors_before_halting,
                pauli = pauli,
                num_teleportations=num_teleportations
            )

            logical_error_rate = logical_errors / samples_performed
            print(f"Logical error rate: {logical_error_rate}")
            print(f"Logical errors: {logical_errors} out of {samples_performed}")
    # results = {
    #     "samples_performed" : samples_performed, 
    #     "logical_errors" : int(logical_errors),
    #     "logical_error_rate" : logical_error_rate
    # }

    # # Save results
    # with open("results.json", "w") as f:
    #     json.dump(results, f, indent=2)

if __name__ == "__main__":
    main()
