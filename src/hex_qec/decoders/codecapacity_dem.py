"""Circuit-informed single-fault priors for a causal factory stage.

Controlled model faults are propagated through the physical prefix and its
actual preparation decoder at one noiseless reference. Nonlinear repair makes
their independent superposition an approximation, not a conditional posterior.
No physical shot, final oracle, or terminal error label enters construction.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
from itertools import product
from numbers import Integral
from typing import TYPE_CHECKING, Iterable

import numpy as np
import pymatching
from scipy import sparse
import stim

from .surface_gap import SurfaceMWPMHomologyGap

if TYPE_CHECKING:
    from hex_qec.protocols.logical_zero_factory import FactoryCircuitBundle


_APPROXIMATION = "single_fault_at_noiseless_reference_independent_superposition_v1"


class UnsupportedProjectedModel(ValueError):
    """A retained mechanism/model cannot be represented by the H3 lift."""


@dataclass(frozen=True, order=True)
class FaultSignature:
    detectors: tuple[int, ...] = ()
    logical: tuple[int, ...] = ()

    def __post_init__(self):
        for name in ("detectors", "logical"):
            values = tuple(getattr(self, name))
            if (any(isinstance(v, bool) or not isinstance(v, Integral) or v < 0 for v in values)
                    or len(set(values)) != len(values)):
                raise ValueError("signature supports must contain unique nonnegative integers")
            object.__setattr__(self, name, tuple(sorted(int(v) for v in values)))


@dataclass(frozen=True)
class FaultMechanism:
    mechanism_id: int
    instruction_index: int
    operand_index: int
    paulis: tuple[tuple[int, str], ...]
    probability: float
    noise_gate: str
    gate_probability: float
    origin_stage: int
    origin_region: str


@dataclass(frozen=True)
class ProjectedFault:
    mechanism: FaultMechanism
    signature: FaultSignature
    raw_signed_signature: FaultSignature
    interpreted_x: tuple[int, ...]


@dataclass(frozen=True)
class ProjectedEvent:
    signature: FaultSignature
    probability: float
    mechanism_ids: tuple[int, ...]

    def __post_init__(self):
        q, ids = float(self.probability), tuple(self.mechanism_ids)
        if not np.isfinite(q) or not 0 <= q <= 1:
            raise ValueError("event probabilities must be finite and in [0,1]")
        if (not ids or len(set(ids)) != len(ids)
                or any(isinstance(v, bool) or not isinstance(v, Integral) or v < 0 for v in ids)):
            raise ValueError("independent mechanism IDs must be distinct nonnegative integers")
        object.__setattr__(self, "probability", q)
        object.__setattr__(self, "mechanism_ids", tuple(sorted(int(v) for v in ids)))


def merge_independent_events(events: Iterable[ProjectedEvent]) -> tuple[ProjectedEvent, ...]:
    """XOR-merge only equal COMPLETE signatures of independent mechanisms."""
    combined: dict[FaultSignature, ProjectedEvent] = {}
    seen: set[int] = set()
    for event in sorted(events, key=lambda e: e.mechanism_ids):
        q = float(event.probability)
        if not np.isfinite(q) or not 0 <= q <= 1:
            raise ValueError("event probabilities must be finite and in [0,1]")
        ids = tuple(event.mechanism_ids)
        if not ids or len(set(ids)) != len(ids) or seen.intersection(ids):
            raise ValueError("independent mechanism IDs must be distinct and nonempty")
        seen.update(ids)
        previous = combined.get(event.signature)
        if previous is not None:
            q = previous.probability * (1 - q) + q * (1 - previous.probability)
            ids = previous.mechanism_ids + ids
        combined[event.signature] = ProjectedEvent(event.signature, q, tuple(sorted(ids)))
    return tuple(combined[key] for key in sorted(combined))


@dataclass(frozen=True)
class ProjectedErrorModel:
    """Immutable online-only events, retaining no-ops and logical-only events."""

    num_detectors: int
    events: tuple[ProjectedEvent, ...]

    def __post_init__(self):
        object.__setattr__(self, "events", tuple(self.events))
        if isinstance(self.num_detectors, bool) or not isinstance(self.num_detectors, Integral) or self.num_detectors < 1:
            raise ValueError("num_detectors must be positive")
        for event in self.events:
            if (any(d >= self.num_detectors for d in event.signature.detectors)
                    or any(l != 0 for l in event.signature.logical)):
                raise ValueError("event support lies outside the online detectors/one logical row")
            if not np.isfinite(event.probability) or not 0 <= event.probability <= 1:
                raise ValueError("event probabilities must be finite and in [0,1]")

    @property
    def active_events(self) -> tuple[ProjectedEvent, ...]:
        return tuple(event for event in self.events if event.probability > 0
                     and (event.signature.detectors or event.signature.logical))

    @property
    def graphlike(self) -> bool:
        return all(len(event.signature.detectors) <= 2 for event in self.active_events)

    def to_stim_dem(self) -> stim.DetectorErrorModel:
        # Include even no-op/zero-probability events in this inspectable export.
        lines = []
        for event in self.events:
            targets = [f"D{d}" for d in event.signature.detectors]
            targets += [f"L{l}" for l in event.signature.logical]
            lines.append(f"error({event.probability:.17g}) " + " ".join(targets))
        lines += [f"detector D{self.num_detectors - 1}", "logical_observable L0"]
        return stim.DetectorErrorModel("\n".join(lines))

    def matching_matrices(self) -> tuple[sparse.csc_matrix, np.ndarray, np.ndarray]:
        """Return H, L, natural log weights, failing before lossy conversion."""
        events = self.active_events
        if not events:
            raise UnsupportedProjectedModel("zero-noise/no-active-event prior has no finite matching weights; use the explicit Hamming baseline")
        if not self.graphlike:
            raise UnsupportedProjectedModel("projected hyperedge has >2 detectors; no decomposition or event dropping is permitted")
        if any(not event.signature.detectors for event in events):
            raise UnsupportedProjectedModel("detector-free logical events are retained but unsupported by the two-boundary lift")
        q = np.array([event.probability for event in events], dtype=np.float64)
        if np.any(q >= .5):
            raise UnsupportedProjectedModel("projected prior needs 0<q<1/2 for positive finite log weights")
        rows, columns = [], []
        for col, event in enumerate(events):
            rows.extend(event.signature.detectors)
            columns.extend([col] * len(event.signature.detectors))
        h = sparse.csc_matrix((np.ones(len(rows), dtype=np.uint8), (rows, columns)),
                              shape=(self.num_detectors, len(events)))
        logical = np.array([bool(event.signature.logical) for event in events], dtype=np.uint8)
        return h, logical, np.log1p(-q) - np.log(q)

    def compile_gap(self) -> SurfaceMWPMHomologyGap:
        """Explicit setup boundary; builders cache the returned native handle."""
        h, logical, weights = self.matching_matrices()
        try:
            return SurfaceMWPMHomologyGap(h, logical, weights, score_units="log_weight")
        except ValueError as error:
            raise UnsupportedProjectedModel(f"projected model fails the H3 lift: {error}") from error


@dataclass(frozen=True)
class PreparationDecoderConvention:
    frame: str = "canonical_reset_xz_at_stage_boundaries_v1"
    preparation_prior: str = "hex_legacy_matchable"
    prefix_online: str = "factory_causal_hamming_v1"
    reference: str = "stim_noiseless_reference_with_canonical_reset_maps_v1"


@dataclass(frozen=True)
class ProjectedDEMDiagnostics:
    mechanism_count: int
    active_mechanism_count: int
    event_count: int
    raw_vs_resolved_mismatches: int
    hyperedge_event_count: int
    detector_free_logical_event_count: int
    no_effect_mechanism_count: int
    zero_noise: bool
    lift_error: str | None
    zero_probability_instruction_count: int = 0


@dataclass(frozen=True)
class ProjectedDEMResult:
    stage_id: int
    model: ProjectedErrorModel
    faults: tuple[ProjectedFault, ...]
    diagnostics: ProjectedDEMDiagnostics
    convention: PreparationDecoderConvention
    graphlike: bool
    h3_lift_valid: bool
    circuit_sha256: str
    prefix_sha256: str
    configuration_sha256: str
    reference_sha256: str
    model_sha256: str
    prior_convention: str = "circuit_informed_projected"
    approximation: str = _APPROXIMATION
    weight_units: str = "log_weight"
    projection_batch_size: int = 1024


def _digest(value: object) -> str:
    return hashlib.sha256(repr(value).encode()).hexdigest()


def _independent_depolarizing_probability(p: float, qubits: int) -> float:
    # Exact symmetric Pauli-channel factorization, as in Stim's DEM analyzer.
    # Each of the 4**qubits-1 Pauli generators is independently Bernoulli(q).
    ratio = 4**qubits / (4**qubits - 1)
    if not 0 <= p < 1 / ratio:
        raise ValueError("over-mixing depolarization is unsupported")
    q = float(-.5 * np.expm1(np.log1p(-ratio * p) / (2 ** (2 * qubits - 1))))
    if p > 0 and q == 0:
        raise ValueError("independent depolarizing generator probability underflow")
    return q


def _enumerate_faults(bundle: FactoryCircuitBundle, stage_index: int) -> tuple[FaultMechanism, ...]:
    stage = bundle.stages[stage_index]
    regions = [(s.index, r) for s in bundle.stages[:stage_index + 1]
               for r in (*s.preparations, s.coupling, s.measurement)]
    faults = []
    for index, instruction in enumerate(bundle.circuit[:stage.measurement.instructions.stop]):
        if isinstance(instruction, stim.CircuitRepeatBlock):
            raise ValueError("projected factory requires a flat stage-aware circuit")
        gate = stim.gate_data(instruction.name)
        args = instruction.gate_args_copy()
        if gate.produces_measurements and args and any(args):
            raise ValueError("use explicit pre-readout Pauli noise; noisy measurement arguments are unsupported")
        if not gate.is_noisy_gate or gate.produces_measurements:
            continue
        if instruction.name not in {"X_ERROR", "Y_ERROR", "Z_ERROR", "DEPOLARIZE1", "DEPOLARIZE2"}:
            raise ValueError(f"unsupported noise mechanism {instruction.name}; no terms were discarded")
        owner = next(((s, r.name) for s, r in regions if r.instructions.start <= index < r.instructions.stop), None)
        if owner is None:
            raise ValueError("noise mechanism has no stage/preparation ledger owner")
        p = args[0]
        targets = instruction.targets_copy()
        arity = 2 if instruction.name == "DEPOLARIZE2" else 1
        q = (_independent_depolarizing_probability(p, arity)
             if instruction.name.startswith("DEPOLARIZE") else p)
        # An impossible event has no post-decoder response to infer: at p=0
        # the configured prep graph correctly has no noisy DEM edges at all.
        if q == 0:
            continue
        for offset in range(0, len(targets), arity):
            choices = product("IXYZ", repeat=arity) if instruction.name.startswith("DEPOLARIZE") else [(instruction.name[0],)]
            for paulis in choices:
                support = tuple((target.value, pauli) for target, pauli in zip(targets[offset:offset + arity], paulis)
                                if pauli != "I")
                if support:
                    faults.append(FaultMechanism(len(faults), index, offset // arity, support, q,
                                                 instruction.name, p, *owner))
    return tuple(faults)


def _propagate_faults(circuit: stim.Circuit, faults: tuple[FaultMechanism, ...]) -> np.ndarray:
    """One deterministic setup lane per model term, never physical MC shots."""
    if not faults:
        return np.zeros((0, circuit.num_measurements), dtype=bool)
    simulator = stim.FlipSimulator(batch_size=len(faults), num_qubits=circuit.num_qubits,
                                   disable_stabilizer_randomization=True, seed=0)
    locations: dict[int, list[tuple[int, FaultMechanism]]] = {}
    for lane, fault in enumerate(faults):
        locations.setdefault(fault.instruction_index, []).append((lane, fault))
    for index, instruction in enumerate(circuit):
        fragment = stim.Circuit()
        fragment.append(instruction)
        simulator.do(fragment.without_noise())
        # Canonicalize erased, unobservable components after reset. These
        # sentinels change only deterministic maps, never the sampled circuit.
        if instruction.name in {"R", "RX", "MR"}:
            targets = [target.value for target in instruction.targets_copy()]
            reset = stim.Circuit()
            reset.append("R" if instruction.name == "RX" else "RX", targets)
            reset.append("RX" if instruction.name == "RX" else "R", targets)
            simulator.do(reset)
        for lane, fault in locations.get(index, ()):
            for qubit, pauli in fault.paulis:
                simulator.set_pauli_flip(pauli, qubit_index=qubit, instance_index=lane)
    return simulator.get_measurement_flips().T


def _signatures(syndromes: np.ndarray, logical: np.ndarray) -> tuple[FaultSignature, ...]:
    return tuple(FaultSignature(tuple(np.flatnonzero(row)), (0,) if bit else ())
                 for row, bit in zip(syndromes, logical))


class ProjectedDEMBuilder:
    """Worker-local cache from a full circuit, stage ledger and prep plans.

    build(stage_index) rejects unsupported active models. inspect(stage_index)
    retains all terms/diagnostics even when compilation is unsupported. Prior
    construction never samples, calls terminal evaluation, or reads an oracle.
    Do not mutate the supplied native prep plans after constructing this object.
    """

    def __init__(self, bundle: FactoryCircuitBundle, *,
                 convention: PreparationDecoderConvention = PreparationDecoderConvention(),
                 fault_batch_size: int = 1024):
        # Lazy imports avoid modularisation -> decoders -> simulation cycles.
        from hex_qec.simulation.factory import FactoryBatchDecoder

        if convention != PreparationDecoderConvention():
            raise ValueError("unsupported preparation/reference convention")
        if isinstance(fault_batch_size, bool) or not isinstance(fault_batch_size, Integral) or fault_batch_size < 1:
            raise ValueError("fault_batch_size must be a positive integer")
        self._fault_batch_size = int(fault_batch_size)
        self._bundle = replace(bundle, circuit=bundle.circuit.copy())
        actual = hashlib.sha256(str(self._bundle.circuit).encode()).hexdigest()
        if actual != bundle.metadata["circuit_sha256"]:
            raise ValueError("factory circuit disagrees with its configuration hash")
        if (bundle.metadata["frame_convention"] != convention.frame
                or bundle.metadata["preparation_prior"] != convention.preparation_prior):
            raise ValueError("preparation/frame convention disagrees with the bundle")
        self._decoder = FactoryBatchDecoder(self._bundle)
        self._hz = bundle.preparation_frames[0].module.z_pcm.copy().tocsc()
        self._lz = np.zeros(bundle.code.num_data_qubits, dtype=np.uint8)
        self._lz[list(bundle.code.logical_z)] = 1
        # Include actual native weights and frame maps, not just a named
        # convention, in cache identity. Custom prep backends need a separate
        # validated convention instead of borrowing this model's label.
        prep_identity = []
        for plan in bundle.preparation_frames:
            decoders = []
            for name in ("x_dem_decoder", "z_dem_decoder", "x_decoder", "z_decoder"):
                native = getattr(getattr(plan.module, name), "decoder", None)
                if not isinstance(native, pymatching.Matching) or not plan.module.matchable:
                    raise ValueError("projected prior currently requires the legacy matchable PyMatching preparation convention")
                decoders.append(tuple((a, b, tuple(sorted(data["fault_ids"])), float(data["weight"]))
                                      for a, b, data in native.edges()))
            matrices = (plan.x_map, plan.z_map, plan.module.x_pcm, plan.module.z_pcm,
                        plan.module.x_dem_correction_to_local_measurement_flips,
                        plan.module.z_dem_correction_to_local_measurement_flips)
            maps = tuple((matrix.shape, matrix.indptr.tolist(), matrix.indices.tolist(), matrix.data.tolist())
                         for matrix in (m.tocsc() for m in matrices))
            prep_identity.append((plan.region, str(plan.module.circuit), decoders, maps))
        self._convention, self._circuit_hash = convention, actual
        self._configuration_hash = _digest((bundle.code, bundle.preparation, bundle.stages,
                                            bundle.ledger, tuple(sorted(bundle.metadata.items())),
                                            prep_identity, convention, _APPROXIMATION, self._fault_batch_size,
                                            stim.__version__, pymatching.__version__))
        self._results: dict[int, ProjectedDEMResult] = {}
        self._gaps: dict[int, SurfaceMWPMHomologyGap] = {}

    def inspect(self, stage_index: int = 0) -> ProjectedDEMResult:
        if (isinstance(stage_index, bool) or not isinstance(stage_index, Integral)
                or not 0 <= stage_index < len(self._bundle.stages)):
            raise ValueError("stage_index is outside the factory")
        stage_index = int(stage_index)
        if stage_index in self._results:
            return self._results[stage_index]
        bundle, stage = self._bundle, self._bundle.stages[stage_index]
        prefix = bundle.circuit[:stage.measurement.instructions.stop]
        faults = _enumerate_faults(bundle, stage_index)
        reference = prefix.without_noise().reference_sample()[None, :]
        baseline = self._decoder.decode_stage_input(reference, stage_index)
        projected = []
        # Bound dense record storage by batch_size * prefix measurements;
        # never retain the full mechanisms-by-records table for large codes.
        for start in range(0, len(faults), self._fault_batch_size):
            chunk = faults[start:start + self._fault_batch_size]
            flips = _propagate_faults(prefix, chunk)
            try:
                interpreted = self._decoder.decode_stage_input(reference ^ flips, stage_index) ^ baseline
            except ValueError as error:
                raise UnsupportedProjectedModel(f"controlled faults are outside the configured preparation decoder support: {error}") from error
            effective = _signatures(interpreted @ self._hz.T % 2, interpreted @ self._lz % 2)
            raw_syndrome = np.column_stack([np.logical_xor.reduce(flips[:, flow.parity.records], axis=1)
                                           for flow in stage.terminal_checks])
            raw = _signatures(raw_syndrome, np.logical_xor.reduce(flips[:, stage.raw_logical_outcome.records], axis=1))
            projected.extend(ProjectedFault(fault, signature, signed, tuple(np.flatnonzero(error)))
                             for fault, signature, signed, error in zip(chunk, effective, raw, interpreted))
        projected = tuple(projected)
        events = merge_independent_events(ProjectedEvent(f.signature, f.mechanism.probability,
                                                        (f.mechanism.mechanism_id,)) for f in projected)
        model = ProjectedErrorModel(len(bundle.code.z_checks), events)
        lift_error = None
        try:
            self._gaps[stage_index] = model.compile_gap()
        except UnsupportedProjectedModel as error:
            lift_error = str(error)
        active = model.active_events
        diagnostics = ProjectedDEMDiagnostics(
            len(faults), sum(f.probability > 0 for f in faults), len(events),
            sum(f.mechanism.probability > 0 and f.signature != f.raw_signed_signature for f in projected),
            sum(len(e.signature.detectors) > 2 for e in active),
            sum(not e.signature.detectors and bool(e.signature.logical) for e in active),
            sum(not f.signature.detectors and not f.signature.logical for f in projected),
            not any(f.probability > 0 for f in faults), lift_error,
            sum(i.name in {"X_ERROR", "Y_ERROR", "Z_ERROR", "DEPOLARIZE1", "DEPOLARIZE2"}
                and i.gate_args_copy() == [0.] for i in prefix),
        )
        result = ProjectedDEMResult(stage_index, model, projected, diagnostics, self._convention,
                                    model.graphlike, lift_error is None, self._circuit_hash,
                                    hashlib.sha256(str(prefix).encode()).hexdigest(),
                                    self._configuration_hash, _digest(reference.tolist()), _digest(model),
                                    projection_batch_size=self._fault_batch_size)
        self._results[stage_index] = result
        return result

    def build(self, stage_index: int = 0) -> ProjectedDEMResult:
        result = self.inspect(stage_index)
        if not result.h3_lift_valid and not result.diagnostics.zero_noise:
            raise UnsupportedProjectedModel(result.diagnostics.lift_error)
        return result

    def compile_gap(self, stage_index: int = 0) -> SurfaceMWPMHomologyGap:
        result = self.build(stage_index)
        if not result.h3_lift_valid:
            raise UnsupportedProjectedModel(result.diagnostics.lift_error)
        return self._gaps[int(stage_index)]
