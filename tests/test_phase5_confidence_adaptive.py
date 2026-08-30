import numpy as np
import pymatching

from hex_qec.circuit_generation import get_parity_check_matrices
from hex_qec.decoders import (
    DecodeResult,
    make_bplsd_decoder_generator,
)
from hex_qec.modularisation import (
    AdaptiveSERounds,
    generate_adaptive_state_prep_module,
)
from hex_qec.protocols import knill_online_offline_adaptive
from hex_qec.simulation import (
    AdaptivePolicyContext,
    AlwaysLongPolicy,
    AlwaysShortPolicy,
    ClusterLLRPolicy,
    StatefulAdaptiveKnillExecutor,
    StatefulAdaptiveStatePrepExecutor,
)


def _max_confidence(results):
    values = [result.confidence for result in results if result.confidence is not None]
    return np.max(np.stack(values), axis=0) if values else None


def test_cluster_llr_policy_uses_decode_result_confidence():
    policy = ClusterLLRPolicy(0.2)
    result = DecodeResult(
        correction=np.zeros((3, 1), dtype=np.uint8),
        confidence=np.array([0.0, 0.2, 0.5]),
    )

    actual = policy.should_extend(
        result,
        context=AdaptivePolicyContext(batch_size=3),
    )

    np.testing.assert_array_equal(actual, [False, False, True])


def test_bplsd_adapter_returns_recovery_and_cluster_llr():
    pcm = np.array([[1, 1]], dtype=np.uint8)
    decoder = make_bplsd_decoder_generator(0.01)(pcm)
    result = decoder.decode_batch(np.array([[0], [1]], dtype=np.uint8))

    assert result.correction.shape == (2, 2)
    assert result.confidence.shape == (2,)
    assert result.metrics["cluster_llr"].shape == (2,)


def test_real_cluster_llr_threshold_produces_mixed_short_long_batch():
    parity_checks = get_parity_check_matrices("surface", 3)
    decoder_generator = make_bplsd_decoder_generator(0.1)
    schedule = AdaptiveSERounds(1, 3, ClusterLLRPolicy(0.01))
    description = generate_adaptive_state_prep_module(
        parity_checks,
        schedule,
        "z",
        0.1,
        list(range(17)),
        decoder_generator,
        False,
        confidence_aggregator=_max_confidence,
    )

    execution = StatefulAdaptiveStatePrepExecutor().execute(
        description,
        batch_size=8,
        seed=2,
    )

    assert np.any(execution.used_long)
    assert np.any(~execution.used_long)
    assert execution.confidence is not None
    assert execution.confidence.shape == (8,)


def test_adaptive_knill_endpoints_support_two_teleportations():
    parity_checks = get_parity_check_matrices("surface", 3)
    for policy in (AlwaysShortPolicy(), AlwaysLongPolicy()):
        result = knill_online_offline_adaptive(
            parity_checks,
            AdaptiveSERounds(1, 2, policy),
            pymatching.Matching.from_check_matrix,
            pymatching.Matching.from_check_matrix,
            True,
            0.0,
            2,
            100,
            "z",
            2,
            batch_size=2,
            seed=7,
        )

        assert result.to_legacy_tuple() == (2, 0)
        assert len(result.state_prep_stats) == 4
        assert all(
            item.teleportation_index in {0, 1}
            and item.state_basis in {"x", "z"}
            for item in result.state_prep_stats
        )


def test_adaptive_knill_confidence_smoke_with_bplsd():
    parity_checks = get_parity_check_matrices("surface", 3)
    decoder_generator = make_bplsd_decoder_generator(0.01)
    result = knill_online_offline_adaptive(
        parity_checks,
        AdaptiveSERounds(1, 2, ClusterLLRPolicy(0.001)),
        pymatching.Matching.from_check_matrix,
        decoder_generator,
        False,
        0.01,
        2,
        100,
        "z",
        1,
        confidence_aggregator=_max_confidence,
        batch_size=2,
        seed=4,
        detail_level="analysis",
    )

    assert result.samples_performed == 2
    assert len(result.state_prep_stats) == 2
    assert result.per_shot["confidence"].shape == (2, 2)
    assert result.per_shot["used_long"].shape == (2, 2)
