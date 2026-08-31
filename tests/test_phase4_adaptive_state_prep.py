import numpy as np
import pymatching
import pytest

from hex_qec.circuit_generation import get_parity_check_matrices
from hex_qec.modularisation import (
    AdaptiveSERounds,
    generate_adaptive_state_prep_module,
    generate_adaptive_state_prep_modules,
)
from hex_qec.modularisation.module_generation import (
    generate_logical_measurement_module,
    generate_state_prep_modules,
)
from hex_qec.modularisation.results import normalize_module_decode_output
from hex_qec.circuit_generation.circuit_generation import (
    stabilizer_measurement_circuit_both_detectors,
)
from hex_qec.simulation import (
    AdaptivePolicyContext,
    AlwaysLongPolicy,
    AlwaysShortPolicy,
    StatefulAdaptiveStatePrepExecutor,
)


def test_forced_policies_return_uniform_masks():
    context = AdaptivePolicyContext(batch_size=4)

    np.testing.assert_array_equal(
        AlwaysShortPolicy().should_extend(None, context=context),
        np.array([False, False, False, False]),
    )
    np.testing.assert_array_equal(
        AlwaysLongPolicy().should_extend(None, context=context),
        np.array([True, True, True, True]),
    )


def make_adaptive_state_prep(
    *, short_rounds=1, long_rounds=3, pauli="z", physical_error=0.0
):
    parity_checks = get_parity_check_matrices("surface", 3)
    schedule = AdaptiveSERounds(short_rounds, long_rounds, AlwaysShortPolicy())
    return generate_adaptive_state_prep_module(
        parity_checks,
        schedule,
        pauli,
        physical_error,
        list(range(17)),
        pymatching.Matching.from_check_matrix,
        True,
    ), parity_checks


def test_adaptive_description_has_exact_short_extra_long_decomposition():
    description, _ = make_adaptive_state_prep()

    assert description.short_circuit + description.extra_circuit == description.long_circuit
    assert description.short_circuit.num_measurements == 8
    assert description.extra_circuit.num_measurements == 16
    assert description.long_circuit.num_measurements == 24
    assert description.short_module.circuit == description.short_circuit
    assert description.long_module.circuit == description.long_circuit


def test_surface_code_ordering_is_explicit_and_shared_by_fixed_adaptive_builders():
    parity_checks = get_parity_check_matrices("surface", 3)
    support = list(range(17))
    fixed_default = generate_state_prep_modules(
        parity_checks, 2, "z", 0.0, [support],
        pymatching.Matching.from_check_matrix, True,
    )[0]
    fixed_surface = generate_state_prep_modules(
        parity_checks, 2, "z", 0.0, [support],
        pymatching.Matching.from_check_matrix, True, surface_code=True,
    )[0]
    adaptive_surface = generate_adaptive_state_prep_module(
        parity_checks,
        AdaptiveSERounds(1, 2, AlwaysShortPolicy()),
        "z",
        0.0,
        support,
        pymatching.Matching.from_check_matrix,
        True,
        surface_code=True,
    )

    assert fixed_default.circuit != fixed_surface.circuit
    assert adaptive_surface.short_circuit + adaptive_surface.extra_circuit == adaptive_surface.long_circuit
    assert adaptive_surface.short_circuit != fixed_default.circuit
    data_qubits = set(range(parity_checks[0].shape[1]))
    for instruction in adaptive_surface.extra_circuit:
        if instruction.name in {"R", "RX", "RY"}:
            assert not any(
                target.is_qubit_target and target.qubit_value in data_qubits
                for target in instruction.targets_copy()
            )


def test_surface_code_stabilizer_diagnostics_are_debug_only(capsys):
    parity_checks = get_parity_check_matrices("surface", 3)

    stabilizer_measurement_circuit_both_detectors(
        parity_checks, "z", 1, 0.0, surface_code=True
    )
    assert capsys.readouterr().out == ""

    stabilizer_measurement_circuit_both_detectors(
        parity_checks, "z", 1, 0.0, surface_code=True, debug=True
    )
    output = capsys.readouterr().out
    assert "measure_X_stabilizers_surface_code!!!!" in output
    assert "measure_Z_stabilizers_surface_code!!!!" in output


def test_logical_measurement_qubit_diagnostic_is_debug_only(capsys):
    parity_checks = get_parity_check_matrices("surface", 3)
    support = list(range(9))

    generate_logical_measurement_module(
        parity_checks,
        0.0,
        "z",
        support,
        pymatching.Matching.from_check_matrix,
    )
    assert capsys.readouterr().out == ""

    generate_logical_measurement_module(
        parity_checks,
        0.0,
        "z",
        support,
        pymatching.Matching.from_check_matrix,
        debug=True,
    )
    assert capsys.readouterr().out == "Code number qubits: 9\n"


def test_schedule_validates_two_level_rounds():
    with pytest.raises(ValueError, match="at least 1"):
        AdaptiveSERounds(0, 1, AlwaysShortPolicy())
    with pytest.raises(ValueError, match="strictly less"):
        AdaptiveSERounds(3, 2, AlwaysShortPolicy())
    with pytest.raises(ValueError, match="strictly less"):
        AdaptiveSERounds(2, 2, AlwaysShortPolicy())


def test_adaptive_state_prep_generator_accepts_multiple_block_supports():
    parity_checks = get_parity_check_matrices("surface", 3)
    schedule = AdaptiveSERounds(1, 3, AlwaysShortPolicy())
    modules = generate_adaptive_state_prep_modules(
        parity_checks,
        schedule,
        "z",
        0.0,
        [list(range(17)), list(range(17, 34))],
        pymatching.Matching.from_check_matrix,
        True,
        event_id_prefix="teleportation=0,state=z",
        teleportation_index=0,
    )

    assert len(modules) == 2
    assert [module.event_id for module in modules] == [
        "teleportation=0,state=z[0]",
        "teleportation=0,state=z[1]",
    ]
    assert all(module.teleportation_index == 0 for module in modules)


def test_always_short_commits_short_result_and_does_not_run_extra_rounds():
    description, _ = make_adaptive_state_prep()

    execution = StatefulAdaptiveStatePrepExecutor().execute(
        description, batch_size=8, seed=11
    )

    assert not np.any(execution.used_long)
    assert execution.long_result is None
    assert execution.selected_measurements.shape == (8, 8)
    np.testing.assert_array_equal(
        execution.selected_measurements, execution.short_measurements
    )


def test_always_long_continues_same_shot_and_decodes_full_history():
    description, _ = make_adaptive_state_prep()
    seen = []
    original_long_decoder = description.long_module.c_func

    def recording_long_decoder(measurements):
        seen.append(measurements.copy())
        return original_long_decoder(measurements)

    description.long_module.c_func = recording_long_decoder
    description.schedule = AdaptiveSERounds(1, 3, AlwaysLongPolicy())

    execution = StatefulAdaptiveStatePrepExecutor().execute(
        description, batch_size=8, seed=12
    )

    assert np.all(execution.used_long)
    assert execution.long_result is not None
    assert execution.selected_measurements.shape == (8, 24)
    assert len(seen) == 1
    assert seen[0].shape == (8, 24)
    np.testing.assert_array_equal(
        seen[0], execution.selected_measurements
    )
    np.testing.assert_array_equal(
        execution.selected_measurements[:, :8], execution.short_measurements
    )


def test_mixed_policy_mask_executes_exact_per_shot_continuations():
    description, _ = make_adaptive_state_prep()

    class MixedPolicy:
        def should_extend(self, decode_result, *, context):
            return np.arange(context.batch_size) % 2 == 1

    description.schedule = AdaptiveSERounds(1, 3, MixedPolicy())
    execution = StatefulAdaptiveStatePrepExecutor().execute(
        description, batch_size=4, seed=15
    )

    np.testing.assert_array_equal(execution.used_long, [False, True, False, True])
    assert execution.selected_result is None
    assert execution.selected_results is not None
    assert isinstance(execution.selected_measurements, list)
    assert len(execution.selected_measurements) == 4
    assert execution.selected_measurements[0].shape == (8,)
    assert execution.selected_measurements[1].shape == (24,)


@pytest.mark.parametrize("pauli", ["x", "z"])
def test_forced_endpoints_match_ordinary_fixed_state_prep_decoders(pauli):
    description, parity_checks = make_adaptive_state_prep(pauli=pauli)
    support = list(range(17))
    ordinary_short = generate_state_prep_modules(
        parity_checks,
        1,
        pauli,
        0.0,
        [support],
        pymatching.Matching.from_check_matrix,
        matchable=True,
    )[0]
    ordinary_long = generate_state_prep_modules(
        parity_checks,
        3,
        pauli,
        0.0,
        [support],
        pymatching.Matching.from_check_matrix,
        matchable=True,
    )[0]

    short_execution = StatefulAdaptiveStatePrepExecutor().execute(
        description, batch_size=8, seed=13
    )
    description.schedule = AdaptiveSERounds(1, 3, AlwaysLongPolicy())
    long_execution = StatefulAdaptiveStatePrepExecutor().execute(
        description, batch_size=8, seed=14
    )

    adaptive_short = normalize_module_decode_output(
        short_execution.selected_result
    )
    ordinary_short_result = normalize_module_decode_output(
        ordinary_short.c_func(short_execution.short_measurements)
    )
    adaptive_long = normalize_module_decode_output(long_execution.selected_result)
    ordinary_long_result = normalize_module_decode_output(
        ordinary_long.c_func(long_execution.selected_measurements)
    )
    np.testing.assert_array_equal(
        adaptive_short.corrections, ordinary_short_result.corrections
    )
    np.testing.assert_array_equal(
        adaptive_long.corrections, ordinary_long_result.corrections
    )
