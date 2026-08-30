"""Stateful two-level adaptive state-preparation execution."""

from dataclasses import dataclass
from typing import Any, Sequence

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


@dataclass
class _CorrectionEvent:
    unit_index: int
    module: Any
    corrections: np.ndarray


class _AdaptiveShotRunner:
    """Unoptimized one-shot executor used by the adaptive protocol path."""

    def __init__(self, *, seed: int | None) -> None:
        self.simulator = stim.FlipSimulator(
            batch_size=1,
            disable_stabilizer_randomization=False,
            seed=seed,
        )
        self.units: list[Any] = []
        self.correction_events: list[_CorrectionEvent] = []
        self.event_observations: list[AdaptiveEventObservation] = []
        self.logical_error = False
        self.postselected = False
        self._map_cache: dict[tuple[int, ...], list[Any | None]] = {}

    @staticmethod
    def _circuit_for_units(units: Sequence[Any]) -> stim.Circuit:
        circuit = stim.Circuit()
        for unit in units:
            circuit += unit.circuit
        return circuit

    @staticmethod
    def _noise_free_circuit_for_units(units: Sequence[Any]) -> stim.Circuit:
        circuit = stim.Circuit()
        for unit in units:
            circuit += unit.circuit.without_noise()
        return circuit

    def _measurement_count(self, units: Sequence[Any] | None = None) -> int:
        return sum(unit.num_measurements for unit in (units or self.units))

    def _detector_count(self, units: Sequence[Any] | None = None) -> int:
        return sum(unit.num_detectors for unit in (units or self.units))

    def _correction_maps(self, units: Sequence[Any]) -> list[Any | None]:
        key = tuple(id(unit) for unit in units)
        if key in self._map_cache:
            return self._map_cache[key]

        maps: list[Any | None] = []
        previous_detectors = 0
        for index, module in enumerate(units):
            before = self._noise_free_circuit_for_units(units[:index])
            after = self._noise_free_circuit_for_units(units[index + 1 :])
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
        self._map_cache[key] = maps
        return maps

    def _corrected_measurements(self, units: Sequence[Any]) -> np.ndarray:
        circuit = self._circuit_for_units(units)
        flips = self.simulator.get_measurement_flips()
        measurements = reconstruct_measurement_records(
            np.asarray(circuit.reference_sample(), dtype=bool),
            flips,
        )[0]
        software_flips = np.zeros(measurements.shape, dtype=bool)
        maps = self._correction_maps(units)
        for correction_event in self.correction_events:
            correction_map = maps[correction_event.unit_index]
            if correction_map is None:
                continue
            correction = np.asarray(correction_event.corrections).reshape(1, -1)
            updates = (csc_matrix(correction) @ correction_map).toarray()[0] % 2
            software_flips ^= updates.astype(bool)
        return np.logical_xor(measurements, software_flips)

    def _append_unit(self, module: Any, result: ModuleDecodeResult) -> None:
        unit_index = len(self.units)
        self.units.append(module)
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
        previous_measurements = self._measurement_count()
        self.simulator.do(description.short_circuit)
        short_units = self.units + [description.short_module]
        short_measurements = self._corrected_measurements(short_units)
        short_local = short_measurements[
            previous_measurements : previous_measurements
            + description.short_module.num_measurements
        ]
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
            self.simulator.do(description.extra_circuit)
            long_units = self.units + [description.long_module]
            long_measurements = self._corrected_measurements(long_units)
            long_local = long_measurements[
                previous_measurements : previous_measurements
                + description.long_module.num_measurements
            ]
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
        self.event_observations.append(
            AdaptiveEventObservation(
                event_id=description.event_id,
                teleportation_index=description.teleportation_index,
                state_basis=description.state_basis,
                confidence=confidence,
                used_long=bool(extend[0]),
            )
        )
        self._append_unit(selected_module, selected_result)

    def _run_standard_module(self, module: Any) -> None:
        previous_measurements = self._measurement_count()
        previous_detectors = self._detector_count()
        self.simulator.do(module.circuit)
        units = self.units + [module]
        measurements = self._corrected_measurements(units)

        if isinstance(module, no_measurement_module):
            self.units.append(module)
            return

        local_measurements = measurements[
            previous_measurements : previous_measurements + module.num_measurements
        ]
        if isinstance(module, logical_measurement_module):
            values = module.c_func(local_measurements.reshape(1, -1))
            expected = np.asarray(module.c_func_expected_output)
            self.logical_error |= bool(np.any(values[0] != expected))
            self.units.append(module)
            return

        if isinstance(module, only_postselection_module):
            self.postselected ^= bool(module.c_func(local_measurements.reshape(1, -1))[0])
            self.units.append(module)
            return

        if isinstance(module, detector_module):
            converter = self._circuit_for_units(units).compile_m2d_converter()
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

        result = normalize_module_decode_output(module.c_func(local_input))
        self._append_unit(module, result)

    def run(self, modules: Sequence[Any]) -> tuple[bool, bool, list[AdaptiveEventObservation]]:
        for module in modules:
            if isinstance(module, AdaptiveStatePrepModule):
                self._run_adaptive_event(module)
            else:
                self._run_standard_module(module)

        circuit = self._circuit_for_units(self.units)
        corrected = self._corrected_measurements(self.units)
        if circuit.num_detectors:
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

    def _run_batch(self, batch_number: int) -> tuple[np.ndarray, np.ndarray, list[list[AdaptiveEventObservation]]]:
        errors = np.zeros(self.batch_size, dtype=bool)
        postselected = np.zeros(self.batch_size, dtype=bool)
        observations: list[list[AdaptiveEventObservation]] = []
        for shot in range(self.batch_size):
            shot_seed = None
            if self.seed is not None:
                shot_seed = (self.seed + batch_number * self.batch_size + shot) % (2**64)
            runner = _AdaptiveShotRunner(seed=shot_seed)
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
    ):
        from hex_qec.modularisation.results import (
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
            errors, postselected, observations = self._run_batch(batch_number)
            if observations and not event_order:
                event_order = [
                    (item.event_id, item.teleportation_index, item.state_basis)
                    for item in observations[0]
                ]
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
        used_long_matrix = np.zeros((total_shots, len(event_order)), dtype=bool)
        for event_index, (event_id, teleportation_index, state_basis) in enumerate(event_order):
            event_observations = [shot[event_index] for shot in all_observations]
            used_long = np.array([item.used_long for item in event_observations], dtype=bool)
            confidences = np.array([
                np.nan if item.confidence is None else item.confidence
                for item in event_observations
            ])
            confidence_matrix[:, event_index] = confidences
            used_long_matrix[:, event_index] = used_long
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

        per_shot = None
        if detail_level in {"analysis", "debug"}:
            per_shot = {
                "final_logical_error": final_errors,
                "postselected": final_postselected,
                "confidence": confidence_matrix,
                "used_long": used_long_matrix,
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
