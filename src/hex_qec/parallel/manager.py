"""Spawn-based persistent-worker coordinator for generic simulation jobs."""

from __future__ import annotations

import multiprocessing as mp
import os
import pickle
import queue
import time
import traceback as traceback_module
import warnings
from dataclasses import replace
from typing import Callable, Iterable, Sequence

from .checkpoint import CheckpointError, CheckpointStore
from .chunking import ChunkSizeController, first_missing_index, merge_intervals
from .types import (
    ChunkResult,
    JobProgressSnapshot,
    JobState,
    JobReady,
    LoadJob,
    ParallelExecutionOptions,
    ParallelJobResult,
    ParallelJobSpec,
    ParallelRunResult,
    ProgressSnapshot,
    RunLease,
    ShotLease,
    StopWorker,
    WorkerError,
    WorkerState,
    WorkerWarning,
)


class ParallelWorkerError(RuntimeError):
    """A child-process failure, including its original traceback."""


def _pin_worker(worker_id: int, cpu_ids: tuple[int, ...] | None, output_queue) -> None:
    if cpu_ids is None:
        return
    cpu = cpu_ids[worker_id % len(cpu_ids)]
    try:
        os.sched_setaffinity(0, {cpu})
    except (AttributeError, OSError, PermissionError) as error:
        output_queue.put(
            WorkerWarning(
                worker_id,
                f"could not pin worker to CPU {cpu}: {error}",
            )
        )


def _parallel_worker_main(worker_id: int, input_queue, output_queue, cpu_ids) -> None:
    """Module-level target required for the spawn start method."""

    _pin_worker(worker_id, cpu_ids, output_queue)
    prepared = None
    current_job_id = None
    current_lease_id = None
    output_queue.put(JobReady(worker_id=worker_id, job_id=None))
    while True:
        message = input_queue.get()
        if isinstance(message, StopWorker):
            return
        try:
            if isinstance(message, LoadJob):
                prepared = message.spec.factory.prepare()
                if not hasattr(prepared, "run_chunk"):
                    raise TypeError("prepared job must provide run_chunk")
                current_job_id = message.spec.job_id
                current_lease_id = None
                output_queue.put(JobReady(worker_id, current_job_id))
            elif isinstance(message, RunLease):
                if prepared is None or current_job_id != message.lease.job_id:
                    raise RuntimeError(
                        f"worker has no prepared state for job {message.lease.job_id!r}"
                    )
                current_lease_id = message.lease.lease_id
                result = prepared.run_chunk(
                    message.lease.shot_start,
                    message.lease.shot_count,
                    message.seed_base,
                )
                if not isinstance(result, ChunkResult):
                    raise TypeError("run_chunk must return a ChunkResult")
                if (
                    result.job_id != message.lease.job_id
                    or result.shot_start != message.lease.shot_start
                    or result.shots != message.lease.shot_count
                ):
                    raise ValueError("run_chunk result does not match its shot lease")
                # The compact PreparedParallelJob protocol intentionally
                # does not carry lease IDs.  The worker owns that binding.
                result = replace(result, lease_id=message.lease.lease_id)
                output_queue.put(result)
                current_lease_id = None
            else:
                raise ValueError(f"unknown worker message {type(message).__name__}")
        except BaseException as error:  # propagate every worker failure
            output_queue.put(
                WorkerError(
                    worker_id=worker_id,
                    job_id=current_job_id,
                    lease_id=current_lease_id,
                    exception_type=type(error).__name__,
                    message=str(error),
                    traceback="".join(traceback_module.format_exc()),
                )
            )
            return


def _available_cpus(allowed_cpu_ids: tuple[int, ...] | None) -> tuple[int, ...]:
    try:
        available = set(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        count = getattr(os, "process_cpu_count", None)
        count = count() if count is not None else os.cpu_count()
        available = set(range(count or 1))
    if allowed_cpu_ids is not None:
        available &= set(allowed_cpu_ids)
        if not available:
            raise ValueError("allowed_cpu_ids has no CPU in the process affinity set")
    return tuple(sorted(available))


class ParallelManager:
    """Own job scheduling, aggregation, progress, and checkpoint state."""

    def __init__(
        self,
        options: ParallelExecutionOptions,
        *,
        progress_callback: Callable[[ProgressSnapshot], None] | None = None,
    ) -> None:
        self.options = options
        self.progress_callback = progress_callback
        self.last_snapshot: ProgressSnapshot | None = None

    def _resolve_worker_count(self, job_count: int) -> int:
        cpus = _available_cpus(self.options.allowed_cpu_ids)
        requested = len(cpus) if self.options.num_workers == "auto" else self.options.num_workers
        if requested > len(cpus):
            raise ValueError(
                f"num_workers={requested} exceeds {len(cpus)} available CPUs"
            )
        return requested if job_count else 0

    @staticmethod
    def _validate_pickleability(specs: Sequence[ParallelJobSpec]) -> None:
        for spec in specs:
            try:
                pickle.dumps(LoadJob(spec))
            except Exception as error:
                raise TypeError(
                    f"parallel factory for job {spec.job_id!r} is not pickleable "
                    "under spawn; use a top-level class or functools.partial"
                ) from error

    @staticmethod
    def _select_job(
        states: dict[str, JobState], workers: dict[int, WorkerState]
    ) -> JobState | None:
        active_counts: dict[str, int] = {}
        for worker in workers.values():
            if worker.job_id is not None and not worker.stopping:
                active_counts[worker.job_id] = active_counts.get(worker.job_id, 0) + 1
        candidates = [state for state in states.values() if not state.complete]
        if not candidates:
            return None
        return min(
            candidates,
            key=lambda state: (active_counts.get(state.spec.job_id, 0), state.spec.job_id),
        )

    @staticmethod
    def _allocate_lease(
        state: JobState,
        requested_size: int,
    ) -> ShotLease | None:
        if state.complete:
            return None
        covered = [*state.completed_ranges]
        covered.extend((lease.shot_start, lease.end) for lease in state.active_leases.values())
        start = first_missing_index(covered, state.spec.max_shots)
        if start is None:
            return None
        next_boundary = state.spec.max_shots
        for left, _ in covered:
            if left > start:
                next_boundary = min(next_boundary, left)
        count = min(requested_size, state.spec.max_shots - start, next_boundary - start)
        if count < 1:
            return None
        while True:
            state.lease_counter += 1
            lease_id = f"{state.spec.job_id}:{state.lease_counter}"
            if lease_id not in state.completed_lease_ids and lease_id not in state.active_leases:
                break
        lease = ShotLease(state.spec.job_id, start, count, lease_id)
        state.active_leases[lease.lease_id] = lease
        return lease

    @staticmethod
    def _record_result(state: JobState, result: ChunkResult) -> None:
        lease = state.active_leases.pop(result.lease_id, None)
        if lease is None:
            if result.lease_id in state.completed_lease_ids:
                raise RuntimeError(f"duplicate live chunk result {result.lease_id!r}")
            raise RuntimeError(f"unknown lease result {result.lease_id!r}")
        if (
            result.job_id != lease.job_id
            or result.shot_start != lease.shot_start
            or result.shots != lease.shot_count
        ):
            raise RuntimeError(f"chunk result does not match lease {lease.lease_id!r}")
        state.completed_ranges = merge_intervals(
            state.completed_ranges, (lease.shot_start, lease.end)
        )
        state.completed_lease_ids.add(lease.lease_id)
        state.shots_completed += result.shots
        state.logical_errors += result.logical_errors
        for name, value in result.custom_counts.items():
            state.custom_counts[name] = state.custom_counts.get(name, 0) + value

    def _make_snapshot(
        self,
        states: dict[str, JobState],
        workers: dict[int, WorkerState],
        controllers: dict[tuple[int, str], ChunkSizeController],
        started: float,
    ) -> ProgressSnapshot:
        elapsed = max(0.0, time.monotonic() - started)
        rows: list[JobProgressSnapshot] = []
        for state in states.values():
            worker_count = sum(worker.job_id == state.spec.job_id for worker in workers.values())
            rate = state.shots_completed / elapsed if elapsed else 0.0
            eta = (
                (state.spec.max_shots - state.shots_completed) / rate
                if rate > 0 and not state.stopped_by_error_limit
                else None
            )
            controller = next(
                (
                    controller
                    for (worker_id, job_id), controller in controllers.items()
                    if job_id == state.spec.job_id and workers[worker_id].job_id == job_id
                ),
                None,
            )
            rows.append(
                JobProgressSnapshot(
                    job_id=state.spec.job_id,
                    metadata=state.spec.metadata,
                    workers=worker_count,
                    shots_completed=state.shots_completed,
                    shots_target=state.spec.max_shots,
                    logical_errors=state.logical_errors,
                    rate_shots_per_second=rate,
                    eta_seconds=eta,
                    current_chunk_shots=controller.current_shots if controller else None,
                )
            )
        snapshot = ProgressSnapshot(
            jobs_remaining=sum(not state.complete for state in states.values()),
            total_shots_completed=sum(state.shots_completed for state in states.values()),
            total_shots_target=sum(state.spec.max_shots for state in states.values()),
            total_logical_errors=sum(state.logical_errors for state in states.values()),
            elapsed_seconds=elapsed,
            jobs=tuple(rows),
        )
        self.last_snapshot = snapshot
        if self.progress_callback is not None:
            self.progress_callback(snapshot)
        if self.options.verbose >= 1:
            self._print_snapshot(snapshot)
        return snapshot

    def _print_snapshot(self, snapshot: ProgressSnapshot) -> None:
        print(f"{snapshot.jobs_remaining} jobs remaining:")
        for row in snapshot.jobs:
            eta = "-" if row.eta_seconds is None else f"{row.eta_seconds:.1f}s"
            print(
                f"  {row.workers:7d} {row.shots_completed}/{row.shots_target:<10d} "
                f"{row.logical_errors:6d} {row.rate_shots_per_second:9.1f}/s "
                f"{eta:>8s} {row.job_id}"
            )

    @staticmethod
    def _report_native_threads() -> None:
        values = {
            name: os.environ[name]
            for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")
            if name in os.environ
        }
        large = {name: value for name, value in values.items() if value.isdigit() and int(value) > 1}
        if large:
            print("native thread settings (consider one thread per worker): " + repr(large))

    def run(self, jobs: Iterable[ParallelJobSpec]) -> ParallelRunResult:
        specs = list(jobs)
        if len({spec.job_id for spec in specs}) != len(specs):
            raise ValueError("job_id values must be unique")
        self._validate_pickleability(specs)
        states = {spec.job_id: JobState(spec) for spec in specs}
        checkpoint = CheckpointStore(self.options.checkpoint_path)
        for result in checkpoint.load(specs):
            state = states[result.job_id]
            if result.shot_start + result.shots > state.spec.max_shots:
                raise CheckpointError(f"checkpoint result exceeds job {result.job_id!r}")
            self._record_result_from_checkpoint(state, result)
        if not specs or all(state.complete for state in states.values()):
            return self._result(states, "none")

        if self.options.verbose >= 1:
            self._report_native_threads()

        worker_count = self._resolve_worker_count(len(specs))
        context = mp.get_context(self.options.multiprocessing_start_method)
        output_queue = context.Queue()
        input_queues = [context.Queue() for _ in range(worker_count)]
        cpu_ids = _available_cpus(self.options.allowed_cpu_ids) if self.options.pin_workers else None
        workers: dict[int, WorkerState] = {}
        processes = []
        controllers: dict[tuple[int, str], ChunkSizeController] = {}
        started = time.monotonic()
        last_status = started - self.options.status_interval_seconds
        try:
            for worker_id, input_queue in enumerate(input_queues):
                process = context.Process(
                    target=_parallel_worker_main,
                    args=(worker_id, input_queue, output_queue, cpu_ids),
                    name=f"hex-parallel-worker-{worker_id}",
                )
                process.start()
                processes.append(process)
                workers[worker_id] = WorkerState(
                    worker_id=worker_id,
                    pid=process.pid,
                )

            while True:
                if all(state.complete for state in states.values()) and not any(
                    worker.busy for worker in workers.values()
                ):
                    break
                try:
                    message = output_queue.get(timeout=0.2)
                except queue.Empty:
                    for worker_id, process in enumerate(processes):
                        if not process.is_alive() and not workers[worker_id].stopping:
                            raise ParallelWorkerError(
                                f"worker {worker_id} exited unexpectedly with code "
                                f"{process.exitcode}"
                            )
                    now = time.monotonic()
                    if now - last_status >= self.options.status_interval_seconds:
                        self._make_snapshot(states, workers, controllers, started)
                        last_status = now
                    continue

                if isinstance(message, WorkerWarning):
                    warnings.warn(message.message, RuntimeWarning, stacklevel=2)
                    continue
                worker = workers.get(message.worker_id) if isinstance(message, (JobReady, WorkerError)) else None
                if isinstance(message, WorkerError):
                    raise ParallelWorkerError(
                        f"worker {message.worker_id} failed in job {message.job_id!r} "
                        f"lease {message.lease_id!r}: {message.exception_type}: "
                        f"{message.message}\n{message.traceback}"
                    )
                if isinstance(message, JobReady):
                    if worker is None:
                        raise RuntimeError(f"unknown worker {message.worker_id}")
                    worker.ready = True
                    worker.loading = False
                    worker.busy = False
                    if message.job_id is not None and worker.job_id != message.job_id:
                        raise RuntimeError("worker reported an unexpected prepared job")
                    self._dispatch_worker(worker, input_queues[worker.worker_id], states, workers, controllers)
                elif isinstance(message, ChunkResult):
                    worker = next(
                        (item for item in workers.values() if item.current_lease and item.current_lease.lease_id == message.lease_id),
                        None,
                    )
                    if worker is None:
                        raise RuntimeError(f"received result for unknown lease {message.lease_id!r}")
                    state = states[message.job_id]
                    self._record_result(state, message)
                    checkpoint.append(message, state.spec)
                    worker.busy = False
                    worker.current_lease = None
                    worker.chunks_completed += 1
                    if worker.job_id is not None:
                        controllers[(worker.worker_id, worker.job_id)].observe(message.runtime_seconds)
                    self._dispatch_worker(worker, input_queues[worker.worker_id], states, workers, controllers)
                    now = time.monotonic()
                    if self.options.verbose >= 2:
                        print(
                            f"chunk {message.lease_id}: {message.shots} shots, "
                            f"{message.logical_errors} errors in {message.runtime_seconds:.3f}s"
                        )
                    if now - last_status >= self.options.status_interval_seconds:
                        self._make_snapshot(states, workers, controllers, started)
                        last_status = now
                else:
                    raise RuntimeError(f"unknown manager message {type(message).__name__}")
        except BaseException:
            self._shutdown(processes, input_queues, terminate=True)
            raise
        else:
            self._shutdown(processes, input_queues, terminate=False)
        self._make_snapshot(states, workers, controllers, started)
        return self._result(states, self.options.multiprocessing_start_method)

    @staticmethod
    def _record_result_from_checkpoint(state: JobState, result: ChunkResult) -> None:
        if result.lease_id in state.completed_lease_ids:
            return
        state.completed_ranges = merge_intervals(
            state.completed_ranges, (result.shot_start, result.shot_start + result.shots)
        )
        state.completed_lease_ids.add(result.lease_id)
        state.shots_completed += result.shots
        state.logical_errors += result.logical_errors
        for name, value in result.custom_counts.items():
            state.custom_counts[name] = state.custom_counts.get(name, 0) + value

    def _dispatch_worker(
        self,
        worker: WorkerState,
        input_queue,
        states: dict[str, JobState],
        workers: dict[int, WorkerState],
        controllers: dict[tuple[int, str], ChunkSizeController],
    ) -> None:
        if worker.busy or worker.loading or worker.stopping:
            return
        if worker.job_id is None or states[worker.job_id].complete:
            state = self._select_job(states, workers)
            if state is None:
                worker.stopping = True
                input_queue.put(StopWorker())
                return
            worker.job_id = state.spec.job_id
            controller = controllers.setdefault(
                (worker.worker_id, worker.job_id),
                ChunkSizeController(
                    self.options.target_chunk_seconds,
                    self.options.initial_chunk_shots,
                    self.options.max_chunk_shots,
                ),
            )
            input_queue.put(LoadJob(state.spec))
            worker.loading = True
            return
        state = states[worker.job_id]
        if state.stopped_by_error_limit:
            worker.job_id = None
            self._dispatch_worker(worker, input_queue, states, workers, controllers)
            return
        controller = controllers[(worker.worker_id, worker.job_id)]
        lease = self._allocate_lease(state, controller.next_size(state.spec.max_shots))
        if lease is None:
            worker.job_id = None
            self._dispatch_worker(worker, input_queue, states, workers, controllers)
            return
        worker.current_lease = lease
        worker.busy = True
        input_queue.put(RunLease(lease, state.spec.seed_base))

    @staticmethod
    def _shutdown(processes, input_queues, *, terminate: bool) -> None:
        if terminate:
            for process in processes:
                if process.is_alive():
                    process.terminate()
        else:
            for input_queue, process in zip(input_queues, processes):
                if process.is_alive():
                    input_queue.put(StopWorker())
        for process in processes:
            process.join(timeout=5.0)
            if process.is_alive():
                process.terminate()
                process.join(timeout=2.0)
        for input_queue in input_queues:
            input_queue.close()

    @staticmethod
    def _result(states: dict[str, JobState], start_method: str) -> ParallelRunResult:
        return ParallelRunResult(
            jobs=tuple(
                ParallelJobResult(
                    job_id=state.spec.job_id,
                    shots=state.shots_completed,
                    logical_errors=state.logical_errors,
                    custom_counts=dict(state.custom_counts),
                    completed_ranges=tuple(state.completed_ranges),
                    metadata=dict(state.spec.metadata),
                )
                for state in states.values()
            ),
            metadata={"multiprocessing_start_method": start_method},
        )


def run_parallel(
    jobs: Iterable[ParallelJobSpec],
    options: ParallelExecutionOptions,
    *,
    progress_callback: Callable[[ProgressSnapshot], None] | None = None,
) -> ParallelRunResult:
    """Convenience wrapper around :class:`ParallelManager`."""

    return ParallelManager(options, progress_callback=progress_callback).run(jobs)
