import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pymatching
import stim

from diagnostics.forced_long_consistency import (
    CheckpointStore,
    DiagnosticConfig,
    apply_measurement_permutation,
    build_adaptive_modules,
    build_fixed_modules,
    build_measurement_permutation,
    check_permutation,
    classify_diagnostic,
    compare_physical_instructions,
    json_safe,
    pairwise_statistics,
    stripped_detector_circuit,
    _check_cache,
    _check_decoder_endpoints,
)
from hex_qec.circuit_generation import get_parity_check_matrices
from hex_qec.simulation import AlwaysLongPolicy, StatefulAdaptiveKnillExecutor


def test_physical_instruction_comparison_checks_order_and_arguments():
    same = compare_physical_instructions(stim.Circuit("M 0"), stim.Circuit("M 0"))
    different = compare_physical_instructions(
        stim.Circuit("M 0"), stim.Circuit("X_ERROR(0.1) 0\nM 0")
    )
    assert same["exact_equal"]
    assert not different["exact_equal"]
    assert different["first_difference"]["index"] == 0


def test_fixed_long_equals_adaptive_long_state_prep_for_d3_both_bases():
    parity = get_parity_check_matrices("surface", 3)
    fixed = build_fixed_modules(parity, 3, 0.0, num_teleportations=1, pauli="z", surface_code=True)
    adaptive = build_adaptive_modules(parity, 3, 0.0, short_rounds=1, num_teleportations=1, pauli="z", surface_code=True)
    fixed_preps = [module for module in fixed if module.__class__.__name__ == "css_detector_module"]
    adaptive_preps = [module for module in adaptive if hasattr(module, "long_module")]
    for left, right in zip(fixed_preps, adaptive_preps):
        assert compare_physical_instructions(left.circuit, right.long_module.circuit)["exact_equal"]


def test_short_plus_stripped_extra_equals_stripped_long():
    parity = get_parity_check_matrices("surface", 3)
    adaptive = build_adaptive_modules(parity, 3, 0.0, short_rounds=1, num_teleportations=1, pauli="z", surface_code=True)
    description = next(module for module in adaptive if hasattr(module, "long_module"))
    assert stripped_detector_circuit(description.short_circuit + description.extra_circuit) == stripped_detector_circuit(description.long_circuit)


def test_permutation_is_z_short_z_extra_x_short_x_extra_and_bijective():
    permutation = build_measurement_permutation(2, 3, 4, 5)
    assert permutation == [0, 1, 5, 6, 7, 8, 2, 3, 4, 9, 10, 11, 12, 13]
    checked = check_permutation(permutation)
    assert checked["bijective"]
    assert checked["duplicates"] == 0
    assert checked["missing"] == []


def test_correction_vector_permutation_round_trip():
    permutation = build_measurement_permutation(2, 3, 4, 5)
    logical = np.arange(len(permutation)) % 2
    physical = np.empty_like(logical)
    physical[np.asarray(permutation)] = logical
    np.testing.assert_array_equal(apply_measurement_permutation(physical, permutation), logical)


def test_decoder_endpoints_are_equal_on_shared_noiseless_and_noisy_records():
    parity = get_parity_check_matrices("surface", 3)
    fixed = build_fixed_modules(parity, 3, 0.001, num_teleportations=1, pauli="z", surface_code=True)
    adaptive = build_adaptive_modules(parity, 3, 0.001, short_rounds=1, num_teleportations=1, pauli="z", surface_code=True)
    checked = _check_decoder_endpoints(fixed, adaptive, seed=17)
    assert checked["equal"]
    assert all(item["equal"] for values in checked["bases"].values() for item in values)


def test_reference_cache_matches_assembled_reference_after_repeated_path():
    parity = get_parity_check_matrices("surface", 3)
    modules = build_fixed_modules(parity, 3, 0.0, num_teleportations=1, pauli="z", surface_code=True)
    executor = StatefulAdaptiveKnillExecutor(modules, batch_size=2, seed=19)
    executor.simulate_result(2, 10**6)
    checked = _check_cache(executor)
    assert checked["entries"] >= 1
    assert checked["equal"]


def _synthetic_rows(statuses):
    return [
        {"distance": 3, "physical_error": 0.0, "pair": pair, "status": status}
        for pair, status in zip(("A_vs_B", "B_vs_C", "A_vs_C"), statuses)
    ]


def test_statistical_classification_logic():
    assert classify_diagnostic(False, _synthetic_rows(["equivalent_within_margin"] * 3), margin_supplied=True)["classification"] == "no_discrepancy_detected"
    assert classify_diagnostic(False, _synthetic_rows(["equivalent_within_margin", "difference_detected", "difference_detected"]), margin_supplied=True)["classification"] == "adaptive_split_path_suspect"
    assert classify_diagnostic(False, _synthetic_rows(["difference_detected", "equivalent_within_margin", "difference_detected"]), margin_supplied=True)["classification"] == "stateful_executor_suspect"
    assert classify_diagnostic(False, _synthetic_rows(["inconclusive"] * 3), margin_supplied=True)["classification"] == "statistically_inconclusive"


def test_json_serialization_has_no_nan_or_infinity():
    encoded = json.dumps(json_safe({"nan": np.nan, "infinity": float("inf")}), allow_nan=False)
    assert "NaN" not in encoded
    assert "Infinity" not in encoded


def test_checkpoint_resume_skips_completed_row(tmp_path):
    path = tmp_path / "raw_counts.csv"
    store = CheckpointStore(path)
    config = DiagnosticConfig(output_dir=tmp_path, shots=2, batch_size=2)
    row = {"config_signature": config.signature, "workflow": "legacy_static", "distance": 3, "physical_error": 0.0, "stage": "base", "shots": 2, "logical_errors": 0}
    store.append(row)
    resumed = CheckpointStore(path)
    assert resumed.contains(row)
    resumed.append(row)
    assert len(resumed.rows) == 1
    assert config.signature == DiagnosticConfig(output_dir=tmp_path, shots=2, batch_size=2, extended_multiplier=5).signature


def test_pairwise_statistics_uses_independent_binomial_comparisons():
    config = DiagnosticConfig(distances=(3,), physical_errors=(0.0,), shots=100, equivalence_margin=0.1)
    rows = [
        {"distance": "3", "physical_error": "0.0", "workflow": workflow, "stage": "pooled", "shots": "100", "logical_errors": str(errors)}
        for workflow, errors in (("legacy_static", 2), ("stateful_contiguous_long", 2), ("adaptive_forced_long", 3))
    ]
    result = pairwise_statistics(rows, config)
    assert {row["pair"] for row in result} == {"A_vs_B", "B_vs_C", "A_vs_C"}
    assert all("fisher_p_value" in row and "holm_adjusted_p_value" in row for row in result)
