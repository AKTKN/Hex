"""Optional generic local-process execution for simulation shots."""

from .chunking import ChunkController, ChunkSizeController, first_missing_index, merge_intervals
from .checkpoint import CheckpointError, CheckpointStore
from .manager import ParallelManager, ParallelWorkerError, run_parallel
from .types import (
    ChunkResult,
    JobProgressSnapshot,
    JobState,
    ParallelExecutionOptions,
    ParallelJobFactory,
    ParallelJobResult,
    ParallelJobSpec,
    ParallelRunResult,
    PreparedParallelJob,
    ProgressSnapshot,
    ShotLease,
    WorkerState,
)

__all__ = [
    "ChunkResult",
    "ChunkController",
    "ChunkSizeController",
    "CheckpointError",
    "CheckpointStore",
    "JobProgressSnapshot",
    "JobState",
    "ParallelExecutionOptions",
    "ParallelJobFactory",
    "ParallelJobResult",
    "ParallelJobSpec",
    "ParallelManager",
    "ParallelRunResult",
    "ParallelWorkerError",
    "PreparedParallelJob",
    "ProgressSnapshot",
    "ShotLease",
    "WorkerState",
    "first_missing_index",
    "merge_intervals",
    "run_parallel",
]
