import pytest

from hex_qec.parallel import (
    ChunkResult,
    ChunkSizeController,
    JobState,
    ParallelExecutionOptions,
    ParallelJobSpec,
    ParallelManager,
    ProgressSnapshot,
    ShotLease,
    WorkerState,
    first_missing_index,
    merge_intervals,
)


class DummyFactory:
    def prepare(self):
        raise AssertionError("not used by pure scheduler tests")


def make_state(job_id="job", shots=100, max_errors=None):
    return JobState(ParallelJobSpec(job_id, DummyFactory(), shots, max_errors=max_errors))


def complete(state, lease, errors=0):
    ParallelManager._record_result(
        state,
        ChunkResult(
            state.spec.job_id,
            lease.lease_id,
            lease.shot_start,
            lease.shot_count,
            errors,
            0.1,
        ),
    )


def test_single_job_allocates_exact_global_range_and_truncates_final_chunk():
    state = make_state(shots=100)
    leases = []
    while not state.complete:
        lease = ParallelManager._allocate_lease(state, 37)
        assert lease is not None
        leases.append(lease)
        complete(state, lease)

    assert [(lease.shot_start, lease.end) for lease in leases] == [
        (0, 37),
        (37, 74),
        (74, 100),
    ]
    assert state.completed_ranges == [(0, 100)]
    assert first_missing_index(state.completed_ranges, 100) is None


def test_multiple_active_workers_receive_disjoint_ranges():
    state = make_state(shots=100)
    leases = [ParallelManager._allocate_lease(state, 25) for _ in range(4)]
    assert all(lease is not None for lease in leases)
    ranges = [(lease.shot_start, lease.end) for lease in leases]
    assert sorted(ranges) == [(0, 25), (25, 50), (50, 75), (75, 100)]
    assert len({index for start, end in ranges for index in range(start, end)}) == 100


def test_checkpointed_hole_is_skipped_without_overlap():
    state = make_state(shots=100)
    ParallelManager._record_result_from_checkpoint(
        state,
        ChunkResult("job", "old", 40, 20, 0, 0.1),
    )
    lease = ParallelManager._allocate_lease(state, 50)
    assert lease is not None
    assert (lease.shot_start, lease.end) == (0, 40)
    complete(state, lease)
    lease = ParallelManager._allocate_lease(state, 50)
    assert lease is not None
    assert (lease.shot_start, lease.end) == (60, 100)


def test_scheduler_prefers_job_with_fewest_active_workers():
    states = {name: make_state(name, 10) for name in ("a", "b", "c")}
    workers = {
        0: WorkerState(0, job_id="a"),
        1: WorkerState(1, job_id="a"),
        2: WorkerState(2, job_id="b"),
    }
    assert ParallelManager._select_job(states, workers).spec.job_id == "c"
    workers[2].job_id = "c"
    assert ParallelManager._select_job(states, workers).spec.job_id == "b"


class RecordingQueue:
    def __init__(self):
        self.messages = []

    def put(self, message):
        self.messages.append(message)


def test_worker_stays_sticky_until_job_completion():
    from hex_qec.parallel.types import LoadJob, RunLease

    state = make_state("a", 1)
    states = {"a": state, "b": make_state("b", 3)}
    worker = WorkerState(0, job_id="a", ready=True)
    workers = {0: worker}
    controllers = {(0, "a"): ChunkSizeController(1.0, 1, 10)}
    queue = RecordingQueue()
    manager = ParallelManager(ParallelExecutionOptions(num_workers=1))

    manager._dispatch_worker(worker, queue, states, workers, controllers)
    assert isinstance(queue.messages[-1], RunLease)
    assert worker.job_id == "a"
    lease = queue.messages[-1].lease
    complete(state, lease)
    worker.busy = False
    worker.current_lease = None
    manager._dispatch_worker(worker, queue, states, workers, controllers)
    assert isinstance(queue.messages[-1], LoadJob)
    assert worker.job_id == "b"


def test_chunk_controller_ramps_and_clamps():
    controller = ChunkSizeController(1.0, initial_shots=2, max_shots=8)
    assert controller.observe(0.1) == 4
    assert controller.observe(0.1) == 8
    assert controller.observe(0.1) == 8
    assert controller.observe(2.0) == 4
    assert controller.observe(2.0) == 2
    assert controller.next_size(1) == 1


def test_max_errors_prevents_new_lease_allocation():
    state = make_state(shots=100, max_errors=1)
    lease = ParallelManager._allocate_lease(state, 10)
    assert lease is not None
    complete(state, lease, errors=1)
    assert state.stopped_by_error_limit
    assert ParallelManager._allocate_lease(state, 10) is None


def test_progress_snapshot_contains_aggregate_counts():
    state = make_state(shots=10)
    lease = ParallelManager._allocate_lease(state, 4)
    assert lease is not None
    complete(state, lease, errors=2)
    manager = ParallelManager(ParallelExecutionOptions(num_workers=1))
    snapshot = manager._make_snapshot(
        {"job": state},
        {0: WorkerState(0, job_id="job")},
        {},
        0.0,
    )
    assert isinstance(snapshot, ProgressSnapshot)
    assert snapshot.total_shots_completed == 4
    assert snapshot.total_logical_errors == 2
    assert snapshot.jobs[0].shots_completed == 4


@pytest.mark.parametrize(
    "kwargs",
    [
        {"num_workers": 0},
        {"target_chunk_seconds": 0},
        {"initial_chunk_shots": 0},
        {"max_chunk_shots": 0},
        {"initial_chunk_shots": 2, "max_chunk_shots": 1},
        {"verbose": 3},
    ],
)
def test_parallel_options_validate_aggressively(kwargs):
    with pytest.raises(ValueError):
        ParallelExecutionOptions(**kwargs)


def test_interval_helpers_reject_overlap_and_find_missing_index():
    assert merge_intervals([(0, 2)], (2, 4)) == [(0, 4)]
    with pytest.raises(ValueError):
        merge_intervals([(0, 3)], (2, 4))
    assert first_missing_index([(0, 2), (4, 6)], 7) == 2
    assert first_missing_index([(0, 7)], 7) is None
