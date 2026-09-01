from __future__ import annotations

from dataclasses import dataclass

import pymatching

from hex_qec.circuit_generation import get_parity_check_matrices
from hex_qec.modularisation import AdaptiveSERounds
from hex_qec.modularisation.results import SimulationResult, SimulationSummary
from hex_qec.protocols.knill_online_offline import (
    _build_knill_online_offline_adaptive_executor,
)
from hex_qec.protocols import knill_online_offline_adaptive
from hex_qec.parallel import ParallelExecutionOptions
from hex_qec.protocols.parallel_adapters import run_adaptive_executor_chunk
from hex_qec.simulation import AlwaysLongPolicy


@dataclass
class RecordingExecutor:
    seed: int | None = 9
    batch_size: int = 11

    def __post_init__(self):
        self.calls = []

    def simulate_result(self, max_shots, max_errors_before_halting, *, detail_level):
        self.calls.append((self.seed, self.batch_size, max_shots, max_errors_before_halting, detail_level))
        return SimulationResult(
            SimulationSummary(max_shots, 0, 0.0, 0.0),
            detail_level=detail_level,
        )


def test_executor_chunk_adapter_maps_global_seed_and_restores_state():
    executor = RecordingExecutor()
    result = run_adaptive_executor_chunk(executor, 13, 4, 100)
    assert result.shots == 4
    assert executor.calls == [(113, 4, 4, 5, "summary")]
    assert executor.seed == 9
    assert executor.batch_size == 11


def test_executor_chunk_adapter_restores_state_after_failure():
    class FailingExecutor(RecordingExecutor):
        def simulate_result(self, *args, **kwargs):
            raise RuntimeError("expected")

    executor = FailingExecutor()
    try:
        run_adaptive_executor_chunk(executor, 2, 3, 10)
    except RuntimeError as error:
        assert str(error) == "expected"
    else:
        raise AssertionError("expected adapter failure")
    assert executor.seed == 9
    assert executor.batch_size == 11


def test_real_adaptive_executor_is_invariant_to_exact_chunk_partition():
    parity_checks = get_parity_check_matrices("surface", 3)
    schedule = AdaptiveSERounds(1, 2, AlwaysLongPolicy())
    serial = _build_knill_online_offline_adaptive_executor(
        parity_checks,
        schedule,
        pymatching.Matching.from_check_matrix,
        pymatching.Matching.from_check_matrix,
        True,
        0.003,
        "z",
        1,
        batch_size=8,
        seed=123,
    ).simulate_result(8, 100, detail_level="summary")

    executor = _build_knill_online_offline_adaptive_executor(
        parity_checks,
        schedule,
        pymatching.Matching.from_check_matrix,
        pymatching.Matching.from_check_matrix,
        True,
        0.003,
        "z",
        1,
        batch_size=1,
        seed=None,
    )
    first = run_adaptive_executor_chunk(executor, 0, 3, 123)
    second = run_adaptive_executor_chunk(executor, 3, 5, 123)
    assert first.logical_errors + second.logical_errors == serial.logical_errors
    assert sum(item.short_count or 0 for item in first.state_prep_stats) + sum(
        item.short_count or 0 for item in second.state_prep_stats
    ) == sum(item.short_count or 0 for item in serial.state_prep_stats)
    assert sum(item.long_count or 0 for item in first.state_prep_stats) + sum(
        item.long_count or 0 for item in second.state_prep_stats
    ) == sum(item.long_count or 0 for item in serial.state_prep_stats)


def test_parallel_adaptive_knill_matches_serial_for_worker_counts():
    parity_checks = get_parity_check_matrices("surface", 3)
    common = dict(
        parity_check_tuple=parity_checks,
        adaptive_schedule=AdaptiveSERounds(1, 2, AlwaysLongPolicy()),
        online_decoder_generator=pymatching.Matching.from_check_matrix,
        offline_decoder_generator=pymatching.Matching.from_check_matrix,
        matchable_offline_decoding=True,
        physical_error=0.003,
        max_shots=8,
        max_errors_before_halting=100,
        pauli="z",
        num_teleportations=1,
        seed=123,
    )
    serial = knill_online_offline_adaptive(**common, batch_size=8)
    parallel_results = [
        knill_online_offline_adaptive(
            **common,
            parallel_options=ParallelExecutionOptions(
                num_workers=workers,
                initial_chunk_shots=1,
                max_chunk_shots=3,
                target_chunk_seconds=1.0,
            ),
        )
        for workers in (1, 2, 4)
    ]
    for result in parallel_results:
        assert result.to_legacy_tuple() == serial.to_legacy_tuple()
        assert [item.short_count for item in result.state_prep_stats] == [
            item.short_count for item in serial.state_prep_stats
        ]
        assert [item.long_count for item in result.state_prep_stats] == [
            item.long_count for item in serial.state_prep_stats
        ]
        assert [item.both_count for item in result.bell_pair_stats] == [
            item.both_count for item in serial.bell_pair_stats
        ]


def test_parallel_adaptive_checkpoint_replay(tmp_path):
    parity_checks = get_parity_check_matrices("surface", 3)
    common = dict(
        parity_check_tuple=parity_checks,
        adaptive_schedule=AdaptiveSERounds(1, 2, AlwaysLongPolicy()),
        online_decoder_generator=pymatching.Matching.from_check_matrix,
        offline_decoder_generator=pymatching.Matching.from_check_matrix,
        matchable_offline_decoding=True,
        physical_error=0.003,
        max_shots=4,
        max_errors_before_halting=100,
        pauli="z",
        num_teleportations=1,
        seed=321,
    )
    options = ParallelExecutionOptions(
        num_workers=1,
        initial_chunk_shots=1,
        max_chunk_shots=2,
        checkpoint_path=tmp_path / "adaptive.jsonl",
    )
    first = knill_online_offline_adaptive(**common, parallel_options=options)
    second = knill_online_offline_adaptive(**common, parallel_options=options)
    assert first.to_legacy_tuple() == second.to_legacy_tuple()
    assert [item.long_count for item in first.state_prep_stats] == [
        item.long_count for item in second.state_prep_stats
    ]


def test_parallel_adaptive_rejects_unsupported_detail_and_profiler():
    parity_checks = get_parity_check_matrices("surface", 3)
    common = dict(
        parity_check_tuple=parity_checks,
        adaptive_schedule=AdaptiveSERounds(1, 2, AlwaysLongPolicy()),
        online_decoder_generator=pymatching.Matching.from_check_matrix,
        offline_decoder_generator=pymatching.Matching.from_check_matrix,
        matchable_offline_decoding=True,
        physical_error=0.0,
        max_shots=1,
        max_errors_before_halting=100,
        pauli="z",
        num_teleportations=1,
        seed=1,
        parallel_options=ParallelExecutionOptions(num_workers=1),
    )
    import pytest

    with pytest.raises(NotImplementedError, match="summary"):
        knill_online_offline_adaptive(**common, detail_level="analysis")
    with pytest.raises(ValueError, match="profiler"):
        knill_online_offline_adaptive(**common, profiler=object())
