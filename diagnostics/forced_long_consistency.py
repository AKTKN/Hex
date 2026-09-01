"""Independent A/B/C consistency diagnostic for forced-long Knill runs.

This module intentionally does not import anything from ``validation``.  It
uses the public Hex builders and executors, plus a few private executor
helpers where inspecting the exact production permutation/cache is the point
of the diagnostic.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import platform
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np
import pymatching
import stim
from scipy.stats import fisher_exact

from hex_qec.circuit_generation import (
    create_stabilizers_and_block_template,
    generate_blocks,
    get_parity_check_matrices,
    noiseless_unitary_state_prep,
)
from hex_qec.modularisation import (
    AdaptiveSERounds,
    generate_adaptive_state_prep_module,
    generate_bell_measurement_and_correction_module,
    generate_logical_measurement_module,
    generate_state_prep_modules,
    generate_transversal_cnot_module,
    modularised_circuit,
    no_measurement_module,
)
from hex_qec.protocols import knill_online_offline, knill_online_offline_adaptive
from hex_qec.simulation import (
    AlwaysLongPolicy,
    StatefulAdaptiveKnillExecutor,
)
from hex_qec.simulation import adaptive as adaptive_impl
from hex_qec.modularisation.results import normalize_module_decode_output


WORKFLOWS = ("legacy_static", "stateful_contiguous_long", "adaptive_forced_long")
PAIR_NAMES = (("A", "B"), ("B", "C"), ("A", "C"))
WORKFLOW_LABELS = {"A": "legacy_static", "B": "stateful_contiguous_long", "C": "adaptive_forced_long"}


def _finite(value: Any) -> Any:
    """Convert NumPy values and non-finite floats to standard JSON values."""

    if isinstance(value, np.ndarray):
        return [_finite(item) for item in value.tolist()]
    if isinstance(value, (np.integer, np.floating, np.bool_)):
        value = value.item()
    if isinstance(value, dict):
        return {str(key): _finite(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finite(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def json_safe(value: Any) -> Any:
    """Return a recursively JSON-safe representation (never NaN/Infinity)."""

    return _finite(value)


def _instruction_signature(instruction: Any) -> tuple[str, str, tuple[float, ...]]:
    return (
        instruction.name,
        " ".join(str(target) for target in instruction.targets_copy()),
        tuple(float(x) for x in instruction.gate_args_copy()),
    )


def _physical_instruction_signatures(circuit: stim.Circuit) -> list[tuple[str, str, tuple[float, ...]]]:
    """Flatten instructions and omit only non-physical Stim annotations."""

    ignored = {"DETECTOR", "OBSERVABLE_INCLUDE", "SHIFT_COORDS", "QUBIT_COORDS"}
    return [_instruction_signature(item) for item in circuit if item.name not in ignored]


def compare_physical_instructions(first: stim.Circuit, second: stim.Circuit) -> dict[str, Any]:
    """Compare ordered physical Stim instructions, including gates/noise/measurements."""

    left = _physical_instruction_signatures(first)
    right = _physical_instruction_signatures(second)
    first_difference = None
    for index, (a, b) in enumerate(zip(left, right)):
        if a != b:
            first_difference = {"index": index, "first": a, "second": b}
            break
    if first_difference is None and len(left) != len(right):
        index = min(len(left), len(right))
        first_difference = {
            "index": index,
            "first": left[index] if index < len(left) else None,
            "second": right[index] if index < len(right) else None,
        }
    return {
        "exact_equal": first_difference is None,
        "num_qubits_first": int(first.num_qubits),
        "num_qubits_second": int(second.num_qubits),
        "num_measurements_first": int(first.num_measurements),
        "num_measurements_second": int(second.num_measurements),
        "num_detectors_first": int(first.num_detectors),
        "num_detectors_second": int(second.num_detectors),
        "instruction_count_first": len(left),
        "instruction_count_second": len(right),
        "first_difference": first_difference,
    }


def stripped_detector_circuit(circuit: stim.Circuit) -> stim.Circuit:
    """Remove detector annotations while retaining all physical operations."""

    result = stim.Circuit()
    for instruction in circuit:
        if instruction.name in {"DETECTOR", "OBSERVABLE_INCLUDE", "SHIFT_COORDS", "QUBIT_COORDS"}:
            continue
        result.append(instruction.name, instruction.targets_copy(), instruction.gate_args_copy())
    return result


def build_measurement_permutation(
    z_short: int,
    x_short: int,
    z_extra: int,
    x_extra: int,
    start: int = 0,
) -> list[int]:
    """Return production convention: logical long index -> physical index."""

    z_short_indices = list(range(start, start + z_short))
    x_short_start = start + z_short
    x_short_indices = list(range(x_short_start, x_short_start + x_short))
    z_extra_start = x_short_start + x_short
    z_extra_indices = list(range(z_extra_start, z_extra_start + z_extra))
    x_extra_start = z_extra_start + z_extra
    x_extra_indices = list(range(x_extra_start, x_extra_start + x_extra))
    return z_short_indices + z_extra_indices + x_short_indices + x_extra_indices


def apply_measurement_permutation(values: Sequence[Any], permutation: Sequence[int]) -> np.ndarray:
    """Read physical values in logical order using the production mapping."""

    values = np.asarray(values)
    permutation = np.asarray(permutation, dtype=int)
    if values.shape[0] != permutation.size:
        raise ValueError("permutation and vector have different lengths")
    return values[permutation]


def check_permutation(permutation: Sequence[int], length: int | None = None) -> dict[str, Any]:
    permutation = list(map(int, permutation))
    expected_length = len(permutation) if length is None else int(length)
    valid = (
        len(permutation) == expected_length
        and sorted(permutation) == list(range(expected_length))
    )
    return {
        "length": len(permutation),
        "expected_length": expected_length,
        "bijective": valid,
        "duplicates": len(permutation) - len(set(permutation)),
        "missing": sorted(set(range(expected_length)) - set(permutation)),
        "out_of_range": [x for x in permutation if x < 0 or x >= expected_length],
        "permutation": permutation,
    }


def production_pair_permutation(
    z_description: Any,
    x_description: Any,
    *,
    seed: int = 0,
) -> list[int]:
    """Obtain the mapping from the actual production pair executor."""

    executor = StatefulAdaptiveKnillExecutor(
        [z_description, x_description], batch_size=1, seed=seed
    )
    runner = adaptive_impl._AdaptiveShotRunner(
        seed=seed,
        correction_map_cache=executor._correction_map_cache,
        reference_sample_cache=executor._reference_sample_cache,
        stripped_suffix_cache=executor._stripped_suffix_cache,
    )
    runner._run_adaptive_pair(z_description, x_description)
    return list(runner.measurement_permutation)


def wilson_interval(errors: int, shots: int, confidence: float = 0.95) -> tuple[float, float]:
    if shots <= 0:
        return (None, None)  # type: ignore[return-value]
    from scipy.stats import norm

    z = float(norm.ppf(0.5 + confidence / 2))
    p = errors / shots
    denominator = 1 + z * z / shots
    centre = (p + z * z / (2 * shots)) / denominator
    radius = z * math.sqrt(p * (1 - p) / shots + z * z / (4 * shots * shots)) / denominator
    return max(0.0, centre - radius), min(1.0, centre + radius)


def newcombe_risk_difference_interval(
    first_errors: int,
    first_shots: int,
    second_errors: int,
    second_shots: int,
    confidence: float = 0.95,
) -> tuple[float, float]:
    """Newcombe hybrid score interval for ``second risk - first risk``."""

    first_low, first_high = wilson_interval(first_errors, first_shots, confidence)
    second_low, second_high = wilson_interval(second_errors, second_shots, confidence)
    if first_low is None or second_low is None:
        return (None, None)  # type: ignore[return-value]
    return second_low - first_high, second_high - first_low


def fisher_two_sided(first_errors: int, first_shots: int, second_errors: int, second_shots: int) -> float:
    _, p_value = fisher_exact(
        [[first_errors, first_shots - first_errors], [second_errors, second_shots - second_errors]],
        alternative="two-sided",
    )
    return float(p_value)


def holm_bonferroni(p_values: Sequence[float]) -> list[float]:
    indexed = sorted(enumerate(float(p) for p in p_values), key=lambda item: item[1])
    adjusted = [1.0] * len(indexed)
    running = 0.0
    for rank, (original, p_value) in enumerate(indexed):
        running = max(running, min(1.0, (len(indexed) - rank) * p_value))
        adjusted[original] = running
    return adjusted


def classify_pair(
    fisher_significant: bool,
    equivalence_demonstrated: bool,
) -> str:
    if fisher_significant:
        return "difference_detected"
    if equivalence_demonstrated:
        return "equivalent_within_margin"
    return "inconclusive"


def classify_diagnostic(
    structural_failure: bool,
    pair_rows: Sequence[dict[str, Any]],
    *,
    margin_supplied: bool,
) -> dict[str, Any]:
    if structural_failure:
        return {
            "classification": "structural_mismatch_detected",
            "evidence": ["At least one deterministic structural check failed."],
            "recommended_next_action": "Inspect the saved structural mismatch before collecting more Monte Carlo data.",
        }
    by_pair = {(row["distance"], row["physical_error"], row["pair"]): row for row in pair_rows}
    differences = [row for row in pair_rows if row.get("status") == "difference_detected"]
    ab_resolved = any(row["pair"] == "A_vs_B" for row in differences)
    bc_resolved = any(row["pair"] == "B_vs_C" for row in differences)
    all_equivalent = bool(margin_supplied) and bool(pair_rows) and all(
        row.get("status") == "equivalent_within_margin" for row in pair_rows
    )
    if ab_resolved and not bc_resolved:
        classification = "stateful_executor_suspect"
        evidence = ["A vs B has a resolved difference while B vs C does not."]
    elif bc_resolved and not ab_resolved:
        classification = "adaptive_split_path_suspect"
        evidence = ["B vs C has a resolved difference while A vs B does not."]
    elif all_equivalent:
        classification = "no_discrepancy_detected"
        evidence = ["All A/B, B/C, and A/C comparisons are equivalent within the requested margin."]
    else:
        classification = "statistically_inconclusive"
        evidence = ["No conservative implementation-specific classification was resolved."]
    return {
        "classification": classification,
        "evidence": evidence,
        "recommended_next_action": (
            "Collect fresh larger samples at unresolved points."
            if classification == "statistically_inconclusive"
            else "Review the pairwise evidence and saved raw rows before changing production code."
        ),
    }


@dataclass(frozen=True)
class DiagnosticConfig:
    distances: tuple[int, ...] = (3, 5)
    physical_errors: tuple[float, ...] = (0.002, 0.003, 0.005)
    shots: int = 76800
    short_rounds: int = 1
    num_teleportations: int = 1
    pauli: str = "z"
    surface_code: bool = True
    batch_size: int = 256
    equivalence_margin: float | None = None
    alpha: float = 0.05
    base_seed: int = 20260901
    extended_multiplier: float = 0.0
    output_dir: Path = Path("diagnostics/results/forced_long_consistency")
    overwrite: bool = False
    continue_after_structural_failure: bool = False

    @property
    def signature(self) -> str:
        # The requested extension size changes only which additional rows are
        # requested; it must not make an already completed base run
        # incompatible with the follow-up invocation.
        payload = {key: str(value) for key, value in asdict(self).items() if key not in {"output_dir", "overwrite", "extended_multiplier"}}
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


def _blocks_and_initial(parity_check_tuple: tuple[Any, ...], num_teleportations: int):
    block_template, _, _, _ = create_stabilizers_and_block_template(*parity_check_tuple)
    blocks = generate_blocks(2 * num_teleportations + 1, block_template)
    plus = no_measurement_module(
        noiseless_unitary_state_prep(parity_check_tuple, "x", eigenvalue=0),
        blocks[0]["data_qubits"],
    )
    zero = no_measurement_module(
        noiseless_unitary_state_prep(parity_check_tuple, "z", eigenvalue=0),
        blocks[0]["data_qubits"],
    )
    return blocks, (zero, plus)


def _state_support(blocks: Sequence[dict[str, Any]], index: int) -> list[int]:
    return (
        blocks[index]["data_qubits"]
        + blocks[index]["x_ancillas"]
        + blocks[index]["z_ancillas"]
    )


def build_fixed_modules(parity_check_tuple: tuple[Any, ...], distance: int, physical_error: float, *, num_teleportations: int, pauli: str, surface_code: bool) -> list[Any]:
    blocks, (zero_initial, plus_initial) = _blocks_and_initial(parity_check_tuple, num_teleportations)
    zero_preps = generate_state_prep_modules(
        parity_check_tuple, distance, "z", physical_error,
        [_state_support(blocks, 2 * i + 1) for i in range(num_teleportations)],
        pymatching.Matching.from_check_matrix, matchable=True, surface_code=surface_code,
    )
    plus_preps = generate_state_prep_modules(
        parity_check_tuple, distance, "x", physical_error,
        [_state_support(blocks, 2 * i + 2) for i in range(num_teleportations)],
        pymatching.Matching.from_check_matrix, matchable=True, surface_code=surface_code,
    )
    modules = [plus_initial if pauli.lower() == "x" else zero_initial]
    for i in range(num_teleportations):
        modules.extend([zero_preps[i], plus_preps[i]])
        modules.append(generate_transversal_cnot_module(
            physical_error, blocks[2 * i + 2]["data_qubits"], blocks[2 * i + 1]["data_qubits"],
        ))
        modules.append(generate_bell_measurement_and_correction_module(
            parity_check_tuple, physical_error,
            blocks[2 * (i - 1) + 2]["data_qubits"],
            blocks[2 * i + 1]["data_qubits"], blocks[2 * i + 2]["data_qubits"],
            decoder_generator=pymatching.Matching.from_check_matrix,
        ))
    modules.append(generate_logical_measurement_module(
        parity_check_tuple, physical_error, pauli=pauli,
        new_support=blocks[2 * num_teleportations]["data_qubits"],
        decoder_generator=pymatching.Matching.from_check_matrix,
        expected_logical_values=[],
    ))
    return modules


def build_adaptive_modules(parity_check_tuple: tuple[Any, ...], distance: int, physical_error: float, *, short_rounds: int, num_teleportations: int, pauli: str, surface_code: bool) -> list[Any]:
    blocks, (zero_initial, plus_initial) = _blocks_and_initial(parity_check_tuple, num_teleportations)
    schedule = AdaptiveSERounds(short_rounds, distance, AlwaysLongPolicy())
    modules = [plus_initial if pauli.lower() == "x" else zero_initial]
    for i in range(num_teleportations):
        zero = generate_adaptive_state_prep_module(
            parity_check_tuple, schedule, "z", physical_error, _state_support(blocks, 2 * i + 1),
            pymatching.Matching.from_check_matrix, True, surface_code=surface_code,
            event_id=f"teleportation={i},state=z", teleportation_index=i,
        )
        plus = generate_adaptive_state_prep_module(
            parity_check_tuple, schedule, "x", physical_error, _state_support(blocks, 2 * i + 2),
            pymatching.Matching.from_check_matrix, True, surface_code=surface_code,
            event_id=f"teleportation={i},state=x", teleportation_index=i,
        )
        modules.extend([zero, plus])
        modules.append(generate_transversal_cnot_module(
            physical_error, blocks[2 * i + 2]["data_qubits"], blocks[2 * i + 1]["data_qubits"],
        ))
        modules.append(generate_bell_measurement_and_correction_module(
            parity_check_tuple, physical_error,
            blocks[2 * (i - 1) + 2]["data_qubits"],
            blocks[2 * i + 1]["data_qubits"], blocks[2 * i + 2]["data_qubits"],
            decoder_generator=pymatching.Matching.from_check_matrix,
        ))
    modules.append(generate_logical_measurement_module(
        parity_check_tuple, physical_error, pauli=pauli,
        new_support=blocks[2 * num_teleportations]["data_qubits"],
        decoder_generator=pymatching.Matching.from_check_matrix,
        expected_logical_values=[],
    ))
    return modules


def assemble_modules(modules: Sequence[Any]) -> stim.Circuit:
    circuit = stim.Circuit()
    for module in modules:
        circuit += module.circuit
    return circuit


def run_workflow_a(parity_check_tuple: tuple[Any, ...], config: DiagnosticConfig, distance: int, physical_error: float, seed: int) -> tuple[int, int]:
    return knill_online_offline(
        parity_check_tuple, distance,
        pymatching.Matching.from_check_matrix, pymatching.Matching.from_check_matrix, True,
        physical_error, config.shots, 10**12, config.pauli, config.num_teleportations,
        surface_code=config.surface_code, seed=seed,
    )


def run_workflow_b(parity_check_tuple: tuple[Any, ...], config: DiagnosticConfig, distance: int, physical_error: float, seed: int) -> tuple[int, int]:
    modules = build_fixed_modules(parity_check_tuple, distance, physical_error,
                                  num_teleportations=config.num_teleportations,
                                  pauli=config.pauli, surface_code=config.surface_code)
    result = StatefulAdaptiveKnillExecutor(modules, batch_size=config.batch_size, seed=seed).simulate_result(
        config.shots, 10**12, detail_level="summary"
    )
    return result.samples_performed, result.logical_errors


def run_workflow_c(parity_check_tuple: tuple[Any, ...], config: DiagnosticConfig, distance: int, physical_error: float, seed: int) -> tuple[int, int]:
    result = knill_online_offline_adaptive(
        parity_check_tuple, AdaptiveSERounds(config.short_rounds, distance, AlwaysLongPolicy()),
        pymatching.Matching.from_check_matrix, pymatching.Matching.from_check_matrix, True,
        physical_error, config.shots, 10**12, config.pauli, config.num_teleportations,
        batch_size=config.batch_size, seed=seed, surface_code=config.surface_code,
        detail_level="summary",
    )
    return result.samples_performed, result.logical_errors


def _stable_seed(base_seed: int, workflow: str, distance: int, physical_error: float, stage: str) -> int:
    data = f"{base_seed}|{workflow}|{distance}|{physical_error:.17g}|{stage}".encode()
    return int.from_bytes(hashlib.blake2b(data, digest_size=8).digest(), "little")


class CheckpointStore:
    """CSV checkpoint store with configuration-aware row identity."""

    fields = ["config_signature", "git_sha", "python", "stim", "pymatching", "workflow", "distance", "physical_error", "stage", "seed", "shots", "logical_errors"]

    def __init__(self, path: Path, *, overwrite: bool = False):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if overwrite and self.path.exists():
            self.path.unlink()
        self.rows = []
        if self.path.exists():
            with self.path.open(newline="") as handle:
                self.rows = list(csv.DictReader(handle))

    @staticmethod
    def key(row: dict[str, Any]) -> tuple[str, ...]:
        return tuple(str(row.get(field, "")) for field in ("config_signature", "git_sha", "workflow", "distance", "physical_error", "stage"))

    def contains(self, row: dict[str, Any]) -> bool:
        return self.key(row) in {self.key(existing) for existing in self.rows}

    def append(self, row: dict[str, Any]) -> None:
        if self.contains(row):
            return
        self.rows.append({field: str(row.get(field, "")) for field in self.fields})
        with self.path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=self.fields)
            writer.writeheader()
            writer.writerows(self.rows)


def _version(package: Any) -> str:
    return str(getattr(package, "__version__", "unknown"))


def _git_sha() -> str:
    try:
        return __import__("subprocess").check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def _sparse_equal(first: Any, second: Any) -> bool:
    return first.shape == second.shape and (first != second).nnz == 0


def _map_difference(first: Any, second: Any) -> dict[str, Any]:
    if first is None or second is None:
        return {"equal": first is second, "shape_first": None if first is None else first.shape, "shape_second": None if second is None else second.shape}
    if _sparse_equal(first, second):
        return {"equal": True, "shape": list(first.shape), "nnz": int(first.nnz)}
    difference = (first != second).tocoo()
    return {
        "equal": False, "shape_first": list(first.shape), "shape_second": list(second.shape),
        "nnz_first": int(first.nnz), "nnz_second": int(second.nnz),
        "first_difference": [int(difference.row[0]), int(difference.col[0])] if difference.nnz else None,
    }


def _check_decoder_endpoints(fixed_modules: Sequence[Any], adaptive_modules: Sequence[Any], *, seed: int) -> dict[str, Any]:
    results = {}
    fixed_preps = [m for m in fixed_modules if m.__class__.__name__ == "css_detector_module"]
    adaptive_preps = [m.long_module for m in adaptive_modules if hasattr(m, "long_module")]
    for prep_index, (fixed, adaptive) in enumerate(zip(fixed_preps, adaptive_preps)):
        basis = ("z", "x")[prep_index % 2]
        basis_key = f"{basis}[{prep_index // 2}]"
        sampler = fixed.circuit.compile_sampler(seed=seed)
        noisy = np.asarray(sampler.sample(8), dtype=bool)
        noiseless = np.tile(np.asarray(fixed.circuit.reference_sample(), dtype=bool), (8, 1))
        comparisons = []
        for label, records in (("noiseless", noiseless), ("noisy", noisy)):
            left = normalize_module_decode_output(fixed.c_func(records)).corrections
            right = normalize_module_decode_output(adaptive.c_func(records)).corrections
            equal = np.array_equal(left, right)
            comparisons.append({"records": label, "equal": equal, "mismatch_count": int(np.sum(np.any(left != right, axis=1))), "first_mismatch": None if equal else int(np.flatnonzero(np.any(left != right, axis=1))[0])})
        results[basis_key] = comparisons
    return {"equal": all(item["equal"] for values in results.values() for item in values), "bases": results}


def _check_cache(executor: StatefulAdaptiveKnillExecutor) -> dict[str, Any]:
    circuit_by_key: dict[tuple[int, int], stim.Circuit] = {}
    for module in executor.modules:
        if hasattr(module, "circuit"):
            circuit_by_key[(id(module.circuit), module.num_measurements)] = module.circuit
        if hasattr(module, "short_module"):
            for candidate in (module.short_module, module.long_module):
                circuit_by_key[(id(candidate.circuit), candidate.num_measurements)] = candidate.circuit
    for circuit in executor._stripped_suffix_cache.values():
        circuit_by_key[(id(circuit), circuit.num_measurements)] = circuit
    failures = []
    for key, cached in executor._reference_sample_cache._entries.items():
        assembled = stim.Circuit()
        missing = False
        for circuit_id, measurements, _ in key:
            circuit = circuit_by_key.get((circuit_id, measurements))
            if circuit is None:
                missing = True
                break
            assembled += circuit
        if missing or not np.array_equal(cached, np.asarray(assembled.reference_sample(), dtype=bool)):
            failures.append({"key": key, "missing_segment": missing})
    return {"equal": not failures, "entries": len(executor._reference_sample_cache._entries), "failures": failures}


def structural_checks(parity_check_tuple: tuple[Any, ...], config: DiagnosticConfig, distance: int, physical_error: float) -> dict[str, Any]:
    fixed = build_fixed_modules(parity_check_tuple, distance, physical_error, num_teleportations=config.num_teleportations, pauli=config.pauli, surface_code=config.surface_code)
    contiguous = build_fixed_modules(parity_check_tuple, distance, physical_error, num_teleportations=config.num_teleportations, pauli=config.pauli, surface_code=config.surface_code)
    adaptive = build_adaptive_modules(parity_check_tuple, distance, physical_error, short_rounds=config.short_rounds, num_teleportations=config.num_teleportations, pauli=config.pauli, surface_code=config.surface_code)
    fixed_prep = [m for m in fixed if m.__class__.__name__ == "css_detector_module"]
    adaptive_prep = [m for m in adaptive if hasattr(m, "long_module")]
    prep_checks = []
    split_checks = []
    for prep_index, (ordinary, description) in enumerate(zip(fixed_prep, adaptive_prep)):
        basis = ("z", "x")[prep_index % 2]
        prep_checks.append({
            "basis": basis,
            "stim_exact_equal": ordinary.circuit == description.long_module.circuit,
            **compare_physical_instructions(ordinary.circuit, description.long_module.circuit),
        })
        split_checks.append({
            "basis": basis,
            "stim_exact_equal": description.short_circuit + description.extra_circuit == description.long_circuit,
            **compare_physical_instructions(
                stripped_detector_circuit(description.short_circuit + description.extra_circuit),
                stripped_detector_circuit(description.long_circuit),
            ),
        })
    fixed_circuit = assemble_modules(fixed)
    contiguous_circuit = assemble_modules(contiguous)
    full_check = compare_physical_instructions(fixed_circuit, contiguous_circuit)
    decoder_check = _check_decoder_endpoints(fixed, adaptive, seed=_stable_seed(config.base_seed, "decoder", distance, physical_error, "structural"))
    fixed_maps = adaptive_impl._generate_correction_maps(tuple(fixed))
    contiguous_maps = adaptive_impl._generate_correction_maps(tuple(contiguous))
    map_checks = [_map_difference(a, b) for a, b in zip(fixed_maps, contiguous_maps)]
    map_equal = all(item["equal"] for item in map_checks)

    z, x = adaptive_prep[0], adaptive_prep[1]
    z_short, x_short = z.short_module.num_measurements, x.short_module.num_measurements
    z_extra, x_extra = z.extra_circuit.num_measurements, x.extra_circuit.num_measurements
    expected_permutation = build_measurement_permutation(z_short, x_short, z_extra, x_extra)
    permutation = production_pair_permutation(
        z,
        x,
        seed=_stable_seed(config.base_seed, "permutation", distance, physical_error, "structural"),
    )
    permutation_check = check_permutation(permutation)
    permutation_check["expected_order_equal"] = permutation == expected_permutation
    logical = np.arange(len(permutation))
    physical = np.empty_like(logical)
    physical[np.asarray(permutation)] = logical
    permutation_check["round_trip_equal"] = np.array_equal(apply_measurement_permutation(physical, permutation), logical)

    # Expand the pair permutation to the complete protocol.  Measurements
    # before/after the state-preparation pair retain identity ordering.
    full_permutation: list[int] = []
    physical_cursor = logical_cursor = 0
    adaptive_index = 0
    adaptive_descriptions = [m for m in adaptive if hasattr(m, "long_module")]
    index = 0
    while index < len(fixed):
        module = fixed[index]
        if index + 1 < len(fixed) and module.__class__.__name__ == "css_detector_module" and fixed[index + 1].__class__.__name__ == "css_detector_module":
            z_description, x_description = adaptive_descriptions[adaptive_index], adaptive_descriptions[adaptive_index + 1]
            z_short_count = z_description.short_module.num_measurements
            x_short_count = x_description.short_module.num_measurements
            z_extra_count = z_description.extra_circuit.num_measurements
            x_extra_count = x_description.extra_circuit.num_measurements
            pair = build_measurement_permutation(z_short_count, x_short_count, z_extra_count, x_extra_count, physical_cursor)
            full_permutation.extend(pair)
            physical_cursor += z_short_count + x_short_count + z_extra_count + x_extra_count
            logical_cursor += module.num_measurements + fixed[index + 1].num_measurements
            adaptive_index += 2
            index += 2
            continue
        full_permutation.extend(range(physical_cursor, physical_cursor + module.num_measurements))
        physical_cursor += module.num_measurements
        logical_cursor += module.num_measurements
        index += 1

    propagation_failures = []
    for module_index, correction_map in enumerate(fixed_maps):
        if correction_map is None:
            continue
        for row in range(correction_map.shape[0]):
            logical_update = np.asarray(correction_map.getrow(row).toarray()).ravel() % 2
            physical_update = np.zeros_like(logical_update)
            if logical_update.size != len(full_permutation):
                propagation_failures.append({"module_index": module_index, "row": row, "reason": "map/permutation length mismatch"})
                continue
            physical_update[np.asarray(full_permutation)] = logical_update
            round_trip = apply_measurement_permutation(physical_update, full_permutation)
            expected = logical_update
            if not np.array_equal(round_trip, expected):
                propagation_failures.append({"module_index": module_index, "row": row})
    propagation = {"equal": not propagation_failures, "rows_checked": int(sum(m.shape[0] for m in fixed_maps if m is not None)), "failures": propagation_failures}

    b_executor = StatefulAdaptiveKnillExecutor(contiguous, batch_size=min(config.batch_size, 256), seed=_stable_seed(config.base_seed, "B", distance, physical_error, "structural"))
    b_result = b_executor.simulate_result(min(config.batch_size, 256), 10**12)
    c_executor = StatefulAdaptiveKnillExecutor(adaptive, batch_size=min(config.batch_size, 256), seed=_stable_seed(config.base_seed, "C", distance, physical_error, "structural"))
    c_result = c_executor.simulate_result(min(config.batch_size, 256), 10**12)
    cache_check = {"B": _check_cache(b_executor), "C": _check_cache(c_executor)}
    final_check = {"B": {"shots": b_result.shots, "logical_errors": b_result.logical_errors}, "C": {"shots": c_result.shots, "logical_errors": c_result.logical_errors}}
    checks = {
        "state_prep_circuit_equality": {"equal": all(item["stim_exact_equal"] for item in prep_checks), "bases": prep_checks},
        "short_extra_physical_equality": {"equal": all(item["stim_exact_equal"] and item["exact_equal"] for item in split_checks), "bases": split_checks},
        "full_contiguous_circuit_equality": full_check,
        "decoder_endpoint_equality": decoder_check,
        "correction_map_equality": {"equal": map_equal, "modules": map_checks},
        "measurement_permutation": permutation_check,
        "permuted_correction_propagation": propagation,
        "reference_cache_consistency": cache_check,
        "final_software_frame": final_check,
    }
    checks["all_passed"] = bool(
        checks["state_prep_circuit_equality"]["equal"]
        and checks["short_extra_physical_equality"]["equal"]
        and checks["full_contiguous_circuit_equality"]["exact_equal"]
        and checks["decoder_endpoint_equality"]["equal"]
        and checks["correction_map_equality"]["equal"]
        and checks["measurement_permutation"]["bijective"]
        and checks["measurement_permutation"]["expected_order_equal"]
        and checks["measurement_permutation"]["round_trip_equal"]
        and checks["permuted_correction_propagation"]["equal"]
        and checks["reference_cache_consistency"]["B"]["equal"]
        and checks["reference_cache_consistency"]["C"]["equal"]
        and final_check["B"]["logical_errors"] == 0
        and final_check["C"]["logical_errors"] == 0
    )
    return checks


def pairwise_statistics(raw_rows: Sequence[dict[str, Any]], config: DiagnosticConfig) -> list[dict[str, Any]]:
    rows = []
    for distance in config.distances:
        for physical_error in config.physical_errors:
            point = {(row["distance"], row["physical_error"], row["workflow"]): row for row in raw_rows if row["stage"] == "pooled"}
            for first_label, second_label in PAIR_NAMES:
                first = point[(str(distance), str(physical_error), WORKFLOW_LABELS[first_label])]
                second = point[(str(distance), str(physical_error), WORKFLOW_LABELS[second_label])]
                first_errors, first_shots = int(first["logical_errors"]), int(first["shots"])
                second_errors, second_shots = int(second["logical_errors"]), int(second["shots"])
                rd = second_errors / second_shots - first_errors / first_shots
                ci_low, ci_high = newcombe_risk_difference_interval(first_errors, first_shots, second_errors, second_shots, 1 - config.alpha)
                eq_low, eq_high = newcombe_risk_difference_interval(first_errors, first_shots, second_errors, second_shots, 1 - 2 * config.alpha)
                rows.append({"distance": distance, "physical_error": physical_error, "pair": f"{first_label}_vs_{second_label}", "first_workflow": WORKFLOW_LABELS[first_label], "second_workflow": WORKFLOW_LABELS[second_label], "risk_difference": rd, "rd_ci_low": ci_low, "rd_ci_high": ci_high, "fisher_p_value": fisher_two_sided(first_errors, first_shots, second_errors, second_shots), "equivalence_ci_low": eq_low, "equivalence_ci_high": eq_high, "first_errors": first_errors, "first_shots": first_shots, "second_errors": second_errors, "second_shots": second_shots})
    adjusted = holm_bonferroni([row["fisher_p_value"] for row in rows])
    for row, adjusted_p in zip(rows, adjusted):
        row["holm_adjusted_p_value"] = adjusted_p
        row["equivalent_within_margin"] = bool(config.equivalence_margin is not None and row["equivalence_ci_low"] > -config.equivalence_margin and row["equivalence_ci_high"] < config.equivalence_margin)
        row["status"] = classify_pair(adjusted_p < config.alpha, row["equivalent_within_margin"])
    return rows


def _workflow_row(config: DiagnosticConfig, workflow: str, distance: int, physical_error: float, stage: str, seed: int, shots: int, errors: int, git_sha: str) -> dict[str, Any]:
    return {"config_signature": config.signature, "git_sha": git_sha, "python": platform.python_version(), "stim": _version(stim), "pymatching": _version(pymatching), "workflow": workflow, "distance": distance, "physical_error": physical_error, "stage": stage, "seed": seed, "shots": shots, "logical_errors": errors}


def _read_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def _count_row(row: dict[str, Any]) -> dict[str, Any]:
    copied = dict(row)
    copied["distance"] = str(copied["distance"])
    copied["physical_error"] = str(copied["physical_error"])
    copied["stage"] = str(copied["stage"])
    return copied


def _report_markdown(report: dict[str, Any]) -> str:
    diagnosis = report["diagnosis"]
    lines = ["# Forced-long consistency diagnostic", "", "## Final diagnosis", "", f"**{diagnosis['classification']}** — {diagnosis['evidence'][0]}", "", "## Structural checks", "", "| check | d | p | result | details |", "|---|---:|---:|---|---|"]
    for item in report["structural_checks"]:
        for name, value in item["checks"].items():
            if name == "all_passed":
                continue
            result = value.get("equal", value.get("exact_equal", value.get("all_passed", ""))) if isinstance(value, dict) else value
            lines.append(f"| {name} | {item['distance']} | {item['physical_error']} | {result} |  |")
    lines += ["", "## Base Monte Carlo", "", "| d | p | workflow | errors/shots | LER | 95% CI |", "|---:|---:|---|---:|---:|---|"]
    for row in report["monte_carlo"]["base"]:
        errors, shots = int(row["logical_errors"]), int(row["shots"])
        low, high = wilson_interval(errors, shots)
        lines.append(f"| {row['distance']} | {row['physical_error']} | {row['workflow']} | {errors}/{shots} | {errors/shots:.6g} | [{low:.6g}, {high:.6g}] |")
    lines += ["", "## Pairwise comparisons", "", "| d | p | pair | RD | RD 95% CI | Fisher Holm p | equivalence CI | status |", "|---:|---:|---|---:|---|---:|---|---|"]
    for row in report["pairwise_statistics"]:
        lines.append(f"| {row['distance']} | {row['physical_error']} | {row['pair']} | {row['risk_difference']:.6g} | [{row['rd_ci_low']:.6g}, {row['rd_ci_high']:.6g}] | {row['holm_adjusted_p_value']:.6g} | [{row['equivalence_ci_low']:.6g}, {row['equivalence_ci_high']:.6g}] | {row['status']} |")
    lines += ["", "## Interpretation", "", "A/B compares the legacy compiled workflow with the stateful executor; B/C isolates the synchronized adaptive split path. Fisher tests use independent binomial samples, with one Holm-Bonferroni family containing every point and pair. Equivalence is claimed only when the 90% risk-difference interval lies strictly inside the requested absolute margin.", ""]
    return "\n".join(lines)


def run_diagnostic(config: DiagnosticConfig) -> dict[str, Any]:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    raw_path = config.output_dir / "raw_counts.csv"
    store = CheckpointStore(raw_path, overwrite=config.overwrite)
    git_sha = _git_sha()
    structural = []
    for distance in config.distances:
        parity = get_parity_check_matrices("surface", distance)
        for physical_error in config.physical_errors:
            started = time.perf_counter()
            checks = structural_checks(parity, config, distance, physical_error)
            structural.append({"distance": distance, "physical_error": physical_error, "checks": checks, "seconds": time.perf_counter() - started})
    structural_failure = any(not item["checks"]["all_passed"] for item in structural)
    if structural_failure and not config.continue_after_structural_failure:
        raw_rows = _read_rows(raw_path)
        report = {"schema_version": 1, "diagnostic": "forced_long_consistency", "git_sha": git_sha, "configuration": json_safe(asdict(config)), "structural_checks": structural, "monte_carlo": {"base": [], "extended": [], "pooled": []}, "pairwise_statistics": [], "diagnosis": classify_diagnostic(True, [], margin_supplied=config.equivalence_margin is not None)}
        _write_reports(config.output_dir, report)
        return report
    for distance in config.distances:
        parity = get_parity_check_matrices("surface", distance)
        for physical_error in config.physical_errors:
            for workflow in WORKFLOWS:
                seed = _stable_seed(config.base_seed, workflow, distance, physical_error, "base")
                probe = _workflow_row(config, workflow, distance, physical_error, "base", seed, config.shots, 0, git_sha)
                if store.contains(probe):
                    continue
                runner = {"legacy_static": run_workflow_a, "stateful_contiguous_long": run_workflow_b, "adaptive_forced_long": run_workflow_c}[workflow]
                shots, errors = runner(parity, config, distance, physical_error, seed)
                store.append(_workflow_row(config, workflow, distance, physical_error, "base", seed, shots, errors, git_sha))
    base_rows = [_count_row(row) for row in store.rows if row["stage"] == "base"]
    pooled_rows = list(base_rows)
    extended_rows: list[dict[str, Any]] = []
    if config.extended_multiplier > 1:
        base_stats = pairwise_statistics([dict(row, stage="pooled") for row in base_rows], config) if base_rows else []
        suspicious_points = {(row["distance"], row["physical_error"]) for row in base_stats if row["status"] != "equivalent_within_margin"}
        for distance, physical_error in suspicious_points:
            distance_int, error_float = int(distance), float(physical_error)
            parity = get_parity_check_matrices("surface", distance_int)
            extra_shots = int(round(config.shots * (config.extended_multiplier - 1)))
            extra_config = DiagnosticConfig(**{**asdict(config), "shots": extra_shots, "output_dir": config.output_dir, "overwrite": False})
            for workflow in WORKFLOWS:
                seed = _stable_seed(config.base_seed, workflow, distance_int, error_float, "extended")
                probe = _workflow_row(config, workflow, distance_int, error_float, "extended", seed, extra_shots, 0, git_sha)
                if store.contains(probe):
                    continue
                runner = {"legacy_static": run_workflow_a, "stateful_contiguous_long": run_workflow_b, "adaptive_forced_long": run_workflow_c}[workflow]
                shots, errors = runner(parity, extra_config, distance_int, error_float, seed)
                store.append(_workflow_row(config, workflow, distance_int, error_float, "extended", seed, shots, errors, git_sha))
        extended_rows = [_count_row(row) for row in store.rows if row["stage"] == "extended"]
        pooled_rows = []
        for distance in config.distances:
            for physical_error in config.physical_errors:
                for workflow in WORKFLOWS:
                    matching = [row for row in base_rows + extended_rows if int(row["distance"]) == distance and float(row["physical_error"]) == physical_error and row["workflow"] == workflow]
                    pooled_rows.append({**matching[0], "stage": "pooled", "shots": sum(int(row["shots"]) for row in matching), "logical_errors": sum(int(row["logical_errors"]) for row in matching)})
    else:
        pooled_rows = [{**row, "stage": "pooled"} for row in base_rows]
    stats = pairwise_statistics(pooled_rows, config) if not structural_failure or config.continue_after_structural_failure else []
    report = {"schema_version": 1, "diagnostic": "forced_long_consistency", "git_sha": git_sha, "configuration": json_safe(asdict(config)), "structural_checks": structural, "monte_carlo": {"base": base_rows, "extended": extended_rows, "pooled": pooled_rows}, "pairwise_statistics": stats, "diagnosis": classify_diagnostic(structural_failure, stats, margin_supplied=config.equivalence_margin is not None)}
    _write_reports(config.output_dir, report)
    return report


def _write_reports(output_dir: Path, report: dict[str, Any]) -> None:
    safe = json_safe(report)
    with (output_dir / "structural_checks.json").open("w") as handle:
        json.dump(safe["structural_checks"], handle, indent=2, allow_nan=False)
    with (output_dir / "pairwise_statistics.csv").open("w", newline="") as handle:
        rows = safe["pairwise_statistics"]
        if rows:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader(); writer.writerows(rows)
    with (output_dir / "diagnostic_report.json").open("w") as handle:
        json.dump(safe, handle, indent=2, allow_nan=False)
    (output_dir / "diagnostic_report.md").write_text(_report_markdown(safe))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--distances", nargs="+", type=int, default=[3, 5])
    parser.add_argument("--physical-errors", nargs="+", type=float, default=[0.002, 0.003, 0.005])
    parser.add_argument("--shots", type=int, default=76800)
    parser.add_argument("--short-rounds", type=int, default=1)
    parser.add_argument("--num-teleportations", type=int, default=1)
    parser.add_argument("--pauli", choices=("x", "z"), default="z")
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--alpha", type=float, default=0.05)
    parser.add_argument("--surface-code", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--equivalence-margin", type=float)
    parser.add_argument("--base-seed", type=int, default=20260901)
    parser.add_argument("--extended-multiplier", type=float, default=0)
    parser.add_argument("--output-dir", type=Path, default=Path("diagnostics/results/forced_long_consistency"))
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--continue-after-structural-failure", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.smoke:
        args.distances, args.physical_errors, args.shots = [3], [0.0], 256
        args.extended_multiplier = 0
    if args.shots <= 0 or args.batch_size <= 0 or args.shots % args.batch_size:
        raise SystemExit("--shots must be a positive multiple of --batch-size")
    config = DiagnosticConfig(
        distances=tuple(args.distances), physical_errors=tuple(args.physical_errors), shots=args.shots,
        short_rounds=args.short_rounds, num_teleportations=args.num_teleportations, pauli=args.pauli,
        batch_size=args.batch_size, equivalence_margin=args.equivalence_margin, base_seed=args.base_seed,
        alpha=args.alpha, surface_code=args.surface_code, extended_multiplier=args.extended_multiplier, output_dir=args.output_dir, overwrite=args.overwrite,
        continue_after_structural_failure=args.continue_after_structural_failure,
    )
    report = run_diagnostic(config)
    print(json.dumps({"classification": report["diagnosis"]["classification"], "structural_passed": all(item["checks"]["all_passed"] for item in report["structural_checks"]), "output_dir": str(config.output_dir)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
