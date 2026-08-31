import numpy as np
import pymatching
import pytest

from hex_qec.circuit_generation import get_parity_check_matrices
from hex_qec.decoders import (
    CSSInnerDecodeResults,
    DecodeResult,
    HexBPLSDDecoder,
    all_components_max_confidence,
    dem_only_max_confidence,
    make_bplsd_decoder_generator,
)
from hex_qec.modularisation import (
    AdaptiveSERounds,
    generate_adaptive_state_prep_module,
)
from hex_qec.protocols import knill_online_offline, knill_online_offline_adaptive
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


def test_bplsd_cluster_llr_uses_full_final_cluster_membership():
    # The installed ldpc fork exposes final_bit_count plus growth history,
    # while its solution is a recovery vector. This case has three final
    # cluster bits but only two selected recovery bits.
    pcm = np.array(
        [[1, 1, 0, 0], [0, 1, 1, 0], [0, 0, 1, 1]],
        dtype=np.uint8,
    )
    priors = np.array([0.01, 0.02, 0.03, 0.04])
    decoder = HexBPLSDDecoder(
        pcm,
        priors,
        max_iter=1,
        bp_method="minimum_sum",
        lsd_method="LSD_0",
        lsd_order=0,
        always_run_lsd=True,
    )
    result = decoder.decode_batch(np.array([[0, 1, 0]], dtype=np.uint8))

    stats = decoder.decoder.statistics
    active = next(
        item for item in stats["individual_cluster_stats"].values()
        if item["active"]
    )
    assert active["final_bit_count"] == 3
    assert np.count_nonzero(active["solution"]) == 2

    llrs = np.log1p(-priors) - np.log(priors)
    expected = np.sum(llrs[[1, 2, 3]]) / np.sum(llrs)
    np.testing.assert_allclose(result.confidence, [expected])


@pytest.mark.parametrize("syndrome", ([0, 1, 0], [1, 0, 0], [1, 1, 0], [1, 1, 1]))
def test_bplsd_cluster_llr_matches_growth_history_for_small_syndromes(syndrome):
    pcm = np.array(
        [[1, 1, 0, 0], [0, 1, 1, 0], [0, 0, 1, 1]],
        dtype=np.uint8,
    )
    priors = np.array([0.01, 0.02, 0.03, 0.04])
    decoder = HexBPLSDDecoder(
        pcm,
        priors,
        max_iter=1,
        bp_method="minimum_sum",
        lsd_method="LSD_0",
        lsd_order=0,
        always_run_lsd=True,
    )
    result = decoder.decode_batch(np.asarray([syndrome], dtype=np.uint8))
    stats = decoder.decoder.statistics
    history = stats["global_timestep_bit_history"]
    memberships = []
    for cluster_id, cluster in stats["individual_cluster_stats"].items():
        if not cluster.get("active", False):
            continue
        bits = set()
        for timestep in history.values():
            bits.update(timestep.get(cluster_id, []))
        memberships.append(sorted(bits))
    weights = np.log1p(-priors) - np.log(priors)
    expected = (
        np.linalg.norm([np.sum(weights[bits]) for bits in memberships], ord=2)
        / np.sum(weights)
        if memberships
        else 0.0
    )
    np.testing.assert_allclose(result.confidence, [expected])


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
        assert len(result.bell_pair_stats) == 2
        assert all(
            item.teleportation_index in {0, 1}
            and item.state_basis in {"x", "z"}
            for item in result.state_prep_stats
        )


def test_fixed_knill_surface_code_keyword_is_backward_compatible():
    parity_checks = get_parity_check_matrices("surface", 3)
    result = knill_online_offline(
        parity_checks,
        2,
        pymatching.Matching.from_check_matrix,
        pymatching.Matching.from_check_matrix,
        True,
        0.0,
        2,
        100,
        "z",
        1,
        surface_code=True,
    )
    assert result == (256, 0)


def test_adaptive_knill_synchronizes_pair_when_one_patch_requests_extension():
    parity_checks = get_parity_check_matrices("surface", 3)

    class ExtendZOnlyPolicy:
        def should_extend(self, decode_result, *, context):
            return np.full(context.batch_size, context.state_basis == "z")

    result = knill_online_offline_adaptive(
        parity_checks,
        AdaptiveSERounds(1, 2, ExtendZOnlyPolicy()),
        pymatching.Matching.from_check_matrix,
        pymatching.Matching.from_check_matrix,
        True,
        0.0,
        2,
        100,
        "z",
        1,
        batch_size=2,
        seed=8,
        detail_level="analysis",
    )

    assert result.to_legacy_tuple() == (2, 0)
    assert result.bell_pair_stats[0].long_count == 2
    assert result.bell_pair_stats[0].z_only_count == 2
    assert result.bell_pair_stats[0].x_only_count == 0
    assert result.bell_pair_stats[0].both_count == 0
    np.testing.assert_array_equal(result.per_shot["would_extend"], [[True, False], [True, False]])
    assert result.per_shot["pair_risk"].shape == (2, 2)
    np.testing.assert_array_equal(
        result.per_shot["pair_risk"][:, 0], result.per_shot["pair_risk"][:, 1]
    )
    np.testing.assert_array_equal(result.per_shot["used_long_pair"], [[True], [True]])
    np.testing.assert_array_equal(result.per_shot["used_long"], [[True, True], [True, True]])


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


def test_css_inner_decode_results_is_list_compatible():
    # CSSInnerDecodeResults is a NamedTuple: a confidence_aggregator that
    # treats it as a plain 4-element list (iteration/indexing/slicing) must
    # keep working exactly as before.
    results = CSSInnerDecodeResults(
        x_dem=DecodeResult(correction=np.zeros((1, 1))),
        z_dem=DecodeResult(correction=np.zeros((1, 1))),
        x_capacity=DecodeResult(correction=np.zeros((1, 1))),
        z_capacity=DecodeResult(correction=np.zeros((1, 1))),
    )
    assert len(results) == 4
    assert list(results) == [
        results.x_dem, results.z_dem, results.x_capacity, results.z_capacity,
    ]
    assert results[:2] == (results.x_dem, results.z_dem)


def test_dem_only_default_excludes_code_capacity_confidence():
    """Item 6.A: mock four inner decode results with poor code-capacity
    confidence and good DEM confidence; the current adaptive patch decision
    must stay short.  Then make DEM confidence poor and the patch must
    request long."""

    good = np.array([0.0])
    bad = np.array([999.0])
    results_good_dem = CSSInnerDecodeResults(
        x_dem=DecodeResult(correction=np.zeros((1, 1)), confidence=good),
        z_dem=DecodeResult(correction=np.zeros((1, 1)), confidence=good),
        x_capacity=DecodeResult(correction=np.zeros((1, 1)), confidence=bad),
        z_capacity=DecodeResult(correction=np.zeros((1, 1)), confidence=bad),
    )
    policy = ClusterLLRPolicy(threshold=0.5)
    context = AdaptivePolicyContext(batch_size=1)

    confidence = dem_only_max_confidence(results_good_dem)
    np.testing.assert_array_equal(confidence, [0.0])
    extend = policy.should_extend(
        DecodeResult(correction=np.zeros((1, 1)), confidence=confidence),
        context=context,
    )
    assert not bool(extend[0]), "poor code-capacity confidence must not force extension"

    # all_components_max_confidence WOULD have picked up the bad
    # code-capacity value -- confirming the exclusion above is deliberate,
    # not an accident of the mocked numbers.
    all_confidence = all_components_max_confidence(results_good_dem)
    np.testing.assert_array_equal(all_confidence, [999.0])

    # Now make DEM confidence itself poor: the patch must request long.
    results_bad_dem = results_good_dem._replace(
        x_dem=DecodeResult(correction=np.zeros((1, 1)), confidence=np.array([1.0])),
    )
    confidence_bad = dem_only_max_confidence(results_bad_dem)
    extend_bad = policy.should_extend(
        DecodeResult(correction=np.zeros((1, 1)), confidence=confidence_bad),
        context=context,
    )
    assert bool(extend_bad[0])


class _BasisSelectivePolicy:
    """Diagnostic policy: extends a patch based only on its own basis.

    It never reads ``decode_result``.  Used to prove the pair-level executor
    combines each patch's own independent ``AdaptivePolicy`` decision via
    OR, rather than deriving the pair decision from a combined/raw
    confidence value.
    """

    def __init__(self, extend_zero: bool, extend_plus: bool) -> None:
        self.extend_zero = extend_zero
        self.extend_plus = extend_plus

    def should_extend(self, decode_result, *, context):
        want = self.extend_zero if context.state_basis == "z" else self.extend_plus
        return np.full(context.batch_size, want)


@pytest.mark.parametrize(
    "extend_zero,extend_plus",
    [(False, False), (True, False), (False, True), (True, True)],
)
def test_bell_pair_patch_independence_and_or_synchronization(extend_zero, extend_plus):
    """Item 6.B/6.E: the four zero/plus confidence combinations must reduce
    to a synchronized OR decision, and selected_rounds_zero must always
    equal selected_rounds_plus."""

    parity_checks = get_parity_check_matrices("surface", 3)
    policy = _BasisSelectivePolicy(extend_zero, extend_plus)

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
        1,
        batch_size=2,
        seed=11,
        detail_level="analysis",
    )

    expect_long = extend_zero or extend_plus
    per_shot = result.per_shot
    np.testing.assert_array_equal(per_shot["would_extend_zero"], np.full((2, 1), extend_zero))
    np.testing.assert_array_equal(per_shot["would_extend_plus"], np.full((2, 1), extend_plus))
    np.testing.assert_array_equal(per_shot["used_long_pair"], np.full((2, 1), expect_long))

    # selected_rounds_zero == selected_rounds_plus for every shot.
    np.testing.assert_array_equal(per_shot["used_long"][:, 0], per_shot["used_long"][:, 1])
    np.testing.assert_array_equal(per_shot["used_long_pair"][:, 0], per_shot["used_long"][:, 0])

    # used_long_pair must equal would_extend_zero OR would_extend_plus.
    expected_pair = per_shot["would_extend_zero"] | per_shot["would_extend_plus"]
    np.testing.assert_array_equal(per_shot["used_long_pair"], expected_pair)

    pair = result.bell_pair_stats[0]
    if expect_long:
        assert pair.long_count == 2 and pair.short_count == 0
    else:
        assert pair.short_count == 2 and pair.long_count == 0


class _InvertedScorePolicy:
    """Dummy AdaptivePolicy using the OPPOSITE numeric convention from
    ClusterLLRPolicy: here a SMALLER score means LESS confident, and the
    policy extends when its score is below a threshold.  It derives its
    score from ``context`` only (never from ``decode_result.confidence``),
    so this test is deterministic and proves the pair executor's OR-of-
    booleans logic is agnostic to any particular raw-confidence direction
    or threshold convention -- it never assumes a Cluster-LLR-style
    ``max(...) > threshold`` rule.
    """

    def __init__(self, low_basis: str, threshold: float = 0.5) -> None:
        self.low_basis = low_basis
        self.threshold = threshold

    def should_extend(self, decode_result, *, context):
        score = 0.1 if context.state_basis == self.low_basis else 0.9
        return np.full(context.batch_size, score < self.threshold)


@pytest.mark.parametrize("low_basis,expected_cause", [("z", "z_only"), ("x", "x_only")])
def test_pair_or_logic_is_agnostic_to_confidence_direction(low_basis, expected_cause):
    """Item 6.C: a policy with an inverted confidence-direction convention
    still combines correctly at the pair level via OR."""

    parity_checks = get_parity_check_matrices("surface", 3)
    policy = _InvertedScorePolicy(low_basis)

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
        1,
        batch_size=2,
        seed=12,
        detail_level="analysis",
    )

    pair = result.bell_pair_stats[0]
    assert pair.long_count == 2
    assert pair.short_count == 0
    if expected_cause == "z_only":
        assert pair.z_only_count == 2 and pair.x_only_count == 0
    else:
        assert pair.x_only_count == 2 and pair.z_only_count == 0

    per_shot = result.per_shot
    expected_pair = per_shot["would_extend_zero"] | per_shot["would_extend_plus"]
    np.testing.assert_array_equal(per_shot["used_long_pair"], expected_pair)
