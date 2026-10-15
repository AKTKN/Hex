# Tests: baseline coverage and phase boundaries

Run source tests from the Hex worktree root with `PYTHONPATH=src python -m
pytest ...`; `hex-qec` is not installed in the H0 interpreter. This directory
contains Python modules but has no `__init__.py`. Historical executions are in
[TEST.md](../TEST.md); current limitations are in
[STATUS.md](../STATUS.md#auxiliary-system-h0-baseline-audit).

## Existing coverage

| Test file/group | What it checks |
| --- | --- |
| `test_factory_circuit.py` | H1 signed circuit/ledger, preparation frames, oracle isolation, single faults, exact legacy map comparisons |
| `test_phase1_decoder_adapters.py` | Batch/scalar dtype compatibility, decoder factories, rich results, module normalization |
| `test_phase2_results.py` | Aggregate wrappers, legacy tuple compatibility, detail-level validation |
| `test_phase3_stateful_backend.py` | Measurement axes/reconstruction, fixed endpoints, small statistical comparisons |
| `test_phase4_adaptive_state_prep.py` | Short/extra/full decomposition, surface ordering, same-shot/full-history endpoints |
| `test_phase5_confidence_adaptive.py` | BP-LSD membership, real/dummy policies, DEM-only aggregation, pair OR decisions |
| `test_shared_correction_map_cache.py` | Shared maps/reference samples, distinct paths, setup-only suffix stripping |
| `test_walltime_profiling.py` | Optional timing, report structure, seeded outcome preservation |
| `test_validation_infrastructure.py`, `test_knill_repro_analysis.py` | Synthetic checkpoint/statistics/plotting/report checks |
| `test_forced_long_consistency_diagnostic.py` | Independent physical/permutation/frame and statistical-report diagnostics |

Core invariants include `H e = s` over GF(2), records shaped
`(shots, measurements)`, correction maps `(variables, measurements)`, rich
results preserving legacy correction values, and one software-frame application
per inferred correction. Tests distinguish decoder convergence, syndrome
consistency, and logical success. Cache tests check object reuse rather than
flaky elapsed-time thresholds.

## Actually executed in H0 (2026-10-15)

- `PYTHONPATH=src python -m pytest -q tests/test_phase1_decoder_adapters.py tests/test_phase2_results.py`:
  **15 passed**, eight warnings, **1.86 s**.
- `PYTHONPATH=src python -m pytest -q tests/test_validation_infrastructure.py tests/test_knill_repro_analysis.py`:
  **14 passed**, eight warnings, **2.70 s**.
- `PYTHONPATH=src python -m pytest --collect-only -q tests`:
  **99 collected**, eight warnings, **0.88 s**. Collection is not execution.

The existing adapter/result fixtures request one shot but the legacy engine
physically samples 256 deterministic measurements. They were left intact for
baseline compatibility. No new algorithm/fault-boundary tests were necessary
for this documentation-only phase. No full suite, large Monte Carlo, opt-in
validation/profile runner, or factory experiment was run.

## H1 execution and remaining tests

The H1 targeted run passed **77 tests** in **2.68 s**, with eight existing
dependency warnings; two inherited statistical-LER tests were deliberately
deselected. This includes all 41 new factory tests and relevant adapter,
result, surface preparation, fixed stateful/noiseless endpoint, and fixed
Knill compatibility tests. Exact commands and earlier runs are appended to
[TEST.md](../TEST.md#auxiliary-system-h1-single-stage-factory).

The factory tests use d=3/5 and at most 128 seeded shots. They verify both
byproducts, raw/repaired signs, reversed CNOT rejection, exact SE/noise/record
boundaries, two supports, an ideal oracle isolated from all decoders/detectors,
eight physical fault cases and a terminal logical fault, deterministic
legacy map equality, and batch decoder reuse/partition equivalence.
Production multi-stage sampling, logical-error results, gap enumeration, and
projected-prior tests remain later phases.

Later [factory phases](../docs/README.md) must preserve H1's gates and add
two-support role swaps, multi-stage causal checks, scalar/batch execution
equivalence, exhaustive `2^9` sector-cost checks, projected-model rejection,
and legacy-option regressions as those algorithms are implemented. New
production paths must compile/cache circuits, decoders, and sparse maps
outside shot loops. H1 does not start H2.
