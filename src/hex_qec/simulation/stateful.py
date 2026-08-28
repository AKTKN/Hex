"""Stateful fixed-round execution using :class:`stim.FlipSimulator`.

This backend deliberately handles only fixed module sequences.  It executes
the physical circuits sequentially, but leaves decoder corrections in a
separate software measurement frame instead of applying them to the Stim
state.
"""

from dataclasses import dataclass
import json
import logging
import time
from typing import Iterator

import numpy as np
import stim
from scipy.sparse import csc_matrix

from hex_qec.modularisation.modularised_circuit import (
    css_detector_module,
    detector_module,
    logical_measurement_module,
    measurement_module,
    modularised_circuit,
    no_measurement_module,
    only_postselection_module,
)
from hex_qec.modularisation.results import (
    SimulationDetailLevel,
    SimulationResult,
    normalize_module_decode_output,
    validate_simulation_detail_level,
)

logger = logging.getLogger(__name__)


def reconstruct_measurement_records(
    reference_measurements: np.ndarray,
    measurement_flips: np.ndarray,
) -> np.ndarray:
    """Convert FlipSimulator measurement flips into Hex raw records.

    Stim returns measurement flips with shape ``(measurements, shots)``.
    ``Circuit.reference_sample()`` returns the deterministic no-noise record
    with shape ``(measurements,)``.  The result uses Hex's convention of
    shape ``(shots, measurements)`` and is their binary XOR.
    """

    reference = np.asarray(reference_measurements, dtype=bool)
    flips = np.asarray(measurement_flips, dtype=bool)
    if reference.ndim != 1:
        raise ValueError("reference_measurements must be a one-dimensional array")
    if flips.ndim != 2:
        raise ValueError("measurement_flips must have shape (measurements, shots)")
    if flips.shape[0] != reference.shape[0]:
        raise ValueError(
            "reference_measurements and measurement_flips disagree on measurements"
        )
    return np.logical_xor(flips.T, reference[None, :])


@dataclass(frozen=True)
class StatefulMeasurementBatch:
    """Physical raw measurements available after one module has run."""

    module_index: int
    measurements: np.ndarray


class StatefulFlipSimulatorBackend:
    """Execute a fixed ``modularised_circuit`` using a stateful FlipSimulator.

    The backend yields physical measurement prefixes after each module.  The
    decoder/software frame is maintained by ``simulate`` and is never written
    into the ``FlipSimulator`` state.  Consequently, decoded corrections are
    applied once as record interpretation, matching the static engine's
    correction-to-measurement-flip convention.
    """

    def __init__(
        self,
        circuit: modularised_circuit,
        *,
        batch_size: int = 256,
        seed: int | None = None,
    ) -> None:
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        self.circuit = circuit
        self.batch_size = batch_size
        self.seed = seed
        self.reference_measurements = np.asarray(
            circuit.circuit.reference_sample(), dtype=bool
        )

    def iter_module_measurements(
        self,
        *,
        seed: int | None = None,
    ) -> Iterator[StatefulMeasurementBatch]:
        """Yield reconstructed physical records after each circuit module.

        The yielded measurement arrays contain all physical measurements so
        far, not software-corrected records.  Array axes are
        ``(batch_size, measurements_so_far)``.
        """

        simulator = stim.FlipSimulator(
            batch_size=self.batch_size,
            # Actual physical sampling includes intrinsic stabilizer and
            # measurement randomness.
            disable_stabilizer_randomization=False,
            seed=seed,
        )
        measurements_so_far = 0
        for module_index, module in enumerate(self.circuit.circuit_modules):
            simulator.do(module.circuit)
            measurements_so_far += module.num_measurements
            measurement_flips = simulator.get_measurement_flips()
            if measurement_flips.shape != (
                measurements_so_far,
                self.batch_size,
            ):
                raise RuntimeError(
                    "FlipSimulator measurement history has an unexpected shape"
                )
            physical_measurements = reconstruct_measurement_records(
                self.reference_measurements[:measurements_so_far],
                measurement_flips,
            )
            yield StatefulMeasurementBatch(
                module_index=module_index,
                measurements=physical_measurements,
            )

    def _seed_for_batch(self, batch_number: int) -> int | None:
        if self.seed is None:
            return None
        return (self.seed + batch_number) % (2**64)

    def simulate(
        self,
        max_shots: int,
        max_errors_before_halting: int,
        results_path: str = "",
    ) -> tuple[int, int]:
        """Run the fixed module sequence and return legacy aggregate counts."""

        m2d_converter = self.circuit.circuit.compile_m2d_converter()
        total_measurements = self.circuit.circuit.num_measurements

        total_logical_errors = 0
        total_logical_errors_postselected = 0
        samples_performed = 0
        samples_performed_postselected = 0
        batch_number = 0

        while (
            total_logical_errors_postselected < max_errors_before_halting
            and self.batch_size * batch_number < max_shots
        ):
            logger.info("Stateful batch number: %s", batch_number)
            physical_measurements = np.zeros(
                (self.batch_size, total_measurements), dtype=bool
            )
            software_measurement_flips = np.zeros_like(physical_measurements)
            logical_errors = np.zeros((self.batch_size,), dtype=int)
            shots_postselected = np.zeros((self.batch_size,), dtype=int)
            previous_measurements = 0
            previous_detectors = 0

            for batch in self.iter_module_measurements(
                seed=self._seed_for_batch(batch_number)
            ):
                module = self.circuit.circuit_modules[batch.module_index]
                current_measurements = previous_measurements + module.num_measurements
                physical_measurements[:, :current_measurements] = batch.measurements

                # This is the software/decoder state. Unknown future physical
                # measurements remain zero until their module has executed.
                measurement_samples = np.logical_xor(
                    physical_measurements, software_measurement_flips
                )

                if isinstance(module, logical_measurement_module):
                    module_measurements = measurement_samples[
                        :, previous_measurements:current_measurements
                    ]
                    logical_measurement = module.c_func(module_measurements)
                    logical_errors += np.sum(
                        logical_measurement != module.c_func_expected_output,
                        axis=1,
                    )
                    previous_measurements = current_measurements
                    previous_detectors += module.num_detectors
                    continue

                if isinstance(module, no_measurement_module):
                    # This module contributes physical gates but no record
                    # entries or decoder state.
                    continue

                if isinstance(
                    module,
                    (measurement_module, detector_module, css_detector_module),
                ):
                    module_measurements = measurement_samples[
                        :, previous_measurements:current_measurements
                    ]
                    detector_flips, _ = m2d_converter.convert(
                        measurements=measurement_samples,
                        separate_observables=True,
                    )
                    module_detectors = detector_flips[
                        :, previous_detectors : previous_detectors + module.num_detectors
                    ]

                    if isinstance(module, detector_module):
                        module_decode_result = normalize_module_decode_output(
                            module.c_func(module_detectors)
                        )
                    else:
                        module_decode_result = normalize_module_decode_output(
                            module.c_func(module_measurements)
                        )

                    corrections = csc_matrix(module_decode_result.corrections)
                    module_postselection = module_decode_result.postselection
                    if module_postselection is None:
                        module_postselection = np.zeros(
                            (self.batch_size,), dtype=int
                        )
                    measurement_updates = (
                        corrections @ module.correction_to_measurement_flips
                    ).toarray() % 2
                    software_measurement_flips = (
                        software_measurement_flips + measurement_updates
                    ) % 2
                    software_measurement_flips = software_measurement_flips.astype(
                        bool
                    )
                    shots_postselected = (
                        shots_postselected + module_postselection
                    ) % 2

                    previous_measurements = current_measurements
                    previous_detectors += module.num_detectors
                    continue

                if isinstance(module, only_postselection_module):
                    module_measurements = measurement_samples[
                        :, previous_measurements:current_measurements
                    ]
                    shots_postselected = (
                        shots_postselected + module.c_func(module_measurements)
                    ) % 2
                    previous_measurements = current_measurements
                    previous_detectors += module.num_detectors
                    continue

                raise TypeError(f"Unknown module type: {type(module)!r}")

            # Every module has now executed, so the full software-corrected
            # record is available for the same final consistency check as the
            # static backend.
            measurement_samples = np.logical_xor(
                physical_measurements, software_measurement_flips
            )
            detector_flips, _ = m2d_converter.convert(
                measurements=measurement_samples,
                separate_observables=True,
            )
            assert np.sum(detector_flips) == 0

            logical_errors[logical_errors > 0] = 1
            total_logical_errors += np.sum(logical_errors, dtype=int)
            total_logical_errors_postselected += np.sum(
                ((1 - shots_postselected) * logical_errors), dtype=int
            )
            samples_performed += self.batch_size
            samples_performed_postselected += np.sum(
                (1 - shots_postselected), dtype=int
            )
            batch_number += 1

            if results_path:
                logical_error_rate = total_logical_errors / samples_performed
                results = {
                    "samples_performed": int(samples_performed),
                    "logical_errors": int(total_logical_errors),
                    "logical_error_rate": logical_error_rate,
                    "logical_errors_postselected": int(
                        total_logical_errors_postselected
                    ),
                    "samples_performed_postselected": int(
                        samples_performed_postselected
                    ),
                }
                with open(results_path, "w") as result_file:
                    json.dump(results, result_file, indent=2)

        return samples_performed, total_logical_errors

    def simulate_result(
        self,
        max_shots: int,
        max_errors_before_halting: int,
        results_path: str = "",
        detail_level: SimulationDetailLevel = "summary",
    ) -> SimulationResult:
        """Run this backend and wrap its aggregate output."""

        detail_level = validate_simulation_detail_level(detail_level)
        start_time = time.perf_counter()
        samples_performed, logical_errors = self.simulate(
            max_shots=max_shots,
            max_errors_before_halting=max_errors_before_halting,
            results_path=results_path,
        )
        return SimulationResult.from_legacy(
            samples_performed,
            logical_errors,
            runtime_seconds=time.perf_counter() - start_time,
            detail_level=detail_level,
            metadata={
                "execution_backend": "stateful_flip_simulator",
                "adaptive": False,
                "batch_size": self.batch_size,
                "num_modules": len(self.circuit.circuit_modules),
                "num_measurements": self.circuit.circuit.num_measurements,
                "num_detectors": self.circuit.circuit.num_detectors,
            },
        )
