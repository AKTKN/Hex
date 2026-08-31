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
    ClusterLLRPolicy,
)
from .profiling import WallTimeProfiler, TimingEvent

__all__ = [
    "StatefulFlipSimulatorBackend",
    "StatefulMeasurementBatch",
    "reconstruct_measurement_records",
    "AdaptivePolicy",
    "AdaptivePolicyContext",
    "AlwaysShortPolicy",
    "AlwaysLongPolicy",
    "ClusterLLRPolicy",
    "WallTimeProfiler",
    "TimingEvent",
    "AdaptiveStatePrepExecution",
    "StatefulAdaptiveStatePrepExecutor",
    "StatefulAdaptiveKnillExecutor",
]


def __getattr__(name):
    """Lazily expose adaptive execution to avoid the package import cycle."""

    if name in {
        "AdaptiveStatePrepExecution",
        "StatefulAdaptiveStatePrepExecutor",
        "StatefulAdaptiveKnillExecutor",
    }:
        from .adaptive import (
            AdaptiveStatePrepExecution,
            StatefulAdaptiveKnillExecutor,
            StatefulAdaptiveStatePrepExecutor,
        )

        return {
            "AdaptiveStatePrepExecution": AdaptiveStatePrepExecution,
            "StatefulAdaptiveKnillExecutor": StatefulAdaptiveKnillExecutor,
            "StatefulAdaptiveStatePrepExecutor": StatefulAdaptiveStatePrepExecutor,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
