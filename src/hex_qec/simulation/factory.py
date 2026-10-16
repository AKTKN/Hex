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


@dataclass(frozen=True)
class FactoryOperationalBatch:
    """Estimated operational records; all arrays have shots as the first axis.

    Corrected syndromes: (shots,T,m_z), before online Hamming recovery.
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

    logical_error is bool (shots,). H2 leaves gaps=None; no confidence metric
    or threshold is evaluated. H3 can fill (shots,T) scores independently.
    """

    logical_error: np.ndarray
    gaps: np.ndarray | None = None


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

    def __init__(self, bundle: FactoryCircuitBundle):
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

    def decode_operational(self, measurements: np.ndarray, *,
                           shot_id_start: int = 0) -> FactoryOperationalBatch:
        """Decode exactly the operational prefix, excluding the oracle suffix."""
        batch = _measurement_batch(measurements, self._oracle.start)
        shots, n, stages = len(batch), self._readout.num_data_qubits, len(self._stages)
        _validate_shot_ids(shot_id_start, shots)
        initial = self._initial.resolve(batch[:, self._initial.region.measurements.slice])
        memory_x, memory_z = initial.x, initial.z
        syndromes = np.empty((shots, stages, self._readout.num_z_checks), dtype=bool)
        raw_byproducts = np.empty((shots, stages), dtype=bool)
        byproducts = np.empty((shots, stages), dtype=bool)
        resolved = np.empty((shots, stages), dtype=bool)
        frame_x = np.empty((shots, stages, n), dtype=bool)
        frame_z = np.empty_like(frame_x)

        for index, stage in enumerate(self._stages):
            plus_region = stage.preparations[-1]
            plus = self._plans[plus_region.measurements.start].resolve(batch[:, plus_region.measurements.slice])
            # A reset discards that physical support's old X/Z frame. The
            # fresh plus frame comes only from its new local preparation.
            raw = batch[:, stage.measurement.measurements.slice]
            measured = raw ^ memory_x ^ plus.x
            syndrome = self._readout.syndrome(measured)
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
        return FactoryOperationalBatch(shot_id, tuple(stage.index for stage in self._stages),
                                       syndromes, raw_byproducts, byproducts, resolved,
                                       frame_x, frame_z)

    def decode(self, measurements: np.ndarray, *, shot_id_start: int = 0) -> FactoryBatchResult:
        """Decode fixed physical records once; labels cannot affect earlier fields."""
        batch = _measurement_batch(measurements, self._width)
        operational = self.decode_operational(batch[:, :self._oracle.start], shot_id_start=shot_id_start)
        error = self._readout.evaluate_terminal(batch[:, self._oracle.slice], operational.output_frame_x[:, -1])
        return FactoryBatchResult(**vars(operational), logical_error=error)


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
    def from_bundle(cls, bundle: FactoryCircuitBundle, *, seed: int | None = None) -> "CompiledFactory":
        if seed is not None:
            _validate_shot_ids(seed, 1)
            seed = int(seed)
        snapshot = replace(bundle, circuit=bundle.circuit.copy())
        digest = hashlib.sha256(str(snapshot.circuit).encode()).hexdigest()
        if snapshot.metadata["circuit_sha256"] != digest:
            raise ValueError("factory circuit changed since its metadata hash was built")
        metadata = snapshot.metadata
        key = FactoryCacheKey(
            hashlib.sha256(repr(snapshot.code).encode()).hexdigest(), snapshot.code.distance,
            metadata["physical_error"], metadata["noise"], snapshot.preparation.r_0,
            snapshot.preparation.r_plus, len(snapshot.stages), digest,
            metadata["frame_convention"], metadata["preparation_prior"],
            metadata["terminal_label_convention"], seed,
        )
        return cls(key, snapshot.circuit, FactoryBatchDecoder(snapshot),
                   _compile_sampler(snapshot.circuit, seed))

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
