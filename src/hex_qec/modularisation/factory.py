"""Circuit/record contracts and preparation-only frame resolution for factories.

There is deliberately no sampler, online stage decoder, or experiment runner
here. All array transforms use a shot-first batch and GF(2) arithmetic.
"""

from dataclasses import dataclass
from numbers import Integral
from typing import Protocol

import numpy as np
import stim
from scipy.sparse import csc_matrix, csr_matrix

from .modularised_circuit import css_detector_module


def _positive_integer(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, Integral) or value < 1:
        raise ValueError(f"{name} must be a positive integer")


def _support(indices, name: str) -> tuple[int, ...]:
    result = tuple(indices)
    if any(isinstance(index, bool) or not isinstance(index, Integral) or index < 0 for index in result):
        raise ValueError(f"{name} must contain nonnegative integer positions")
    if len(set(result)) != len(result):
        raise ValueError(f"{name} must not repeat positions")
    return tuple(int(index) for index in result)


@dataclass(frozen=True)
class CodeSpec:
    """Geometry-independent CSS supports; rows list data positions, not IDs."""

    family: str
    num_data_qubits: int
    x_checks: tuple[tuple[int, ...], ...]
    z_checks: tuple[tuple[int, ...], ...]
    logical_x: tuple[int, ...]
    logical_z: tuple[int, ...]
    distance: int | None = None

    def __post_init__(self) -> None:
        _positive_integer(self.num_data_qubits, "num_data_qubits")
        for name in ("x_checks", "z_checks"):
            rows = tuple(_support(row, name) for row in getattr(self, name))
            object.__setattr__(self, name, rows)
        for name in ("logical_x", "logical_z"):
            object.__setattr__(self, name, _support(getattr(self, name), name))
        for row in self.x_checks + self.z_checks + (self.logical_x, self.logical_z):
            if not row or any(index >= self.num_data_qubits for index in row):
                raise ValueError("CSS supports must be nonempty and within the data block")


@dataclass(frozen=True)
class PreparationPlan:
    r_0: int
    r_plus: int

    def __post_init__(self) -> None:
        _positive_integer(self.r_0, "r_0")
        _positive_integer(self.r_plus, "r_plus")
        object.__setattr__(self, "r_0", int(self.r_0))
        object.__setattr__(self, "r_plus", int(self.r_plus))


@dataclass(frozen=True)
class IndexRange:
    """Half-open instruction or measurement range."""

    start: int
    stop: int

    def __post_init__(self) -> None:
        if any(isinstance(value, bool) or not isinstance(value, Integral) or value < 0
               for value in (self.start, self.stop)) or self.stop < self.start:
            raise ValueError("range must have nonnegative integer start <= stop")

    @property
    def slice(self) -> slice:
        return slice(self.start, self.stop)


@dataclass(frozen=True)
class CircuitRegion:
    name: str
    instructions: IndexRange
    measurements: IndexRange


@dataclass(frozen=True)
class BlockSupport:
    name: str
    data_qubits: tuple[int, ...]
    x_ancillas: tuple[int, ...]
    z_ancillas: tuple[int, ...]

    def __post_init__(self) -> None:
        for name in ("data_qubits", "x_ancillas", "z_ancillas"):
            object.__setattr__(self, name, _support(getattr(self, name), name))
        if len(set(self.qubits)) != len(self.qubits):
            raise ValueError("data and check-ancilla supports must be disjoint")

    @property
    def qubits(self) -> tuple[int, ...]:
        return self.data_qubits + self.x_ancillas + self.z_ancillas


@dataclass(frozen=True)
class MeasurementRecord:
    index: int
    qubit: int
    basis: str
    block: str
    operation: str
    stage: int
    se_round: int | None = None
    check_basis: str | None = None
    evaluation_only: bool = False


@dataclass(frozen=True)
class MeasurementLedger:
    records: tuple[MeasurementRecord, ...]

    @property
    def oracle_indices(self) -> tuple[int, ...]:
        return tuple(record.index for record in self.records if record.evaluation_only)


@dataclass(frozen=True)
class RecordParity:
    """A signed symbolic check value: XOR(records) XOR constant."""

    records: tuple[int, ...] = ()
    constant: bool = False

    def __post_init__(self) -> None:
        support: set[int] = set()
        for index in self.records:
            if isinstance(index, bool) or not isinstance(index, Integral) or index < 0:
                raise ValueError("record indices must be nonnegative integers")
            support.symmetric_difference_update((int(index),))
        object.__setattr__(self, "records", tuple(sorted(support)))

    def __xor__(self, other: "RecordParity") -> "RecordParity":
        return RecordParity(self.records + other.records, self.constant ^ other.constant)

    def evaluate(self, records: np.ndarray) -> np.ndarray:
        batch = np.asarray(records)
        if batch.ndim != 2 or (self.records and self.records[-1] >= batch.shape[1]):
            raise ValueError("record batch does not cover this parity")
        return np.logical_xor.reduce(batch[:, self.records].astype(bool), axis=1) ^ self.constant


@dataclass(frozen=True)
class SignedCheckFlow:
    """At a circuit prefix, check(qubits) has sign ``parity``.

    Empty qubits represent a deterministic detector closure. ``basis`` names
    the CSS check, even when its ancilla was physically measured in Z.
    """

    block: str
    basis: str
    check_index: int
    qubits: tuple[int, ...]
    parity: RecordParity
    instruction_stop: int
    detector_index: int | None = None

    def as_stim_flow(self, num_qubits: int) -> stim.Flow:
        operator = stim.PauliString(num_qubits)
        for qubit in self.qubits:
            operator[qubit] = self.basis
        if self.parity.constant:
            operator.sign = -1
        return stim.Flow(output=operator, measurements=self.parity.records)


@dataclass(frozen=True)
class TeleportationStage:
    index: int
    consumed_block: str
    surviving_block: str
    preparations: tuple[CircuitRegion, ...]
    coupling: CircuitRegion
    measurement: CircuitRegion
    input_checks: tuple[SignedCheckFlow, ...]
    output_checks: tuple[SignedCheckFlow, ...]
    terminal_checks: tuple[SignedCheckFlow, ...]
    raw_logical_outcome: RecordParity


class FactoryCodeAdapter(Protocol):
    """CSS geometry/noise-specific construction boundary."""

    code: CodeSpec
    matrices: tuple

    def blocks(self) -> tuple[BlockSupport, BlockSupport]: ...

    def prepare(self, block: BlockSupport, basis: str, rounds: int,
                physical_error: float) -> css_detector_module: ...


@dataclass(frozen=True)
class PreparationFrame:
    """Inferred Pauli at the prep boundary, never sampled physical fault truth.

    x/z: (shots, data qubits); corrected_history: (shots, prep measurements);
    x_signs/z_signs: repaired check signs; corrections: legacy module columns.
    """

    x: np.ndarray
    z: np.ndarray
    corrected_history: np.ndarray
    x_signs: np.ndarray
    z_signs: np.ndarray
    corrections: np.ndarray


def _dem_end_frames(module: css_detector_module, basis: str) -> tuple[np.ndarray, np.ndarray]:
    """Propagate Hex's representative corrections using its after-op convention.

    This setup-only FlipSimulator runs one lane per representative, not per
    physical shot. Local measurement maps themselves are reused from Hex.
    """
    circuit = getattr(module, f"{basis}_det_circuit")
    corrections = getattr(module, f"{basis}_correction_array")
    support = module.new_support[:module.num_data_qubits]
    if not corrections:
        zero = np.zeros((0, len(support)), dtype=np.uint8)
        return zero, zero.copy()
    simulator = stim.FlipSimulator(batch_size=len(corrections),
                                   num_qubits=circuit.num_qubits,
                                   disable_stabilizer_randomization=True)
    locations: dict[int, list[tuple[int, str]]] = {}
    for lane, (pauli, offset) in enumerate(corrections):
        locations.setdefault(offset, []).append((lane, pauli))
    for offset, instruction in enumerate(circuit):
        gate = stim.gate_data(instruction.name)
        if not (gate.is_noisy_gate and not gate.produces_measurements):
            simulator.do(instruction)
        for lane, pauli in locations.get(offset, ()):
            if "*" in pauli:
                raise ValueError("Hex CSS representative must be a single Pauli")
            simulator.set_pauli_flip(pauli[0], qubit_index=int(pauli[1:]), instance_index=lane)
    x, z, _, _, _ = simulator.to_numpy(transpose=True, output_xs=True, output_zs=True)
    x, z = x[:, support].astype(np.uint8), z[:, support].astype(np.uint8)
    if module.matchable:
        projection = getattr(module, f"{basis}_dem_hyperedge_to_edge")
        x, z = np.asarray(projection @ x) % 2, np.asarray(projection @ z) % 2
    return x, z


class PreparationFramePlan:
    """Reusable prep-only decoder and sparse end-frame maps.

    ``resolve`` accepts exactly the local preparation record, so it cannot
    consume teleportation or oracle data. It mirrors Hex CSS decoding using
    the existing four decoder handles/maps and caches both m2d converters.
    Mutable decoder handles are used synchronously, never concurrently.
    """

    def __init__(self, module: css_detector_module, block: BlockSupport,
                 region: CircuitRegion):
        self.module, self.block, self.region = module, block, region
        self._x_converter = module.x_det_circuit.compile_m2d_converter()
        self._z_converter = module.z_det_circuit.compile_m2d_converter()
        xx, xz = _dem_end_frames(module, "x")
        zx, zz = _dem_end_frames(module, "z")
        n = module.num_data_qubits
        identity, zero = np.eye(n, dtype=np.uint8), np.zeros((n, n), dtype=np.uint8)
        self.x_map = csc_matrix(np.vstack((xx, zx, zero, identity)))
        self.z_map = csc_matrix(np.vstack((xz, zz, identity, zero)))

    def resolve(self, measurements: np.ndarray) -> PreparationFrame:
        batch = np.asarray(measurements)
        module = self.module
        if batch.ndim != 2 or batch.shape[1] != module.num_measurements:
            raise ValueError("expected exactly the local preparation measurement batch")
        if not np.all((batch == 0) | (batch == 1)):
            raise ValueError("preparation measurements must be binary")
        batch = batch.astype(bool)
        x_syndromes = self._x_converter.convert(measurements=batch, separate_observables=True)[0]
        z_syndromes = self._z_converter.convert(measurements=batch, separate_observables=True)[0]
        x_dem = module.x_dem_decoder.decode_batch(x_syndromes).correction
        z_dem = module.z_dem_decoder.decode_batch(z_syndromes).correction
        updates = (csr_matrix(x_dem) @ module.x_dem_correction_to_local_measurement_flips
                   + csr_matrix(z_dem) @ module.z_dem_correction_to_local_measurement_flips)
        history = batch ^ ((updates.toarray() % 2).astype(bool))
        mx, mz = module.num_x_stabilizers, module.num_z_stabilizers
        last_x, last_z = history[:, -(mx + mz):-mz], history[:, -mz:]
        z_repair = module.x_decoder.decode_batch(last_x).correction
        x_repair = module.z_decoder.decode_batch(last_z).correction
        corrections = np.hstack((x_dem, z_dem, z_repair, x_repair)).astype(np.uint8)
        x_signs = last_x ^ ((z_repair @ module.x_pcm.T) % 2).astype(bool)
        z_signs = last_z ^ ((x_repair @ module.z_pcm.T) % 2).astype(bool)
        if np.any(x_signs) or np.any(z_signs):
            raise ValueError("preparation decoder did not resolve all stabilizer signs")
        return PreparationFrame(
            (corrections @ self.x_map % 2).astype(bool),
            (corrections @ self.z_map % 2).astype(bool),
            history, x_signs, z_signs, corrections,
        )
