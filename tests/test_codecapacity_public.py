"""H5 public options, causal contexts, exact legacy snapshots and cache reuse."""

from dataclasses import fields, replace
from functools import lru_cache
import hashlib
import importlib
from itertools import product

import numpy as np
import pymatching
import pytest
from scipy import sparse
import stim

from hex_qec.circuit_generation import get_parity_check_matrices
from hex_qec.decoders import EffectivePriorBuilder, ProjectedDEMBuilder, UnsupportedProjectedModel
from hex_qec.decoders import codecapacity_dem as prior_impl
from hex_qec.modularisation import (
    PreparationPlan, css_detector_module, logical_measurement_module,
    measurement_module, modularised_circuit, generate_bell_measurement_and_correction_module,
)
from hex_qec.modularisation.online_context import configure_knill_projected_priors
from hex_qec.modularisation.results import normalize_module_decode_output
from hex_qec.protocols import FactoryCircuitBuilder, RotatedSurfaceCodeAdapter, knill_online_offline
from hex_qec.simulation import CompiledFactory, FactoryBatchDecoder


_UNSET = object()


@lru_cache(maxsize=None)
def bundle(T=2, p=.001):
    return FactoryCircuitBuilder(RotatedSurfaceCodeAdapter(3), PreparationPlan(2, 2), p, T_tel=T).build()


@lru_cache(maxsize=None)
def factory(T=2):
    return CompiledFactory.from_bundle(bundle(T), seed=511, create_codecapacity_dem=True)


def capture_knill(monkeypatch, *, rounds=1, T=1, pauli="z", p=.001, mode=False, seed=1021):
    captured = []

    def simulate(self, *args, **kwargs):
        captured.append(self)
        assert kwargs["seed"] == seed
        return 0, 0

    monkeypatch.setattr(modularised_circuit, "simulate", simulate)
    options = {} if mode is _UNSET else {"create_codecapacity_dem": mode}
    assert knill_online_offline(
        get_parity_check_matrices("surface", 3), rounds,
        pymatching.Matching.from_check_matrix, pymatching.Matching.from_check_matrix,
        True, p, 0, 999, pauli, T, "", True, seed, **options,
    ) == (0, 0)
    return captured[0]


def decode_knill(protocol, records):
    """Legacy batch replay on saved <=128-shot records, including residuals."""
    working = records.copy()
    labels = np.zeros(len(records), dtype=bool)
    corrections = []
    offset = 0
    for module in protocol.circuit_modules:
        local = working[:, offset:offset + module.num_measurements]
        if isinstance(module, logical_measurement_module):
            labels |= np.any(module.c_func(local) != module.c_func_expected_output, axis=1)
        elif isinstance(module, (measurement_module, css_detector_module)):
            correction = normalize_module_decode_output(module.c_func(local)).corrections
            corrections.append(correction)
            working ^= (sparse.csc_matrix(correction) @ module.correction_to_measurement_flips).toarray() % 2 != 0
        offset += module.num_measurements
    detectors = protocol.circuit.compile_m2d_converter().convert(measurements=working, separate_observables=True)[0]
    assert not detectors.any()
    return labels, np.hstack(corrections).astype(np.int8)


# Computed from an isolated git archive of H4 commit 7df0b96, Stim 1.15.0 /
# PyMatching 2.3.1, seed 1021, 64 shots, d=3, p=.015. No baseline regeneration.
@pytest.mark.parametrize("rounds,T,pauli,circuit_sha,raw_sha,label_sha,correction_sha,errors", [
    (1, 1, "x", "4efe81053bcc69404cb31c7fa3217a89394bf794f3fe11c11fdc4a7d850d5d01",
     "ed18ce40809053fb74a4f1500bf36ab657290787c4c703cf2c4b30701c257ea9",
     "c15c39a199384850cbf745b956fadac843c8897631d6ae2012d37b5cecd5aa16",
     "1996185a08fb351818bbfbc0c6fc3fdf5aacc4329ccb73d185356b802f77a3e2", 11),
    (2, 2, "z", "207af0eb35eef6b56301f2bd03ed9f20c2aa12793efc0654c2038ce82f430394",
     "e214c30bf4abf84e61059e637198b9877d03f64750bb284955bab6b9f8b4f2c6",
     "1ba9dbf922b51aaddf40a562f7cef3ca37d2e4ab120e234968becca893072662",
     "d4426bb1f95752ec481f235b92bd7e445900c5bcd9927b0552cedd4c1b37b1ef", 9),
])
def test_false_fixed_seed_matches_h4_circuit_raw_samples_labels_and_corrections(
        monkeypatch, rounds, T, pauli, circuit_sha, raw_sha, label_sha, correction_sha, errors):
    implicit = capture_knill(monkeypatch, rounds=rounds, T=T, pauli=pauli, p=.015, mode=_UNSET)
    explicit = capture_knill(monkeypatch, rounds=rounds, T=T, pauli=pauli, p=.015, mode=False)
    assert explicit.circuit == implicit.circuit
    assert hashlib.sha256(str(explicit.circuit).encode()).hexdigest() == circuit_sha
    raw = explicit.circuit.compile_sampler(seed=1021).sample(64)
    np.testing.assert_array_equal(raw, implicit.circuit.compile_sampler(seed=1021).sample(64))
    labels, corrections = decode_knill(explicit, raw)
    # Native libraries do not promise cross-version sampling/tie decisions.
    # Always compare implicit/explicit False, and pin historical hashes only
    # in the original library environment.
    if (stim.__version__, pymatching.__version__) == ("1.15.0", "2.3.1"):
        for array, expected in ((raw, raw_sha), (labels, label_sha), (corrections, correction_sha)):
            assert hashlib.sha256(array.tobytes()).hexdigest() == expected
        assert labels.sum() == errors
    other = decode_knill(implicit, raw)
    np.testing.assert_array_equal(labels, other[0])
    np.testing.assert_array_equal(corrections, other[1])


@pytest.mark.parametrize("pauli", ["x", "z"])
def test_full_knill_true_smoke_both_sectors_and_noisy_final_readout(monkeypatch, pauli):
    legacy = capture_knill(monkeypatch, pauli=pauli)
    weighted = capture_knill(monkeypatch, pauli=pauli, mode=True)
    assert weighted.circuit == legacy.circuit
    raw = weighted.circuit.compile_sampler(seed=1021).sample(32)
    np.testing.assert_array_equal(raw, legacy.circuit.compile_sampler(seed=1021).sample(32))
    original = raw.copy()
    labels, corrections = decode_knill(weighted, raw)
    assert labels.dtype == bool and labels.shape == (32,)
    assert corrections.shape[0] == 32
    np.testing.assert_array_equal(raw, original)
    bell = next(m for m in weighted.circuit_modules if isinstance(m, measurement_module))
    assert tuple(p.sector for p in bell.projected_priors) == ("x", "z")
    for result in bell.projected_priors:
        assert result.h3_lift_valid and result.diagnostics.mechanism_count == 1058
        assert "single_fault_at_noiseless_reference" in result.approximation
        assert any("css_detector_module" in f.mechanism.origin_region for f in result.faults)
        assert max(f.mechanism.instruction_index for f in result.faults) < len(weighted.circuit) - 2
    final = weighted.circuit_modules[-1].circuit
    assert final[0].name == ("Z_ERROR" if pauli == "x" else "X_ERROR")
    assert final[0].gate_args_copy() == [.001]
    # Native event corrections need not have data-qubit width. Bell's public
    # output still has one logical Z and one logical X feed-forward bit.
    assert bell.c_func(raw[:, -27:-9]).shape == (32, 2)


def test_full_knill_bell_parities_match_exhaustive_both_sector_minima(monkeypatch):
    protocol = capture_knill(monkeypatch, mode=True)
    bell = next(m for m in protocol.circuit_modules if isinstance(m, measurement_module))
    all_syndromes = np.array(list(product((0, 1), repeat=4)), dtype=np.uint8)
    matrices = get_parity_check_matrices("surface", 3)
    readouts = []
    classes = []
    for prior, h in zip(bell.projected_priors, matrices[:2]):
        event_h, logical, weights = prior.model.matching_matrices()
        candidates = np.array(list(product((0, 1), repeat=len(weights))), dtype=np.uint8)
        costs = candidates @ weights
        signs = candidates @ event_h.T % 2
        parity = candidates @ logical % 2
        minima = np.array([[costs[np.all(signs == s, axis=1) & (parity == b)].min()
                            for b in (0, 1)] for s in all_syndromes])
        best = (minima[:, 1] < minima[:, 0]).astype(np.uint8)
        records = pymatching.Matching.from_check_matrix(h).decode_batch(all_syndromes)
        readouts.append(records)
        classes.append(best)
    logicals = matrices[2:]
    expected = np.column_stack([(records @ logical.T % 2).ravel().astype(bool) ^ best.astype(bool)
                                for records, logical, best in zip(readouts, logicals, classes)])
    np.testing.assert_array_equal(bell.c_func(np.hstack(readouts)), expected)


@pytest.mark.parametrize("rounds", [2, 3])
def test_full_knill_unsupported_logical_terms_raise_without_sampling(monkeypatch, rounds):
    def forbidden(*args, **kwargs):
        raise AssertionError("unsupported model reached physical sampling")
    monkeypatch.setattr(stim.Circuit, "compile_sampler", forbidden)
    with pytest.raises(UnsupportedProjectedModel, match="stage 0 sector x: detector-free logical"):
        capture_knill(monkeypatch, rounds=rounds, mode=True)


def test_full_knill_two_stages_use_actual_projected_prefixes(monkeypatch):
    context_impl = importlib.import_module("hex_qec.modularisation.online_context")
    contexts = []

    class RecordingBuilder(EffectivePriorBuilder):
        def __init__(self, context, **kwargs):
            contexts.append(context)
            super().__init__(context, **kwargs)

    monkeypatch.setattr(context_impl, "EffectivePriorBuilder", RecordingBuilder)
    protocol = capture_knill(monkeypatch, T=2, mode=True)
    assert [(c.stage_id, c.sector) for c in contexts] == [(0, "x"), (0, "z"), (1, "x"), (1, "z")]
    raw = protocol.circuit.compile_sampler(seed=218).sample(16)
    labels, _ = decode_knill(protocol, raw)
    assert labels.shape == (16,)
    working, offset, stage = raw.copy(), 0, 0
    for module in protocol.circuit_modules:
        if isinstance(module, measurement_module):
            for sector, context in enumerate(contexts[2*stage:2*stage+2]):
                # Independent replay includes the already-configured previous
                # Bell feed-forward, and no current/future recovery or label.
                np.testing.assert_array_equal(
                    context.interpret(raw[:, :offset + 18]),
                    working[:, offset + sector*9:offset + (sector+1)*9],
                )
                assert context.convention.prefix_online == "knill_causal_projected_v1"
            stage += 1
        if isinstance(module, (css_detector_module, measurement_module)):
            correction = module.c_func(working[:, offset:offset + module.num_measurements])
            working ^= (sparse.csc_matrix(correction) @ module.correction_to_measurement_flips).toarray() % 2 != 0
        offset += module.num_measurements


def test_full_knill_context_excludes_final_readout_and_reuses_preparation_converters(monkeypatch):
    context_impl = importlib.import_module("hex_qec.modularisation.online_context")
    contexts = []

    class RecordingBuilder(EffectivePriorBuilder):
        def __init__(self, context, **kwargs):
            contexts.append(context)
            super().__init__(context, **kwargs)

    monkeypatch.setattr(context_impl, "EffectivePriorBuilder", RecordingBuilder)
    protocol = capture_knill(monkeypatch)
    # Setup may use native objects. Decode after setup must not reconstruct any.
    configure_knill_projected_priors(protocol, get_parity_check_matrices("surface", 3))
    raw = protocol.circuit.compile_sampler(seed=411).sample(16)
    bell = next(m for m in protocol.circuit_modules if isinstance(m, measurement_module))
    original = bell.projected_priors
    expected = decode_knill(protocol, raw)
    assert len(contexts) == 2
    working, offset = raw.copy(), 0
    for module in protocol.circuit_modules:
        if module is bell:
            break
        if isinstance(module, css_detector_module):
            correction = module.c_func(working[:, offset:offset + module.num_measurements])
            working ^= (sparse.csc_matrix(correction) @ module.correction_to_measurement_flips).toarray() % 2 != 0
        offset += module.num_measurements
    for index, context in enumerate(contexts):
        np.testing.assert_array_equal(context.interpret(raw[:, :-9]), working[:, offset + 9*index:offset + 9*(index + 1)])
    for context in contexts:
        assert context.circuit.num_measurements == raw.shape[1] - 9
        with pytest.raises(ValueError, match="exactly its causal prefix"):
            context.interpret(raw)
    # Final noise/truth cannot enter either prior, even through its cache key.
    final = protocol.circuit_modules[-1]
    final.circuit = final.circuit.without_noise()
    configure_knill_projected_priors(protocol, get_parity_check_matrices("surface", 3))
    assert original == bell.projected_priors
    # The standalone public gadget can use supplied complete contexts too.
    direct = generate_bell_measurement_and_correction_module(
        get_parity_check_matrices("surface", 3), .001,
        list(range(9)), list(range(17, 26)), list(range(34, 43)),
        pymatching.Matching.from_check_matrix, create_codecapacity_dem=True,
        online_contexts=tuple(contexts[:2]),
    )
    assert direct.circuit == bell.circuit
    np.testing.assert_array_equal(direct.c_func(raw[:, -27:-9]), bell.c_func(raw[:, -27:-9]))
    wrong_contexts = (replace(contexts[0], sector="z"), contexts[1])
    with pytest.raises(ValueError, match="code/sector"):
        context_impl.configure_bell_projected_priors(direct, get_parity_check_matrices("surface", 3), wrong_contexts)
    prep = next(m for m in protocol.circuit_modules if isinstance(m, css_detector_module))
    prep.matchable = False
    with pytest.raises(UnsupportedProjectedModel, match="legacy matchable PyMatching"):
        configure_knill_projected_priors(protocol, get_parity_check_matrices("surface", 3))
    prep.matchable = True
    original = bell.projected_priors

    def forbidden(*args, **kwargs):
        raise AssertionError("expensive native object constructed during decoding")

    monkeypatch.setattr(stim, "FlipSimulator", forbidden)
    monkeypatch.setattr(pymatching.Matching, "from_check_matrix", forbidden)
    monkeypatch.setattr(prior_impl, "_propagate_faults", forbidden)
    # decode_knill's independent final residual check uses one converter;
    # check the actual prep/Bell callbacks directly under this stricter guard.
    monkeypatch.setattr(stim.Circuit, "compile_m2d_converter", forbidden)
    for module in protocol.circuit_modules:
        if isinstance(module, (css_detector_module, measurement_module)):
            module.c_func(np.zeros((16, module.num_measurements), dtype=bool))
    assert bell.projected_priors is original
    assert expected[0].shape == (16,)


@pytest.mark.parametrize("T", [1, 2])
def test_factory_true_causal_frames_gap_units_and_saved_record_batch_equality(T):
    compiled = factory(T)
    legacy = CompiledFactory.from_bundle(bundle(T), seed=511)
    raw = legacy.sample_measurements(32)
    np.testing.assert_array_equal(raw, CompiledFactory.from_bundle(bundle(T), seed=511).sample_measurements(32))
    assert compiled.circuit == legacy.circuit
    result = compiled.decode(raw)
    assert result.gap_units == "log_weight" and result.gaps.shape == (32, T)
    assert np.isfinite(result.gaps).all() and (result.gaps >= 0).all()
    assert result.frame_resolved.all()
    assert compiled.cache_key.create_codecapacity_dem
    assert len(compiled.cache_key.projected_prior_sha256) == T
    assert compiled.cache_key != legacy.cache_key
    for stage in range(T):
        assert compiled.projected_priors[stage].convention.prefix_online == "factory_causal_projected_v1"
        lx = np.zeros(9, dtype=bool)
        lx[list(bundle(T).code.logical_x)] = True
        region = bundle(T).stages[stage].preparations[-1]
        plan = next(p for p in bundle(T).preparation_frames if p.region == region)
        plus = plan.resolve(raw[:, region.measurements.slice])
        np.testing.assert_array_equal(result.output_frame_x[:, stage], plus.x ^ (result.logical_byproducts[:, stage, None] & lx))
    for shot in range(4):
        scalar = compiled.decode(raw[shot:shot + 1], shot_id_start=shot)
        for f in fields(result):
            value = getattr(result, f.name)
            if isinstance(value, np.ndarray):
                np.testing.assert_array_equal(getattr(scalar, f.name), value[shot:shot + 1])
    changed = raw.copy()
    changed[:, bundle(T).oracle.measurements.slice] ^= True
    other = compiled.decode(changed)
    for name in vars(result).keys() - {"logical_error"}:
        np.testing.assert_array_equal(getattr(result, name), getattr(other, name))


def test_factory_true_earlier_policy_identity_and_future_isolation():
    compiled = factory()
    hamming_context = ProjectedDEMBuilder(bundle()).build(1)
    assert compiled.projected_priors[1].configuration_sha256 != hamming_context.configuration_sha256
    raw = CompiledFactory.from_bundle(bundle(), seed=71).sample_measurements(16)
    changed = raw.copy()
    cutoff = bundle().stages[0].measurement.measurements.stop
    changed[:, cutoff:] = raw[::-1, cutoff:]
    a, b = compiled.decode(raw), compiled.decode(changed)
    for name in ("corrected_syndromes", "logical_byproducts", "output_frame_x", "output_frame_z", "gaps"):
        np.testing.assert_array_equal(getattr(a, name)[:, 0], getattr(b, name)[:, 0])


def test_factory_true_reuses_graphs_sampler_and_maps(monkeypatch):
    implementation = importlib.import_module("hex_qec.simulation.factory")
    prepared_bundle = bundle()  # Keep counts independent of test ordering.
    counts = dict(matching=0, sampler=0)
    matching, sampler = pymatching.Matching.from_check_matrix, implementation._compile_sampler

    def count_matching(*args, **kwargs):
        counts["matching"] += 1
        return matching(*args, **kwargs)

    def count_sampler(*args, **kwargs):
        counts["sampler"] += 1
        return sampler(*args, **kwargs)

    monkeypatch.setattr(pymatching.Matching, "from_check_matrix", count_matching)
    monkeypatch.setattr(implementation, "_compile_sampler", count_sampler)
    compiled = CompiledFactory.from_bundle(prepared_bundle, seed=179, create_codecapacity_dem=True)
    setup = counts.copy()
    assert setup == {"matching": 8, "sampler": 1}  # 3+3 spatial and 2 projected sector graphs.

    def forbidden(*args, **kwargs):
        raise AssertionError("factory rebuilt native object after setup")

    monkeypatch.setattr(stim, "FlipSimulator", forbidden)
    monkeypatch.setattr(stim.Circuit, "compile_m2d_converter", forbidden)
    monkeypatch.setattr(prior_impl, "_enumerate_prefix_faults", forbidden)
    compiled.sample(16)
    compiled.sample(16, shot_id_start=16)
    assert counts == setup


def test_full_knill_physical_fault_boundaries_match_controlled_raw_propagation(monkeypatch):
    protocol = capture_knill(monkeypatch, mode=True)
    bell = next(m for m in protocol.circuit_modules if isinstance(m, measurement_module))
    prefix = sum((m.circuit for m in protocol.circuit_modules[:-1]), stim.Circuit())
    faults = tuple(f.mechanism for f in bell.projected_priors[0].faults)
    selected = [next(f for f in faults if f.origin_region == region and f.noise_gate == gate)
                for region, gate in (("css_detector_module_1", "X_ERROR"),
                                     ("css_detector_module_2", "Z_ERROR"),
                                     ("measurement_module_4", "Z_ERROR"),
                                     ("measurement_module_4", "X_ERROR"))]
    selected.append(next(f for f in faults if f.origin_region == "measurement_module_4"
                         and f.noise_gate == "DEPOLARIZE2" and len(f.paulis) == 2))
    # Include an ancilla-SE fault as well as preparation resets, correlated
    # coupling and both destructive basis readouts (including MRX reset).
    selected.append(next(f for f in faults if f.origin_region == "css_detector_module_2"
                         and f.noise_gate == "Z_ERROR" and f.paulis[0][0] >= 43))
    for fault in selected:
        offset = fault.instruction_index + 1
        physical = stim.FlipSimulator(batch_size=16, num_qubits=prefix.num_qubits, seed=71)
        physical.do(prefix[:offset].without_noise())
        altered = physical.copy(copy_rng=True)
        for qubit, pauli in fault.paulis:
            mask = np.zeros((prefix.num_qubits, 16), dtype=bool)
            mask[qubit] = True
            altered.broadcast_pauli_errors(pauli=pauli, mask=mask)
        physical.do(prefix[offset:].without_noise())
        altered.do(prefix[offset:].without_noise())
        delta = (physical.get_measurement_flips() ^ altered.get_measurement_flips()).T
        expected = prior_impl._propagate_faults(prefix, (fault,))[0]
        np.testing.assert_array_equal(delta, np.broadcast_to(expected, delta.shape))


def test_zero_noise_true_and_incomplete_standalone_context_fail_explicitly(monkeypatch):
    with pytest.raises(UnsupportedProjectedModel, match="Hamming baseline"):
        CompiledFactory.from_bundle(bundle(1, 0.), create_codecapacity_dem=True)
    with pytest.raises(UnsupportedProjectedModel, match="Hamming baseline"):
        capture_knill(monkeypatch, p=0., mode=True)
    with pytest.raises(ValueError, match="full preparation"):
        generate_bell_measurement_and_correction_module(
            get_parity_check_matrices("surface", 3), .001, list(range(9)), list(range(9, 18)),
            list(range(18, 27)), pymatching.Matching.from_check_matrix, create_codecapacity_dem=True,
        )


def test_context_and_public_flag_boundaries(monkeypatch):
    context = ProjectedDEMBuilder(bundle()).context()
    with pytest.raises(ValueError, match="binary H"):
        replace(context, logical=np.ones(8))
    with pytest.raises(ValueError, match="outside its causal prefix"):
        replace(context, raw_logical=(context.circuit.num_measurements,))
    with pytest.raises(ValueError, match="invalid pre-recovery"):
        EffectivePriorBuilder(replace(context, interpret=lambda records: np.zeros((len(records), 1)))).build()
    with pytest.raises(ValueError, match="policy identity"):
        ProjectedDEMBuilder(bundle()).context(interpret=lambda records: records)
    for value in (1, "True", None):
        with pytest.raises(ValueError, match="must be bool"):
            FactoryBatchDecoder(bundle(), create_codecapacity_dem=value)
        with pytest.raises(ValueError, match="must be bool"):
            capture_knill(monkeypatch, mode=value)
