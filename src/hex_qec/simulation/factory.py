"""Static sampling and causal batched frame processing for two-block factories.

Only the terminal evaluation method can read oracle records. Operational
processing uses local preparation converters and stage readout slices, never
a full-circuit measurement-to-detector converter or physical fault truth.
"""

from dataclasses import dataclass, field, replace
import hashlib
from numbers import Integral
from types import MappingProxyType

import numpy as np
import pymatching
import stim

from hex_qec.modularisation.factory import FACTORY_FRAME_CONVENTION, _positive_integer
from hex_qec.decoders.factory_surface import SurfaceFactoryReadout
from hex_qec.protocols.logical_zero_factory import FactoryCircuitBundle


@dataclass(frozen=True)
class FactoryCacheKey:
    """Complete worker-local compilation identity, including sampler seed."""

    code_sha256: str
    distance: int | None
    physical_error: float
    noise: str
    r_0: int
    r_plus: int
    T_tel: int
    circuit_sha256: str
    frame_convention: str
    preparation_prior: str
    terminal_label_convention: str
    seed: int | None
    decoder_policy: str = "factory_causal_hamming_v1"
    stim_version: str = stim.__version__
    pymatching_version: str = pymatching.__version__
    gap_policy: str = "surface_two_boundary_hamming_v1"
    create_codecapacity_dem: bool = False
    projected_prior_sha256: tuple[str, ...] = ()
    noise_model_sha256: str = ""


@dataclass(frozen=True)
class FactoryOperationalBatch:
    """Estimated operational records; all arrays have shots as the first axis.

    Corrected syndromes: (shots,T,m_z), before configured online recovery.
    Raw/corrected byproducts and frame_resolved: (shots,T).
    Output frames: (shots,T,n), after the stage's inferred logical X update.
    frame_resolved reports decoder consistency, not physical state truth.
    """

    shot_id: np.ndarray
    stage_ids: tuple[int, ...]
    corrected_syndromes: np.ndarray
    raw_logical_byproducts: np.ndarray
    logical_byproducts: np.ndarray
    frame_resolved: np.ndarray
    output_frame_x: np.ndarray
    output_frame_z: np.ndarray


@dataclass(frozen=True)
class FactoryBatchResult(FactoryOperationalBatch):
    """Operational data plus one evaluation-only terminal logical-error label.

    logical_error is bool (shots,). H3 populates float64 gaps (shots,T) in
    gap_units. No threshold or postselection is evaluated. Defaults retain
    compatibility with callers constructing the former H2 result directly.
    """

    logical_error: np.ndarray
    gaps: np.ndarray | None = None
    gap_units: str = "hamming_weight"


def _validate_shot_ids(start: int, shots: int) -> None:
    if (isinstance(start, bool) or not isinstance(start, Integral) or int(start) < 0
            or int(start) + int(shots) > 2**64):
        raise ValueError("shot IDs must fit uint64 without overflow")


def _measurement_batch(measurements: np.ndarray, width: int) -> np.ndarray:
    batch = np.asarray(measurements)
    if batch.ndim != 2 or batch.shape[1] != width or batch.shape[0] < 1:
        raise ValueError(f"expected a nonempty measurement batch of width {width}")
    if not np.all((batch == 0) | (batch == 1)):
        raise ValueError("measurement records must be binary")
    return batch.astype(bool, copy=False)


class FactoryBatchDecoder:
    """Worker-local, synchronous offline decoder for an already-built factory.

    Construction caches spatial matching objects and local preparation plans.
    Decode methods allocate shot arrays only and never construct circuits,
    samplers, matching graphs, or correction maps. They do not mutate inputs.
    """

    def __init__(self, bundle: FactoryCircuitBundle, *, create_codecapacity_dem: bool = False):
        if not isinstance(create_codecapacity_dem, bool):
            raise ValueError("create_codecapacity_dem must be bool")
        bundle.validate()
        if bundle.metadata["frame_convention"] != FACTORY_FRAME_CONVENTION:
            raise ValueError("unsupported factory frame convention")
        self._stages = bundle.stages
        self._oracle = bundle.oracle.measurements
        self._width = bundle.circuit.num_measurements
        self._plans = MappingProxyType({plan.region.measurements.start: plan
                                       for plan in bundle.preparation_frames})
        if len(self._plans) != len(self._stages) + 1:
            raise ValueError("factory must have one zero prep and one plus prep per stage")
        self._initial = self._plans[self._stages[0].preparations[0].measurements.start]
        self._readout = SurfaceFactoryReadout(bundle.code, self._initial.module.z_pcm)
        self._projected_gaps = []
        priors = []
        if create_codecapacity_dem:
            from hex_qec.decoders.codecapacity_dem import EffectivePriorBuilder, ProjectedDEMBuilder
            source = ProjectedDEMBuilder(bundle)
            for stage in self._stages:
                context = source.context(
                    stage.index, interpret=lambda records, j=stage.index: self.decode_stage_input(records, j),
                    prefix_policy_identity=tuple((p.model_sha256, p.configuration_sha256) for p in priors),
                )
                service = EffectivePriorBuilder(context)
                prior = service.build()
                self._projected_gaps.append(service.compile_gap())
                priors.append(prior)
        self._projected_gaps = tuple(self._projected_gaps)
        self.projected_priors = tuple(priors)

    @property
    def gap_units(self) -> str:
        return "log_weight" if self._projected_gaps else self._readout.gap_units

    def decode_operational(self, measurements: np.ndarray, *,
                           shot_id_start: int = 0) -> FactoryOperationalBatch:
        """Decode exactly the operational prefix, excluding the oracle suffix."""
        return self._decode_operational(measurements, shot_id_start=shot_id_start)[0]

    def _decode_operational(self, measurements: np.ndarray, *,
                            shot_id_start: int, stage_count: int | None = None,
                            score_gaps: bool = True) -> tuple[FactoryOperationalBatch, np.ndarray, np.ndarray]:
        active = self._stages if stage_count is None else self._stages[:stage_count]
        width = self._oracle.start if stage_count is None else active[-1].measurement.measurements.stop
        batch = _measurement_batch(measurements, width)
        shots, n, stages = len(batch), self._readout.num_data_qubits, len(active)
        _validate_shot_ids(shot_id_start, shots)
        initial = self._initial.resolve(batch[:, self._initial.region.measurements.slice])
        memory_x, memory_z = initial.x, initial.z
        syndromes = np.empty((shots, stages, self._readout.num_z_checks), dtype=bool)
        raw_byproducts = np.empty((shots, stages), dtype=bool)
        byproducts = np.empty((shots, stages), dtype=bool)
        resolved = np.empty((shots, stages), dtype=bool)
        frame_x = np.empty((shots, stages, n), dtype=bool)
        frame_z = np.empty_like(frame_x)
        gaps = (np.empty((shots, stages), dtype=np.float64) if score_gaps
                else np.zeros((shots, stages), dtype=np.float64))

        for index, stage in enumerate(active):
            plus_region = stage.preparations[-1]
            plus = self._plans[plus_region.measurements.start].resolve(batch[:, plus_region.measurements.slice])
            # A reset discards that physical support's old X/Z frame. The
            # fresh plus frame comes only from its new local preparation.
            raw = batch[:, stage.measurement.measurements.slice]
            measured = raw ^ memory_x ^ plus.x
            syndrome = self._readout.syndrome(measured)
            # Score only this stage's corrected syndrome, before recovery.
            # The graph is independent of future records and terminal truth.
            if index < len(self._projected_gaps):
                sectors = self._projected_gaps[index].decode_batch(syndrome)
                if score_gaps:
                    gaps[:, index] = sectors.gap
                # Projected corrections index fault events, not data qubits.
                byproduct = self._readout.logical_parity(measured) ^ sectors.best_class.astype(bool)
            else:
                if score_gaps:
                    gaps[:, index] = self._readout.score_gap(syndrome)
                recovery = self._readout.recover(syndrome)
                byproduct = self._readout.logical_parity(measured ^ recovery)
            memory_x = plus.x ^ self._readout.byproduct_frame(byproduct)
            memory_z = plus.z ^ memory_z  # Z_target propagates to the new control
            syndromes[:, index] = syndrome
            raw_byproducts[:, index] = self._readout.logical_parity(raw)
            byproducts[:, index] = byproduct
            resolved[:, index] = True  # prep signs and online syndrome were checked
            frame_x[:, index] = memory_x
            frame_z[:, index] = memory_z

        shot_id = np.arange(shots, dtype=np.uint64) + np.uint64(shot_id_start)
        return FactoryOperationalBatch(shot_id, tuple(stage.index for stage in active),
                                       syndromes, raw_byproducts, byproducts, resolved,
                                       frame_x, frame_z), gaps, measured

    def decode_stage_input(self, measurements: np.ndarray, stage_index: int) -> np.ndarray:
        """Return interpreted (shots,n) Z records before this stage's recovery.

        Requires exactly the prefix ending at this stage's destructive readout.
        Used for setup-time controlled-fault projection; no final oracle or
        terminal label is evaluated and no gap is reported. Earlier stages use their configured
        recovery, including already-built projected priors during H5 setup.
        """
        if (isinstance(stage_index, bool) or not isinstance(stage_index, Integral)
                or not 0 <= stage_index < len(self._stages)):
            raise ValueError("stage_index is outside the factory")
        return self._decode_operational(measurements, shot_id_start=0,
                                       stage_count=int(stage_index) + 1, score_gaps=False)[2]

    def decode(self, measurements: np.ndarray, *, shot_id_start: int = 0) -> FactoryBatchResult:
        """Decode fixed physical records once; labels cannot affect earlier fields."""
        batch = _measurement_batch(measurements, self._width)
        operational, gaps, _ = self._decode_operational(batch[:, :self._oracle.start], shot_id_start=shot_id_start)
        error = self._readout.evaluate_terminal(batch[:, self._oracle.slice], operational.output_frame_x[:, -1])
        return FactoryBatchResult(**vars(operational), logical_error=error,
                                  gaps=gaps, gap_units=self.gap_units)


def _compile_sampler(circuit: stim.Circuit, seed: int | None):
    """One instrumentable setup boundary, never called by decode/sample loops."""
    return circuit.compile_sampler(seed=seed)


@dataclass(frozen=True)
class CompiledFactory:
    """Frozen case configuration owning worker-local cached native handles.

    Native sampler RNG state advances across calls. Configuration never
    changes; the public circuit property returns a copy. Not for concurrent
    use or pickling across workers. Construct independently in each worker.
    """

    cache_key: FactoryCacheKey
    _circuit: stim.Circuit = field(repr=False, compare=False)
    _decoder: FactoryBatchDecoder = field(repr=False, compare=False)
    _sampler: object = field(repr=False, compare=False)

    @classmethod
    def from_bundle(cls, bundle: FactoryCircuitBundle, *, seed: int | None = None,
                    create_codecapacity_dem: bool = False) -> "CompiledFactory":
        if seed is not None:
            _validate_shot_ids(seed, 1)
            seed = int(seed)
        snapshot = replace(bundle, circuit=bundle.circuit.copy())
        digest = hashlib.sha256(str(snapshot.circuit).encode()).hexdigest()
        if snapshot.metadata["circuit_sha256"] != digest:
            raise ValueError("factory circuit changed since its metadata hash was built")
        metadata = snapshot.metadata
        decoder = FactoryBatchDecoder(snapshot, create_codecapacity_dem=create_codecapacity_dem)
        key = FactoryCacheKey(
            hashlib.sha256(repr(snapshot.code).encode()).hexdigest(), snapshot.code.distance,
            metadata["physical_error"], metadata["noise"], snapshot.preparation.r_0,
            snapshot.preparation.r_plus, len(snapshot.stages), digest,
            metadata["frame_convention"], metadata["preparation_prior"],
            metadata["terminal_label_convention"], seed,
        )
        if create_codecapacity_dem:
            key = replace(key, create_codecapacity_dem=True, decoder_policy="factory_causal_projected_v1",
                          gap_policy="surface_two_boundary_projected_v1",
                          projected_prior_sha256=tuple(p.configuration_sha256 for p in decoder.projected_priors))
        if "noise_model_sha256" in metadata:
            key = replace(key, noise_model_sha256=metadata["noise_model_sha256"])
        return cls(key, snapshot.circuit, decoder,
                   _compile_sampler(snapshot.circuit, seed))

    @property
    def projected_priors(self) -> tuple:
        """Inspectable immutable model/provenance results, empty in False mode."""
        return self._decoder.projected_priors

    @property
    def circuit(self) -> stim.Circuit:
        return self._circuit.copy()

    def sample_measurements(self, shots: int) -> np.ndarray:
        """Draw a fixed full trajectory using the one precompiled sampler."""
        _positive_integer(shots, "shots")
        return self._sampler.sample(shots=int(shots))

    def sample(self, shots: int, *, shot_id_start: int = 0) -> FactoryBatchResult:
        """Sample and decode a chunk; callers provide its absolute shot offset."""
        _positive_integer(shots, "shots")
        _validate_shot_ids(shot_id_start, shots)
        return self.decode(self.sample_measurements(shots), shot_id_start=shot_id_start)

    def decode(self, measurements: np.ndarray, *, shot_id_start: int = 0) -> FactoryBatchResult:
        return self._decoder.decode(measurements, shot_id_start=shot_id_start)

    def decode_operational(self, measurements: np.ndarray, *,
                           shot_id_start: int = 0) -> FactoryOperationalBatch:
        return self._decoder.decode_operational(measurements, shot_id_start=shot_id_start)
