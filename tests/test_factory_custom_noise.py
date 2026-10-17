"""HEX-N2: factory-only channels, preparation maps, physical faults and caches.

New physical batches have at most seven d=3 shots. Controlled fault lanes
and DEM enumeration are setup/model checks, not Monte Carlo experiments.
"""

from dataclasses import fields, replace
from functools import lru_cache
import hashlib
import json

import numpy as np
import pymatching
import pytest
import stim
from scipy.sparse import csc_matrix

from hex_qec.circuit_generation import FactoryNoiseModel, IdleWindow, PlusPreparationIdle
from hex_qec.circuit_generation.factory_noise import idle_depolarizing_probability
from hex_qec.circuit_generation.factory_surface import _custom_preparation_circuit
from hex_qec.circuit_generation.circuit_generation import stabilizer_measurement_circuit_both_detectors
from hex_qec.decoders import ProjectedDEMBuilder, UnsupportedProjectedModel
from hex_qec.modularisation import PreparationPlan
from hex_qec.protocols import FactoryCircuitBuilder, RotatedSurfaceCodeAdapter
from hex_qec.simulation import CompiledFactory, FactoryBatchDecoder, FactoryOperationalBatch
from hex_qec.simulation import factory as execution


CUSTOM = FactoryNoiseModel(one_qubit=.5, two_qubit=2, measurement=3, reset=4,
    post_cnot_control=IdleWindow(.75, 2),
    during_plus_preparation=PlusPreparationIdle(True, .25, 3))
ZERO = FactoryNoiseModel(one_qubit=0, two_qubit=0, idle=0, measurement=0, reset=0,
    post_cnot_control=IdleWindow(2), during_plus_preparation=PlusPreparationIdle(True))


@lru_cache(maxsize=None)
def bundle(model=CUSTOM, T=2, p=.001, r_plus=2):
    return FactoryCircuitBuilder(RotatedSurfaceCodeAdapter(3), PreparationPlan(2,r_plus),
                                 p, T_tel=T, noise_model=model).build()


def targets(instruction):
    return tuple(t.value for t in instruction.targets_copy())


def assert_operational_equal(a, b):
    for field in fields(FactoryOperationalBatch):
        np.testing.assert_array_equal(getattr(a, field.name), getattr(b, field.name))


@pytest.mark.parametrize("T,circuit_hash,raw_hash,frame_x,frame_z,gap_hash", [
    (1, "515b25ec9a9882c7e65238c828eddcf2cc6512ddeaf0338427a9b02bb64c37f1",
     "e67e8c0978484d17cf8271fa89572e3e1af913310a235572b4c322adf3fa9552",
     "b6556835053845620bad462bfeebebf04dfc515e2971088af7380ba30ac52885",
     "e4deaf7e49a954e4b122ea62002aefbd1351120de9d0a0a2e93edb9801b3ff44",
     "489d5314869b589597b61bca6f19a20445d61783924713ff476a05ad2b64024b"),
    (2, "ab28155b024ac9882bd82055238f30a02f0882a9a4bd43f92168f2d8853f4f07",
     "3eaa6ca97c6c7ffb35caccedcbb750695f0ba1def5f34a026fdc44b16b7ba646",
     "793879267a083a95a863be2123bf7f0933ae33532b6ea2c590413c897ed83eb1",
     "a59786dcd124d0970aecc9bbdd2c460760f24ac7d0e1cb192c9a6677e9f1cc48",
     "0b53a30f71a745f3034eb7b6f24ffd4abd7d3da3b908d439caf6a83c3a891f51"),
])
def test_legacy_h5_golden_circuit_records_frames_and_gap(T, circuit_hash, raw_hash, frame_x, frame_z, gap_hash):
    b = bundle(None,T)
    assert b.metadata["noise"] == "hex_uniform"
    assert "noise_model_sha256" not in b.metadata
    assert b.metadata["circuit_sha256"] == circuit_hash
    explicit = FactoryCircuitBuilder(RotatedSurfaceCodeAdapter(3), PreparationPlan(2,2),
                                      .001,T_tel=T,noise_model=None).build()
    assert explicit.circuit == b.circuit
    f = CompiledFactory.from_bundle(b,seed=971)
    raw = f.sample_measurements(7)
    r = f.decode(raw)
    if (stim.__version__,pymatching.__version__) == ("1.16.0","2.4.0"):
        for array, digest in ((raw,raw_hash), (r.output_frame_x,frame_x),
                              (r.output_frame_z,frame_z), (r.gaps,gap_hash)):
            assert hashlib.sha256(array.tobytes()).hexdigest() == digest
        assert not r.logical_error.any()
    other = CompiledFactory.from_bundle(explicit,seed=971)
    np.testing.assert_array_equal(other.sample_measurements(7),raw)
    assert_operational_equal(other.decode(raw),r)
    assert other.cache_key == f.cache_key


def test_legacy_h5_noisy_golden_includes_actual_error_and_every_result_array():
    # Produced independently from git archive 4278d29, not current source.
    b=bundle(None,T=2,p=.04)
    assert b.metadata["circuit_sha256"] == "4a9a29fe54ae4f66379510ff1906850d9bfeabda6fa439d4504182de9ec5b4c8"
    f=CompiledFactory.from_bundle(b,seed=971)
    raw=f.sample_measurements(7)
    r=f.decode(raw)
    if (stim.__version__,pymatching.__version__) == ("1.16.0","2.4.0"):
        assert hashlib.sha256(raw.tobytes()).hexdigest() == "46efd76596428e4a062afaca40a7fdf5432e7a2d3e4c127a5ba4f834a59362d4"
        assert r.logical_error.sum() == 1
        arrays=b"".join(v.tobytes() for v in vars(r).values() if isinstance(v,np.ndarray))
        assert hashlib.sha256(arrays).hexdigest() == "95e8bb53d7dd798c68f4fe41ae71541732da5eda9671bd78ec4f25aba40dfcf4"


@pytest.mark.parametrize("T", [1,2,3])
def test_zero_custom_operations_remain_logical_zero(T):
    b = bundle(ZERO,T)
    assert all(not stim.gate_data(i.name).is_noisy_gate or i.gate_args_copy() == [0.]
               or stim.gate_data(i.name).produces_measurements for i in b.circuit)
    f = CompiledFactory.from_bundle(b,seed=1729)
    r = f.sample(7)
    assert not r.logical_error.any() and not r.corrected_syndromes.any()
    assert r.frame_resolved.all()
    np.testing.assert_array_equal(r.gaps,3)
    assert all(s.storage_idle is None and s.post_cnot_control_idle is None for s in b.stages)


@pytest.mark.parametrize("basis", ["X","Z"])
def test_custom_preparation_preserves_native_order_and_attaches_exact_channels(basis):
    adapter = RotatedSurfaceCodeAdapter(3)
    p = .01
    actual = _custom_preparation_circuit(adapter.matrices,basis,2,p,CUSTOM)
    # Independent expected expansion retains every original CX/noise boundary;
    # stripping noise before expansion would incorrectly delay two-qubit errors.
    native = stabilizer_measurement_circuit_both_detectors(adapter.matrices,basis.lower(),2,0,surface_code=True)
    expected = stim.Circuit()
    for i in native:
        name, support = i.name, i.targets_copy()
        if name in {"X_ERROR","Z_ERROR","DEPOLARIZE2"}:
            continue
        if name == "MR":
            expected.append("X_ERROR",support,p*CUSTOM.measurement)
        expected.append(i)
        if name in {"R","RX","MR"}:
            expected.append("Z_ERROR" if name == "RX" else "X_ERROR",support,p*CUSTOM.reset)
        elif name == "H":
            expected.append("DEPOLARIZE1",support,p*CUSTOM.one_qubit)
        elif name in {"CX","CZ"}:
            expected.append("DEPOLARIZE2",support,p*CUSTOM.two_qubit)
    assert actual == expected
    assert actual.without_noise() == native.without_noise()
    assert sum(i.name == "DEPOLARIZE2" for i in actual) == 48
    # Readout after the terminal H is in physical Z, hence X_ERROR before MR.
    for index,i in enumerate(actual):
        if i.name == "MR":
            assert actual[index-1].name == "X_ERROR"
            assert actual[index-1].gate_args_copy() == [p*CUSTOM.measurement]
            assert actual[index+1].name == "X_ERROR"
            assert actual[index+1].gate_args_copy() == [p*CUSTOM.reset]


def test_post_cnot_control_and_storage_regions_alternate_exact_supports():
    b = bundle()
    assert b.circuit.num_qubits == 34 and len(b.blocks) == 2
    for j,s in enumerate(b.stages):
        target,control = b.blocks[j%2], b.blocks[(j+1)%2]
        assert (s.consumed_block,s.surviving_block) == (target.name,control.name)
        region = s.post_cnot_control_idle
        assert region.instructions.stop == s.coupling.instructions.stop
        assert region.instructions.stop == s.measurement.instructions.start
        channel = b.circuit[region.instructions.slice]
        assert len(channel) == 1 and channel[0].name == "DEPOLARIZE1"
        assert targets(channel[0]) == control.data_qubits
        assert channel[0].gate_args_copy()[0] == idle_depolarizing_probability(.001,1,.75,2)
        gate = b.circuit[s.coupling.instructions.start:region.instructions.start]
        assert sum(i.name == "CX" for i in gate) == 9
        assert all(i.gate_args_copy() == [.002] for i in gate if i.name == "DEPOLARIZE2")
        readout = b.circuit[s.measurement.instructions.slice]
        assert readout[0].name == "X_ERROR" and readout[0].gate_args_copy() == [.003]
        assert targets(readout[0]) == target.data_qubits
        if j == 0:
            assert s.storage_idle is None
        else:
            region = s.storage_idle
            assert region.instructions.start == s.preparations[-1].instructions.stop
            assert region.instructions.stop == s.coupling.instructions.start
            channel = b.circuit[region.instructions.slice]
            assert len(channel) == 1 and targets(channel[0]) == target.data_qubits
            assert channel[0].gate_args_copy()[0] == idle_depolarizing_probability(.001,1,2*.25,3)
    assert bundle(T=1).stages[0].storage_idle is None
    assert b.metadata["initial_preparation_schedule"] == "parallel_no_storage_idle"
    assert "excludes_prep_storage" in b.metadata["module_local_prior_scope"]
    oracle = b.circuit[b.oracle.instructions.slice]
    assert len(oracle) == 1 and oracle[0].name == "M" and not oracle[0].gate_args_copy()


@pytest.mark.parametrize("duration", [0,.5,2])
def test_idle_duration_resolves_without_generic_data_idles(duration):
    model = replace(CUSTOM,post_cnot_control=IdleWindow(duration,2))
    b = bundle(model)
    data = set(b.blocks[0].data_qubits+b.blocks[1].data_qubits)
    data_channels = [i for i in b.circuit if i.name == "DEPOLARIZE1" and set(targets(i)) <= data]
    assert len(data_channels) == (3 if duration else 1)  # two post windows plus one storage
    for s in b.stages:
        assert (s.post_cnot_control_idle is not None) == bool(duration)
        if duration:
            i=b.circuit[s.post_cnot_control_idle.instructions.start]
            assert i.gate_args_copy()[0] == idle_depolarizing_probability(.001,1,duration,2)


def test_storage_duration_uses_resolved_round_count_and_can_be_disabled():
    b = bundle(r_plus=3)
    i=b.circuit[b.stages[1].storage_idle.instructions.start]
    assert i.gate_args_copy()[0] == idle_depolarizing_probability(.001,1,3*.25,3)
    b = bundle(replace(CUSTOM,during_plus_preparation=PlusPreparationIdle(False,.25,3)))
    assert all(s.storage_idle is None for s in b.stages)


def test_preparation_priors_and_maps_are_rebuilt_from_actual_custom_circuit():
    b,uniform = bundle(),bundle(None)
    raw=b.circuit.compile_sampler(seed=91).sample(7)
    changed_prior=False
    for plan,old in zip(b.preparation_frames,uniform.preparation_frames):
        m=plan.module
        assert m.circuit == b.circuit[plan.region.instructions.slice]
        assert m.circuit != old.module.circuit
        for basis in ("x","z"):
            circuit=getattr(m,f"{basis}_det_circuit")
            dem=circuit.detector_error_model(allow_gauge_detectors=False,approximate_disjoint_errors=False)
            assert dem == getattr(m,f"{basis}_dem")
            changed_prior |= not np.array_equal(getattr(m,f"{basis}_dem_priors"),getattr(old.module,f"{basis}_dem_priors"))
            h=getattr(m,f"{basis}_dem_check_matrix")
            local=getattr(m,f"{basis}_dem_correction_to_local_detector_flips")
            assert (csc_matrix(h.T) != local).nnz == 0
        records=raw[:,plan.region.measurements.slice]
        frame=plan.resolve(records)
        np.testing.assert_array_equal(frame.corrections,m.c_func(records))
        assert not frame.x_signs.any() and not frame.z_signs.any()
        # Independently use the original global Pauli propagation machinery in
        # both readout bases to verify final-frame maps, including joint faults.
        for gate,mapping in (("M",plan.x_map),("MX",plan.z_map)):
            readout=stim.Circuit()
            readout.append(gate,list(plan.block.data_qubits))
            m.generate_measurement_flip_map(stim.Circuit(),readout,0)
            np.testing.assert_array_equal(m.correction_to_measurement_flips[:,-9:].toarray()%2,mapping.toarray())
    assert changed_prior


def test_joint_pauli_preparation_representatives_are_one_fault_lane():
    # A sparse physical model forces some representatives to remain genuine
    # two-body faults. They must not be discarded or independently split.
    model = FactoryNoiseModel(one_qubit=0,measurement=0,reset=0)
    b=bundle(model)
    products=[]
    for plan in b.preparation_frames:
        for basis in ("x","z"):
            products.extend(p for p,_ in getattr(plan.module,f"{basis}_correction_array") if "*" in p)
        records=b.circuit.without_noise().compile_sampler(seed=91).sample(3)
        frame=plan.resolve(records[:,plan.region.measurements.slice])
        assert not frame.x_signs.any() and not frame.z_signs.any()
    assert products  # this physical model exercises joint representatives
    for plan in b.preparation_frames:
        m=plan.module
        assert m.allow_pauli_products
        for basis in ("x","z"):
            assert (csc_matrix(getattr(m,f"{basis}_dem_check_matrix").T)
                    != getattr(m,f"{basis}_dem_correction_to_local_detector_flips")).nnz == 0
        for gate,mapping in (("M",plan.x_map),("MX",plan.z_map)):
            readout=stim.Circuit()
            readout.append(gate,list(plan.block.data_qubits))
            m.generate_measurement_flip_map(stim.Circuit(),readout,0)
            np.testing.assert_array_equal(m.correction_to_measurement_flips[:,-9:].toarray()%2,mapping.toarray())


def test_strict_signed_flows_and_dem_with_both_idle_windows():
    b=bundle()
    b.validate()
    dem=b.operational_circuit.detector_error_model(allow_gauge_detectors=False,approximate_disjoint_errors=False)
    assert dem.num_detectors == len(b.detector_flows) and dem.num_observables == 0
    for s in b.stages:
        for flow in s.input_checks+s.output_checks:
            assert b.circuit[:flow.instruction_stop].has_flow(flow.as_stim_flow(b.circuit.num_qubits),unsigned=False)
    bad=replace(b.stages[1],storage_idle=replace(b.stages[1].storage_idle,instructions=b.stages[1].post_cnot_control_idle.instructions))
    with pytest.raises(ValueError,match="idle region"):
        replace(b,stages=(b.stages[0],bad)).validate()


def test_surviving_control_logical_x_changes_label_with_identical_destructive_record():
    b=bundle(T=1)
    stop=b.stages[0].post_cnot_control_idle.instructions.start
    sim=stim.FlipSimulator(batch_size=7,num_qubits=b.circuit.num_qubits,seed=341)
    sim.do(b.circuit[:stop].without_noise())
    altered=sim.copy(copy_rng=True)
    support=[b.blocks[1].data_qubits[q] for q in b.code.logical_x]
    fault=stim.Circuit()
    fault.append("X_ERROR",support,1)
    altered.do(fault)
    suffix=b.circuit[stop:].without_noise()
    sim.do(suffix)
    altered.do(suffix)
    ref=b.circuit.without_noise().reference_sample()[None,:]
    raw=ref^sim.get_measurement_flips().T
    faulty=ref^altered.get_measurement_flips().T
    np.testing.assert_array_equal(raw[:,:b.oracle.measurements.start],faulty[:,:b.oracle.measurements.start])
    f=CompiledFactory.from_bundle(b,seed=41)
    before,after=f.decode(raw),f.decode(faulty)
    assert_operational_equal(before,after)
    np.testing.assert_array_equal(before.gaps,after.gaps)
    assert not before.logical_error.any() and after.logical_error.all()


@lru_cache(maxsize=1)
def informed():
    b=bundle()
    f=CompiledFactory.from_bundle(b,seed=441,create_codecapacity_dem=True)
    return f,f.sample_measurements(7)


def test_both_prior_modes_share_physical_circuit_and_oracle_isolation():
    b=bundle()
    f,raw=informed()
    hamming=CompiledFactory.from_bundle(b,seed=441)
    assert f.circuit == hamming.circuit
    np.testing.assert_array_equal(raw,hamming.sample_measurements(7))
    assert f.decode(raw).gap_units == "log_weight"
    assert hamming.decode(raw).gap_units == "hamming_weight"
    altered=raw.copy()
    altered[:,b.oracle.measurements.slice]^=True
    for decoder in (f,hamming):
        before,after=decoder.decode(raw),decoder.decode(altered)
        assert_operational_equal(before,after)
        np.testing.assert_array_equal(before.gaps,after.gaps)
        assert np.isfinite(before.gaps).all() and (before.gaps>=0).all()


def test_true_prior_retains_custom_mechanisms_and_local_boundary_distinction():
    f,_=informed()
    b=bundle()
    first,second=f.projected_priors
    for prior in (first,second):
        assert prior.h3_lift_valid
        assert "noiseless_reference" in prior.approximation
        assert all(f.mechanism.instruction_index < b.oracle.instructions.start for f in prior.faults)
    post=b.stages[0].post_cnot_control_idle.instructions.start
    assert any(f.mechanism.instruction_index==post and f.mechanism.noise_gate=="DEPOLARIZE1" for f in first.faults)
    # Native H5 full-prefix projection also includes inter-stage storage;
    # a local body sliced at coupling begins *after* this region.
    storage=b.stages[1].storage_idle.instructions.start
    assert storage < b.stages[1].coupling.instructions.start
    assert not any(f.mechanism.instruction_index==storage for f in first.faults)
    assert any(f.mechanism.instruction_index==storage and f.mechanism.origin_region=="during_plus_preparation" for f in second.faults)


@pytest.mark.parametrize("field", ["one_qubit","two_qubit","idle","measurement","reset"])
def test_noise_changes_physical_and_decoder_cache_identities(field):
    first=bundle()
    second=bundle(replace(CUSTOM,**{field:getattr(CUSTOM,field)*1.25}))
    assert first.metadata["circuit_sha256"] != second.metadata["circuit_sha256"]
    assert first.metadata["physical_noise_sha256"] != second.metadata["physical_noise_sha256"]
    a=CompiledFactory.from_bundle(first,seed=45).cache_key
    b=CompiledFactory.from_bundle(second,seed=45).cache_key
    assert a != b and a.noise_model_sha256 != b.noise_model_sha256
    assert json.loads(first.metadata["noise_model_json"]) == CUSTOM.as_dict()


def test_zero_p_parameter_identity_and_window_cache_changes():
    a,b=bundle(CUSTOM,p=0),bundle(replace(CUSTOM,post_cnot_control=IdleWindow(2,2)),p=0)
    assert a.circuit == b.circuit
    assert CompiledFactory.from_bundle(a).cache_key != CompiledFactory.from_bundle(b).cache_key
    for model in (replace(CUSTOM,post_cnot_control=IdleWindow(2,2)),
                  replace(CUSTOM,during_plus_preparation=PlusPreparationIdle(True,.5,3))):
        assert bundle(model).metadata["circuit_sha256"] != bundle().metadata["circuit_sha256"]
        assert ProjectedDEMBuilder(bundle(model))._configuration_hash != ProjectedDEMBuilder(bundle())._configuration_hash


def test_compilation_and_native_maps_are_cached_outside_batches(monkeypatch):
    b=bundle(CUSTOM,T=3)
    assert b.preparation_frames[1].module is b.preparation_frames[3].module
    assert b.preparation_frames[1].x_map is b.preparation_frames[3].x_map
    f=CompiledFactory.from_bundle(b,seed=95)
    raw=f.sample_measurements(7)
    expected=f.decode(raw)
    def forbidden(*args,**kwargs):
        raise AssertionError("native setup called during batch decoding")
    monkeypatch.setattr(pymatching.Matching,"from_check_matrix",forbidden)
    monkeypatch.setattr(execution,"_compile_sampler",forbidden)
    monkeypatch.setattr(RotatedSurfaceCodeAdapter,"prepare",forbidden)
    for part in (raw,raw[:3],raw[3:]):
        result=f.decode(part)
        assert np.isfinite(result.gaps).all()
    assert_operational_equal(expected,f.decode(raw))
    f.sample(3)


@pytest.mark.parametrize("model", ["hex_uniform",{},False])
def test_bad_noise_object_rejected(model):
    with pytest.raises(ValueError,match="noise_model"):
        FactoryCircuitBuilder(RotatedSurfaceCodeAdapter(3),PreparationPlan(1,1),noise_model=model)


@pytest.mark.parametrize("model", [FactoryNoiseModel(two_qubit=2000),
    FactoryNoiseModel(post_cnot_control=IdleWindow(.5,1000)),
    FactoryNoiseModel(idle=2000,post_cnot_control=IdleWindow(0))])
def test_invalid_resolved_probabilities_fail_before_preparing(model,monkeypatch):
    def forbidden(*args,**kwargs):
        raise AssertionError("preparation began before noise validation")
    monkeypatch.setattr(RotatedSurfaceCodeAdapter,"prepare",forbidden)
    with pytest.raises(ValueError):
        FactoryCircuitBuilder(RotatedSurfaceCodeAdapter(3),PreparationPlan(1,1),.001,noise_model=model)


def test_custom_zero_noise_true_and_overmixing_prior_reject_without_fallback():
    with pytest.raises(UnsupportedProjectedModel,match="Hamming"):
        CompiledFactory.from_bundle(bundle(ZERO),create_codecapacity_dem=True)
    model=FactoryNoiseModel(idle=800,post_cnot_control=IdleWindow(1))
    with pytest.raises(ValueError,match="over-mixing"):
        CompiledFactory.from_bundle(bundle(model),create_codecapacity_dem=True)
