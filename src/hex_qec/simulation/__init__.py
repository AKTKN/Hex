"""Simulation backends for Hex."""

from .stateful import (
    StatefulFlipSimulatorBackend,
    StatefulMeasurementBatch,
    reconstruct_measurement_records,
)
from .policies import (
    AdaptivePolicy,
    AdaptivePolicyContext,
    AlwaysLongPolicy,
    AlwaysShortPolicy,
)

__all__ = [
    "StatefulFlipSimulatorBackend",
    "StatefulMeasurementBatch",
    "reconstruct_measurement_records",
    "AdaptivePolicy",
    "AdaptivePolicyContext",
    "AlwaysShortPolicy",
    "AlwaysLongPolicy",
    "AdaptiveStatePrepExecution",
    "StatefulAdaptiveStatePrepExecutor",
]


def __getattr__(name):
    """Lazily expose adaptive execution to avoid the package import cycle."""

    if name in {"AdaptiveStatePrepExecution", "StatefulAdaptiveStatePrepExecutor"}:
        from .adaptive import (
            AdaptiveStatePrepExecution,
            StatefulAdaptiveStatePrepExecutor,
        )

        return {
            "AdaptiveStatePrepExecution": AdaptiveStatePrepExecution,
            "StatefulAdaptiveStatePrepExecutor": StatefulAdaptiveStatePrepExecutor,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
