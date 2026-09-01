# `parallel`

This package is an optional, generic local-process runner for simulation
shots. It has no imports from the QEC, decoder, Stim, or protocol layers.
Protocol adapters supply a pickleable `ParallelJobFactory`; the generic
manager only sees jobs, leases, and additive chunk results.

## Manager, worker, job, and lease

The `ParallelManager` owns global scheduling, aggregate counts, progress
callbacks, checkpoint writes, and shutdown. A persistent child `Worker` owns
one input queue and shares one result queue with the other workers. A worker
receives a `LOAD_JOB` message, calls the factory's `prepare()` once, and
reuses the resulting prepared state for every subsequent lease assigned to
that job. It is reassigned only after that job is complete.

Each `ParallelJobSpec` has a stable caller-supplied `job_id`, a target
`max_shots`, an optional `max_errors`, and an optional `seed_base`. A
`ShotLease` is a finite half-open global range `[shot_start,
shot_start + shot_count)`. The manager allocates each range once; a normal
run covers every index below `max_shots` exactly once. A `ChunkResult` carries
only aggregate counts and compact additive custom counts, so IPC scales with
the number of chunks rather than the number of shots.

For an explicit seed, shot `i` uses `(seed_base + i) mod 2**64`. The adaptive
Knill adapter resets an executor's temporary seed to `seed_base + shot_start`
and its temporary batch size to the lease size for one call, then restores
both fields. This avoids reusing the executor's internal batch-number seed
range while preserving worker-local caches.

## Scheduling and chunk sizes

Workers are initially assigned to unfinished jobs with the fewest active
workers. Assignment is sticky until a job completes. Each worker/job pair
starts at `initial_chunk_shots`; after a result, chunks double when runtime is
below `0.3 * target_chunk_seconds`, halve when above `1.3 * target`, and are
always clamped to `[1, max_chunk_shots]` and the job's remaining range.

`max_errors` stops new lease allocation once the manager's aggregate error
count reaches the target. Already-running leases are allowed to finish, so
the final error count can overshoot by the bounded in-flight work.

## Processes, errors, CPU use, and progress

Production uses a local `multiprocessing.get_context("spawn")`; it never
changes the application's global start method. `num_workers="auto"` uses
the current process's scheduler affinity when available, then process CPU
count/CPU count fallbacks. `allowed_cpu_ids` intersects that set. With
`pin_workers=True`, workers attempt best-effort affinity pinning and the
manager emits a warning if the platform refuses it.

Only the manager prints normal status. `verbose=0` is silent except for
errors, `verbose=1` periodically prints a compact job table, and `verbose=2`
also prints chunk completions. A structured `ProgressSnapshot` can be
received through `progress_callback`. The manager reports existing
`OMP_NUM_THREADS`, `OPENBLAS_NUM_THREADS`, and `MKL_NUM_THREADS` values above
one in verbose mode; it does not mutate the environment, so callers should
normally configure one native thread per worker themselves.

Worker exceptions are returned with worker/job/lease identity and the full
traceback. The manager stops scheduling, shuts down/terminates remaining
workers with bounded joins, and raises `ParallelWorkerError` in the parent.

## Checkpoint and resume

When `checkpoint_path` is set, the manager appends one JSONL record for each
completed lease. Workers never write this file. On resume, completed ranges
are reconstructed as disjoint intervals even when records arrived out of
order; exact duplicate records are safely ignored and conflicting or
overlapping records are rejected. A crash after physical completion but
before the parent append can rerun that lease. Thus execution is at-least-
once, while counted checkpoint ranges are exactly-once.

## Current scope

The public adaptive Knill hook supports `detail_level="summary"` only in
parallel mode. Detailed profiler aggregation, analysis/debug per-shot
merging, the legacy static backend, arbitrary non-pickleable decoder
generator closures, work stealing, distributed execution, and nested
multiprocessing are not implemented. Serial use of closure-based decoders
remains unchanged.
