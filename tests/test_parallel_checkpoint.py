from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from hex_qec.parallel import (
    ChunkResult,
    ParallelExecutionOptions,
    ParallelJobSpec,
    ParallelManager,
)
from hex_qec.parallel.checkpoint import CheckpointError, CheckpointStore


@dataclass
class CheckpointFactory:
    job_id: str

    def prepare(self):
        return CheckpointPrepared(self.job_id)


@dataclass
class CheckpointPrepared:
    job_id: str

    def run_chunk(self, shot_start, shot_count, seed_base):
        errors = sum((shot_start + i) % 5 == 0 for i in range(shot_count))
        return ChunkResult(
            self.job_id,
            "worker-assigned",
            shot_start,
            shot_count,
            errors,
            0.01,
            {"weighted": shot_count * 2},
        )


def make_spec(path, fingerprint="v1"):
    return ParallelJobSpec(
        "job",
        CheckpointFactory("job"),
        10,
        seed_base=17,
        config_fingerprint=fingerprint,
        metadata={"distance": 3},
    )


def options(path):
    return ParallelExecutionOptions(
        num_workers=1,
        initial_chunk_shots=2,
        max_chunk_shots=2,
        checkpoint_path=path,
        status_interval_seconds=0.05,
    )


def test_resume_reconstructs_holes_and_matches_uninterrupted_run(tmp_path):
    path = tmp_path / "run.jsonl"
    spec = make_spec(path)
    store = CheckpointStore(path)
    # Completion order is intentionally not shot order.  Range [7, 10) is
    # left for the restarted manager.
    store.append(ChunkResult("job", "lease-b", 4, 3, 1, 0.1, {"weighted": 6}), spec)
    store.append(ChunkResult("job", "lease-a", 0, 4, 1, 0.1, {"weighted": 8}), spec)
    resumed = ParallelManager(options(path)).run([spec])
    uninterrupted = ParallelManager(
        ParallelExecutionOptions(
            num_workers=1,
            initial_chunk_shots=2,
            max_chunk_shots=2,
            status_interval_seconds=0.05,
        )
    ).run([make_spec(tmp_path / "unused.jsonl")])
    assert resumed.shots == uninterrupted.shots == 10
    assert resumed.logical_errors == uninterrupted.logical_errors
    assert resumed.jobs[0].custom_counts == uninterrupted.jobs[0].custom_counts
    assert resumed.jobs[0].completed_ranges == ((0, 10),)


def test_duplicate_checkpoint_record_is_safely_deduplicated(tmp_path):
    path = tmp_path / "duplicate.jsonl"
    spec = make_spec(path)
    result = ChunkResult("job", "same", 0, 10, 2, 0.1, {"weighted": 20})
    store = CheckpointStore(path)
    store.append(result, spec)
    store.append(result, spec)
    resumed = ParallelManager(options(path)).run([spec])
    assert resumed.shots == 10
    assert resumed.logical_errors == 2
    assert resumed.jobs[0].custom_counts == {"weighted": 20}


def test_checkpoint_configuration_mismatch_is_clear(tmp_path):
    path = tmp_path / "mismatch.jsonl"
    old_spec = make_spec(path, "old")
    CheckpointStore(path).append(
        ChunkResult("job", "lease", 0, 2, 0, 0.1), old_spec
    )
    with pytest.raises(CheckpointError, match="fingerprint mismatch"):
        ParallelManager(options(path)).run([make_spec(path, "new")])


def test_malformed_checkpoint_line_is_clear(tmp_path):
    path = tmp_path / "bad.jsonl"
    path.write_text('{"schema_version": 1}\nnot-json\n')
    with pytest.raises(CheckpointError, match="missing keys"):
        ParallelManager(options(path)).run([make_spec(path)])
    path.write_text("not-json\n")
    with pytest.raises(CheckpointError, match="malformed checkpoint line 1"):
        ParallelManager(options(path)).run([make_spec(path)])


def test_conflicting_duplicate_lease_is_rejected(tmp_path):
    path = tmp_path / "conflict.jsonl"
    spec = make_spec(path)
    store = CheckpointStore(path)
    store.append(ChunkResult("job", "lease", 0, 2, 0, 0.1), spec)
    store.append(ChunkResult("job", "lease", 0, 2, 1, 0.1), spec)
    with pytest.raises(CheckpointError, match="conflicting duplicate"):
        ParallelManager(options(path)).run([spec])

