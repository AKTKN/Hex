"""H1 circuit, signed-boundary and prep-frame checks; no factory runner."""

from dataclasses import FrozenInstanceError, replace
from functools import lru_cache

import numpy as np
import pymatching
import pytest
import stim

from hex_qec.modularisation import BlockSupport, CodeSpec, IndexRange, PreparationPlan, RecordParity
from hex_qec.protocols import (
    FactoryCircuitBuilder, RotatedSurfaceCodeAdapter,
)


@lru_cache(maxsize=None)
def factory(distance=3, p=0.001, r_0=2, r_plus=2):
    return FactoryCircuitBuilder(RotatedSurfaceCodeAdapter(distance), PreparationPlan(r_0, r_plus), p).build()


def online_boundary(bundle, operational):
    """Test-only single-stage boundary calculation; accepts no oracle bits."""
    frames = tuple(plan.resolve(operational[:, plan.region.measurements.slice])
                   for plan in bundle.preparation_frames)
    stage = bundle.stages[0]
    measured = operational[:, stage.measurement.measurements.slice] ^ frames[0].x ^ frames[1].x
    module = bundle.preparation_frames[0].module
    syndrome = ((measured @ module.z_pcm.T) % 2).astype(bool)
    syndrome ^= frames[0].z_signs ^ frames[1].z_signs
    recovery = module.z_decoder.decode_batch(syndrome).correction.astype(bool)
    byproduct = ((measured ^ recovery) @ module.parity_check_tuple[3].T % 2).astype(bool)[:, 0]
    return syndrome, byproduct, frames


def evaluation_label(bundle, raw, byproduct, frames):
    """Test oracle only: ideal Z readout, spatial recovery, then logical Z."""
    module = bundle.preparation_frames[0].module
    corrected = raw[:, bundle.oracle.measurements.slice] ^ frames[1].x
    lx = module.parity_check_tuple[2].toarray()[0].astype(bool)
    corrected ^= byproduct[:, None] & lx[None, :]
    syndrome = (corrected @ module.z_pcm.T % 2).astype(bool)
    recovery = module.z_decoder.decode_batch(syndrome).correction.astype(bool)
    return (((corrected ^ recovery) @ module.parity_check_tuple[3].T) % 2).astype(bool)[:, 0]


@pytest.mark.parametrize("distance,depths", [(3, (1, 1)), (3, (2, 3)), (5, (1, 2))])
def test_zero_noise_both_outcomes_and_correct_x_byproduct(distance, depths):
    bundle = factory(distance, 0.0, *depths)
    raw = bundle.circuit.compile_sampler(seed=1729).sample(128)
    syndrome, byproduct, frames = online_boundary(bundle, raw[:, :bundle.oracle.measurements.start])
    assert not syndrome.any()
    assert set(bundle.stages[0].raw_logical_outcome.evaluate(raw)) == {False, True}
    assert set(byproduct) == {False, True}
    assert not evaluation_label(bundle, raw, byproduct, frames).any()
    assert evaluation_label(bundle, raw, ~byproduct, frames).all()


def test_raw_signed_checks_include_both_random_preparation_signs():
    bundle = factory(3, 0.0, 2, 2)
    raw = bundle.circuit.compile_sampler(seed=121).sample(64)
    stage = bundle.stages[0]
    a, b = bundle.preparation_frames
    fa = a.resolve(raw[:, a.region.measurements.slice])
    fb = b.resolve(raw[:, b.region.measurements.slice])
    mx, mz = len(bundle.code.x_checks), len(bundle.code.z_checks)
    last_ax = fa.corrected_history[:, -(mx + mz):-mz]
    last_bz = fb.corrected_history[:, -mz:]
    assert last_ax.any() and last_bz.any()  # intrinsic preparation randomness
    np.testing.assert_array_equal(fa.z @ a.module.x_pcm.T % 2, last_ax)
    np.testing.assert_array_equal(fb.x @ b.module.z_pcm.T % 2, last_bz)
    assert not fa.x_signs.any() and not fb.z_signs.any()
    measured = raw[:, stage.measurement.measurements.slice]
    assert (measured @ a.module.z_pcm.T % 2).any()  # assuming raw signs zero is wrong
    assert not ((measured ^ fa.x ^ fb.x) @ a.module.z_pcm.T % 2).any()
    for check in stage.terminal_checks:
        assert not check.parity.evaluate(raw).any()
        assert len(check.parity.records) == len(bundle.code.z_checks[check.check_index]) + 2
    # The other CNOT sign rule is equally necessary: X_B becomes X_A * X_B.
    for flow in stage.output_checks:
        before = next(check for check in stage.input_checks
                      if (check.block, check.basis, check.check_index) == (flow.block, flow.basis, flow.check_index))
        assert len(flow.parity.records) == (2 if (flow.block, flow.basis) in {("A", "Z"), ("B", "X")} else 1)
        if len(flow.parity.records) == 1:
            assert before.parity == flow.parity


@pytest.mark.parametrize("p", [0.0, 0.002])
def test_strict_dem_and_every_signed_check_flow(p):
    bundle = factory(3, p, 2, 3)
    bundle.validate()
    dem = bundle.operational_circuit.detector_error_model(
        allow_gauge_detectors=False, approximate_disjoint_errors=False,
    )
    assert dem.num_detectors == len(bundle.detector_flows)
    assert dem.num_observables == 0
    for stage in bundle.stages:
        for flow in stage.input_checks + stage.output_checks:
            assert bundle.circuit[:flow.instruction_stop].has_flow(flow.as_stim_flow(bundle.circuit.num_qubits), unsigned=False)
    first = bundle.detector_flows[0]
    wrong_sign = replace(first, parity=RecordParity(first.parity.records, True))
    assert not bundle.circuit[:first.instruction_stop].has_flow(wrong_sign.as_stim_flow(bundle.circuit.num_qubits), unsigned=False)


def test_reversed_cnot_fails_signed_checks_and_strict_dem():
    bundle = factory(3, 0.0, 1, 1)
    coupling = bundle.stages[0].coupling.instructions
    reversed_gate = stim.Circuit()
    for instruction in bundle.circuit[coupling.slice]:
        if instruction.name == "CX":
            targets = instruction.targets_copy()
            swapped = [target for pair in zip(targets[1::2], targets[::2]) for target in pair]
            reversed_gate.append("CX", swapped)
        else:
            reversed_gate.append(instruction)
    circuit = bundle.circuit[:coupling.start] + reversed_gate + bundle.circuit[coupling.stop:]
    with pytest.raises(ValueError, match="signed CSS check"):
        replace(bundle, circuit=circuit).validate()
    with pytest.raises(ValueError, match="non-deterministic"):
        circuit[:bundle.oracle.instructions.start].detector_error_model(allow_gauge_detectors=False)


def test_ledger_depths_two_supports_and_noiseless_terminal_oracle():
    bundle = factory(3, 0.002, 2, 3)
    assert len(bundle.blocks) == 2 and bundle.circuit.num_qubits == 34
    assert len(set(bundle.blocks[0].qubits + bundle.blocks[1].qubits)) == 34
    assert tuple(record.index for record in bundle.ledger.records) == tuple(range(bundle.circuit.num_measurements))
    for block, rounds, frame in zip(bundle.blocks, (2, 3), bundle.preparation_frames):
        records = [record for record in bundle.ledger.records if record.operation == f"prepare_{block.name}"]
        assert len(records) == rounds * 8
        assert {record.se_round for record in records} == set(range(1, rounds + 1))
        assert {record.basis for record in records} == {"Z"}  # physical ancilla MR basis
        assert {record.check_basis for record in records} == {"X", "Z"}
        region = next(region for region in bundle.stages[0].preparations if region.name == f"prepare_{block.name}")
        fragment = bundle.circuit[region.instructions.slice]
        assert fragment == frame.module.circuit
        assert fragment[0].name == ("R" if block.name == "A" else "RX")
        assert fragment[1].name == ("X_ERROR" if block.name == "A" else "Z_ERROR")
        assert fragment[1].gate_args_copy() == [0.002]
        assert tuple(target.value for target in fragment[1].targets_copy()) == block.data_qubits
        resets = [instruction for instruction in fragment if instruction.name in {"R", "RX"}
                  and any(target.value in block.data_qubits for target in instruction.targets_copy())]
        assert len(resets) == 1
    gate = bundle.circuit[bundle.stages[0].coupling.instructions.slice]
    pairs = [tuple(target.value for target in instruction.targets_copy())
             for instruction in gate if instruction.name == "CX"]
    assert pairs == list(zip(bundle.blocks[1].data_qubits, bundle.blocks[0].data_qubits))
    depolarization = [instruction for instruction in gate if instruction.name == "DEPOLARIZE2"]
    assert len(depolarization) == 9
    assert all(instruction.gate_args_copy() == [0.002] for instruction in depolarization)
    measurement = bundle.circuit[bundle.stages[0].measurement.instructions.slice]
    assert measurement[0].name == "X_ERROR" and measurement[0].gate_args_copy() == [0.002]
    oracle = bundle.circuit[bundle.oracle.instructions.slice]
    assert len(oracle) == 1 and oracle[0].name == "M" and not oracle[0].gate_args_copy()
    assert tuple(target.value for target in oracle[0].targets_copy()) == bundle.blocks[1].data_qubits
    assert len(bundle.oracle_record_indices) == 9
    assert bundle.circuit.num_observables == 0
    assert all(record < bundle.oracle.measurements.start for flow in bundle.detector_flows for record in flow.parity.records)
    # No standalone deterministic check on the inherently random logical outcome.
    assert bundle.stages[0].raw_logical_outcome not in {flow.parity for flow in bundle.detector_flows}
    with pytest.raises(TypeError):
        bundle.metadata["T_tel"] = 2
    with pytest.raises(FrozenInstanceError):
        bundle.preparation.r_0 = 99


def test_oracle_is_rejected_as_decoder_input_and_cannot_change_operational_results():
    bundle = factory()
    raw = bundle.circuit.compile_sampler(seed=31).sample(32)
    operational = raw[:, :bundle.oracle.measurements.start]
    syndrome, byproduct, frames = online_boundary(bundle, operational)
    altered = raw.copy()
    altered[:, bundle.oracle.measurements.slice] ^= True
    changed = online_boundary(bundle, altered[:, :bundle.oracle.measurements.start])
    np.testing.assert_array_equal(changed[0], syndrome)
    np.testing.assert_array_equal(changed[1], byproduct)
    for original, new in zip(frames, changed[2]):
        np.testing.assert_array_equal(original.corrections, new.corrections)
    for plan in bundle.preparation_frames:
        with pytest.raises(ValueError, match="exactly the local"):
            plan.resolve(raw)
    bad = bundle.circuit.copy()
    bad.insert(bundle.oracle.instructions.start, stim.Circuit("X_ERROR(0.1) 17"))
    with pytest.raises(ValueError, match="noiseless terminal"):
        replace(bundle, circuit=bad).validate()


@pytest.mark.parametrize("basis", ["Z", "X"])
def test_preparation_boundary_maps_match_legacy_pauli_propagation(basis):
    bundle = factory()
    for plan in bundle.preparation_frames:
        readout = stim.Circuit()
        readout.append("M" if basis == "Z" else "MX", list(plan.block.data_qubits))
        plan.module.generate_measurement_flip_map(stim.Circuit(), readout, 0)
        actual = plan.module.correction_to_measurement_flips[:, -9:].toarray() % 2
        expected = (plan.x_map if basis == "Z" else plan.z_map).toarray()
        np.testing.assert_array_equal(actual, expected)


def test_preparation_resolution_preserves_legacy_and_reuses_decoders(monkeypatch):
    bundle = factory()
    raw = bundle.circuit.compile_sampler(seed=101).sample(64)
    expected = [plan.module.c_func(raw[:, plan.region.measurements.slice]) for plan in bundle.preparation_frames]

    def no_new_graph(*args, **kwargs):
        raise AssertionError("Matching constructed during frame resolution")

    monkeypatch.setattr(pymatching.Matching, "from_check_matrix", no_new_graph)
    for plan, legacy in zip(bundle.preparation_frames, expected):
        local = raw[:, plan.region.measurements.slice]
        whole = plan.resolve(local)
        np.testing.assert_array_equal(whole.corrections, legacy)
        left, right = plan.resolve(local[:17]), plan.resolve(local[17:])
        np.testing.assert_array_equal(whole.x, np.vstack((left.x, right.x)))
        np.testing.assert_array_equal(whole.z, np.vstack((left.z, right.z)))
        assert whole.x.dtype == whole.z.dtype == np.bool_
        assert not whole.x_signs.any() and not whole.z_signs.any()


def test_preparation_rejects_unresolved_check_signs(monkeypatch):
    from hex_qec.decoders import DecodeResult

    bundle = factory(3, 0.0, 2, 2)
    plan = bundle.preparation_frames[0]
    raw = bundle.circuit.compile_sampler(seed=19).sample(32)

    class NoRepair:
        def decode_batch(self, syndromes):
            return DecodeResult(np.zeros((len(syndromes), 9), dtype=np.uint8))

    monkeypatch.setattr(plan.module, "x_decoder", NoRepair())
    with pytest.raises(ValueError, match="resolve all stabilizer signs"):
        plan.resolve(raw[:, plan.region.measurements.slice])


def inject(bundle, offset, paulis):
    return (bundle.circuit[:offset].without_noise() + stim.Circuit(paulis)
            + bundle.circuit[offset:].without_noise())


@pytest.mark.parametrize("boundary", ["reset_A", "reset_B", "se_readout_A", "se_readout_B",
                                     "cnot_A", "cnot_B", "cnot_correlated", "teleport_readout"])
def test_single_fault_boundaries_have_consistent_frames_and_terminal_label(boundary):
    bundle = factory()
    a, b = bundle.blocks
    stage = bundle.stages[0]
    if boundary.startswith("reset"):
        block = a if boundary == "reset_A" else b
        region = stage.preparations[0 if block == a else 1]
        offset = region.instructions.start + 1
        pauli = ("X" if block == a else "Z") + f" {block.data_qubits[0]}"
    elif boundary.startswith("se_readout"):
        block = a if boundary == "se_readout_A" else b
        region = stage.preparations[0 if block == a else 1]
        offset = max(index for index in range(region.instructions.start, region.instructions.stop)
                     if bundle.circuit[index].name == "MR" and
                     bundle.circuit[index].targets_copy()[0].value in block.z_ancillas)
        pauli = f"X {block.z_ancillas[0]}"
    elif boundary == "cnot_correlated":
        offset = stage.coupling.instructions.stop
        pauli = f"X {a.data_qubits[0]} {b.data_qubits[0]}"
    elif boundary.startswith("cnot"):
        offset = stage.coupling.instructions.stop
        pauli = f"X {(a if boundary == 'cnot_A' else b).data_qubits[0]}"
    else:
        offset = stage.measurement.instructions.start + 1
        pauli = f"X {a.data_qubits[0]}"
    raw = inject(bundle, offset, pauli).compile_sampler(seed=77).sample(32)
    syndrome, byproduct, frames = online_boundary(bundle, raw[:, :bundle.oracle.measurements.start])
    assert syndrome.shape == (32, 4)
    assert not evaluation_label(bundle, raw, byproduct, frames).any()
    if boundary in {"cnot_A", "teleport_readout"}:
        assert syndrome.any()


def test_terminal_logical_fault_changes_only_evaluation_label():
    bundle = factory()
    ideal = bundle.circuit.without_noise()
    raw = ideal.compile_sampler(seed=54).sample(32)
    pauli = "X " + " ".join(str(bundle.blocks[1].data_qubits[q]) for q in bundle.code.logical_x)
    faulty = inject(bundle, bundle.oracle.instructions.start, pauli).compile_sampler(seed=54).sample(32)
    np.testing.assert_array_equal(raw[:, :bundle.oracle.measurements.start], faulty[:, :bundle.oracle.measurements.start])
    syndrome, byproduct, frames = online_boundary(bundle, raw[:, :bundle.oracle.measurements.start])
    assert not syndrome.any()
    assert not evaluation_label(bundle, raw, byproduct, frames).any()
    assert evaluation_label(bundle, faulty, byproduct, frames).all()


@pytest.mark.parametrize("depth", [0, -1, True, 1.5])
def test_invalid_preparation_depths_rejected(depth):
    with pytest.raises(ValueError, match="positive integer"):
        PreparationPlan(depth, 1)
    with pytest.raises(ValueError, match="positive integer"):
        PreparationPlan(1, depth)


@pytest.mark.parametrize("distance", [1, 2, 4, True, 3.5, 999])
def test_unsupported_surface_codes_rejected(distance):
    with pytest.raises(ValueError, match="surface distance"):
        RotatedSurfaceCodeAdapter(distance)


@pytest.mark.parametrize("p", [-0.1, 0.51, float("nan"), float("inf"), True, None, "0.1"])
def test_invalid_noise_rejected(p):
    with pytest.raises(ValueError, match="physical_error"):
        FactoryCircuitBuilder(RotatedSurfaceCodeAdapter(3), PreparationPlan(1, 1), p)


def test_signed_parity_xor_normalization_and_shapes():
    parity = RecordParity((2, 0, 2), True) ^ RecordParity((1,), True)
    assert parity == RecordParity((0, 1))
    np.testing.assert_array_equal(parity.evaluate(np.array([[0, 1], [1, 1]])), [True, False])
    with pytest.raises(ValueError, match="record batch"):
        parity.evaluate(np.zeros((1, 1)))
    with pytest.raises(ValueError, match="nonnegative"):
        RecordParity((-1,))
    plan = factory().preparation_frames[0]
    with pytest.raises(ValueError, match="binary"):
        plan.resolve(np.full((1, plan.module.num_measurements), 2))


def test_generic_contract_shapes_and_disjoint_supports():
    with pytest.raises(ValueError, match="within the data block"):
        CodeSpec("custom", 3, ((3,),), ((0,),), (1,), (2,))
    with pytest.raises(ValueError, match="disjoint"):
        BlockSupport("A", (0, 1), (1,), (2,))
    with pytest.raises(ValueError, match="repeat"):
        BlockSupport("A", (0, 0), (1,), (2,))
    with pytest.raises(ValueError, match="range"):
        IndexRange(2, 1)

    class OverlappingAdapter(RotatedSurfaceCodeAdapter):
        def blocks(self):
            a, _ = super().blocks()
            return a, replace(a, name="B")

    with pytest.raises(ValueError, match="disjoint"):
        FactoryCircuitBuilder(OverlappingAdapter(3), PreparationPlan(1, 1)).build()

    class WrongSizeAdapter(RotatedSurfaceCodeAdapter):
        def blocks(self):
            a, b = super().blocks()
            return replace(a, data_qubits=a.data_qubits[:-1]), b

    with pytest.raises(ValueError, match="dimensions"):
        FactoryCircuitBuilder(WrongSizeAdapter(3), PreparationPlan(1, 1)).build()
