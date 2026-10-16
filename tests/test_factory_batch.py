"""H2 causal batches, reused supports, and independent legacy-frame replay."""

import copy
from dataclasses import FrozenInstanceError, fields, replace
from functools import lru_cache
import importlib

import numpy as np
import pymatching
import pytest
import stim

from hex_qec.modularisation import (
    IndexRange, PreparationFramePlan, PreparationPlan, measurement_module,
    modularised_circuit, no_measurement_module,
)
from hex_qec.modularisation.module_generation import (
    generate_logical_measurement_module, generate_transversal_cnot_module,
)
from hex_qec.modularisation.factory import RecordParity
from hex_qec.decoders.factory_surface import SurfaceFactoryReadout
from hex_qec.protocols import FactoryCircuitBuilder, RotatedSurfaceCodeAdapter
from hex_qec.simulation import (
    CompiledFactory, FactoryBatchDecoder, FactoryBatchResult, FactoryOperationalBatch,
)


@lru_cache(maxsize=None)
def factory(T=3, p=0.002, distance=3, r_0=2, r_plus=2):
    return FactoryCircuitBuilder(RotatedSurfaceCodeAdapter(distance),
                                 PreparationPlan(r_0, r_plus), p, T_tel=T).build()


def assert_operational_equal(first, second, stages=None):
    for description in fields(FactoryOperationalBatch):
        a, b = getattr(first, description.name), getattr(second, description.name)
        if isinstance(a, np.ndarray):
            if stages is not None and a.ndim >= 2:
                a, b = a[:, :stages], b[:, :stages]
            np.testing.assert_array_equal(a, b, err_msg=description.name)
        else:
            assert a == b


@pytest.mark.parametrize("T", [1, 2, 3])
def test_zero_noise_results_and_shapes(T):
    bundle = factory(T, 0.0, r_0=1, r_plus=2)
    compiled = CompiledFactory.from_bundle(bundle, seed=1729)
    result = compiled.sample(64, shot_id_start=2**63 + 7)
    assert isinstance(result, FactoryBatchResult)
    assert result.stage_ids == tuple(range(T))
    assert result.shot_id.dtype == np.uint64
    np.testing.assert_array_equal(result.shot_id, np.arange(64, dtype=np.uint64) + np.uint64(2**63 + 7))
    assert result.logical_error.shape == (64,) and result.logical_error.dtype == np.bool_
    assert not result.logical_error.any()
    assert result.corrected_syndromes.shape == (64, T, 4)
    assert not result.corrected_syndromes.any()
    assert result.output_frame_x.shape == result.output_frame_z.shape == (64, T, 9)
    assert result.frame_resolved.all() and result.frame_resolved.shape == (64, T)
    assert result.gaps.shape == (64, T) and result.gaps.dtype == np.float64
    assert result.gap_units == "hamming_weight"
    np.testing.assert_array_equal(result.gaps, 3)
    for name in ("corrected_syndromes", "raw_logical_byproducts", "logical_byproducts",
                 "output_frame_x", "output_frame_z", "frame_resolved"):
        assert getattr(result, name).dtype == np.bool_
    assert result.logical_byproducts.shape == result.raw_logical_byproducts.shape == (64, T)
    for stage in range(T):
        assert set(result.raw_logical_byproducts[:, stage]) == {False, True}
    with pytest.raises(FrozenInstanceError):
        compiled.cache_key = None
    with pytest.raises(FrozenInstanceError):
        compiled.cache_key.T_tel = 99
    public_circuit = compiled.circuit
    public_circuit.append("X", [0])
    assert public_circuit != compiled.circuit  # caller edits cannot change the compiled case


def test_distance_five_two_stage_smoke():
    result = CompiledFactory.from_bundle(factory(2, 0.0, 5, 1, 1), seed=18).sample(16)
    assert not result.logical_error.any()
    assert result.output_frame_x.shape == (16, 2, 25)
    assert result.corrected_syndromes.shape == (16, 2, 12)


def test_two_support_role_swaps_resets_and_preparation_template_reuse():
    bundle = factory()
    assert bundle.circuit.num_qubits == 34 and len(bundle.blocks) == 2
    assert [(stage.consumed_block, stage.surviving_block) for stage in bundle.stages] == [
        ("A", "B"), ("B", "A"), ("A", "B"),
    ]
    assert len(bundle.preparation_frames) == 4
    first_plus, repeated_plus = bundle.preparation_frames[1], bundle.preparation_frames[3]
    for name in ("module", "x_map", "z_map", "_x_converter", "_z_converter"):
        assert getattr(first_plus, name) is getattr(repeated_plus, name)
    assert first_plus.region != repeated_plus.region
    for stage in bundle.stages[1:]:
        assert len(stage.preparations) == 1
        region = stage.preparations[0]
        previous = bundle.stages[stage.index - 1]
        assert region.instructions.start >= previous.measurement.instructions.stop
        fragment = bundle.circuit[region.instructions.slice]
        fresh = next(block for block in bundle.blocks if block.name == stage.surviving_block)
        assert fragment[0].name == "RX"
        assert tuple(target.value for target in fragment[0].targets_copy()) == fresh.data_qubits
        # Each ancilla family has explicit reset before it is reused for SE.
        for support in (fresh.x_ancillas, fresh.z_ancillas):
            assert any(instruction.name == "R" and tuple(target.value for target in instruction.targets_copy()) == support
                       for instruction in fragment)
    assert len(bundle.oracle_record_indices) == 9
    assert {record.block for record in bundle.ledger.records if record.evaluation_only} == {"B"}
    assert bundle.operational_circuit.num_observables == 0
    bundle.validate()
    with pytest.raises(ValueError, match="measurement width"):
        first_plus.bind(replace(first_plus.region, measurements=IndexRange(0, 1)))


def test_last_oracle_uses_the_actual_surviving_block_for_even_stage_count():
    bundle = factory(2)
    assert {record.block for record in bundle.ledger.records if record.evaluation_only} == {"A"}
    assert tuple(target.value for target in bundle.circuit[-1].targets_copy()) == bundle.blocks[0].data_qubits


def test_oracle_changes_labels_without_changing_any_operational_field():
    bundle = factory()
    compiled = CompiledFactory.from_bundle(bundle, seed=101)
    raw = compiled.sample_measurements(32)
    baseline = compiled.decode(raw)
    altered = raw.copy()
    altered[:, [bundle.oracle.measurements.start + q for q in bundle.code.logical_x]] ^= True
    changed = compiled.decode(altered)
    assert_operational_equal(baseline, changed)
    np.testing.assert_array_equal(changed.logical_error, ~baseline.logical_error)
    assert_operational_equal(baseline, compiled.decode(raw))  # terminal handle leaves no online state
    assert_operational_equal(baseline, compiled.decode_operational(raw[:, :bundle.oracle.measurements.start]))
    with pytest.raises(ValueError, match="width"):
        compiled.decode_operational(raw)


@pytest.mark.parametrize("future_stage", [1, 2])
def test_future_records_do_not_change_earlier_stage_results(future_stage):
    bundle = factory()
    compiled = CompiledFactory.from_bundle(bundle, seed=2026)
    raw = compiled.sample_measurements(32)
    baseline = compiled.decode(raw)
    altered = raw.copy()
    start = bundle.stages[future_stage].preparations[0].measurements.start
    altered[:, start:] ^= np.random.default_rng(714).integers(0, 2, altered[:, start:].shape).astype(bool)
    changed = compiled.decode(altered)
    assert_operational_equal(baseline, changed, stages=future_stage)


def test_reproducibility_same_seed_and_chunk_partition():
    bundle = factory()
    first, second = (CompiledFactory.from_bundle(bundle, seed=829) for _ in range(2))
    for shots, start in ((17, 0), (31, 17)):
        raw_a, raw_b = first.sample_measurements(shots), second.sample_measurements(shots)
        np.testing.assert_array_equal(raw_a, raw_b)
        a, b = first.decode(raw_a, shot_id_start=start), second.decode(raw_b, shot_id_start=start)
        assert_operational_equal(a, b)
        np.testing.assert_array_equal(a.logical_error, b.logical_error)
        np.testing.assert_array_equal(a.shot_id, np.arange(start, start + shots, dtype=np.uint64))


def test_scalar_and_partitioned_decode_equal_full_batch_without_mutating_input():
    compiled = CompiledFactory.from_bundle(factory(), seed=77)
    raw = compiled.sample_measurements(32)
    saved = raw.copy()
    raw.flags.writeable = False
    batch = compiled.decode(raw)
    singles = [compiled.decode(raw[index:index + 1], shot_id_start=index) for index in range(32)]
    for description in fields(FactoryBatchResult):
        value = getattr(batch, description.name)
        if isinstance(value, np.ndarray):
            np.testing.assert_array_equal(value, np.concatenate([getattr(result, description.name) for result in singles]))
    split = [compiled.decode(raw[:13]), compiled.decode(raw[13:], shot_id_start=13)]
    for name in ("logical_error", "output_frame_x", "output_frame_z", "corrected_syndromes", "shot_id"):
        np.testing.assert_array_equal(getattr(batch, name), np.concatenate([getattr(part, name) for part in split]))
    np.testing.assert_array_equal(raw, saved)


def legacy_record_replay(bundle, raw, probe_basis, *, canonical_resets=True):
    """Independent reference: old module callbacks plus global correction maps.

    The final X probe uses synthetic zeros; only its deterministic correction
    delta is inspected. Canonical reset sentinels are used only for reference
    propagation maps, never physical sampling. R;RX and RX prepare the same
    state, but R;RX clears both components of a deterministic FlipSimulator
    frame, whereas RX alone can retain an invisible X stabilizer component.
    """
    matrices = bundle.preparation_frames[0].module.parity_check_tuple
    hz, lz = matrices[1], matrices[3]
    matching = pymatching.Matching.from_check_matrix(hz)
    plans = {plan.region.measurements.start: plan for plan in bundle.preparation_frames}
    blocks = {block.name: block for block in bundle.blocks}
    modules, byproduct_modules = [], []
    for stage in bundle.stages:
        for region in stage.preparations:
            plan = plans[region.measurements.start]
            if canonical_resets and plan.module.circuit[0].name == "RX":
                reset = stim.Circuit()
                reset.append("R", list(plan.block.data_qubits))
                modules.append(no_measurement_module(reset, list(range(reset.num_qubits))))
            modules.append(copy.copy(plan.module))
        target, control = blocks[stage.consumed_block], blocks[stage.surviving_block]
        modules.append(generate_transversal_cnot_module(bundle.metadata["physical_error"],
                                                        list(control.data_qubits), list(target.data_qubits)))

        def decode_byproduct(measurements):
            syndrome = measurements @ hz.T % 2
            recovery = matching.decode_batch(syndrome)
            return (measurements ^ recovery.astype(bool)) @ lz.T % 2

        fragment = bundle.circuit[stage.measurement.instructions.slice]
        logical_x = "*".join(f"X{control.data_qubits[q]}" for q in bundle.code.logical_x)
        measurement = measurement_module(fragment, decode_byproduct, [(logical_x, len(fragment))],
                                         new_support=list(range(fragment.num_qubits)))
        modules.append(measurement)
        byproduct_modules.append(measurement)
    final = generate_logical_measurement_module(matrices, 0.0, probe_basis.lower(),
                list(blocks[bundle.stages[-1].surviving_block].data_qubits),
                pymatching.Matching.from_check_matrix)
    modules.append(final)
    engine = modularised_circuit(modules)
    engine.generate_correction_to_measurement_flip_map()
    assert engine.circuit.num_measurements == raw.shape[1]
    records = raw.copy()
    if probe_basis == "X":
        records[:, bundle.oracle.measurements.slice] = False
    original_probe = records[:, bundle.oracle.measurements.slice].copy()
    offset, outcomes = 0, []
    for module in modules[:-1]:
        if hasattr(module, "correction_to_measurement_flips"):
            correction = module.c_func(records[:, offset:offset + module.num_measurements])
            if module in byproduct_modules:
                outcomes.append(correction[:, 0].astype(bool))
            records ^= (correction @ module.correction_to_measurement_flips % 2).astype(bool)
        offset += module.num_measurements
    corrected_probe = records[:, bundle.oracle.measurements.slice]
    return np.column_stack(outcomes), original_probe ^ corrected_probe, final.c_func(corrected_probe)[:, 0].astype(bool)


@pytest.mark.parametrize("T", [1, 2, 3])
def test_noisy_fixed_records_match_legacy_global_maps_in_both_pauli_bases(T):
    bundle = factory(T, 0.02, r_0=2, r_plus=2)
    compiled = CompiledFactory.from_bundle(bundle, seed=138)
    raw = compiled.sample_measurements(32)
    result = compiled.decode(raw)
    for basis, expected_frame in (("Z", result.output_frame_x[:, -1]), ("X", result.output_frame_z[:, -1])):
        byproducts, frame, labels = legacy_record_replay(bundle, raw, basis)
        np.testing.assert_array_equal(result.logical_byproducts, byproducts)
        np.testing.assert_array_equal(expected_frame, frame)
        if basis == "Z":
            np.testing.assert_array_equal(result.logical_error, labels)


@pytest.mark.parametrize("T", [2, 3])
def test_unmodified_legacy_reset_gauge_has_same_labels_and_physical_frame(T):
    bundle = factory(T, 0.02)
    compiled = CompiledFactory.from_bundle(bundle, seed=138)
    raw = compiled.sample_measurements(32)
    result = compiled.decode(raw)
    hx, hz, lx, lz = bundle.preparation_frames[0].module.parity_check_tuple
    for basis, expected, check, logical in (
            ("Z", result.output_frame_x[:, -1], hz, lz),
            ("X", result.output_frame_z[:, -1], hx, lx)):
        _, frame, labels = legacy_record_replay(bundle, raw, basis, canonical_resets=False)
        difference = frame ^ expected
        # Equal syndrome and logical action imply a stabilizer-only difference
        # for the supported k=1 CSS code; frame coordinates may differ.
        assert not (difference @ check.T % 2).any()
        assert not (difference @ logical.T % 2).any()
        if basis == "Z":
            np.testing.assert_array_equal(result.logical_error, labels)


@pytest.mark.parametrize("stage_index,block_role", [(0, "target"), (0, "control"), (1, "target"),
                                                   (1, "control"), (2, "target"), (2, "control")])
def test_injected_single_x_faults_follow_each_block_role(stage_index, block_role):
    bundle = factory()
    compiled = CompiledFactory.from_bundle(bundle, seed=42)
    stage = bundle.stages[stage_index]
    block_name = stage.consumed_block if block_role == "target" else stage.surviving_block
    block = next(block for block in bundle.blocks if block.name == block_name)
    offset = stage.coupling.instructions.stop
    circuit = (bundle.circuit[:offset].without_noise() + stim.Circuit(f"X {block.data_qubits[0]}")
               + bundle.circuit[offset:].without_noise())
    raw = circuit.compile_sampler(seed=99).sample(32)
    result = compiled.decode(raw)
    assert not result.logical_error.any()
    if block_role == "target":
        assert result.corrected_syndromes[:, stage_index].any()
    elif stage_index < 2:
        assert result.corrected_syndromes[:, stage_index + 1].any()
    # Check both full Pauli frame components against independent global maps.
    for basis, expected in (("Z", result.output_frame_x[:, -1]), ("X", result.output_frame_z[:, -1])):
        byproducts, frame, _ = legacy_record_replay(bundle, raw, basis)
        np.testing.assert_array_equal(result.logical_byproducts, byproducts)
        np.testing.assert_array_equal(frame, expected)


@pytest.mark.parametrize("stage_index", [0, 1, 2])
def test_survivor_logical_fault_persists_through_later_teleportations(stage_index):
    bundle = factory()
    compiled = CompiledFactory.from_bundle(bundle, seed=3)
    stage = bundle.stages[stage_index]
    block = next(block for block in bundle.blocks if block.name == stage.surviving_block)
    offset = stage.coupling.instructions.stop
    logical = "X " + " ".join(str(block.data_qubits[q]) for q in bundle.code.logical_x)
    circuit = bundle.circuit[:offset].without_noise() + stim.Circuit(logical) + bundle.circuit[offset:].without_noise()
    result = compiled.decode(circuit.compile_sampler(seed=7).sample(32))
    assert result.logical_error.all()


def test_objects_built_once_and_never_constructed_in_decode_or_sample(monkeypatch):
    implementation = importlib.import_module("hex_qec.simulation.factory")
    real_matching = pymatching.Matching.from_check_matrix
    real_sampler = implementation._compile_sampler
    counts = {"matching": 0, "sampler": 0}

    def counting_matching(*args, **kwargs):
        counts["matching"] += 1
        return real_matching(*args, **kwargs)

    def counting_sampler(*args, **kwargs):
        counts["sampler"] += 1
        return real_sampler(*args, **kwargs)

    monkeypatch.setattr(pymatching.Matching, "from_check_matrix", counting_matching)
    monkeypatch.setattr(implementation, "_compile_sampler", counting_sampler)
    bundle = FactoryCircuitBuilder(RotatedSurfaceCodeAdapter(3), PreparationPlan(2, 2), 0.002, T_tel=3).build()
    compiled = CompiledFactory.from_bundle(bundle, seed=38)
    assert counts == {"matching": 15, "sampler": 1}  # 3 prep templates * 4, online, oracle, gap

    def forbidden(*args, **kwargs):
        raise AssertionError("expensive object initialized while processing shots")

    monkeypatch.setattr(stim, "FlipSimulator", forbidden)
    monkeypatch.setattr(PreparationFramePlan, "__init__", forbidden)
    monkeypatch.setattr(pymatching.Matching, "from_check_matrix", forbidden)
    monkeypatch.setattr(implementation, "_compile_sampler", forbidden)
    compiled.sample(17)
    raw = compiled.sample_measurements(31)
    compiled.decode(raw)
    compiled.decode(raw[:1])
    assert counts == {"matching": 15, "sampler": 1}


def test_cache_key_configuration_coverage_and_seed_identity():
    bundle = factory()
    key = CompiledFactory.from_bundle(bundle, seed=12).cache_key
    same = CompiledFactory.from_bundle(bundle, seed=12).cache_key
    assert key == same and hash(key) == hash(same)
    assert (key.distance, key.physical_error, key.noise, key.r_0, key.r_plus, key.T_tel) == (3, 0.002, "hex_uniform", 2, 2, 3)
    assert key.circuit_sha256 == bundle.metadata["circuit_sha256"]
    assert key.frame_convention == bundle.metadata["frame_convention"]
    assert key.seed == 12 and key.stim_version == stim.__version__
    for T, p, r0, rp in ((1, 0.002, 2, 2), (3, 0.003, 2, 2), (3, 0.002, 1, 2), (3, 0.002, 2, 1)):
        assert CompiledFactory.from_bundle(factory(T, p, r_0=r0, r_plus=rp), seed=12).cache_key != key
    assert CompiledFactory.from_bundle(bundle, seed=13).cache_key != key
    # Change one probability without changing any signed-flow boundaries.
    instruction = bundle.circuit[1]
    changed = bundle.circuit[:1]
    changed.append(instruction.name, instruction.targets_copy(), [0.003])
    changed += bundle.circuit[2:]
    with pytest.raises(ValueError, match="metadata hash"):
        CompiledFactory.from_bundle(replace(bundle, circuit=changed), seed=12)


@pytest.mark.parametrize("T", [0, -1, True, 1.5])
def test_invalid_stage_counts(T):
    with pytest.raises(ValueError, match="T_tel"):
        FactoryCircuitBuilder(RotatedSurfaceCodeAdapter(3), PreparationPlan(1, 1), T_tel=T)


def test_invalid_batches_shot_ids_and_zero_shots():
    bundle = factory(1)
    compiled = CompiledFactory.from_bundle(bundle, seed=99)
    raw = compiled.sample_measurements(4)
    for data in (raw[:, :-1], raw[0], raw[:0]):
        with pytest.raises(ValueError, match="measurement batch"):
            compiled.decode(data)
    with pytest.raises(ValueError, match="binary"):
        compiled.decode(np.full(raw.shape, 2))
    for shots in (0, -1, True, 1.5):
        with pytest.raises(ValueError, match="positive integer"):
            compiled.sample(shots)
    for start in (-1, True, 2**64, np.uint64(2**64 - 1)):
        with pytest.raises(ValueError, match="uint64"):
            compiled.decode(raw, shot_id_start=start)
    edge = compiled.decode(raw[:1], shot_id_start=np.uint64(2**64 - 1))
    assert edge.shot_id.tolist() == [2**64 - 1]
    for seed in (-1, True, 2**64):
        with pytest.raises(ValueError, match="uint64"):
            CompiledFactory.from_bundle(bundle, seed=seed)


def test_decoder_rejects_noncausal_stage_contracts_and_unknown_conventions():
    bundle = factory()
    stages = bundle.stages
    earlier_prep = replace(stages[1], preparations=(stages[0].preparations[-1],))
    wrong_roles = replace(stages[0], consumed_block=stages[0].surviving_block)
    wrong_byproduct = replace(stages[0], raw_logical_outcome=RecordParity((0,)))
    for index, changed, message in ((1, earlier_prep, "causal stage boundary"),
                                    (0, wrong_roles, "roles must alternate"),
                                    (0, wrong_byproduct, "own readout records")):
        with pytest.raises(ValueError, match=message):
            FactoryBatchDecoder(replace(bundle, stages=stages[:index] + (changed,) + stages[index + 1:]))
    with pytest.raises(ValueError, match="stage count"):
        FactoryBatchDecoder(replace(bundle, metadata={**bundle.metadata, "T_tel": 1}))
    with pytest.raises(ValueError, match="frame convention"):
        FactoryBatchDecoder(replace(bundle, metadata={**bundle.metadata, "frame_convention": "unknown"}))


def test_surface_readout_rejects_unsupported_family_and_unresolved_recoveries():
    bundle = factory(1)
    hz = bundle.preparation_frames[0].module.z_pcm
    with pytest.raises(ValueError, match="rotated_surface only"):
        SurfaceFactoryReadout(replace(bundle.code, family="unsupported"), hz)
    readout = SurfaceFactoryReadout(bundle.code, hz)

    class BrokenMatching:
        def decode_batch(self, syndrome):
            return np.zeros((len(syndrome), bundle.code.num_data_qubits), dtype=bool)

    fault = np.zeros((1, bundle.code.num_data_qubits), dtype=bool)
    fault[0, 0] = True
    syndrome = readout.syndrome(fault)
    assert syndrome.any()
    readout._online = BrokenMatching()
    with pytest.raises(ValueError, match="online decoder did not resolve"):
        readout.recover(syndrome)
    readout._terminal = BrokenMatching()
    with pytest.raises(ValueError, match="terminal evaluation decoder did not resolve"):
        readout.evaluate_terminal(fault, np.zeros_like(fault))
