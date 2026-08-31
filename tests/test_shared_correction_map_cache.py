import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pymatching
import pytest

import hex_qec.simulation.adaptive as adaptive_impl
from hex_qec.circuit_generation import get_parity_check_matrices
from hex_qec.modularisation import AdaptiveSERounds
from hex_qec.modularisation import generate_adaptive_state_prep_module
from hex_qec.protocols import knill_online_offline_adaptive
from hex_qec.simulation import (
    AlwaysLongPolicy,
    AlwaysShortPolicy,
    StatefulAdaptiveKnillExecutor,
    WallTimeProfiler,
)


def test_separate_shot_runners_reuse_the_same_prepared_map(monkeypatch):
    generated = []
    map_object = object()

    def fake_generate(units):
        generated.append(tuple(units))
        return (map_object,)

    monkeypatch.setattr(adaptive_impl, "_generate_correction_maps", fake_generate)
    cache = adaptive_impl._CorrectionMapCache()
    unit = object()
    cache.prepare((unit,))

    first = adaptive_impl._AdaptiveShotRunner(
        seed=1,
        correction_map_cache=cache,
    )
    second = adaptive_impl._AdaptiveShotRunner(
        seed=2,
        correction_map_cache=cache,
    )

    first_maps = first._correction_maps((unit,))
    second_maps = second._correction_maps((unit,))

    assert first_maps is second_maps
    assert first_maps[0] is map_object
    assert len(generated) == 1
    assert cache.generation_count == 1


def test_different_logical_paths_use_distinct_cache_entries(monkeypatch):
    generated = []

    def fake_generate(units):
        value = object()
        generated.append((tuple(units), value))
        return (value,)

    monkeypatch.setattr(adaptive_impl, "_generate_correction_maps", fake_generate)
    cache = adaptive_impl._CorrectionMapCache()
    short_module = object()
    long_module = object()

    short_maps = cache.prepare((short_module,))
    long_maps = cache.prepare((long_module,))

    assert adaptive_impl._path_key((short_module,)) != adaptive_impl._path_key(
        (long_module,)
    )
    assert short_maps is not long_maps
    assert short_maps[0] is not long_maps[0]
    assert len(cache.keys) == 2
    assert len(generated) == 2


@pytest.mark.parametrize("pauli", ["z", "x"])
def test_precomputed_suffix_matches_detector_stripping_for_both_bases(pauli):
    parity_checks = get_parity_check_matrices("surface", 3)
    description = generate_adaptive_state_prep_module(
        parity_checks,
        AdaptiveSERounds(1, 2, AlwaysShortPolicy()),
        pauli,
        0.0,
        list(range(17)),
        pymatching.Matching.from_check_matrix,
        True,
        surface_code=True,
    )
    executor = StatefulAdaptiveKnillExecutor([description], batch_size=1)
    precomputed = executor._stripped_suffix_cache[id(description)]

    assert precomputed == adaptive_impl._without_detectors(description.extra_circuit)
    assert "DETECTOR" not in str(precomputed)
    assert precomputed.num_measurements == (
        adaptive_impl._without_detectors(description.extra_circuit).num_measurements
    )


def test_suffix_stripping_happens_once_and_always_short_does_not_execute_it(
    monkeypatch,
):
    calls = []
    original = adaptive_impl._without_detectors

    def counted(circuit):
        calls.append(circuit)
        return original(circuit)

    monkeypatch.setattr(adaptive_impl, "_without_detectors", counted)
    parity_checks = get_parity_check_matrices("surface", 3)
    profiler = WallTimeProfiler()
    result = knill_online_offline_adaptive(
        parity_checks,
        AdaptiveSERounds(1, 2, AlwaysShortPolicy()),
        online_decoder_generator=pymatching.Matching.from_check_matrix,
        offline_decoder_generator=pymatching.Matching.from_check_matrix,
        matchable_offline_decoding=True,
        physical_error=0.0,
        max_shots=3,
        max_errors_before_halting=10,
        pauli="z",
        num_teleportations=1,
        batch_size=1,
        seed=456,
        surface_code=True,
        detail_level="analysis",
        profiler=profiler,
    )

    assert result.shots == 3
    assert len(calls) == 2
    assert not any(
        event.section == "shot.physical.long.zero" for event in profiler.events
    )
    assert not any(
        event.section == "shot.physical.long.plus" for event in profiler.events
    )


def test_one_teleportation_prepares_short_and_long_paths_before_shots():
    parity_checks = get_parity_check_matrices("surface", 3)
    profiler = WallTimeProfiler()
    result = knill_online_offline_adaptive(
        parity_checks,
        AdaptiveSERounds(1, 2, AlwaysLongPolicy()),
        online_decoder_generator=pymatching.Matching.from_check_matrix,
        offline_decoder_generator=pymatching.Matching.from_check_matrix,
        matchable_offline_decoding=True,
        physical_error=0.0,
        max_shots=3,
        max_errors_before_halting=10,
        pauli="z",
        num_teleportations=1,
        batch_size=1,
        seed=123,
        surface_code=True,
        detail_level="analysis",
        profiler=profiler,
    )

    setup_generations = [
        event
        for event in profiler.events
        if event.phase == "setup"
        and event.section == "setup.correction_map.generate"
    ]
    measured_fallbacks = [
        event
        for event in profiler.events
        if event.phase == "measured"
        and event.section == "shot.correction_map.fallback_generate"
    ]
    measured_lookups = [
        event
        for event in profiler.events
        if event.phase == "measured"
        and event.section == "shot.correction_map.lookup"
    ]

    assert result.shots == 3
    assert len(set(event.shot_index for event in measured_lookups)) == 3
    assert not measured_fallbacks
    # Five all-short path prefixes plus the long branch and its three
    # downstream prefixes are distinct logical paths (initial/short prefixes
    # are shared between the two branch plans).
    assert len(setup_generations) == 9
    assert {event.phase for event in setup_generations} == {"setup"}
    assert {event.shot_index for event in setup_generations} == {-1}
    assert len(set(event.shot_index for event in measured_lookups)) == 3


def test_shared_cache_keeps_two_teleportation_workflow_working():
    parity_checks = get_parity_check_matrices("surface", 3)
    result = knill_online_offline_adaptive(
        parity_checks,
        AdaptiveSERounds(1, 2, AlwaysLongPolicy()),
        online_decoder_generator=pymatching.Matching.from_check_matrix,
        offline_decoder_generator=pymatching.Matching.from_check_matrix,
        matchable_offline_decoding=True,
        physical_error=0.0,
        max_shots=1,
        max_errors_before_halting=10,
        pauli="z",
        num_teleportations=2,
        batch_size=1,
        seed=321,
        surface_code=True,
        detail_level="analysis",
    )
    assert result.shots == 1
    assert result.per_shot["used_long_pair"].shape == (1, 2)
