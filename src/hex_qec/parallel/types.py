"""QEC-independent types used by the optional parallel shot runner."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Mapping, Protocol, Sequence


class PreparedParallelJob(Protocol):
    """Worker-local prepared state for one parallel job."""

    def run_chunk(
        self,
        shot_start: int,
        shot_count: int,
        seed_base: int | None,
    ) -> "ChunkResult": ...


class ParallelJobFactory(Protocol):
    """Pickleable factory used once by each worker assigned to a job."""

    def prepare(self) -> PreparedParallelJob: ...


@dataclass(frozen=True)
class ParallelExecutionOptions:
    """Validated knobs for the local-process parallel coordinator."""

    num_workers: int | Literal["auto"] = "auto"
    target_chunk_seconds: float = 1.0
    initial_chunk_shots: int = 1
    max_chunk_shots: int = 1024
    status_interval_seconds: float = 1.0
    verbose: int = 0
    checkpoint_path: Path | None = None
    allowed_cpu_ids: tuple[int, ...] | None = None
    pin_workers: bool = False
    multiprocessing_start_method: str = "spawn"

    def __post_init__(self) -> None:
        if self.num_workers != "auto" and (
            not isinstance(self.num_workers, int) or self.num_workers < 1
        ):
            raise ValueError("num_workers must be 'auto' or a positive integer")
        if self.target_chunk_seconds <= 0:
            raise ValueError("target_chunk_seconds must be positive")
        if self.initial_chunk_shots < 1:
            raise ValueError("initial_chunk_shots must be positive")
        if self.max_chunk_shots < 1:
            raise ValueError("max_chunk_shots must be positive")
        if self.initial_chunk_shots > self.max_chunk_shots:
            raise ValueError("initial_chunk_shots cannot exceed max_chunk_shots")
        if self.status_interval_seconds <= 0:
            raise ValueError("status_interval_seconds must be positive")
        if self.verbose not in (0, 1, 2):
            raise ValueError("verbose must be 0, 1, or 2")
        if self.allowed_cpu_ids is not None:
            if not self.allowed_cpu_ids:
                raise ValueError("allowed_cpu_ids cannot be empty")
            if any(cpu < 0 for cpu in self.allowed_cpu_ids):
                raise ValueError("allowed_cpu_ids must contain non-negative IDs")
            if len(set(self.allowed_cpu_ids)) != len(self.allowed_cpu_ids):
                raise ValueError("allowed_cpu_ids must not contain duplicates")
        if not isinstance(self.multiprocessing_start_method, str):
            raise ValueError("multiprocessing_start_method must be a string")


@dataclass(frozen=True)
class ParallelJobSpec:
    """One simulation configuration and its global shot range."""

    job_id: str
    factory: ParallelJobFactory
    max_shots: int
    max_errors: int | None = None
    seed_base: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    config_fingerprint: str | None = None

    def __post_init__(self) -> None:
        if not self.job_id:
            raise ValueError("job_id must be non-empty")
        if self.max_shots < 0:
            raise ValueError("max_shots must be non-negative")
        if self.max_errors is not None and self.max_errors < 1:
            raise ValueError("max_errors must be positive when supplied")
        if self.seed_base is not None and not 0 <= self.seed_base < 2**64:
            raise ValueError("seed_base must be in [0, 2**64)")


@dataclass(frozen=True)
class ShotLease:
    """A contiguous, manager-owned global shot range."""

    job_id: str
    shot_start: int
    shot_count: int
    lease_id: str

    def __post_init__(self) -> None:
        if not self.job_id or not self.lease_id:
            raise ValueError("job_id and lease_id must be non-empty")
        if self.shot_start < 0:
            raise ValueError("shot_start must be non-negative")
        if self.shot_count < 1:
            raise ValueError("shot_count must be positive")

    @property
    def end(self) -> int:
        return self.shot_start + self.shot_count


@dataclass(frozen=True)
class ChunkResult:
    """Additive result for one completed shot lease."""

    job_id: str
    lease_id: str
    shot_start: int
    shots: int
    logical_errors: int
    runtime_seconds: float
    custom_counts: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.job_id or not self.lease_id:
            raise ValueError("job_id and lease_id must be non-empty")
        if self.shot_start < 0 or self.shots < 1:
            raise ValueError("shot_start must be non-negative and shots positive")
        if not 0 <= self.logical_errors <= self.shots:
            raise ValueError("logical_errors must be between zero and shots")
        if self.runtime_seconds < 0:
            raise ValueError("runtime_seconds must be non-negative")
        for name, value in self.custom_counts.items():
            if not isinstance(name, str) or not isinstance(value, int):
                raise ValueError("custom_counts must map strings to integers")


@dataclass
class JobState:
    """Manager-owned progress and active leases for one job."""

    spec: ParallelJobSpec
    completed_ranges: list[tuple[int, int]] = field(default_factory=list)
    completed_lease_ids: set[str] = field(default_factory=set)
    active_leases: dict[str, ShotLease] = field(default_factory=dict)
    shots_completed: int = 0
    logical_errors: int = 0
    custom_counts: dict[str, int] = field(default_factory=dict)
    lease_counter: int = 0

    @property
    def stopped_by_error_limit(self) -> bool:
        return (
            self.spec.max_errors is not None
            and self.logical_errors >= self.spec.max_errors
        )

    @property
    def complete(self) -> bool:
        return self.shots_completed >= self.spec.max_shots or self.stopped_by_error_limit

    @property
    def shots_remaining(self) -> int:
        return max(0, self.spec.max_shots - self.shots_completed)


@dataclass
class WorkerState:
    """Manager-side state for one persistent child process."""

    worker_id: int
    job_id: str | None = None
    busy: bool = False
    loading: bool = False
    ready: bool = False
    current_lease: ShotLease | None = None
    chunks_completed: int = 0
    pid: int | None = None
    stopping: bool = False


@dataclass(frozen=True)
class JobProgressSnapshot:
    job_id: str
    metadata: Mapping[str, Any]
    workers: int
    shots_completed: int
    shots_target: int
    logical_errors: int
    rate_shots_per_second: float
    eta_seconds: float | None
    current_chunk_shots: int | None


@dataclass(frozen=True)
class ProgressSnapshot:
    jobs_remaining: int
    total_shots_completed: int
    total_shots_target: int
    total_logical_errors: int
    elapsed_seconds: float
    jobs: tuple[JobProgressSnapshot, ...]


@dataclass(frozen=True)
class ParallelJobResult:
    job_id: str
    shots: int
    logical_errors: int
    custom_counts: Mapping[str, int]
    completed_ranges: tuple[tuple[int, int], ...]
    metadata: Mapping[str, Any]


@dataclass(frozen=True)
class ParallelRunResult:
    jobs: tuple[ParallelJobResult, ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def shots(self) -> int:
        return sum(job.shots for job in self.jobs)

    @property
    def logical_errors(self) -> int:
        return sum(job.logical_errors for job in self.jobs)

    @property
    def logical_error_rate(self) -> float:
        return self.logical_errors / self.shots if self.shots else 0.0


@dataclass(frozen=True)
class LoadJob:
    spec: ParallelJobSpec


@dataclass(frozen=True)
class RunLease:
    lease: ShotLease
    seed_base: int | None


@dataclass(frozen=True)
class StopWorker:
    pass


@dataclass(frozen=True)
class JobReady:
    worker_id: int
    job_id: str | None


@dataclass(frozen=True)
class WorkerWarning:
    worker_id: int
    message: str


@dataclass(frozen=True)
class WorkerError:
    worker_id: int
    job_id: str | None
    lease_id: str | None
    exception_type: str
    message: str
    traceback: str
