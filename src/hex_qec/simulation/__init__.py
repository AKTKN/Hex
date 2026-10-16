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
    "CompiledFactory", "FactoryBatchDecoder", "FactoryBatchResult",
    "FactoryOperationalBatch", "FactoryCacheKey",
]


def __getattr__(name):
    """Lazily expose factory/adaptive execution to avoid package import cycles."""

    if name in {"CompiledFactory", "FactoryBatchDecoder", "FactoryBatchResult",
                "FactoryOperationalBatch", "FactoryCacheKey"}:
        from . import factory
        return getattr(factory, name)
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
