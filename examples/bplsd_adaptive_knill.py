"""Small BP-LSD confidence-aware adaptive Knill example.

This example deliberately uses ``matchable_offline_decoding=False`` so the
DEM probabilities passed by Hex are directly usable as BP-LSD error-channel
probabilities.  Code-capacity decoder calls receive a uniform channel from
``make_bplsd_decoder_generator``.

``confidence_aggregator`` selects which of the four inner CSS decode results
(``x_dem``, ``z_dem``, ``x_capacity``, ``z_capacity``) feed the adaptive
policy.  This example uses ``dem_only_max_confidence``, the current default
for the adaptive-SE experiment: code-capacity confidence is intentionally
excluded because its decoder uses a uniform, non-circuit-derived prior (see
``FUTURE.md``, "Code-capacity confidence for adaptive state preparation").
``all_components_max_confidence`` is available for diagnostic comparison
only; it is not theoretically justified as a stopping metric yet.
"""

import pymatching

from hex_qec.circuit_generation import get_parity_check_matrices
from hex_qec.decoders import dem_only_max_confidence, make_bplsd_decoder_generator
from hex_qec.modularisation import AdaptiveSERounds
from hex_qec.protocols import knill_online_offline_adaptive
from hex_qec.simulation import ClusterLLRPolicy


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
        confidence_aggregator=dem_only_max_confidence,
        detail_level="analysis",
        seed=1234,
    )


if __name__ == "__main__":
    result = run_example()
    print(result.summary)
    for event in result.state_prep_stats:
        print(event)
