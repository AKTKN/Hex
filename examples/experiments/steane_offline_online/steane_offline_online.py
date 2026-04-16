import stim
import pymatching
from ldpc import BpDecoder, BpOsdDecoder
import numpy as np
from numpy import ndarray

from hex_qec.circuit_generation import get_parity_check_matrices, stabilizer_measurement_circuit, noiseless_unitary_state_prep
from hex_qec.circuit_generation import generate_blocks, create_stabilizers_and_block_template
#from hex_qec.modularisation import logical_measurement_module, no_measurement_module, modularised_circuit, detector_module, css_detector_module, measurement_module
#from hex_qec.modularisation import generate_logical_measurement_module, generate_state_prep_modules, generate_state_prep_module_no_noise
from hex_qec.protocols import steane_online_offline

from typing import List, Dict, Tuple, Callable, Any
from pprint import pprint
from datetime import datetime
import subprocess
import argparse
import json
import time
import logging
import sys

def steane_error_correction(
        code,
        distance,
        online_decoder,
        offline_decoder,
        matchable_offline_decoding,
        physical_error_rate,
        max_shots,
        max_errors_before_halting,
        pauli,
        num_teleportations,
        results_path,
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

    samples_performed, logical_errors = steane_online_offline(
            parity_check_tuple,
            syndrome_measurement_rounds,
            online_decoder_generator,
            offline_decoder_generator,
            matchable_offline_decoding,
            physical_error_rate,
            max_shots,
            max_errors_before_halting,
            pauli,
            num_teleportations,
            results_path = results_path,
    )

    return samples_performed, logical_errors

def main():
    parser = argparse.ArgumentParser(description="Surface code logical error rate simulation")
    parser.add_argument("--code", type=str, help="Name of the code")
    parser.add_argument("--distance", type=int, help="Code distance (odd number)")
    parser.add_argument("--online_decoder", type=str, help="Name of online decoder")
    parser.add_argument("--offline_decoder", type=str, help="Name of offline decoder")
    parser.add_argument("--matchable_offline_decoding", help="Is the dem for the offline decoding matchable", action="store_true")
    parser.add_argument("--physical_error_rate", type=float, help="Physical error rate")
    parser.add_argument("--max_shots", type=int, help="Maximum number of shots")
    parser.add_argument("--max_errors_before_halting", type=int, help="Halt simulation if this number of errors is seen")
    parser.add_argument("--pauli", type=str, help="Basis to prepare logical state and to perform logical measurement")
    parser.add_argument("--num_teleportations", type=int, help="Number of teleportations to perform")
    args = parser.parse_args()

    samples_performed, logical_errors = steane_error_correction(
        args.code,
        args.distance,
        args.online_decoder,
        args.offline_decoder,
        args.matchable_offline_decoding,
        args.physical_error_rate,
        args.max_shots,
        args.max_errors_before_halting,
        pauli = args.pauli,
        num_teleportations=args.num_teleportations,
        results_path = "results.json"
    )

    logical_error_rate = logical_errors / samples_performed
    print(f"Logical error rate: {logical_error_rate}")
    print(f"Logical errors: {logical_errors} out of {samples_performed}")
    results = {
        "samples_performed" : samples_performed, 
        "logical_errors" : int(logical_errors),
        "logical_error_rate" : logical_error_rate
    }

    # Save results
    with open("results.json", "w") as f:
        json.dump(results, f, indent=2)

if __name__ == "__main__":
    main()
