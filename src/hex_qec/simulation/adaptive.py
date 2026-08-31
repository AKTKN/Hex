"""Stateful two-level adaptive state-preparation execution."""

from contextlib import nullcontext
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np
import stim
from scipy.sparse import csc_matrix

from hex_qec.decoders import DecodeResult
from hex_qec.modularisation.adaptive_state_prep import AdaptiveStatePrepModule
from hex_qec.modularisation.modularised_circuit import (
    css_detector_module,
    detector_module,
    logical_measurement_module,
    measurement_module,
    no_measurement_module,
    only_postselection_module,
)
from hex_qec.modularisation.results import (
    ModuleDecodeResult,
    normalize_module_decode_output,
)
from .policies import AdaptivePolicyContext
from .stateful import reconstruct_measurement_records


def _profile_section(profiler: Any, name: str, *, absolute: bool = True):
    """Return an opt-in timing context without coupling execution to it."""

    if profiler is None:
        return nullcontext()
    return profiler.section(name, absolute=absolute)


@dataclass
class AdaptiveStatePrepExecution:
    """Records one batch execution of an adaptive preparation.

    ``selected_result`` and ``selected_measurements`` are populated for a
    uniform policy, preserving the diagnostic API.  For a mixed policy, the
    selected correction widths can differ between shots, so
    ``selected_results`` and ``selected_measurements`` contain one entry per
    shot and ``selected_result`` is ``None``.
    """

    short_result: ModuleDecodeResult
    long_result: ModuleDecodeResult | None
    selected_result: ModuleDecodeResult | None
    short_measurements: np.ndarray
    selected_measurements: np.ndarray | list[np.ndarray]
    used_long: np.ndarray
    selected_results: list[ModuleDecodeResult] | None = None
    confidence: np.ndarray | None = None


def _seed_for_shot(seed: int | None, shot: int) -> int | None:
    if seed is None:
        return None
    return (seed + shot) % (2**64)


def _slice_decode_result(
    result: DecodeResult,
    indices: np.ndarray,
) -> DecodeResult:
    def slice_value(value: np.ndarray | None) -> np.ndarray | None:
        if value is None:
            return None
        array = np.asarray(value)
        return array[indices]

    return DecodeResult(
        correction=np.asarray(result.correction)[indices],
        confidence=slice_value(result.confidence),
        converged=slice_value(result.converged),
        metrics={
            name: np.asarray(value)[indices]
            for name, value in result.metrics.items()
        },
    )


def _slice_module_result(
    result: ModuleDecodeResult,
    indices: np.ndarray,
) -> ModuleDecodeResult:
    decode_result = result.decode_result
    sliced_decode = (
        _slice_decode_result(decode_result, indices)
        if decode_result is not None
        else None
    )
    return ModuleDecodeResult(
        corrections=np.asarray(result.corrections)[indices],
        postselection=(
            np.asarray(result.postselection)[indices]
            if result.postselection is not None
            else None
        ),
        decode_result=sliced_decode,
        metrics={
            name: np.asarray(value)[indices]
            for name, value in result.metrics.items()
        },
    )


class StatefulAdaptiveStatePrepExecutor:
    """Execute one adaptive preparation with exact per-shot continuation.

    A batch of one-shot ``FlipSimulator`` instances is used intentionally as
    the unoptimized reference implementation.  This permits a mixed policy
    mask while ensuring that each long shot continues the exact simulator
    state that generated its short record.
    """

    def execute(
        self,
        description: AdaptiveStatePrepModule,
        *,
        batch_size: int = 256,
        seed: int | None = None,
    ) -> AdaptiveStatePrepExecution:
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")

        simulators: list[stim.FlipSimulator] = []
        short_records: list[np.ndarray] = []
        short_reference = np.asarray(
            description.short_circuit.reference_sample(), dtype=bool
        )
        for shot in range(batch_size):
            simulator = stim.FlipSimulator(
                batch_size=1,
                disable_stabilizer_randomization=False,
                seed=_seed_for_shot(seed, shot),
            )
            simulator.do(description.short_circuit)
            simulators.append(simulator)
            short_records.append(
                reconstruct_measurement_records(
                    short_reference,
                    simulator.get_measurement_flips(),
                )[0]
            )
        short_measurements = np.asarray(short_records, dtype=bool)
        short_result = normalize_module_decode_output(
            description.short_rich_decoder(short_measurements)
        )
        short_decode = short_result.decode_result or DecodeResult(
            correction=short_result.corrections
        )
        context = AdaptivePolicyContext(
            batch_size=batch_size,
            event_id=description.event_id,
            teleportation_index=description.teleportation_index,
            state_basis=description.state_basis,
        )
        extend_mask = np.asarray(
            description.schedule.policy.should_extend(
                short_decode,
                context=context,
            ),
            dtype=bool,
        )
        if extend_mask.shape != (batch_size,):
            raise ValueError("adaptive policy must return one boolean per shot")
        short_decode = short_result.decode_result or DecodeResult(
            correction=short_result.corrections
        )
        confidence = (
            np.asarray(short_decode.confidence)
            if short_decode.confidence is not None
            else None
        )
        low_indices = np.flatnonzero(extend_mask)
        high_indices = np.flatnonzero(~extend_mask)

        if len(low_indices) == 0:
            return AdaptiveStatePrepExecution(
                short_result=short_result,
                long_result=None,
                selected_result=short_result,
                short_measurements=short_measurements,
                selected_measurements=short_measurements,
                used_long=extend_mask,
                selected_results=[
                    _slice_module_result(short_result, np.array([shot]))
                    for shot in range(batch_size)
                ],
                confidence=confidence,
            )

        long_reference = np.asarray(
            description.long_circuit.reference_sample(), dtype=bool
        )
        long_records: list[np.ndarray] = []
        for shot in low_indices:
            # No reset or reinitialization occurs here: this is the same
            # physical simulator that produced this shot's short record.
            simulators[shot].do(description.extra_circuit)
            long_record = reconstruct_measurement_records(
                long_reference,
                simulators[shot].get_measurement_flips(),
            )[0]
            if not np.array_equal(
                long_record[: description.short_circuit.num_measurements],
                short_measurements[shot],
            ):
                raise RuntimeError(
                    "long continuation changed the short measurement prefix"
                )
            long_records.append(long_record)
        long_measurements = np.asarray(long_records, dtype=bool)
        long_result = normalize_module_decode_output(
            description.long_rich_decoder(long_measurements)
        )

        selected_results: list[ModuleDecodeResult] = []
        for shot in range(batch_size):
            if extend_mask[shot]:
                selected_results.append(
                    _slice_module_result(
                        long_result,
                        np.array([np.flatnonzero(low_indices == shot)[0]]),
                    )
                )
            else:
                selected_results.append(
                    _slice_module_result(short_result, np.array([shot]))
                )

        if len(high_indices) == 0:
            selected_result = long_result
            selected_measurements: np.ndarray | list[np.ndarray] = long_measurements
        elif len(low_indices) == 0:
            selected_result = short_result
            selected_measurements = short_measurements
        else:
            selected_result = None
            selected_measurements = [
                short_measurements[shot]
                if not extend_mask[shot]
                else long_measurements[np.flatnonzero(low_indices == shot)[0]]
                for shot in range(batch_size)
            ]
        return AdaptiveStatePrepExecution(
            short_result=short_result,
            long_result=long_result,
            selected_result=selected_result,
            short_measurements=short_measurements,
            selected_measurements=selected_measurements,
            used_long=extend_mask,
            selected_results=selected_results,
            confidence=confidence,
        )


@dataclass
class AdaptiveEventObservation:
    event_id: str | None
    teleportation_index: int | None
    state_basis: str | None
    confidence: float | None
    used_long: bool
    would_extend: bool | None = None
    pair_id: str | None = None
    pair_risk: float | None = None


@dataclass
class _PhysicalSegment:
    """A measured physical circuit segment without a decoder callback."""

    circuit: stim.Circuit
    num_measurements: int
    num_detectors: int = 0


def _without_detectors(circuit: stim.Circuit) -> stim.Circuit:
    """Remove detector annotations before executing a non-contiguous suffix."""

    result = stim.Circuit()
    for instruction in circuit:
        if instruction.name == "DETECTOR":
            continue
        result.append(
            instruction.name,
            instruction.targets_copy(),
            instruction.gate_args_copy(),
        )
    return result


@dataclass
class _CorrectionEvent:
    unit_index: int
    module: Any
    corrections: np.ndarray


def _path_key(units: Sequence[Any]) -> tuple[int, ...]:
    """Identify a deterministic logical module path by its module identities."""

    return tuple(id(unit) for unit in units)


def _noise_free_circuit_for_units(units: Sequence[Any]) -> stim.Circuit:
    circuit = stim.Circuit()
    for unit in units:
        circuit += unit.circuit.without_noise()
    return circuit


def _generate_correction_maps(units: Sequence[Any]) -> tuple[Any | None, ...]:
    """Generate the existing correction maps for one logical module path."""

    maps: list[Any | None] = []
    previous_detectors = 0
    for index, module in enumerate(units):
        before = _noise_free_circuit_for_units(units[:index])
        after = _noise_free_circuit_for_units(units[index + 1 :])
        if isinstance(module, measurement_module):
            module.generate_measurement_flip_map(before, after)
            maps.append(module.correction_to_measurement_flips)
        elif isinstance(module, (detector_module, css_detector_module)):
            module.generate_measurement_flip_map(
                before,
                after,
                previous_detectors,
            )
            maps.append(module.correction_to_measurement_flips)
        else:
            maps.append(None)
        previous_detectors += module.num_detectors
    return tuple(maps)


class _CorrectionMapCache:
    """Executor-lifetime, read-only-after-preparation correction-map store."""

    def __init__(self) -> None:
        self._entries: dict[tuple[int, ...], tuple[Any | None, ...]] = {}
        self.generation_count = 0

    def get(self, key: tuple[int, ...]) -> tuple[Any | None, ...] | None:
        return self._entries.get(key)

    def prepare(self, units: Sequence[Any]) -> tuple[Any | None, ...]:
        key = _path_key(units)
        maps = self._entries.get(key)
        if maps is None:
            maps = _generate_correction_maps(units)
            self._entries[key] = maps
            self.generation_count += 1
        return maps

    @property
    def keys(self) -> tuple[tuple[int, ...], ...]:
        return tuple(self._entries)


class _AdaptiveShotRunner:
    """Unoptimized one-shot executor used by the adaptive protocol path."""

    def __init__(
        self,
        *,
        seed: int | None,
        profiler: Any = None,
        correction_map_cache: _CorrectionMapCache | None = None,
        stripped_suffix_cache: Mapping[int, stim.Circuit] | None = None,
    ) -> None:
        self.profiler = profiler
        self.simulator = stim.FlipSimulator(
            batch_size=1,
            disable_stabilizer_randomization=False,
            seed=seed,
        )
        self.units: list[Any] = []
        self.physical_units: list[Any] = []
        self.correction_events: list[_CorrectionEvent] = []
        self.event_observations: list[AdaptiveEventObservation] = []
        self.logical_error = False
        self.postselected = False
        # Standalone shot runners retain a private fallback cache for the
        # legacy/internal use case.  Protocol-created runners receive the
        # executor-owned cache below and never regenerate prepared paths.
        self._correction_map_cache = correction_map_cache or _CorrectionMapCache()
        self._stripped_suffix_cache = stripped_suffix_cache
        # logical measurement index -> physical measurement index.  It is
        # normally identity; a long synchronized pair has z-short, x-short,
        # z-extra, x-extra in the physical record but z-long, x-long in the
        # logical correction-map order.
        self.measurement_permutation: list[int] = []

    @staticmethod
    def _circuit_for_units(units: Sequence[Any]) -> stim.Circuit:
        circuit = stim.Circuit()
        for unit in units:
            circuit += unit.circuit
        return circuit

    @staticmethod
    def _noise_free_circuit_for_units(units: Sequence[Any]) -> stim.Circuit:
        return _noise_free_circuit_for_units(units)

    def _measurement_count(self, units: Sequence[Any] | None = None) -> int:
        return sum(unit.num_measurements for unit in (units or self.units))

    def _detector_count(self, units: Sequence[Any] | None = None) -> int:
        return sum(unit.num_detectors for unit in (units or self.units))

    def _physical_extra_circuit(
        self, description: AdaptiveStatePrepModule
    ) -> stim.Circuit:
        if self._stripped_suffix_cache is None:
            raise RuntimeError(
                "adaptive shot runner requires an executor-prepared suffix cache"
            )
        try:
            return self._stripped_suffix_cache[id(description)]
        except KeyError as error:
            raise RuntimeError(
                "adaptive suffix was not prepared for this module"
            ) from error

    def _correction_maps(self, units: Sequence[Any]) -> tuple[Any | None, ...]:
        key = _path_key(units)
        with _profile_section(self.profiler, "shot.correction_map.lookup"):
            maps = self._correction_map_cache.get(key)
        if maps is not None:
            return maps

        # This is only a compatibility fallback for a path not known during
        # executor preparation.  It is executor-scoped, so repeated shots do
        # not regenerate the same unseen path.
        with _profile_section(self.profiler, "shot.correction_map.fallback_miss"):
            pass
        with _profile_section(self.profiler, "shot.correction_map.fallback_generate"):
            return self._correction_map_cache.prepare(units)

    def _corrected_measurements(
        self,
        physical_units: Sequence[Any] | None = None,
        logical_units: Sequence[Any] | None = None,
        measurement_permutation: Sequence[int] | None = None,
    ) -> np.ndarray:
        physical_units = self.physical_units if physical_units is None else physical_units
        logical_units = self.units if logical_units is None else logical_units
        with _profile_section(
            self.profiler, "corrected_measurements.circuit_assembly"
        ):
            circuit = self._circuit_for_units(physical_units)
        with _profile_section(
            self.profiler, "corrected_measurements.get_measurement_flips"
        ):
            flips = self.simulator.get_measurement_flips()
        with _profile_section(
            self.profiler, "corrected_measurements.reference_sample"
        ):
            reference_sample = np.asarray(circuit.reference_sample(), dtype=bool)
        with _profile_section(
            self.profiler, "corrected_measurements.reconstruct"
        ):
            measurements = reconstruct_measurement_records(
                reference_sample,
                flips,
            )[0]
        logical_length = self._measurement_count(logical_units)
        if logical_length != measurements.shape[0]:
            raise RuntimeError(
                "logical and physical paths do not have the same measurement count"
            )
        permutation = list(
            self.measurement_permutation
            if measurement_permutation is None
            else measurement_permutation
        )
        if len(permutation) != logical_length:
            raise RuntimeError("measurement permutation has the wrong length")
        software_flips = np.zeros(measurements.shape, dtype=bool)
        with _profile_section(
            self.profiler, "corrected_measurements.correction_maps"
        ):
            maps = self._correction_maps(logical_units)
        with _profile_section(
            self.profiler, "corrected_measurements.software_frame"
        ):
            for correction_event in self.correction_events:
                correction_map = maps[correction_event.unit_index]
                if correction_map is None:
                    continue
                correction = np.asarray(correction_event.corrections).reshape(1, -1)
                logical_updates = (
                    csc_matrix(correction) @ correction_map
                ).toarray()[0] % 2
                physical_updates = np.zeros(measurements.shape, dtype=bool)
                physical_updates[np.asarray(permutation)] = logical_updates.astype(bool)
                software_flips ^= physical_updates
        return np.logical_xor(measurements, software_flips)

    def _append_unit(self, module: Any, result: ModuleDecodeResult) -> None:
        unit_index = len(self.units)
        self.units.append(module)
        self.physical_units.append(module)
        start = len(self.measurement_permutation)
        self.measurement_permutation.extend(
            range(start, start + module.num_measurements)
        )
        self.correction_events.append(
            _CorrectionEvent(
                unit_index=unit_index,
                module=module,
                corrections=np.asarray(result.corrections)[0],
            )
        )
        if result.postselection is not None:
            self.postselected ^= bool(np.asarray(result.postselection)[0])

    def _commit_logical_unit(
        self,
        module: Any,
        result: ModuleDecodeResult,
        physical_measurement_indices: Sequence[int] | None = None,
    ) -> None:
        """Commit a decoded module whose physical segment is already present."""

        unit_index = len(self.units)
        self.units.append(module)
        if physical_measurement_indices is None:
            start = len(self.measurement_permutation)
            physical_measurement_indices = range(
                start,
                start + module.num_measurements,
            )
        self.measurement_permutation.extend(physical_measurement_indices)
        self.correction_events.append(
            _CorrectionEvent(
                unit_index=unit_index,
                module=module,
                corrections=np.asarray(result.corrections)[0],
            )
        )
        if result.postselection is not None:
            self.postselected ^= bool(np.asarray(result.postselection)[0])

    def _run_adaptive_event(
        self,
        description: AdaptiveStatePrepModule,
    ) -> None:
        previous_measurements = self._measurement_count(self.physical_units)
        with _profile_section(self.profiler, "shot.physical.short.total"):
            with _profile_section(self.profiler, "shot.physical.short.zero"):
                self.simulator.do(description.short_circuit)
        self.physical_units.append(description.short_module)
        with _profile_section(self.profiler, "shot.reconstruction.short"):
            short_measurements = self._corrected_measurements(
                logical_units=self.units + [description.short_module],
                measurement_permutation=(
                    self.measurement_permutation
                    + list(
                        range(
                            previous_measurements,
                            previous_measurements + description.short_module.num_measurements,
                        )
                    )
                ),
            )
        short_local = short_measurements[
            previous_measurements : previous_measurements
            + description.short_module.num_measurements
        ]
        with _profile_section(self.profiler, "shot.decode.short.zero"):
            short_result = normalize_module_decode_output(
                description.short_rich_decoder(short_local.reshape(1, -1))
            )
        short_decode = short_result.decode_result or DecodeResult(
            correction=short_result.corrections
        )
        context = AdaptivePolicyContext(
            batch_size=1,
            event_id=description.event_id,
            teleportation_index=description.teleportation_index,
            state_basis=description.state_basis,
        )
        with _profile_section(self.profiler, "shot.policy.zero"):
            extend = np.asarray(
                description.schedule.policy.should_extend(
                    short_decode,
                    context=context,
                ),
                dtype=bool,
            )
        if extend.shape != (1,):
            raise ValueError("adaptive policy must return one boolean per shot")

        if bool(extend[0]):
            with _profile_section(self.profiler, "shot.physical.long.total"):
                extra_circuit = self._physical_extra_circuit(description)
                with _profile_section(self.profiler, "shot.physical.long.zero"):
                    self.simulator.do(extra_circuit)
            self.physical_units.append(
                _PhysicalSegment(
                    extra_circuit,
                    extra_circuit.num_measurements,
                )
            )
            with _profile_section(self.profiler, "shot.reconstruction.long"):
                long_measurements = self._corrected_measurements(
                    logical_units=self.units + [description.long_module],
                    measurement_permutation=(
                        self.measurement_permutation
                        + list(
                            range(
                                previous_measurements,
                                previous_measurements
                                + description.long_module.num_measurements,
                            )
                        )
                    ),
                )
            long_local = long_measurements[
                previous_measurements : previous_measurements
                + description.long_module.num_measurements
            ]
            with _profile_section(self.profiler, "shot.decode.long.zero"):
                selected_result = normalize_module_decode_output(
                    description.long_rich_decoder(long_local.reshape(1, -1))
                )
            selected_module = description.long_module
        else:
            selected_result = short_result
            selected_module = description.short_module

        confidence = (
            float(np.asarray(short_decode.confidence).reshape(-1)[0])
            if short_decode.confidence is not None
            else None
        )
        with _profile_section(self.profiler, "shot.result.bookkeeping"):
            self.event_observations.append(
                AdaptiveEventObservation(
                    event_id=description.event_id,
                    teleportation_index=description.teleportation_index,
                    state_basis=description.state_basis,
                    confidence=confidence,
                    used_long=bool(extend[0]),
                    would_extend=bool(extend[0]),
                )
            )
        with _profile_section(self.profiler, "shot.state_prep.correction_commit"):
            self._commit_logical_unit(selected_module, selected_result)

    def _run_adaptive_pair(
        self,
        z_description: AdaptiveStatePrepModule,
        x_description: AdaptiveStatePrepModule,
    ) -> None:
        """Execute the two ancilla patches with one synchronized decision.

        The physical order is ``z-short, x-short, z-extra, x-extra`` so both
        short histories exist before either policy is evaluated.  The logical
        correction-map order is kept as ``z, x``; ``measurement_permutation``
        translates that order into the physical record order.
        """

        previous_measurements = self._measurement_count(self.physical_units)
        with _profile_section(self.profiler, "shot.physical.short.total"):
            with _profile_section(self.profiler, "shot.physical.short.zero"):
                self.simulator.do(z_description.short_circuit)
            self.physical_units.append(z_description.short_module)
            z_short_count = z_description.short_module.num_measurements
            with _profile_section(self.profiler, "shot.physical.short.plus"):
                self.simulator.do(x_description.short_circuit)
            self.physical_units.append(x_description.short_module)
            x_short_count = x_description.short_module.num_measurements

        short_logical_units = self.units + [
            z_description.short_module,
            x_description.short_module,
        ]
        short_permutation = self.measurement_permutation + list(
            range(
                previous_measurements,
                previous_measurements + z_short_count + x_short_count,
            )
        )
        with _profile_section(self.profiler, "shot.reconstruction.short"):
            short_measurements = self._corrected_measurements(
                logical_units=short_logical_units,
                measurement_permutation=short_permutation,
            )
        z_short_local = short_measurements[
            previous_measurements : previous_measurements + z_short_count
        ]
        x_short_local = short_measurements[
            previous_measurements
            + z_short_count : previous_measurements
            + z_short_count
            + x_short_count
        ]

        with _profile_section(self.profiler, "shot.decode.short.zero"):
            z_short_result = normalize_module_decode_output(
                z_description.short_rich_decoder(z_short_local.reshape(1, -1))
            )
        with _profile_section(self.profiler, "shot.decode.short.plus"):
            x_short_result = normalize_module_decode_output(
                x_description.short_rich_decoder(x_short_local.reshape(1, -1))
            )
        z_short_decode = z_short_result.decode_result or DecodeResult(
            correction=z_short_result.corrections
        )
        x_short_decode = x_short_result.decode_result or DecodeResult(
            correction=x_short_result.corrections
        )

        def policy_decision(
            description: AdaptiveStatePrepModule,
            result: DecodeResult,
        ) -> bool:
            context = AdaptivePolicyContext(
                batch_size=1,
                event_id=description.event_id,
                teleportation_index=description.teleportation_index,
                state_basis=description.state_basis,
            )
            decision = np.asarray(
                description.schedule.policy.should_extend(
                    result,
                    context=context,
                ),
                dtype=bool,
            )
            if decision.shape != (1,):
                raise ValueError("adaptive policy must return one boolean per shot")
            return bool(decision[0])

        # Generic pair-level control rule: each patch's own AdaptivePolicy
        # interprets its own confidence (direction/threshold are policy
        # responsibilities, e.g. ClusterLLRPolicy's risk-like `>` versus a
        # metric where smaller means less confident), and the pair decision
        # is the boolean OR of those two independent decisions. Do not
        # replace this with a raw max/min comparison of the two patches'
        # confidence values -- that would hard-code one metric's direction
        # convention into the pair-level executor. `pair_risk`, computed
        # below from confidence alone, is diagnostic metadata only and must
        # never feed back into this decision.
        with _profile_section(self.profiler, "shot.policy.zero"):
            z_would_extend = policy_decision(z_description, z_short_decode)
        with _profile_section(self.profiler, "shot.policy.plus"):
            x_would_extend = policy_decision(x_description, x_short_decode)
        with _profile_section(self.profiler, "shot.policy.synchronized_or"):
            extend_pair = z_would_extend or x_would_extend

        if extend_pair:
            with _profile_section(self.profiler, "shot.physical.long.total"):
                z_extra_circuit = self._physical_extra_circuit(z_description)
                with _profile_section(self.profiler, "shot.physical.long.zero"):
                    self.simulator.do(z_extra_circuit)
                z_extra = _PhysicalSegment(
                    z_extra_circuit,
                    z_extra_circuit.num_measurements,
                )
                self.physical_units.append(z_extra)
                x_extra_circuit = self._physical_extra_circuit(x_description)
                with _profile_section(self.profiler, "shot.physical.long.plus"):
                    self.simulator.do(x_extra_circuit)
                x_extra = _PhysicalSegment(
                    x_extra_circuit,
                    x_extra_circuit.num_measurements,
                )
                self.physical_units.append(x_extra)

            z_extra_start = previous_measurements + z_short_count + x_short_count
            x_extra_start = z_extra_start + z_extra.num_measurements
            z_indices = list(range(previous_measurements, previous_measurements + z_short_count))
            z_indices += list(range(z_extra_start, z_extra_start + z_extra.num_measurements))
            x_indices = list(range(previous_measurements + z_short_count, previous_measurements + z_short_count + x_short_count))
            x_indices += list(range(x_extra_start, x_extra_start + x_extra.num_measurements))
            long_permutation = self.measurement_permutation + z_indices + x_indices
            long_logical_units = self.units + [
                z_description.long_module,
                x_description.long_module,
            ]
            with _profile_section(self.profiler, "shot.reconstruction.long"):
                long_measurements = self._corrected_measurements(
                    logical_units=long_logical_units,
                    measurement_permutation=long_permutation,
                )
            z_long_local = np.concatenate(
                [
                    long_measurements[
                        previous_measurements : previous_measurements + z_short_count
                    ],
                    long_measurements[
                        z_extra_start : z_extra_start + z_extra.num_measurements
                    ],
                ]
            )
            x_long_local = np.concatenate(
                [
                    long_measurements[
                        previous_measurements + z_short_count : previous_measurements
                        + z_short_count + x_short_count
                    ],
                    long_measurements[
                        x_extra_start : x_extra_start + x_extra.num_measurements
                    ],
                ]
            )
            with _profile_section(self.profiler, "shot.decode.long.zero"):
                z_result = normalize_module_decode_output(
                    z_description.long_rich_decoder(z_long_local.reshape(1, -1))
                )
            with _profile_section(self.profiler, "shot.decode.long.plus"):
                x_result = normalize_module_decode_output(
                    x_description.long_rich_decoder(x_long_local.reshape(1, -1))
                )
            z_module = z_description.long_module
            x_module = x_description.long_module
            z_selected_indices = z_indices
            x_selected_indices = x_indices
        else:
            z_result = z_short_result
            x_result = x_short_result
            z_module = z_description.short_module
            x_module = x_description.short_module
            z_selected_indices = list(
                range(previous_measurements, previous_measurements + z_short_count)
            )
            x_selected_indices = list(
                range(
                    previous_measurements + z_short_count,
                    previous_measurements + z_short_count + x_short_count,
                )
            )

        def confidence(result: DecodeResult) -> float | None:
            if result.confidence is None:
                return None
            return float(np.asarray(result.confidence).reshape(-1)[0])

        z_confidence = confidence(z_short_decode)
        x_confidence = confidence(x_short_decode)
        # Diagnostic only: this max() assumes a risk-like convention (larger
        # == less confident), which happens to be true for Cluster LLR. It
        # is exposed for analysis/plotting and is never read back into
        # `extend_pair` above.
        pair_risk = (
            max(z_confidence, x_confidence)
            if z_confidence is not None and x_confidence is not None
            else None
        )
        pair_id = f"teleportation={z_description.teleportation_index}"
        with _profile_section(self.profiler, "shot.result.bookkeeping"):
            self.event_observations.extend([
                AdaptiveEventObservation(
                    event_id=z_description.event_id,
                    teleportation_index=z_description.teleportation_index,
                    state_basis=z_description.state_basis,
                    confidence=z_confidence,
                    used_long=extend_pair,
                    would_extend=z_would_extend,
                    pair_id=pair_id,
                    pair_risk=pair_risk,
                ),
                AdaptiveEventObservation(
                    event_id=x_description.event_id,
                    teleportation_index=x_description.teleportation_index,
                    state_basis=x_description.state_basis,
                    confidence=x_confidence,
                    used_long=extend_pair,
                    would_extend=x_would_extend,
                    pair_id=pair_id,
                    pair_risk=pair_risk,
                ),
            ])
        with _profile_section(self.profiler, "shot.state_prep.correction_commit"):
            self._commit_logical_unit(z_module, z_result, z_selected_indices)
            self._commit_logical_unit(x_module, x_result, x_selected_indices)

    def _run_standard_module(self, module: Any) -> None:
        previous_measurements = self._measurement_count()
        previous_detectors = self._detector_count()
        role = getattr(module, "_profile_role", None)
        physical_name = (
            f"shot.downstream.{role}.physical"
            if role is not None
            else "shot.standard.physical"
        )
        with _profile_section(self.profiler, physical_name):
            self.simulator.do(module.circuit)
        self.physical_units.append(module)
        logical_units = self.units + [module]
        reconstruction_name = (
            f"shot.downstream.{role}.measurement_reconstruction"
            if role is not None
            else "shot.standard.measurement_reconstruction"
        )
        commit_name = (
            f"shot.downstream.{role}.correction_commit"
            if role is not None
            else "shot.standard.correction_commit"
        )
        with _profile_section(self.profiler, reconstruction_name):
            measurements = self._corrected_measurements(
                logical_units=logical_units,
                measurement_permutation=(
                    self.measurement_permutation
                    + list(
                        range(
                            previous_measurements,
                            previous_measurements + module.num_measurements,
                        )
                    )
                ),
            )

        if isinstance(module, no_measurement_module):
            with _profile_section(self.profiler, commit_name):
                self._commit_logical_unit(
                    module,
                    ModuleDecodeResult(corrections=np.zeros((1, 0), dtype=np.uint8)),
                )
            return

        local_measurements = measurements[
            previous_measurements : previous_measurements + module.num_measurements
        ]
        if isinstance(module, logical_measurement_module):
            decode_name = (
                f"shot.downstream.{role}.online_decode"
                if role is not None
                else "shot.standard.decode"
            )
            with _profile_section(self.profiler, decode_name):
                values = module.c_func(local_measurements.reshape(1, -1))
                expected = np.asarray(module.c_func_expected_output)
                self.logical_error |= bool(np.any(values[0] != expected))
            with _profile_section(self.profiler, commit_name):
                self._commit_logical_unit(
                    module,
                    ModuleDecodeResult(corrections=np.zeros((1, 0), dtype=np.uint8)),
                )
            return

        if isinstance(module, only_postselection_module):
            self.postselected ^= bool(module.c_func(local_measurements.reshape(1, -1))[0])
            with _profile_section(self.profiler, commit_name):
                self._commit_logical_unit(
                    module,
                    ModuleDecodeResult(corrections=np.zeros((1, 0), dtype=np.uint8)),
                )
            return

        if isinstance(module, detector_module):
            converter = self._circuit_for_units(self.physical_units).compile_m2d_converter()
            detector_flips, _ = converter.convert(
                measurements=measurements.reshape(1, -1),
                separate_observables=True,
            )
            local_input = detector_flips[
                :, previous_detectors : previous_detectors + module.num_detectors
            ]
        elif isinstance(module, (measurement_module, css_detector_module)):
            local_input = local_measurements.reshape(1, -1)
        else:
            raise TypeError(f"Unknown module type: {type(module)!r}")

        decode_name = (
            f"shot.downstream.{role}.online_decode"
            if role is not None
            else "shot.standard.decode"
        )
        with _profile_section(self.profiler, decode_name):
            result = normalize_module_decode_output(module.c_func(local_input))
        with _profile_section(self.profiler, commit_name):
            self._commit_logical_unit(module, result)

    def run(self, modules: Sequence[Any]) -> tuple[bool, bool, list[AdaptiveEventObservation]]:
        index = 0
        while index < len(modules):
            module = modules[index]
            if (
                isinstance(module, AdaptiveStatePrepModule)
                and index + 1 < len(modules)
                and isinstance(modules[index + 1], AdaptiveStatePrepModule)
                and module.teleportation_index is not None
                and module.teleportation_index == modules[index + 1].teleportation_index
                and {module.state_basis, modules[index + 1].state_basis} == {"x", "z"}
            ):
                z_module, x_module = (
                    (module, modules[index + 1])
                    if module.state_basis == "z"
                    else (modules[index + 1], module)
                )
                self._run_adaptive_pair(z_module, x_module)
                index += 2
                continue
            if isinstance(module, AdaptiveStatePrepModule):
                self._run_adaptive_event(module)
            else:
                role = getattr(module, "_profile_role", None)
                stage_name = (
                    f"shot.downstream.{role}"
                    if role is not None
                    else "shot.standard"
                )
                with _profile_section(self.profiler, stage_name):
                    self._run_standard_module(module)
            index += 1

        with _profile_section(self.profiler, "shot.final.detector_validation"):
            circuit = self._circuit_for_units(self.physical_units)
            corrected = self._corrected_measurements()
        if circuit.num_detectors:
            with _profile_section(
                self.profiler, "shot.final.detector_validation.convert"
            ):
                detector_flips, _ = circuit.compile_m2d_converter().convert(
                    measurements=corrected.reshape(1, -1),
                    separate_observables=True,
                )
            if np.any(detector_flips):
                raise RuntimeError("adaptive software corrections left detector flips")
        return self.logical_error, self.postselected, self.event_observations


class StatefulAdaptiveKnillExecutor:
    """Reference adaptive executor for a sequence containing state-prep events."""

    def __init__(
        self,
        modules: Sequence[Any],
        *,
        batch_size: int = 256,
        seed: int | None = None,
    ) -> None:
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        self.modules = list(modules)
        self.batch_size = batch_size
        self.seed = seed
        self.profiler = self._find_profiler(self.modules)
        self._correction_map_cache = _CorrectionMapCache()
        self._precompute_correction_maps(self.profiler)
        self._stripped_suffix_cache: dict[int, stim.Circuit] = {}
        self._precompute_stripped_suffixes(self.profiler)

    @staticmethod
    def _find_profiler(modules: Sequence[Any]) -> Any | None:
        """Find the opt-in profiler carried by constructed CSS modules."""

        for module in modules:
            candidates = [module]
            if isinstance(module, AdaptiveStatePrepModule):
                candidates.extend([module.short_module, module.long_module])
            for candidate in candidates:
                profiler = getattr(candidate, "profiler", None)
                if profiler is not None:
                    return profiler
        return None

    @staticmethod
    def _is_adaptive_pair(
        modules: Sequence[Any], index: int
    ) -> bool:
        if index + 1 >= len(modules):
            return False
        first = modules[index]
        second = modules[index + 1]
        return (
            isinstance(first, AdaptiveStatePrepModule)
            and isinstance(second, AdaptiveStatePrepModule)
            and first.teleportation_index is not None
            and first.teleportation_index == second.teleportation_index
            and {first.state_basis, second.state_basis} == {"x", "z"}
        )

    def _planned_logical_paths(
        self, choices: Sequence[bool]
    ) -> list[tuple[Any, ...]]:
        """List map paths for one planned short/long branch pattern.

        The planner mirrors the existing runner's logical-unit commits.  It
        records both the short-decode prefix and, for a long choice, the
        complete long path.  For multiple adaptive events the caller plans
        only common all-short/all-long patterns; an unseen mixed pattern uses
        the executor-level one-time fallback in ``_correction_maps``.
        """

        paths: list[tuple[Any, ...]] = []
        logical_units: list[Any] = []
        choice_index = 0
        index = 0
        while index < len(self.modules):
            module = self.modules[index]
            if self._is_adaptive_pair(self.modules, index):
                other = self.modules[index + 1]
                z_description, x_description = (
                    (module, other)
                    if module.state_basis == "z"
                    else (other, module)
                )
                short_path = tuple(
                    [*logical_units, z_description.short_module, x_description.short_module]
                )
                paths.append(short_path)
                use_long = bool(choices[choice_index])
                if use_long:
                    paths.append(tuple([
                        *logical_units,
                        z_description.long_module,
                        x_description.long_module,
                    ]))
                    logical_units.extend([
                        z_description.long_module,
                        x_description.long_module,
                    ])
                else:
                    logical_units.extend([
                        z_description.short_module,
                        x_description.short_module,
                    ])
                choice_index += 1
                index += 2
                continue
            if isinstance(module, AdaptiveStatePrepModule):
                paths.append(tuple([*logical_units, module.short_module]))
                use_long = bool(choices[choice_index])
                if use_long:
                    paths.append(tuple([*logical_units, module.long_module]))
                    logical_units.append(module.long_module)
                else:
                    logical_units.append(module.short_module)
                choice_index += 1
            else:
                logical_units.append(module)
                paths.append(tuple(logical_units))
            index += 1
        paths.append(tuple(logical_units))
        return paths

    def _precompute_correction_maps(self, profiler: Any | None) -> None:
        adaptive_count = sum(
            1
            for index, module in enumerate(self.modules)
            if isinstance(module, AdaptiveStatePrepModule)
            and not (
                index > 0
                and self._is_adaptive_pair(self.modules, index - 1)
            )
        )
        if adaptive_count == 0:
            choice_patterns: tuple[tuple[bool, ...], ...] = ((),)
        elif adaptive_count == 1:
            choice_patterns = ((False,), (True,))
        else:
            # Avoid exponential path enumeration.  These cover the common
            # forced-short and forced-long workflows; mixed paths are still
            # cached exactly once when first encountered by this executor.
            choice_patterns = (
                (False,) * adaptive_count,
                (True,) * adaptive_count,
            )

        planned_paths: list[tuple[Any, ...]] = []
        seen: set[tuple[int, ...]] = set()
        for choices in choice_patterns:
            for path in self._planned_logical_paths(choices):
                key = _path_key(path)
                if key not in seen:
                    seen.add(key)
                    planned_paths.append(path)

        with _profile_section(
            profiler, "setup.correction_map_precompute"
        ):
            for path in planned_paths:
                if self._correction_map_cache.get(_path_key(path)) is not None:
                    continue
                with _profile_section(profiler, "setup.correction_map.generate"):
                    self._correction_map_cache.prepare(path)

    def _precompute_stripped_suffixes(self, profiler: Any | None) -> None:
        with _profile_section(profiler, "setup.suffix_precompute"):
            for module in self.modules:
                if not isinstance(module, AdaptiveStatePrepModule):
                    continue
                module_key = id(module)
                if module_key in self._stripped_suffix_cache:
                    continue
                basis = (
                    "zero"
                    if module.state_basis == "z"
                    else "plus"
                    if module.state_basis == "x"
                    else "other"
                )
                with _profile_section(
                    profiler, f"setup.suffix_precompute.{basis}"
                ):
                    self._stripped_suffix_cache[module_key] = _without_detectors(
                        module.extra_circuit
                    )

    def _run_batch(
        self,
        batch_number: int,
        *,
        profiler: Any = None,
        profile_phase: str = "measured",
        profile_shot_offset: int = 0,
    ) -> tuple[np.ndarray, np.ndarray, list[list[AdaptiveEventObservation]]]:
        errors = np.zeros(self.batch_size, dtype=bool)
        postselected = np.zeros(self.batch_size, dtype=bool)
        observations: list[list[AdaptiveEventObservation]] = []
        for shot in range(self.batch_size):
            shot_seed = None
            if self.seed is not None:
                shot_seed = (self.seed + batch_number * self.batch_size + shot) % (2**64)
            shot_context = (
                profiler.shot(
                    profile_shot_offset + batch_number * self.batch_size + shot,
                    phase=profile_phase,
                )
                if profiler is not None
                else nullcontext()
            )
            with shot_context:
                runner = _AdaptiveShotRunner(
                    seed=shot_seed,
                    profiler=profiler,
                    correction_map_cache=self._correction_map_cache,
                    stripped_suffix_cache=self._stripped_suffix_cache,
                )
                error, postselection, shot_observations = runner.run(self.modules)
            errors[shot] = error
            postselected[shot] = postselection
            observations.append(shot_observations)
        return errors, postselected, observations

    def simulate_result(
        self,
        max_shots: int,
        max_errors_before_halting: int,
        *,
        detail_level: str = "summary",
        profiler: Any = None,
        profile_phase: str = "measured",
        profile_shot_offset: int = 0,
    ):
        from hex_qec.modularisation.results import (
            AdaptiveBellPairStats,
            AdaptiveStatePrepStats,
            SimulationResult,
            SimulationSummary,
            validate_simulation_detail_level,
        )
        import time

        detail_level = validate_simulation_detail_level(detail_level)
        start = time.perf_counter()
        total_errors = 0
        total_postselected_errors = 0
        total_shots = 0
        all_observations: list[list[AdaptiveEventObservation]] = []
        all_errors: list[np.ndarray] = []
        all_postselected: list[np.ndarray] = []
        event_order: list[tuple[str | None, int | None, str | None]] = []
        batch_number = 0
        while (
            total_postselected_errors < max_errors_before_halting
            and self.batch_size * batch_number < max_shots
        ):
            errors, postselected, observations = self._run_batch(
                batch_number,
                profiler=profiler,
                profile_phase=profile_phase,
                profile_shot_offset=profile_shot_offset,
            )
            if observations and not event_order:
                event_order = [
                    (item.event_id, item.teleportation_index, item.state_basis)
                    for item in observations[0]
                ]
            bookkeeping = (
                profiler.context_scope(
                    shot_index=-1,
                    phase=profile_phase,
                )
                if profiler is not None
                else nullcontext()
            )
            with bookkeeping:
                with _profile_section(profiler, "result.accumulation"):
                    total_errors += int(np.sum(errors))
                    total_postselected_errors += int(np.sum(~postselected & errors))
                    total_shots += self.batch_size
                    all_observations.extend(observations)
                    all_errors.append(errors)
                    all_postselected.append(postselected)
            batch_number += 1

        final_errors = np.concatenate(all_errors) if all_errors else np.zeros(0, dtype=bool)
        final_postselected = (
            np.concatenate(all_postselected) if all_postselected else np.zeros(0, dtype=bool)
        )
        event_stats: list[AdaptiveStatePrepStats] = []
        confidence_matrix = np.full((total_shots, len(event_order)), np.nan)
        pair_risk_matrix = np.full((total_shots, len(event_order)), np.nan)
        used_long_matrix = np.zeros((total_shots, len(event_order)), dtype=bool)
        would_extend_matrix = np.zeros((total_shots, len(event_order)), dtype=bool)
        for event_index, (event_id, teleportation_index, state_basis) in enumerate(event_order):
            event_observations = [shot[event_index] for shot in all_observations]
            used_long = np.array([item.used_long for item in event_observations], dtype=bool)
            confidences = np.array([
                np.nan if item.confidence is None else item.confidence
                for item in event_observations
            ])
            confidence_matrix[:, event_index] = confidences
            pair_risk_matrix[:, event_index] = np.array([
                np.nan if item.pair_risk is None else item.pair_risk
                for item in event_observations
            ])
            used_long_matrix[:, event_index] = used_long
            would_extend_matrix[:, event_index] = np.array(
                [bool(item.would_extend) for item in event_observations],
                dtype=bool,
            )
            finite = confidences[np.isfinite(confidences)]
            event_stats.append(
                AdaptiveStatePrepStats(
                    event_id=event_id or f"event[{event_index}]",
                    teleportation_index=teleportation_index,
                    state_basis=state_basis,
                    short_rounds=None,
                    long_rounds=None,
                    short_count=int(np.sum(~used_long)),
                    long_count=int(np.sum(used_long)),
                    fallback_rate=float(np.mean(used_long)),
                    confidence_metric="DecodeResult.confidence",
                    confidence_summary=(
                        {
                            "mean": float(np.mean(finite)),
                            "min": float(np.min(finite)),
                            "max": float(np.max(finite)),
                        }
                        if finite.size
                        else {}
                    ),
                    average_se_rounds=None,
                    logical_error_count=int(np.sum(final_errors)),
                )
            )
            # Round counts are available from the corresponding description.
            for module in self.modules:
                if isinstance(module, AdaptiveStatePrepModule) and module.event_id == event_id:
                    event_stats[-1].short_rounds = module.schedule.short_rounds
                    event_stats[-1].long_rounds = module.schedule.long_rounds
                    event_stats[-1].average_se_rounds = float(
                        np.mean(
                            np.where(
                                used_long,
                                module.schedule.long_rounds,
                                module.schedule.short_rounds,
                            )
                        )
                    )
                    break

        bell_pair_stats: list[AdaptiveBellPairStats] = []
        pair_columns: list[tuple[str, int, int]] = []
        if event_order:
            for event_index in range(0, len(event_order) - 1, 2):
                first = event_order[event_index]
                second = event_order[event_index + 1]
                first_pair = all_observations[0][event_index].pair_id
                second_pair = all_observations[0][event_index + 1].pair_id
                if first_pair is None or first_pair != second_pair:
                    continue
                pair_columns.append((first_pair, event_index, event_index + 1))
                pair_used_long = used_long_matrix[:, event_index]
                if not np.array_equal(
                    pair_used_long,
                    used_long_matrix[:, event_index + 1],
                ):
                    raise RuntimeError("Bell-pair patches selected different SE depths")
                z_would = would_extend_matrix[:, event_index]
                x_would = would_extend_matrix[:, event_index + 1]
                z_only = z_would & ~x_would & pair_used_long
                x_only = x_would & ~z_would & pair_used_long
                both = z_would & x_would & pair_used_long
                short_rounds = next(
                    module.schedule.short_rounds
                    for module in self.modules
                    if isinstance(module, AdaptiveStatePrepModule)
                    and module.event_id == first[0]
                )
                long_rounds = next(
                    module.schedule.long_rounds
                    for module in self.modules
                    if isinstance(module, AdaptiveStatePrepModule)
                    and module.event_id == first[0]
                )
                selected_rounds = np.where(
                    pair_used_long,
                    long_rounds,
                    short_rounds,
                )
                z_risk = confidence_matrix[:, event_index]
                x_risk = confidence_matrix[:, event_index + 1]
                pair_risk = np.maximum(z_risk, x_risk)
                finite_z = z_risk[np.isfinite(z_risk)]
                finite_x = x_risk[np.isfinite(x_risk)]
                finite_pair = pair_risk[np.isfinite(pair_risk)]
                shots = len(pair_used_long)
                denominator = float(shots) if shots else 1.0
                bell_pair_stats.append(
                    AdaptiveBellPairStats(
                        pair_id=first_pair,
                        teleportation_index=first[1],
                        short_rounds=short_rounds,
                        long_rounds=long_rounds,
                        short_count=int(np.sum(~pair_used_long)),
                        long_count=int(np.sum(pair_used_long)),
                        pair_fallback_rate=float(np.mean(pair_used_long)) if shots else 0.0,
                        pair_short_fraction=float(np.mean(~pair_used_long)) if shots else 0.0,
                        pair_long_fraction=float(np.mean(pair_used_long)) if shots else 0.0,
                        mean_effective_rounds=float(np.mean(selected_rounds)) if shots else 0.0,
                        z_only_count=int(np.sum(z_only)),
                        x_only_count=int(np.sum(x_only)),
                        both_count=int(np.sum(both)),
                        z_only_fallback_fraction=float(np.sum(z_only) / denominator),
                        x_only_fallback_fraction=float(np.sum(x_only) / denominator),
                        both_fallback_fraction=float(np.sum(both) / denominator),
                        mean_z_patch_risk=float(np.mean(finite_z)) if finite_z.size else None,
                        mean_x_patch_risk=float(np.mean(finite_x)) if finite_x.size else None,
                        mean_pair_risk=float(np.mean(finite_pair)) if finite_pair.size else None,
                    )
                )

        per_shot = None
        if detail_level in {"analysis", "debug"}:
            per_shot = {
                "final_logical_error": final_errors,
                "postselected": final_postselected,
                "confidence": confidence_matrix,
                "pair_risk": pair_risk_matrix,
                "used_long": used_long_matrix,
                "would_extend": would_extend_matrix,
                "used_long_pair": np.column_stack(
                    [used_long_matrix[:, z_index] for _, z_index, _ in pair_columns]
                )
                if pair_columns
                else np.zeros((total_shots, 0), dtype=bool),
                # Per-pair patch confidence/decision, named by state-basis
                # convention (z == |0_L>, x == |+_L>) rather than combined:
                # requirement is that patch-level decisions stay separate
                # until the pair-level OR (see used_long_pair above).
                "confidence_zero": np.column_stack(
                    [confidence_matrix[:, z_index] for _, z_index, _ in pair_columns]
                )
                if pair_columns
                else np.zeros((total_shots, 0)),
                "confidence_plus": np.column_stack(
                    [confidence_matrix[:, x_index] for _, _, x_index in pair_columns]
                )
                if pair_columns
                else np.zeros((total_shots, 0)),
                "would_extend_zero": np.column_stack(
                    [would_extend_matrix[:, z_index] for _, z_index, _ in pair_columns]
                )
                if pair_columns
                else np.zeros((total_shots, 0), dtype=bool),
                "would_extend_plus": np.column_stack(
                    [would_extend_matrix[:, x_index] for _, _, x_index in pair_columns]
                )
                if pair_columns
                else np.zeros((total_shots, 0), dtype=bool),
                "event_id": np.asarray([x[0] for x in event_order], dtype=object),
                "teleportation_index": np.asarray(
                    [x[1] if x[1] is not None else -1 for x in event_order],
                    dtype=int,
                ),
                "state_basis": np.asarray([x[2] for x in event_order], dtype=object),
            }
        return SimulationResult(
            summary=SimulationSummary(
                shots=total_shots,
                logical_errors=total_errors,
                logical_error_rate=(total_errors / total_shots if total_shots else 0.0),
                runtime_seconds=time.perf_counter() - start,
            ),
            state_prep_stats=event_stats,
            bell_pair_stats=bell_pair_stats,
            metadata={
                "execution_backend": "adaptive_stateful_flip_simulator",
                "adaptive": True,
                "batch_size": self.batch_size,
                "num_modules": len(self.modules),
                "num_state_prep_events": len(event_order),
            },
            per_shot=per_shot,
            detail_level=detail_level,
        )

    def simulate(self, max_shots: int, max_errors_before_halting: int) -> tuple[int, int]:
        result = self.simulate_result(
            max_shots=max_shots,
            max_errors_before_halting=max_errors_before_halting,
        )
        return result.to_legacy_tuple()
