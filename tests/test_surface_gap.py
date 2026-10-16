"""H3 sector exactness against enumeration, graph guards, and causal scores."""

from functools import lru_cache

import numpy as np
import pymatching
import pytest
from scipy import sparse

from hex_qec.decoders import HomologyGapBatch, SurfaceMWPMHomologyGap
from hex_qec.modularisation import PreparationPlan
from hex_qec.protocols import FactoryCircuitBuilder, RotatedSurfaceCodeAdapter
from hex_qec.simulation import CompiledFactory


def enumerate_sectors(h, logical, weights):
    """Independent classical oracle over every error, not stochastic shots."""
    h = sparse.csc_matrix(h).toarray().astype(np.uint8)
    logical = np.asarray(sparse.csc_matrix(logical).toarray()[0], dtype=np.uint8)
    errors = ((np.arange(2**h.shape[1])[:, None] >> np.arange(h.shape[1])) & 1).astype(np.uint8)
    syndromes = errors @ h.T % 2
    classes = errors @ logical % 2
    weights = errors @ np.asarray(weights)
    unique = np.unique(syndromes, axis=0)
    costs = np.empty((len(unique), 2))
    for row, syndrome in enumerate(unique):
        same_syndrome = np.all(syndromes == syndrome, axis=1)
        for sector in (0, 1):
            costs[row, sector] = np.min(weights[same_syndrome & (classes == sector)])
    return unique, costs


WEIGHTS = [
    np.ones(9),
    np.array([.3, 1.6, 2.1, .7, 1.4, 1.8, 2.6, 1.1, .9]),
    np.array([3, 8, 1, 6, 4, 9, 2, 7, 5]) / 4,
    np.random.default_rng(431).uniform(.2, 3, 9),
]


@pytest.mark.parametrize("weights", WEIGHTS, ids=["unit", "nonuniform", "quarters", "seeded"])
@pytest.mark.parametrize("shift_logical", [False, True])
def test_d3_all_512_errors_both_sector_costs_and_logical_assignment(weights, shift_logical):
    _, h, _, logical = RotatedSurfaceCodeAdapter(3).matrices
    logical = logical.toarray()
    if shift_logical:
        logical ^= (np.array([[0, 1, 1, 0]], dtype=np.uint8) @ h % 2).astype(logical.dtype)
    decoder = SurfaceMWPMHomologyGap(h, logical, weights)
    syndromes, expected = enumerate_sectors(h, logical, weights)
    assert len(syndromes) == 16  # Decode unique syndromes, enumerate all 512 errors.
    result = decoder.decode_batch(syndromes)
    assert isinstance(result, HomologyGapBatch)
    np.testing.assert_allclose(result.sector_costs, expected, rtol=0, atol=1e-12)
    np.testing.assert_allclose(result.W0, expected[:, 0], rtol=0, atol=1e-12)
    np.testing.assert_allclose(result.W1, expected[:, 1], rtol=0, atol=1e-12)
    np.testing.assert_allclose(result.gap, np.abs(expected[:, 1] - expected[:, 0]), atol=1e-12)
    # Compare class for unique minima; tiny roundoff at mathematical ties can
    # choose either minimum. An exactly representable tie is tested separately.
    unique = ~np.isclose(expected[:, 0], expected[:, 1], rtol=0, atol=1e-12)
    np.testing.assert_array_equal(result.best_class[unique], np.argmin(expected[unique], axis=1))
    assert result.best_class.dtype == np.uint8 and result.gap.dtype == np.float64
    assert (result.gap >= 0).all() and result.score_units == "weight"
    extended = decoder.extended_check_matrix
    assert np.all(np.diff(extended.indptr) == 2)
    u = decoder.potential
    if shift_logical:
        assert u.any()
    np.testing.assert_array_equal((u @ h % 2) ^ extended.getrow(h.shape[0] + 1).toarray()[0], logical[0])
    for sector in (0, 1):
        correction = result.corrections[:, sector].astype(np.uint8)
        np.testing.assert_array_equal(correction @ h.T % 2, syndromes)
        np.testing.assert_array_equal(correction @ logical.T % 2, sector)


def test_hand_graph_nonzero_potential_and_boundary_parity_signs():
    h = np.array([[1, 1, 0], [0, 1, 1]], dtype=np.uint8)
    logical, weights = [0, 1, 0], [1., 2., 3.]
    decoder = SurfaceMWPMHomologyGap(h, logical, weights, score_units="log_weight")
    np.testing.assert_array_equal(decoder.potential, [0, 1])
    syndrome, expected = enumerate_sectors(h, logical, weights)
    result = decoder.decode_batch(syndrome)
    np.testing.assert_array_equal(result.sector_costs, expected)
    assert result.score_units == "log_weight"
    extended = decoder.extended_check_matrix
    for b in (0, 1):
        t1 = b ^ (syndrome @ decoder.potential % 2)
        t0 = np.bitwise_xor.reduce(syndrome, axis=1) ^ t1
        np.testing.assert_array_equal(result.corrections[:, b] @ extended.T % 2,
                                     np.column_stack((syndrome, t0, t1)))


def test_exact_tie_zero_gap_and_cheapest_parallel_edge_with_full_output_width():
    decoder = SurfaceMWPMHomologyGap([[1, 1]], [0, 1], [1, 1], score_units="hamming_weight")
    result = decoder.decode_batch([[0], [1]])
    np.testing.assert_array_equal(result.sector_costs, [[0, 2], [1, 1]])
    np.testing.assert_array_equal(result.gap, [2, 0])
    np.testing.assert_array_equal(result.best_class, [0, 0])
    # Last input edge is merged away, but result width must still be n=3.
    parallel = SurfaceMWPMHomologyGap([[1, 1, 1]], [0, 1, 1], [1, 2, 5])
    result = parallel.decode_batch([[0], [1]])
    np.testing.assert_array_equal(result.sector_costs, [[0, 3], [1, 2]])
    assert result.corrections.shape == (2, 2, 3)
    assert not result.corrections[:, :, -1].any()


def test_min_sum_gap_is_not_posterior_log_odds():
    _, h, _, l = RotatedSurfaceCodeAdapter(3).matrices
    errors = ((np.arange(512)[:, None] >> np.arange(9)) & 1).astype(np.uint8)
    same = ~np.any(errors @ h.T % 2, axis=1)
    logical = (errors @ l.T % 2)[:, 0]
    mass = np.exp(-errors.sum(axis=1, dtype=np.float64))
    posterior_log_odds = abs(np.log(mass[same & (logical == 0)].sum() / mass[same & (logical == 1)].sum()))
    gap = SurfaceMWPMHomologyGap(h, l, np.ones(9)).decode_batch(np.zeros((1, 4), dtype=np.uint8)).gap[0]
    assert np.isfinite(posterior_log_odds)
    assert gap == 3
    assert not np.isclose(gap, posterior_log_odds)


@pytest.mark.parametrize("h,logical,message", [
    ([[1, 0, 1]], [0, 1, 1], "zero-detector"),
    ([[1], [1], [1]], [1], "degree-1/2"),
    ([[1, 0, 1], [1, 1, 0], [0, 1, 1]], [1, 0, 0], "internal cycle"),
    ([[1, 1]], [0, 0], "both logical boundaries"),
    ([[1, 1], [0, 0]], [0, 1], "all detectors"),
    ([[1, 2]], [0, 1], "check matrix must be binary"),
    ([[1, 1]], [0, .5], "logical observable must be binary"),
    ([[1, 1]], [[0, 1], [1, 0]], "exactly one"),
    (np.empty((0, 2)), [0, 1], "nonempty"),
])
def test_invalid_graph_and_observable_contracts(h, logical, message):
    with pytest.raises(ValueError, match=message):
        SurfaceMWPMHomologyGap(h, logical, np.ones(np.shape(h)[1]))


def test_nonplanar_spatial_graph_is_rejected():
    edges = [(a, b) for a in range(3) for b in range(3, 6)]
    h = np.zeros((6, 11), dtype=np.uint8)
    for col, (a, b) in enumerate(edges):
        h[[a, b], col] = 1
    h[0, -2:] = 1
    l = np.zeros(11, dtype=np.uint8)
    l[-1] = 1
    with pytest.raises(ValueError, match="planar"):
        SurfaceMWPMHomologyGap(h, l, np.ones(11))


@pytest.mark.parametrize("weights", [[0, 1], [-1, 1], [np.inf, 1], [np.nan, 1],
                                     [2**24, 1], [1], [[1, 1]]])
def test_unsupported_or_degenerate_weights(weights):
    with pytest.raises(ValueError, match="positive finite"):
        SurfaceMWPMHomologyGap([[1, 1]], [0, 1], weights)


def test_weight_precision_limit_is_explicit_and_costs_use_original_weights():
    for weights in ([1e-12, 1], [1e-310, 1e-310]):
        with pytest.raises(ValueError, match="native precision"):
            SurfaceMWPMHomologyGap([[1, 1]], [0, 1], weights)
    decoder = SurfaceMWPMHomologyGap([[1, 1]], [0, 1], [.3, 1.6])
    result = decoder.decode_batch([[0], [1]])
    np.testing.assert_allclose(result.sector_costs, [[0, 1.9], [.3, 1.6]], rtol=0, atol=1e-15)


def test_units_binary_batch_validation_and_native_failures():
    with pytest.raises(ValueError, match="unit weights"):
        SurfaceMWPMHomologyGap([[1, 1]], [0, 1], [1, 2], score_units="hamming_weight")
    with pytest.raises(ValueError, match="score units"):
        SurfaceMWPMHomologyGap([[1, 1]], [0, 1], [1, 1], score_units="posterior")
    decoder = SurfaceMWPMHomologyGap([[1, 1]], [0, 1], [1, 1])
    for batch in ([], [0], np.empty((0, 1)), [[0, 0]]):
        with pytest.raises(ValueError, match="syndrome batch"):
            decoder.decode_batch(batch)
    with pytest.raises(ValueError, match="binary"):
        decoder.decode_batch([[2]])

    class BrokenMatching:
        def decode_batch(self, syndromes, **kwargs):
            return np.zeros((len(syndromes), 2), dtype=np.uint8), np.zeros(len(syndromes))

    decoder._matching = BrokenMatching()
    with pytest.raises(ValueError, match="sector constraints"):
        decoder.decode_batch([[1]])

    decoder = SurfaceMWPMHomologyGap([[1, 1]], [0, 1], [1, 1])
    native = decoder._matching.decode_batch

    class WrongWeights:
        def decode_batch(self, syndromes, **kwargs):
            correction, cost = native(syndromes, **kwargs)
            return correction, cost + 100

    decoder._matching = WrongWeights()
    with pytest.raises(ValueError, match="weights disagree"):
        decoder.decode_batch([[1]])


def test_two_batch_calls_same_graph_and_no_per_shot_construction(monkeypatch):
    _, h, _, l = RotatedSurfaceCodeAdapter(3).matrices
    decoder = SurfaceMWPMHomologyGap(h, l, np.ones(9))
    original = decoder._matching.decode_batch
    calls = []

    def record(syndrome, **kwargs):
        calls.append(syndrome.copy())
        return original(syndrome, **kwargs)

    def forbidden(*args, **kwargs):
        raise AssertionError("graph rebuilt while scoring")

    monkeypatch.setattr(decoder._matching, "decode_batch", record)
    monkeypatch.setattr(pymatching.Matching, "from_check_matrix", forbidden)
    syndromes = np.random.default_rng(21).integers(0, 2, (32, 4), dtype=np.uint8)
    syndromes.flags.writeable = False
    batch = decoder.decode_batch(syndromes)
    assert len(calls) == 2 and all(c.shape == (32, 6) for c in calls)
    singles = [decoder.decode_batch(syndromes[i:i + 1]) for i in range(32)]
    for name in ("sector_costs", "corrections", "gap", "best_class"):
        np.testing.assert_array_equal(getattr(batch, name), np.concatenate([getattr(r, name) for r in singles]))
    # Inspection properties return independent copies.
    decoder.extended_check_matrix.data[:] = 0
    decoder.potential[:] = 1
    np.testing.assert_array_equal(batch.gap, decoder.decode_batch(syndromes).gap)


def test_cache_identity_weights_logical_and_units_are_configuration_specific():
    h, l = [[1, 1]], [0, 1]
    baseline = SurfaceMWPMHomologyGap(h, l, [1, 1]).cache_identity
    assert baseline == SurfaceMWPMHomologyGap(h, l, [1, 1]).cache_identity
    for logical, w, units in ((l, [1, 2], "weight"), ([1, 0], [1, 1], "weight"),
                              (l, [1, 1], "hamming_weight")):
        assert baseline != SurfaceMWPMHomologyGap(h, logical, w, score_units=units).cache_identity


@lru_cache(maxsize=None)
def factory_bundle(T=3, p=.02, d=3):
    return FactoryCircuitBuilder(RotatedSurfaceCodeAdapter(d), PreparationPlan(2, 2), p, T_tel=T).build()


def assert_gaps_match_enumeration(bundle, result):
    hz = bundle.preparation_frames[0].module.z_pcm
    l = np.zeros(bundle.code.num_data_qubits, dtype=np.uint8)
    l[list(bundle.code.logical_z)] = 1
    s, costs = enumerate_sectors(hz, l, np.ones(len(l)))
    lookup = {tuple(row): abs(w[1] - w[0]) for row, w in zip(s, costs)}
    expected = [[lookup[tuple(row)] for row in shot] for shot in result.corrected_syndromes]
    np.testing.assert_array_equal(result.gaps, expected)


def test_factory_each_stage_uses_own_corrected_syndrome_and_no_future_oracle():
    bundle = factory_bundle()
    compiled = CompiledFactory.from_bundle(bundle, seed=729)
    raw = compiled.sample_measurements(32)
    result = compiled.decode(raw)
    assert result.gaps.shape == (32, 3) and result.gaps.dtype == np.float64
    assert result.gap_units == "hamming_weight"
    assert compiled.cache_key.gap_policy == "surface_two_boundary_hamming_v1"
    assert_gaps_match_enumeration(bundle, result)
    oracle_changed = raw.copy()
    oracle_changed[:, bundle.oracle.measurements.slice] ^= True
    np.testing.assert_array_equal(result.gaps, compiled.decode(oracle_changed).gaps)
    for index in (1, 2):
        future_changed = raw.copy()
        start = bundle.stages[index].preparations[0].measurements.start
        future_changed[:, start:] ^= np.random.default_rng(24).integers(0, 2, future_changed[:, start:].shape).astype(bool)
        changed = compiled.decode(future_changed)
        np.testing.assert_array_equal(result.gaps[:, :index], changed.gaps[:, :index])
        assert_gaps_match_enumeration(bundle, changed)
    # Scores depend on the syndrome, not the raw readout parity/byproduct.
    logical_changed = raw.copy()
    stage = bundle.stages[-1]
    logical_changed[:, [stage.measurement.measurements.start + q for q in bundle.code.logical_x]] ^= True
    np.testing.assert_array_equal(result.gaps, compiled.decode(logical_changed).gaps)


@pytest.mark.parametrize("T,d", [(1, 3), (2, 3), (3, 3), (2, 5)])
def test_factory_zero_noise_explicit_finite_hamming_rule(T, d):
    compiled = CompiledFactory.from_bundle(factory_bundle(T, 0., d), seed=873)
    result = compiled.sample(16)
    assert not result.logical_error.any() and not result.corrected_syndromes.any()
    np.testing.assert_array_equal(result.gaps, np.full((16, T), d, dtype=np.float64))
    assert np.isfinite(result.gaps).all()
