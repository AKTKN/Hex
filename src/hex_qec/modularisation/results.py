"""Structured outputs for module decoding and fixed-round simulations.

The simulation result classes in this module intentionally do not own a
sampling backend.  They provide a stable place for aggregate results and
future adaptive-experiment metadata while the existing static simulator
continues to produce its historical tuple.
"""

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping

import numpy as np

from hex_qec.decoders import DecodeResult


SimulationDetailLevel = Literal["summary", "analysis", "debug"]


def validate_simulation_detail_level(
    detail_level: str,
) -> SimulationDetailLevel:
    """Validate and return a supported simulation result detail level."""

    if detail_level not in {"summary", "analysis", "debug"}:
        raise ValueError(
            "detail_level must be one of 'summary', 'analysis', or 'debug'"
        )
    return detail_level  # type: ignore[return-value]


@dataclass
class SimulationSummary:
    """Lightweight aggregate counts for one simulation run."""

    shots: int
    logical_errors: int
    logical_error_rate: float
    runtime_seconds: float | None = None


@dataclass
class AdaptiveStatePrepStats:
    """Optional aggregate statistics for a state-preparation event.

    Fixed-round simulations do not expose event-level adaptive information,
    so they return an empty list of these records.  The optional fields make
    the future adaptive result shape explicit without inventing values in
    the fixed-round path.
    """

    event_id: str
    teleportation_index: int | None = None
    state_basis: str | None = None
    short_rounds: int | None = None
    long_rounds: int | None = None
    short_count: int | None = None
    long_count: int | None = None
    fallback_rate: float | None = None
    confidence_metric: str | None = None
    confidence_summary: dict[str, float] = field(default_factory=dict)
    decoder_diagnostics: dict[str, Any] = field(default_factory=dict)
    average_se_rounds: float | None = None


@dataclass
class SimulationResult:
    """Aggregate simulation output with reserved adaptive-result fields.

    ``per_shot`` and ``debug_data`` are deliberately separate from the
    aggregate summary.  They remain ``None`` for the current fixed-round
    implementation because that implementation does not retain those data.
    """

    summary: SimulationSummary
    state_prep_stats: list[AdaptiveStatePrepStats] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    per_shot: dict[str, np.ndarray] | None = None
    debug_data: dict[str, Any] | None = None
    detail_level: SimulationDetailLevel = "summary"

    def __post_init__(self) -> None:
        self.detail_level = validate_simulation_detail_level(self.detail_level)

    @property
    def shots(self) -> int:
        """Compatibility alias for ``summary.shots``."""

        return self.summary.shots

    @property
    def samples_performed(self) -> int:
        """Compatibility alias using the legacy simulation terminology."""

        return self.summary.shots

    @property
    def logical_errors(self) -> int:
        """Compatibility alias for ``summary.logical_errors``."""

        return self.summary.logical_errors

    @property
    def logical_error_rate(self) -> float:
        """Convenience access to the aggregate logical error rate."""

        return self.summary.logical_error_rate

    def to_legacy_tuple(self) -> tuple[int, int]:
        """Return the historical ``(samples_performed, logical_errors)``."""

        return self.summary.shots, self.summary.logical_errors

    @classmethod
    def from_legacy(
        cls,
        samples_performed: int,
        logical_errors: int,
        *,
        runtime_seconds: float | None = None,
        metadata: Mapping[str, Any] | None = None,
        detail_level: SimulationDetailLevel = "summary",
    ) -> "SimulationResult":
        """Wrap the current simulator's two-count return value."""

        logical_error_rate = (
            logical_errors / samples_performed if samples_performed else 0.0
        )
        return cls(
            summary=SimulationSummary(
                shots=samples_performed,
                logical_errors=logical_errors,
                logical_error_rate=logical_error_rate,
                runtime_seconds=runtime_seconds,
            ),
            metadata=dict(metadata or {}),
            detail_level=detail_level,
        )


@dataclass
class ModuleDecodeResult:
    """Normalized output from a measurement or detector module.

    ``corrections`` retains the legacy correction-variable array.  The first
    axis is the shot axis.  ``postselection`` is an optional per-shot flag;
    ``decode_result`` retains the richer decoder output when one was supplied.
    """

    corrections: np.ndarray
    postselection: np.ndarray | None = None
    decode_result: DecodeResult | None = None
    metrics: dict[str, np.ndarray] = field(default_factory=dict)


def normalize_module_decode_output(output: Any) -> ModuleDecodeResult:
    """Normalize current ndarray/tuple returns and structured results.

    Supported forms are:

    - a correction ndarray (legacy);
    - ``(corrections, postselection)`` (legacy);
    - ``DecodeResult``;
    - ``ModuleDecodeResult``;
    - ``(DecodeResult, postselection)``.
    """

    if isinstance(output, ModuleDecodeResult):
        return output

    if isinstance(output, DecodeResult):
        return ModuleDecodeResult(
            corrections=output.correction,
            decode_result=output,
            metrics=dict(output.metrics),
        )

    if isinstance(output, tuple):
        if len(output) != 2:
            raise ValueError(
                "Legacy module decoder tuples must be (corrections, postselection)"
            )
        corrections, postselection = output
        if isinstance(corrections, DecodeResult):
            return ModuleDecodeResult(
                corrections=corrections.correction,
                postselection=postselection,
                decode_result=corrections,
                metrics=dict(corrections.metrics),
            )
        return ModuleDecodeResult(
            corrections=corrections,
            postselection=postselection,
        )

    return ModuleDecodeResult(corrections=output)
