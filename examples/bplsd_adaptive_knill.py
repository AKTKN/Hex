"""Small BP-LSD confidence-aware adaptive Knill example.

This example deliberately uses ``matchable_offline_decoding=False`` so the
DEM probabilities passed by Hex are directly usable as BP-LSD error-channel
probabilities.  Code-capacity decoder calls receive a uniform channel from
``make_bplsd_decoder_generator``.
"""

import numpy as np
import pymatching

from hex_qec.circuit_generation import get_parity_check_matrices
from hex_qec.decoders import make_bplsd_decoder_generator
from hex_qec.modularisation import AdaptiveSERounds
from hex_qec.protocols import knill_online_offline_adaptive
from hex_qec.simulation import ClusterLLRPolicy


def max_decoder_confidence(results):
    """Use the largest risk score from the four CSS decodes."""
    values = [result.confidence for result in results if result.confidence is not None]
    return np.max(np.stack(values), axis=0) if values else None


def run_example():
    physical_error = 0.01
    parity_checks = get_parity_check_matrices("surface", 3)
    offline_decoder = make_bplsd_decoder_generator(
        physical_error,
        alpha=2.0,
    )
    schedule = AdaptiveSERounds(
        short_rounds=1,
        long_rounds=3,
        policy=ClusterLLRPolicy(threshold=0.01),
    )

    return knill_online_offline_adaptive(
        parity_checks,
        schedule,
        online_decoder_generator=pymatching.Matching.from_check_matrix,
        offline_decoder_generator=offline_decoder,
        matchable_offline_decoding=False,
        physical_error=physical_error,
        max_shots=256,
        max_errors_before_halting=100,
        pauli="z",
        num_teleportations=1,
        confidence_aggregator=max_decoder_confidence,
        detail_level="analysis",
        seed=1234,
    )


if __name__ == "__main__":
    result = run_example()
    print(result.summary)
    for event in result.state_prep_stats:
        print(event)
