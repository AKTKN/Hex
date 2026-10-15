# Tests: baseline coverage and phase boundaries

Run source tests from the Hex worktree root with `PYTHONPATH=src python -m
pytest ...`; `hex-qec` is not installed in the H0 interpreter. This directory
contains Python modules but has no `__init__.py`. Historical executions are in
[TEST.md](../TEST.md); current limitations are in
[STATUS.md](../STATUS.md#auxiliary-system-h0-baseline-audit).

## Existing coverage

| Test file/group | What it checks |
| --- | --- |
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

## Proposed tests, not yet present

Later [factory phases](../docs/README.md) need d=3 (occasionally d=5), seeded
batches of at most 128 shots, both random byproduct branches, signed/pure-error
checks, gate-direction and fault-boundary cases, causal oracle perturbation,
two-support role swaps, scalar/batch equivalence, exhaustive `2^9` sector-cost
checks, graph rejection, and legacy-default regressions. New production paths
must compile/cache circuits, decoders, and sparse maps outside shot loops.
H0 adds no source or pytest code and starts none of those later phases.
