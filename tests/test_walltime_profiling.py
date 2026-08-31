from types import SimpleNamespace
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pymatching

from profiling.adaptive_walltime_profile import (
    _event_rows,
    _make_report,
    _summary_rows,
    _write_csv,
)
from hex_qec.circuit_generation import get_parity_check_matrices
from hex_qec.modularisation import AdaptiveSERounds
from hex_qec.protocols import knill_online_offline_adaptive
from hex_qec.simulation import (
    AlwaysLongPolicy,
    TimingEvent,
    WallTimeProfiler,
)


def test_walltime_profiler_records_nested_and_repeated_sections():
    profiler = WallTimeProfiler()
    with profiler.context_scope(shot_index=3, phase="measured"):
        with profiler.section("outer", absolute=True):
            with profiler.section("inner"):
                pass
        with profiler.section("repeat", absolute=True):
            pass
        with profiler.section("repeat", absolute=True):
            pass

    assert {event.section for event in profiler.events} == {
        "outer",
        "outer.inner",
        "repeat",
    }
    assert sum(event.section == "repeat" for event in profiler.events) == 2
    assert all(event.shot_index == 3 for event in profiler.events)


def test_disabled_walltime_profiler_records_no_events():
    profiler = WallTimeProfiler(enabled=False)
    with profiler.section("does_not_matter", absolute=True):
        pass
    assert profiler.events == ()


def test_profile_reports_write_raw_summary_and_markdown(tmp_path):
    events = (
        TimingEvent("shot.total_wall_time", 0.010, 0, "measured", {}),
        TimingEvent("shot.physical.short.total", 0.002, 0, "measured", {}),
        TimingEvent("shot.total_wall_time", 0.011, 1, "measured", {}),
        TimingEvent("shot.physical.short.total", 0.003, 1, "measured", {}),
    )
    args = SimpleNamespace(
        distance=3,
        physical_error=0.0,
        short_rounds=1,
        num_shots=2,
        num_teleportations=1,
        pauli="z",
        seed=1,
    )
    raw = _event_rows(events, args=args, policy_name="always-long", long_rounds=3)
    summary = _summary_rows(events, measured_shots=2, warmup_shots=0)
    _write_csv(tmp_path / "raw.csv", list(raw[0]), raw)
    _write_csv(tmp_path / "summary.csv", list(summary[0]), summary)
    _make_report(
        tmp_path / "report.md",
        args=args,
        long_rounds=3,
        policy_name="always-long",
        result=SimpleNamespace(
            per_shot=None,
            logical_errors=0,
            shots=2,
        ),
        events=events,
        metadata={"git_sha": "test"},
        warmup_shots=0,
    )
    assert (tmp_path / "raw.csv").read_text()
    assert (tmp_path / "summary.csv").read_text()
    assert "unaccounted/other" in (tmp_path / "report.md").read_text()


def test_profiling_does_not_change_seeded_adaptive_result():
    parity_checks = get_parity_check_matrices("surface", 3)
    common = dict(
        parity_check_tuple=parity_checks,
        adaptive_schedule=AdaptiveSERounds(1, 2, AlwaysLongPolicy()),
        online_decoder_generator=pymatching.Matching.from_check_matrix,
        offline_decoder_generator=pymatching.Matching.from_check_matrix,
        matchable_offline_decoding=True,
        physical_error=0.0,
        max_shots=1,
        max_errors_before_halting=10,
        pauli="z",
        num_teleportations=1,
        batch_size=1,
        seed=77,
        surface_code=True,
        detail_level="analysis",
    )
    without_profile = knill_online_offline_adaptive(**common)
    profiler = WallTimeProfiler()
    with_profile = knill_online_offline_adaptive(**common, profiler=profiler)

    assert without_profile.logical_errors == with_profile.logical_errors
    np.testing.assert_array_equal(
        without_profile.per_shot["used_long_pair"],
        with_profile.per_shot["used_long_pair"],
    )
    np.testing.assert_array_equal(
        without_profile.per_shot["would_extend_zero"],
        with_profile.per_shot["would_extend_zero"],
    )
    assert any(event.section == "correction_map.cache_miss" for event in profiler.events)
    assert any(event.section == "corrected_measurements.reference_sample" for event in profiler.events)
