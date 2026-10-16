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
| `test_factory_batch.py` | H2 reused-support refreshes, causal batches, terminal labels, replay in both Pauli bases, cache lifetimes |
| `test_surface_gap.py` | H3 exhaustive sector minima, graph/weight guards, native batching, causal factory gaps |
| `test_codecapacity_dem.py` | H4 physical fault projection, complete events, conditional-model counterexamples, cache and rejection |
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
H2 now supplies production multi-stage sampling and logical-error results.
H3 now adds gap enumeration; projected-prior tests remain later phases.

Later [factory phases](../docs/README.md) must preserve H1's gates and add
two-support role swaps, multi-stage causal checks, scalar/batch execution
equivalence (added in H2), exhaustive `2^9` sector-cost checks, projected-model
rejection, and legacy-option regressions as those algorithms are implemented. New
production paths must compile/cache circuits, decoders, and sparse maps
outside shot loops. H1 does not start H2.

## H2 batch validation

The final targeted run passed **111 tests**, including **34 H2**, all **41 H1**
and 36 existing regressions; two inherited statistical-LER cases were
deselected. It took **10.14 s** with eight existing dependency warnings.
Exact commands, initial failures and their resolution are in
[TEST.md](../TEST.md#auxiliary-system-h2-batched-factory).

New tests use seeded <=64-shot physical batches, mostly d=3, plus one d=5
T=2 smoke case. They cover T=1/2/3 zero noise, two-support role swaps and
data/ancilla resets, single faults on both roles at each stage, persisting
logical faults, last-survivor oracle, future/oracle isolation, shape/dtype/ID
overflow guards, fixed-seed/fixed-partition repeatability, unchanged input,
scalar/partitioned decode equivalence, cache identity and graph/sampler counts.
Failing causal contracts, unsupported family/frame conventions and residual
recovery are rejected. Constructor tests forbid map/simulator/decoder/sampler
construction after compilation, rather than asserting timings.

Independent reference tests run old callbacks/global correction maps on the
same saved noisy/fault records and compare both Pauli frame components and
labels. Exact coordinate comparisons canonicalize the reference reset frame
using reference-only R-before-RX sentinels; the physical circuit is unchanged.
Unmodified legacy reset maps must give identical labels and frames equal
modulo stabilizers. This records the previously invisible RX frame-gauge
difference instead of weakening comparisons to labels alone. The H2 guide
documents the convention and the test log retains the initial failures.

No H3 algorithm, benchmark sweep, full pytest suite, general fault-tolerance
proof, or performance measurement was added/run by H2.

## H3 sector exactness and causal gaps

`PYTHONPATH=src python -m pytest -q tests/test_surface_gap.py` passes **37
tests** in **6.04 s**, with eight existing dependency warnings. The final
targeted H3/H2/H1/legacy run passes **148 tests**, two inherited statistical
tests deselected, in **25.89 s**. Commands and the initial two native-weight
guard failures are recorded in [TEST.md](../TEST.md#auxiliary-system-h3-surface-logical-gap).

The exactness oracle enumerates all `2^9` d=3 X-error patterns and computes
both class minima independently. It queries all 16 unique syndromes using
four weight vectors, including three nonuniform vectors, and two L-row
representatives inducing zero/nonzero potentials. It verifies W0/W1, gap,
minimum class, both correction constraints, degree-two lifted columns, and
the potential identity. A separate exactly representable tie selects class
zero and gap zero; floating near-ties allow either minimizing class within
the stated float64 comparison tolerance. No production enumeration is used.

Other tests cover hand-graph parity signs, parallel-edge merging/width,
posterior-sum distinction, invalid cycles/degree/zero-detector/disconnected/
nonplanar graphs, invalid observables/batches/units/weights, native precision
range, recomputed original-weight costs, bad native residuals/weights, cache
identity, two calls per native batch, no reconstruction and scalar equality.

Factory tests compare each stored stage score to enumeration, perturb future
and oracle records, and change raw logical branches without changing syndrome.
Zero-noise d=3 T=1/2/3 and d=5 T=2 have finite Hamming gap d. New physical
fixtures use <=32 shots. Existing H2 tests now assert filled gap dtypes/shapes
and 15 setup matching objects, preserving all prior frame/label comparisons.
Saved-record probes against the H2 decoder also preserve every operational
field and terminal label. No H4 algorithm, full suite, sweep, performance
benchmark or general fault-tolerance claim is included.

## H4 projected-prior validation

The final targeted H4/H3/H2/H1/legacy command passes **184 tests**, two inherited
statistical cases deselected, eight existing warnings, **40.77 s**. It includes
all **36 H4 tests**. The preceding isolated H4 subset passed 35 tests in
18.37 s before the additional unsupported-model inspection case. Initial
failures, exact commands and probes are in
[TEST.md](../TEST.md#auxiliary-system-h4-projected-factory-priors).

New tests preserve every nonzero mechanism and complete signature, validate
online-only dimensions, XOR merging, independent depolarizing factorization,
natural-log weights, zero-noise handling, noise/graph/topology/degenerate-prior
rejection, actual prep-weight hashes, cache identity and bounded lane storage.
Stage 0/1/2 prefixes cover refresh reuse, future/oracle isolation and no sampling
or terminal-truth calls during construction. Weighted and Hamming comparisons
use the same saved 32 physical shots; weighted sector minima match enumeration
of the nine-event d=3 fixture. Constructor gates forbid new objects after setup.

Independent physical paired-state tests use 16 shots per reset/SE/CNOT/readout
case and verify deterministic raw flip propagation. Seven cases also match the
reference's complete prep-resolved signature. The plus-SE case instead
explicitly preserves a real logical-response mismatch (13/16 records at the
recorded seed), while its corrected syndrome agrees. Raw signed marginals
match Stim's independent DEM to about 4e-15; they still differ from actual prep
repair for 375/1,666 and 280/2,571 reference mechanisms. A separate 36-pair
controlled test exhibits nonlinear double-fault responses, demonstrating why
the model cannot be advertised as an exact conditional or intrinsic marginal.
Controlled setup lanes/classical enumeration are not Monte Carlo shots.

Default H3 samples, every result field, frames and labels match the previous
decoder exactly on saved d=3 T=1/2/3 records. No H5 flag, large sweep, full-suite
execution, experiment output or validated LER-improvement claim is included.


## H5 public options and whole fast selection

`test_codecapacity_public.py` adds 16 tests for complete context/service
integration, both Bell sectors, version-scoped H4 False golden hashes,
noisy final-readout preservation, strict unsupported-model errors,
factory stage policy/frame/gap semantics, causal isolation, direct gadget
contexts, physical fault boundaries and deterministic construction gates.
New physical batches use <=64 shots; native graphs/converters/samplers are
cached and inputs stay unchanged.

Whole fast selection: `PYTHONPATH=src python -m pytest -q tests -k
'not ler_is_statistically_compatible'` finally gives 261 passed, 2 deselected,
8 warnings, 86.27 s. The two inherited 2,048-shot statistical comparisons
are deliberately excluded. After strengthening H5 context/API assertions,
the 15-test subset passes in 37.11 s. Initial failures and exact full commands
are in [TEST.md](../TEST.md#auxiliary-system-h5-public-options-and-whole-implementation-audit).

Full Knill True is tested at d=3 one-SE/T=1 in both Pauli bases and sectors,
plus T=2/Z with manual actual-policy prefix replay;
two/three-SE X-sector logical-only terms raise explicitly. Factory True
covers d=3 (2,2), T=1/2. Tests retain H4's context/nonlinearity counterexamples;
passing model checks do not certify the physical prior or a LER improvement.
See [the H5 guide](../docs/logical_zero_factory_h5.md) for the whole assessment.
