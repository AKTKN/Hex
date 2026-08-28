"""Reference executor for two-level fixed-policy state preparation.

This is deliberately limited to uniform diagnostic policies.  A mixed mask
would require branch-specific simulator states and records, which belongs to
the later confidence-switching phase.
"""

from dataclasses import dataclass

import numpy as np
import stim

from hex_qec.decoders import DecodeResult
from hex_qec.modularisation.adaptive_state_prep import AdaptiveStatePrepModule
from hex_qec.modularisation.results import (
    ModuleDecodeResult,
    normalize_module_decode_output,
)
from .policies import AdaptivePolicyContext
from .stateful import reconstruct_measurement_records


@dataclass
class AdaptiveStatePrepExecution:
    """Records one uniform-policy execution of an adaptive preparation."""

    short_result: ModuleDecodeResult
    long_result: ModuleDecodeResult | None
    selected_result: ModuleDecodeResult
    short_measurements: np.ndarray
    selected_measurements: np.ndarray
    used_long: np.ndarray


class StatefulAdaptiveStatePrepExecutor:
    """Execute one short/long state-preparation description.

    ``AlwaysLongPolicy`` uses the same simulator instance for ``short_circuit``
    and ``extra_circuit``.  The short correction is decoded for diagnostics
    but is never committed when the long result is selected.
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

        simulator = stim.FlipSimulator(
            batch_size=batch_size,
            disable_stabilizer_randomization=False,
            seed=seed,
        )
        long_reference = np.asarray(
            description.long_circuit.reference_sample(), dtype=bool
        )

        simulator.do(description.short_circuit)
        short_flips = simulator.get_measurement_flips()
        short_measurements = reconstruct_measurement_records(
            long_reference[: description.short_circuit.num_measurements],
            short_flips,
        )
        short_result = normalize_module_decode_output(
            description.short_decoder(short_measurements)
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
        if np.any(extend_mask) and np.any(~extend_mask):
            raise NotImplementedError(
                "mixed short/long masks are reserved for the adaptive branching phase"
            )

        if not np.any(extend_mask):
            return AdaptiveStatePrepExecution(
                short_result=short_result,
                long_result=None,
                selected_result=short_result,
                short_measurements=short_measurements,
                selected_measurements=short_measurements,
                used_long=extend_mask,
            )

        # No reset or reinitialization occurs here: this is the same physical
        # simulator that produced short_measurements above.
        simulator.do(description.extra_circuit)
        long_flips = simulator.get_measurement_flips()
        if long_flips.shape != (
            description.long_circuit.num_measurements,
            batch_size,
        ):
            raise RuntimeError("long FlipSimulator measurement history has an unexpected shape")
        long_measurements = reconstruct_measurement_records(
            long_reference,
            long_flips,
        )
        if not np.array_equal(
            long_measurements[:, : description.short_circuit.num_measurements],
            short_measurements,
        ):
            raise RuntimeError("long continuation changed the short measurement prefix")
        long_result = normalize_module_decode_output(
            description.long_decoder(long_measurements)
        )
        return AdaptiveStatePrepExecution(
            short_result=short_result,
            long_result=long_result,
            selected_result=long_result,
            short_measurements=short_measurements,
            selected_measurements=long_measurements,
            used_long=extend_mask,
        )
