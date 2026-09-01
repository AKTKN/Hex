from __future__ import annotations

import multiprocessing
import os
import time
from dataclasses import dataclass

import pytest

from hex_qec.parallel import (
    ChunkResult,
    ParallelExecutionOptions,
    ParallelJobSpec,
    ParallelManager,
    ParallelWorkerError,
)


@dataclass
class FakePreparedJob:
    sleep_seconds: float = 0.0
    fail: bool = False

    def run_chunk(self, shot_start, shot_count, seed_base):
        if self.fail:
            raise RuntimeError("intentional fake backend failure")
        if self.sleep_seconds:
            time.sleep(self.sleep_seconds)
        errors = sum(
            ((seed_base + index) if seed_base is not None else index) % 7 == 0
            for index in range(shot_start, shot_start + shot_count)
        )
        return ChunkResult(
            job_id=self.job_id,
            lease_id=self.lease_id,
            shot_start=shot_start,
            shots=shot_count,
            logical_errors=errors,
            runtime_seconds=self.sleep_seconds,
        )


@dataclass
class FakeFactory:
    sleep_seconds: float = 0.0
    fail: bool = False
    marker_path: str | None = None

    def prepare(self):
        if self.marker_path is not None:
            with open(self.marker_path, "a") as marker:
                marker.write(f"{os.getpid()}\n")
        prepared = FakePreparedJob(self.sleep_seconds, self.fail)
        # The worker fills these fields for each lease.  Keeping the prepared
        # object itself worker-local is the behavior under test.
        return _LeaseBoundFakePrepared(prepared)


class _LeaseBoundFakePrepared:
    def __init__(self, inner):
        self.inner = inner

    def run_chunk(self, shot_start, shot_count, seed_base):
        # The generic manager deliberately does not know fake-job semantics.
        # This implementation uses the fixed job id carried by the factory in
        # a test-specific wrapper below.
        return self.inner.run_chunk(shot_start, shot_count, seed_base)


@dataclass
class CorrectFakeFactory:
    job_id: str
    sleep_seconds: float = 0.0
    fail: bool = False
    marker_path: str | None = None

    def prepare(self):
        if self.marker_path is not None:
            with open(self.marker_path, "a") as marker:
                marker.write(f"{self.job_id}:{os.getpid()}\n")
        return CorrectFakePrepared(self.job_id, self.sleep_seconds, self.fail)


@dataclass
class CorrectFakePrepared:
    job_id: str
    sleep_seconds: float = 0.0
    fail: bool = False

    def run_chunk(self, shot_start, shot_count, seed_base):
        if self.fail:
            raise RuntimeError("intentional fake backend failure")
        if self.sleep_seconds:
            time.sleep(self.sleep_seconds)
        values = [
            ((seed_base + index) if seed_base is not None else index) % 7 == 0
            for index in range(shot_start, shot_start + shot_count)
        ]
        return ChunkResult(
            self.job_id,
            f"unused-{shot_start}",
            shot_start,
            shot_count,
            sum(values),
            self.sleep_seconds,
        )


def options(num_workers, **kwargs):
    values = dict(
        num_workers=num_workers,
        target_chunk_seconds=1.0,
        initial_chunk_shots=1,
        max_chunk_shots=4,
        status_interval_seconds=0.05,
    )
    values.update(kwargs)
    return ParallelExecutionOptions(**values)


def make_job(job_id="job", shots=32, seed=100, factory=None):
    return ParallelJobSpec(
        job_id=job_id,
        factory=factory or CorrectFakeFactory(job_id),
        max_shots=shots,
        seed_base=seed,
    )


@pytest.mark.parametrize("num_workers", [1, 2, 4])
def test_spawn_workers_cover_all_shots_with_identical_totals(num_workers):
    result = ParallelManager(options(num_workers)).run([make_job(shots=40)])
    assert result.shots == 40
    assert result.logical_errors == sum((100 + i) % 7 == 0 for i in range(40))
    assert result.jobs[0].completed_ranges == ((0, 40),)
    assert result.metadata["multiprocessing_start_method"] == "spawn"


def test_completion_order_does_not_change_aggregate_result():
    slow = CorrectFakeFactory("job", sleep_seconds=0.01)
    fast = CorrectFakeFactory("job", sleep_seconds=0.0)
    slow_result = ParallelManager(options(2)).run([make_job(factory=slow, shots=24)])
    fast_result = ParallelManager(options(2)).run([make_job(factory=fast, shots=24)])
    assert slow_result.shots == fast_result.shots == 24
    assert slow_result.logical_errors == fast_result.logical_errors


def test_prepared_job_is_created_once_and_reused_across_chunks(tmp_path):
    marker = tmp_path / "prepared.txt"
    factory = CorrectFakeFactory("job", marker_path=str(marker))
    result = ParallelManager(options(1)).run([make_job(shots=16, factory=factory)])
    assert result.shots == 16
    assert len(marker.read_text().splitlines()) == 1


def test_fully_leased_small_job_does_not_repeatedly_prepare_workers(tmp_path):
    marker = tmp_path / "prepared.txt"
    factory = CorrectFakeFactory("job", marker_path=str(marker))
    result = ParallelManager(
        options(8, initial_chunk_shots=1, max_chunk_shots=1)
    ).run([make_job(shots=2, factory=factory)])
    assert result.shots == 2
    # Several workers may legitimately prepare before the first two leases
    # complete, but no worker may reload in a scheduler loop.
    assert 1 <= len(marker.read_text().splitlines()) <= 8


def test_more_workers_than_shots_have_no_duplicates_or_gaps():
    result = ParallelManager(
        options(8, initial_chunk_shots=1, max_chunk_shots=1)
    ).run([make_job(shots=3)])
    assert result.shots == 3
    assert result.jobs[0].completed_ranges == ((0, 3),)


def test_job_change_prepares_new_state_only_after_previous_job_completes(tmp_path):
    marker = tmp_path / "prepared.txt"
    jobs = [
        make_job("a", shots=5, factory=CorrectFakeFactory("a", marker_path=str(marker))),
        make_job("b", shots=5, factory=CorrectFakeFactory("b", marker_path=str(marker))),
    ]
    result = ParallelManager(options(1)).run(jobs)
    assert result.shots == 10
    lines = marker.read_text().splitlines()
    assert len(lines) == 2
    assert [line.split(":", 1)[0] for line in lines] == ["a", "b"]


def test_worker_exception_propagates_and_children_are_shutdown():
    with pytest.raises(ParallelWorkerError, match="intentional fake backend failure"):
        ParallelManager(options(2)).run(
            [make_job(factory=CorrectFakeFactory("job", fail=True))]
        )
    time.sleep(0.1)
    assert not [child for child in multiprocessing.active_children() if child.is_alive()]


def test_verbose_zero_is_silent_and_verbose_one_is_manager_status(capsys):
    ParallelManager(options(1, verbose=0)).run([make_job(shots=4)])
    assert capsys.readouterr().out == ""
    ParallelManager(options(1, verbose=1)).run([make_job(shots=4)])
    output = capsys.readouterr().out
    assert "jobs remaining" in output
    assert "job" in output


def test_non_pickleable_factory_fails_before_worker_start():
    factory = lambda: None
    with pytest.raises(TypeError, match="not pickleable"):
        ParallelManager(options(1)).run([make_job(factory=factory)])
