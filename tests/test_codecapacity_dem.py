"""H4 controlled-fault projection, complete signatures and causal priors."""

from dataclasses import FrozenInstanceError, replace
from functools import lru_cache
import hashlib
from itertools import combinations

import numpy as np
import pymatching
import pytest
import stim

from hex_qec.decoders import (
    FaultSignature, PreparationDecoderConvention, ProjectedDEMBuilder,
    ProjectedErrorModel, ProjectedEvent, UnsupportedProjectedModel,
    merge_independent_events,
)
from hex_qec.decoders import codecapacity_dem as implementation
from hex_qec.modularisation import PreparationPlan
from hex_qec.protocols import FactoryCircuitBuilder, RotatedSurfaceCodeAdapter
from hex_qec.simulation import CompiledFactory, FactoryBatchDecoder


@lru_cache(maxsize=None)
def bundle(T=2, p=.001, r0=2, rp=2):
    return FactoryCircuitBuilder(RotatedSurfaceCodeAdapter(3), PreparationPlan(r0, rp), p, T_tel=T).build()


@lru_cache(maxsize=None)
def builder(T=2, p=.001, r0=2, rp=2):
    return ProjectedDEMBuilder(bundle(T, p, r0, rp))


def signature(b, records):
    hz = b.preparation_frames[0].module.z_pcm
    l = np.zeros(b.code.num_data_qubits, dtype=np.uint8)
    l[list(b.code.logical_z)] = 1
    return records @ hz.T % 2, records @ l % 2


@pytest.mark.parametrize("stage_index,mechanisms,mismatches", [(0, 1666, 375), (1, 2571, 280)])
def test_all_mechanisms_preserved_and_only_final_online_checks(stage_index, mechanisms, mismatches):
    b, owner = bundle(), builder()
    result = owner.build(stage_index)
    assert result is owner.build(stage_index) is owner.inspect(stage_index)
    assert result.graphlike and result.h3_lift_valid
    assert result.prior_convention == "circuit_informed_projected"
    assert "single_fault" in result.approximation and result.weight_units == "log_weight"
    assert result.diagnostics.mechanism_count == result.diagnostics.active_mechanism_count == mechanisms
    assert result.diagnostics.raw_vs_resolved_mismatches == mismatches
    assert result.diagnostics.event_count == 10
    assert not result.diagnostics.hyperedge_event_count
    assert not result.diagnostics.detector_free_logical_event_count
    assert {f.mechanism.origin_region for f in result.faults} >= {"prepare_A", "prepare_B", "cnot_B_to_A", "teleport_z"}
    assert max(f.mechanism.instruction_index for f in result.faults) < b.stages[stage_index].measurement.instructions.stop
    ids = [i for event in result.model.events for i in event.mechanism_ids]
    assert sorted(ids) == list(range(mechanisms))
    dem = result.model.to_stim_dem()
    assert dem.num_detectors == 4 and dem.num_observables == 1
    assert sum(term.type == "error" for term in dem) == len(result.model.events)
    assert any(term.type == "error" and not term.targets_copy() for term in dem)
    h, l, weights = result.model.matching_matrices()
    assert h.shape == (4, 9) and l.shape == weights.shape == (9,)
    assert np.all(np.isfinite(weights)) and np.all(weights > 0)
    assert owner.compile_gap(stage_index) is owner.compile_gap(stage_index)
    with pytest.raises(FrozenInstanceError):
        result.model_sha256 = "changed"


@pytest.mark.parametrize("stage_index", [0, 1])
def test_raw_signed_detector_marginals_match_independent_stim_dem(stage_index):
    b, result = bundle(), builder().build(stage_index)
    stage = b.stages[stage_index]
    dem = b.circuit[:stage.measurement.instructions.stop].detector_error_model()
    for index, flow in enumerate(stage.terminal_checks):
        expected = 0.
        for term in dem.flattened():
            if term.type == "error" and any(t.is_relative_detector_id() and t.val == flow.detector_index
                                             for t in term.targets_copy()):
                q = term.args_copy()[0]
                expected = expected * (1 - q) + q * (1 - expected)
        actual = 0.
        for fault in result.faults:
            if index in fault.raw_signed_signature.detectors:
                q = fault.mechanism.probability
                actual = actual * (1 - q) + q * (1 - actual)
        np.testing.assert_allclose(actual, expected, rtol=1e-12, atol=1e-15)


def select_fault(b, result, boundary):
    a, c = b.blocks
    if boundary.startswith("reset"):
        block = a if boundary == "reset_A" else c
        gate = "X_ERROR" if block == a else "Z_ERROR"
        return next(f for f in result.faults if f.mechanism.origin_region == f"prepare_{block.name}"
                    and f.mechanism.noise_gate == gate and f.mechanism.paulis[0][0] == block.data_qubits[0])
    if boundary.startswith("SE"):
        block = a if boundary == "SE_A" else c
        return max((f for f in result.faults if f.mechanism.origin_region == f"prepare_{block.name}"
                    and f.mechanism.noise_gate == "Z_ERROR"
                    and f.mechanism.paulis[0][0] in block.x_ancillas + block.z_ancillas),
                   key=lambda f: f.mechanism.instruction_index)
    if boundary == "readout":
        return next(f for f in result.faults if f.mechanism.origin_region == "teleport_z")
    desired = {"CNOT_target": ((a.data_qubits[0], "X"),),
               "CNOT_control": ((c.data_qubits[0], "X"),),
               "CNOT_pair": ((c.data_qubits[0], "X"), (a.data_qubits[0], "X"))}[boundary]
    return next(f for f in result.faults if f.mechanism.origin_region == "cnot_B_to_A" and f.mechanism.paulis == desired)


@pytest.mark.parametrize("boundary", ["reset_A", "reset_B", "SE_A", "SE_B", "CNOT_target",
                                      "CNOT_control", "CNOT_pair", "readout"])
def test_paired_physical_single_faults_characterize_reference_projection(boundary):
    b, result = bundle(), builder().build()
    stage = b.stages[0]
    fault = select_fault(b, result, boundary)
    prefix = b.circuit[:stage.measurement.instructions.stop]
    offset = fault.mechanism.instruction_index + 1
    sim = stim.FlipSimulator(batch_size=16, num_qubits=prefix.num_qubits, seed=341)
    sim.do(prefix[:offset].without_noise())
    altered = sim.copy(copy_rng=True)
    for qubit, pauli in fault.mechanism.paulis:
        mask = np.zeros((prefix.num_qubits, 16), dtype=bool)
        mask[qubit] = True
        altered.broadcast_pauli_errors(pauli=pauli, mask=mask)
    sim.do(prefix[offset:].without_noise())
    altered.do(prefix[offset:].without_noise())
    ref = prefix.without_noise().reference_sample()[None, :]
    raw, faulty = ref ^ sim.get_measurement_flips().T, ref ^ altered.get_measurement_flips().T
    # Independently randomized physical states retain the same controlled
    # Pauli record delta as the setup-only deterministic propagator.
    propagated = implementation._propagate_faults(prefix, (fault.mechanism,))[0]
    np.testing.assert_array_equal(raw ^ faulty, np.broadcast_to(propagated, raw.shape))
    decoder = FactoryBatchDecoder(b)
    before, after = decoder.decode_stage_input(raw, 0), decoder.decode_stage_input(faulty, 0)
    syndrome, logical = signature(b, before ^ after)
    expected = np.zeros(9, dtype=bool)
    expected[list(fault.interpreted_x)] = 1
    expected_s, expected_l = signature(b, expected[None, :])
    np.testing.assert_array_equal(syndrome, np.broadcast_to(expected_s, syndrome.shape))
    if boundary == "SE_B":
        # A real limit of the named fixed-reference approximation, not an
        # asserted universal conditional model. Preserve the observed mismatch.
        assert np.any(logical != expected_l) and np.any(logical == expected_l)
        assert "noiseless_reference" in result.approximation
    else:
        np.testing.assert_array_equal(logical, np.broadcast_to(expected_l, logical.shape))
    if boundary == "reset_A":
        assert fault.raw_signed_signature.logical == (0,)
        assert fault.signature == FaultSignature()  # actual offline repair removes it


def test_nonlinear_double_fault_response_is_not_independent_superposition():
    b, result = bundle(), builder().build()
    prefix = b.circuit[:b.stages[0].measurement.instructions.stop]
    faults = [f for f in result.faults if f.mechanism.origin_region == "prepare_A" and f.mechanism.noise_gate == "X_ERROR"]
    assert len(faults) == 9 and all(f.signature == FaultSignature() for f in faults)
    flips = implementation._propagate_faults(prefix, tuple(f.mechanism for f in faults))
    pairs = list(combinations(range(9), 2))
    reference = prefix.without_noise().reference_sample()[None, :]
    decoder = FactoryBatchDecoder(b)
    changes = (decoder.decode_stage_input(reference ^ np.stack([flips[a] ^ flips[c] for a, c in pairs]), 0)
               ^ decoder.decode_stage_input(reference, 0))
    syndrome, logical = signature(b, changes)
    assert not syndrome.any()
    assert logical.any()  # Individual zero responses cannot predict these O(p^2) failures.


def test_identical_complete_signatures_xor_merge_and_incompatible_logicals_survive():
    same, other = FaultSignature((0,), ()), FaultSignature((0,), (0,))
    terms = [ProjectedEvent(same, .1, (0,)), ProjectedEvent(same, .2, (1,)), ProjectedEvent(other, .1, (2,))]
    merged = merge_independent_events(terms)
    assert merged == merge_independent_events(reversed(terms))
    assert len(merged) == 2
    np.testing.assert_allclose(merged[0].probability, .26, atol=1e-15)
    assert merged[0].mechanism_ids == (0, 1) and merged[1].probability == .1
    with pytest.raises(ValueError, match="distinct"):
        merge_independent_events([terms[0], terms[0]])
    h, l, weights = ProjectedErrorModel(1, merged).matching_matrices()
    np.testing.assert_array_equal(l, [0, 1])
    np.testing.assert_allclose(weights, np.log((1 - np.array([.26, .1])) / np.array([.26, .1])))


@pytest.mark.parametrize("qubits", [1, 2])
def test_exact_independent_depolarizing_generator_probabilities(qubits):
    for p in (0., 1e-12, .001, .1):
        q = implementation._independent_depolarizing_probability(p, qubits)
        recovered_p = -(4**qubits - 1) / 4**qubits * np.expm1(2 ** (2 * qubits - 1) * np.log1p(-2 * q))
        np.testing.assert_allclose(recovered_p, p, rtol=1e-12, atol=1e-20)
    with pytest.raises(ValueError, match="over-mixing"):
        implementation._independent_depolarizing_probability(1., qubits)
    with pytest.raises(ValueError, match="underflow"):
        implementation._independent_depolarizing_probability(np.nextafter(0., 1.), qubits)


def test_zero_noise_has_empty_active_model_and_no_infinite_weight_decoder():
    result = builder(1, 0.).build()
    assert result.diagnostics.zero_noise and not result.model.active_events
    assert result.diagnostics.mechanism_count == 0 and result.diagnostics.zero_probability_instruction_count > 0
    assert result.graphlike and not result.h3_lift_valid
    assert result.model.to_stim_dem().num_detectors == 4
    assert not result.diagnostics.raw_vs_resolved_mismatches
    with pytest.raises(UnsupportedProjectedModel, match="Hamming baseline"):
        builder(1, 0.).compile_gap()


def test_third_stage_reused_plus_support_and_causal_prefix():
    b, owner = bundle(3, .001, 1, 1), builder(3, .001, 1, 1)
    result = owner.build(2)
    assert result.h3_lift_valid and result.stage_id == 2
    assert any(f.mechanism.origin_region == "prepare_B_t002" for f in result.faults)
    assert result.model.to_stim_dem().num_detectors == 4
    assert all(f.mechanism.origin_stage <= 2 for f in result.faults)


@pytest.mark.parametrize("signatures,message", [
    ([FaultSignature((0, 1, 2))], "hyperedge"),
    ([FaultSignature((), (0,))], "detector-free logical"),
    ([FaultSignature((0, 1), (0,)), FaultSignature((1, 2)), FaultSignature((0, 2))], "internal cycle"),
    ([FaultSignature((0,)), FaultSignature((1,))], "both logical boundaries"),
])
def test_graph_hyperedge_and_logical_only_rejection_without_matching(signatures, message, monkeypatch):
    model = ProjectedErrorModel(3, tuple(ProjectedEvent(sig, .1, (index,)) for index, sig in enumerate(signatures)))
    def forbidden(*args, **kwargs):
        raise AssertionError("unsupported model reached Matching")
    monkeypatch.setattr(pymatching.Matching, "from_check_matrix", forbidden)
    with pytest.raises(UnsupportedProjectedModel, match=message):
        model.compile_gap()
    if not signatures[0].detectors:
        assert any(term.type == "error" and any(t.is_logical_observable_id() for t in term.targets_copy())
                   for term in model.to_stim_dem())
    assert len(model.events) == len(signatures)


@pytest.mark.parametrize("probability", [.5, .6])
def test_nonpositive_log_weight_is_rejected(probability):
    model = ProjectedErrorModel(1, (ProjectedEvent(FaultSignature((0,)), probability, (0,)),))
    with pytest.raises(UnsupportedProjectedModel, match="0<q<1/2"):
        model.compile_gap()


def test_inspection_retains_unsupported_active_model_and_strict_build_rejects():
    owner = ProjectedDEMBuilder(bundle(1, .5, 1, 1))
    result = owner.inspect()
    assert result.faults and result.model.events and not result.h3_lift_valid
    assert not result.diagnostics.zero_noise and result.diagnostics.lift_error
    with pytest.raises(UnsupportedProjectedModel):
        owner.build()
    assert owner.inspect() is result


def test_stage_input_width_causality_and_oracle_exclusion(monkeypatch):
    b = bundle()
    decoder = FactoryBatchDecoder(b)
    raw = CompiledFactory.from_bundle(b, seed=652).sample_measurements(16)
    full = decoder.decode(raw)
    for index, stage in enumerate(b.stages):
        prefix = raw[:, :stage.measurement.measurements.stop]
        measured = decoder.decode_stage_input(prefix, index)
        s, _ = signature(b, measured)
        np.testing.assert_array_equal(s, full.corrected_syndromes[:, index])
        with pytest.raises(ValueError, match="width"):
            decoder.decode_stage_input(raw, index)
    for index in (-1, True, 2, 1.5):
        with pytest.raises(ValueError, match="stage_index"):
            decoder.decode_stage_input(raw, index)
    def forbidden(*args, **kwargs):
        raise AssertionError("prior construction sampled or read terminal truth")
    monkeypatch.setattr(stim.Circuit, "compile_sampler", forbidden)
    monkeypatch.setattr(type(decoder._readout), "evaluate_terminal", forbidden)
    result = ProjectedDEMBuilder(b).build(0)
    assert result.model_sha256 == builder().build(0).model_sha256
    # Change only future physical noise; the full configuration hash changes,
    # but every stage-zero model event/probability remains identical.
    offset = next(i for i in range(b.stages[1].preparations[0].instructions.start,
                                   b.stages[1].preparations[0].instructions.stop)
                  if b.circuit[i].name == "Z_ERROR")
    changed = b.circuit[:offset]
    changed.append("Z_ERROR", b.circuit[offset].targets_copy(), [.003])
    changed += b.circuit[offset + 1:]
    metadata = {**b.metadata, "circuit_sha256": hashlib.sha256(str(changed).encode()).hexdigest()}
    other = ProjectedDEMBuilder(replace(b, circuit=changed, metadata=metadata)).build(0)
    assert other.circuit_sha256 != result.circuit_sha256
    assert other.configuration_sha256 != result.configuration_sha256
    assert other.model_sha256 == result.model_sha256 and other.prefix_sha256 == result.prefix_sha256


def test_deterministic_cache_hashes_and_no_per_shot_construction(monkeypatch):
    owner = builder()
    result = owner.build()
    assert result == ProjectedDEMBuilder(bundle()).build()
    assert result.configuration_sha256 != builder(1, .002, 1, 1).build().configuration_sha256
    compiled = owner.compile_gap()
    s = np.random.default_rng(621).integers(0, 2, (16, 4), dtype=np.uint8)
    def forbidden(*args, **kwargs):
        raise AssertionError("expensive object reconstructed after case setup")
    monkeypatch.setattr(implementation, "_propagate_faults", forbidden)
    monkeypatch.setattr(implementation, "_enumerate_faults", forbidden)
    monkeypatch.setattr(stim, "FlipSimulator", forbidden)
    monkeypatch.setattr(pymatching.Matching, "from_check_matrix", forbidden)
    assert owner.build() is result and owner.compile_gap() is compiled
    scores = compiled.decode_batch(s)
    assert scores.gap.shape == (16,) and scores.score_units == "log_weight"


def test_configuration_hash_includes_actual_preparation_weights():
    b = FactoryCircuitBuilder(RotatedSurfaceCodeAdapter(3), PreparationPlan(1, 1), .001).build()
    before = ProjectedDEMBuilder(b).build()
    native = b.preparation_frames[0].module.x_decoder.decoder
    a, c, data = native.edges()[0]
    native.add_edge(a, c, fault_ids=data["fault_ids"], weight=data["weight"] + .25, merge_strategy="replace")
    after = ProjectedDEMBuilder(b).build()
    assert before.circuit_sha256 == after.circuit_sha256
    assert before.configuration_sha256 != after.configuration_sha256


def test_projection_chunk_partition_preserves_all_signatures_and_bounds_lanes(monkeypatch):
    original = implementation._propagate_faults
    sizes = []
    def record(circuit, faults):
        sizes.append(len(faults))
        return original(circuit, faults)
    monkeypatch.setattr(implementation, "_propagate_faults", record)
    expected = builder(1, .002, 1, 1).build()
    sizes.clear()
    owner = ProjectedDEMBuilder(bundle(1, .002, 1, 1), fault_batch_size=128)
    result = owner.build()
    assert len(sizes) > 1 and max(sizes) <= 128
    assert result.model == expected.model and result.faults == expected.faults
    assert result.model_sha256 == expected.model_sha256
    assert result.projection_batch_size == 128


def test_weighted_and_hamming_scores_use_identical_saved_samples_and_exact_model_costs():
    b, owner = bundle(), builder()
    compiled = CompiledFactory.from_bundle(b, seed=620)
    raw = compiled.sample_measurements(32)
    saved = raw.copy()
    baseline = compiled.decode(raw)
    model = owner.build().model
    weighted = owner.compile_gap().decode_batch(baseline.corrected_syndromes[:, 0])
    h, l, weights = model.matching_matrices()
    errors = ((np.arange(2**h.shape[1])[:, None] >> np.arange(h.shape[1])) & 1).astype(np.uint8)
    syndromes, logical, costs = errors @ h.T % 2, errors @ l % 2, errors @ weights
    for index, syndrome in enumerate(baseline.corrected_syndromes[:, 0]):
        for sector in (0, 1):
            expected = costs[np.all(syndromes == syndrome, axis=1) & (logical == sector)].min()
            np.testing.assert_allclose(weighted.sector_costs[index, sector], expected, rtol=0, atol=1e-12)
    assert np.any(weighted.gap != baseline.gaps[:, 0])  # Different declared units/models.
    np.testing.assert_array_equal(raw, saved)
    np.testing.assert_array_equal(compiled.decode(raw).logical_error, baseline.logical_error)


def test_invalid_conventions_hashes_and_unsupported_noise_are_explicit():
    b = bundle()
    with pytest.raises(ValueError, match="convention"):
        ProjectedDEMBuilder(b, convention=replace(PreparationDecoderConvention(), prefix_online="other"))
    with pytest.raises(ValueError, match="configuration hash"):
        ProjectedDEMBuilder(replace(b, circuit=b.circuit.without_noise()))
    with pytest.raises(ValueError, match="convention"):
        ProjectedDEMBuilder(replace(b, metadata={**b.metadata, "preparation_prior": "other"}))
    for size in (0, -1, True, .5):
        with pytest.raises(ValueError, match="fault_batch_size"):
            ProjectedDEMBuilder(b, fault_batch_size=size)
    owner = builder()
    for index in (-1, True, 2, .5):
        with pytest.raises(ValueError, match="stage_index"):
            owner.build(index)
    for gate, args, expected in (("PAULI_CHANNEL_1", [.001, 0, 0], "unsupported noise mechanism"),
                                  ("M", [.001], "noisy measurement arguments")):
        offset = 1 if gate == "PAULI_CHANNEL_1" else next(i for i in range(b.stages[0].measurement.instructions.start,
                                                                          b.stages[0].measurement.instructions.stop)
                                                                      if b.circuit[i].name == "M")
        changed = b.circuit[:offset]
        changed.append(gate, b.circuit[offset].targets_copy(), args)
        changed += b.circuit[offset + 1:]
        metadata = {**b.metadata, "circuit_sha256": hashlib.sha256(str(changed).encode()).hexdigest()}
        with pytest.raises(ValueError, match=expected):
            ProjectedDEMBuilder(replace(b, circuit=changed, metadata=metadata)).build()


@pytest.mark.parametrize("detectors,logical", [((0, 0), ()), ((-1,), ()), ((True,), ()), ((), (-1,))])
def test_signature_support_validation(detectors, logical):
    with pytest.raises(ValueError, match="signature supports"):
        FaultSignature(detectors, logical)


def test_event_probability_ids_and_detector_dimensions_are_validated():
    for q in (-.1, 1.1, np.inf, np.nan):
        with pytest.raises(ValueError, match="probabilities"):
            ProjectedEvent(FaultSignature((0,)), q, (0,))
    for ids in ((), (-1,), (True,), (0, 0)):
        with pytest.raises(ValueError, match="mechanism IDs"):
            ProjectedEvent(FaultSignature((0,)), .1, ids)
    with pytest.raises(ValueError, match="num_detectors"):
        ProjectedErrorModel(0, ())
    for sig in (FaultSignature((4,)), FaultSignature((0,), (1,))):
        with pytest.raises(ValueError, match="outside"):
            ProjectedErrorModel(4, (ProjectedEvent(sig, .1, (0,)),))
