# Implementation status

Date: 2026-08-31
Branch: `hex-adaptive`  
Base commit: `762a9f1` (`feat: Implement adaptive state preparation in Knill protocol`)

## Completed checkpoints

- Read `AGENTS.md`, `PLAN.md`, and `FUTURE.md` before inspection.
- Inspected repository state/history, package layout, exports, dependencies,
  circuit generation, modularisation, protocol builders, examples, and README
  call flow.
- Verified that the local commit matches the upstream snapshot recorded in
  `AGENTS.md`; no tracked core-code changes are present.
- Corrected `AGENTS.md` to describe the actual sparse Matrix Market inputs,
  package exports, and local baseline environment.
- Added package descriptions at:
  `src/hex_qec/circuit_generation/DESCRIPTION.md`,
  `src/hex_qec/modularisation/DESCRIPTION.md`, and
  `src/hex_qec/protocols/DESCRIPTION.md`.
- Added this status report, `TEST.md`, and the theory skeleton `THEORY.md`.
- Implemented Phase 1 decoder results, protocols, legacy decoder adapters, and
  module-output normalization under `src/hex_qec/decoders/` and
  `src/hex_qec/modularisation/results.py`.
- Implemented Phase 2 aggregate simulation results in the existing
  modularisation result module without changing the sampling backend or
  adaptive control flow.
- Implemented Phase 3 `StatefulFlipSimulatorBackend` under
  `src/hex_qec/simulation/stateful.py` for fixed-round module-by-module
  execution with `stim.FlipSimulator`.
- Implemented the Phase 4 two-level state-preparation descriptions and Phase 5
  executor under
  `src/hex_qec/modularisation/adaptive_state_prep.py` and
  `src/hex_qec/simulation/adaptive.py`.
- Added `AdaptivePolicy`, `AlwaysShortPolicy`, `AlwaysLongPolicy`, and the
  example `ClusterLLRPolicy`.
- Implemented confidence-driven mixed short/long execution. Low-confidence
  shots continue the same physical `FlipSimulator` state through the extra
  suffix; the long decoder receives the complete round-1..long history.
- Added `HexBPLSDDecoder` and `make_bplsd_decoder_generator(...)` as an
  adapter example exposing BP-LSD cluster LLR through `DecodeResult.confidence`.
- Added the separate `knill_online_offline_adaptive(...)` result-returning
  entry point, including `|0_L>` and `|+_L>` events at each teleportation.
- Corrected the BP-LSD Cluster LLR adapter to use complete final LSD cluster
  membership.  It uses `final_bits` when available and reconstructs membership
  from the installed fork's growth history when only `final_bit_count` is
  exposed; it never substitutes the recovery `solution` support.
- Added backward-compatible `surface_code=False` options to fixed and adaptive
  Knill entry points and propagated them to all state-preparation builders.
- Synchronized the two patches of every Bell ancilla: both short prefixes are
  decoded before an OR pair decision, and either extension request continues
  both existing physical simulator states.  Added pair-level fallback-cause
  diagnostics and per-shot pair-risk output.
- Added the smoke-sized experiment driver
  `notebooks/surface_code_knill_fixed_adaptive_sweeps.ipynb`; it is opt-in and
  does not run production sweeps.
- Made the surface-code stabilizer-construction diagnostics conditional on
  `debug=True`; ordinary simulation/circuit construction is now silent while
  the diagnostic messages remain available for explicit debugging.
- Made the logical-measurement `Code number qubits: ...` diagnostic
  conditional on `debug=True` as well, so normal protocol construction and
  simulation no longer emit it.
- Integrated the adapters into existing decoder call sites while preserving
  historical input casts and scalar-fallback output dtypes.
- Added focused tests under `tests/test_phase1_decoder_adapters.py`.
- Added a structured-output constructor check for `measurement_module`.
- Verified the legacy adapter with tiny PyMatching, BP, and BP-OSD decoders;
  the installed ldpc version requires `input_vector_type='syndrome'`.
- Made no changes to core numerical, physical-noise, or correction behavior.
- Audited and corrected the confidence workflow used by adaptive state
  preparation (see "Confidence workflow audit" below).  The Bell-pair
  synchronized OR decision (`extend_pair = would_extend_zero OR
  would_extend_plus`, computed from each patch's own `AdaptivePolicy`
  boolean) was already correct and unchanged.  Added
  `hex_qec.decoders.CSSInnerDecodeResults` (a `NamedTuple` replacing the
  four-element list `confidence_aggregator` previously received) and two
  example aggregators, `dem_only_max_confidence` (now the current default
  for adaptive switching: DEM-only) and `all_components_max_confidence`
  (diagnostic-only, retained but explicitly labeled as not theoretically
  justified).  Added `confidence_zero`/`confidence_plus`/
  `would_extend_zero`/`would_extend_plus` per-pair arrays to
  `SimulationResult.per_shot` alongside the existing `used_long_pair`.
  Updated `examples/bplsd_adaptive_knill.py` and
  `notebooks/surface_code_knill_fixed_adaptive_sweeps.ipynb` to use the
  DEM-only default and to validate the code-capacity exclusion directly.
  Added tests under `tests/test_phase5_confidence_adaptive.py` for
  code-capacity exclusion, patch independence/OR synchronization, and a
  dummy inverted-direction policy proving the pair executor never assumes
  a Cluster-LLR-style raw `max(...) > threshold` rule.

## Confidence workflow audit (adaptive state preparation)

Confidence flow, from inner decoder to physical continuation:

```text
decoder-specific soft outputs (per css_detector_module decode call)
    -> CSSInnerDecodeResults(x_dem, z_dem, x_capacity, z_capacity)
    -> confidence_aggregator(results) -> ndarray | None
         (DEM-only default: dem_only_max_confidence;
          diagnostic-only: all_components_max_confidence)
    -> css_detector_module.c_func_rich -> DecodeResult.confidence
    -> AdaptivePolicy.should_extend(decode_result, context=...)
         (metric-specific direction/threshold, e.g. ClusterLLRPolicy's
         risk-like `cluster_llr > threshold`)
    -> would_extend_zero / would_extend_plus (independent per patch)
    -> used_long_pair = would_extend_zero OR would_extend_plus
    -> both |0_L> and |+_L> patches continue to the same selected depth
```

Findings and decisions from the audit:

1. The pair-level OR behavior (`StatefulAdaptiveKnillExecutor`'s
   `_run_adaptive_pair` in `src/hex_qec/simulation/adaptive.py`) already
   computed `extend_pair = z_would_extend or x_would_extend` from two
   independent `policy.should_extend(...)` calls -- never a raw
   `max`/`min` of the two patches' confidence values.  The only `max()` in
   that path builds `pair_risk`, which is explicitly diagnostic metadata
   (`AdaptiveEventObservation.pair_risk` /
   `AdaptiveBellPairStats.mean_*_patch_risk`) and was never read back into
   the decision.  This behavior is preserved unchanged; only clarifying
   comments were added at both sites.
2. Code-capacity confidence exclusion was not previously enforced by any
   default: `confidence_aggregator` has no built-in default anywhere (by
   design -- see decoders/DESCRIPTION.md, "do not create a generic
   framework assumption that all confidence metrics should use max"), so a
   caller supplying no aggregator gets `confidence=None`.  What changed is
   which *example* aggregator is treated as the current experiment
   default: `dem_only_max_confidence` (DEM-only) replaces
   `all_components_max_confidence`/the notebook's old ad hoc
   `worst_css_cluster_llr`-style helper in the notebook, the BP-LSD
   example script, and the DESCRIPTION.md integration example.
   Code-capacity confidence is still computed unconditionally inside
   `c_func_rich`'s `metrics` dict (`x_capacity.cluster_llr`,
   `z_capacity.cluster_llr`) regardless of which aggregator is selected;
   it is simply not read by the default aggregator, and the adaptive
   per-shot result does not currently forward those `metrics` values (only
   the aggregated `confidence` is retained per shot).
3. Introduced `CSSInnerDecodeResults` (`hex_qec/decoders/base.py`) so a
   `confidence_aggregator` can select `results.x_dem`/`results.z_dem`/
   etc. by name instead of positional slicing (`results[:2]`).  It is a
   drop-in, backward-compatible replacement for the historical
   four-element list: iteration, indexing, slicing, and `len()` all behave
   identically, so every existing aggregator (`worst_css_cluster_llr`-style
   callables in tests/examples) kept working unchanged.
4. A smoke-scale finding surfaced while validating the notebook: at the
   validation cell's tiny `distance=3`, `short_rounds=1` configuration,
   with the notebook's configured `BPLSD_OPTIONS`
   (`bp_method="minimum_sum"`, `max_iter=30`), BP alone reliably converges
   on the small DEM check matrix, so DEM-only Cluster LLR confidence is
   identically zero there regardless of physical error rate or seed (0
   nonzero draws in 20+ probed seeds at `physical_error=0.3`).  This is a
   property of that particular decoder-option/distance/round combination,
   not a defect in `dem_only_max_confidence`: the same formula (without
   `BPLSD_OPTIONS`) and the production sweep's `distance=5,
   short_rounds=2` configuration both produce genuine nonzero DEM-only
   confidence (confirmed via `examples/bplsd_adaptive_knill.py` and the
   notebook's own previously recorded `max_dem_only` sweep rows). The
   validation cell now documents and exploits this directly: it contrasts
   `dem_only_max_confidence` (correctly producing zero switching at that
   tiny configuration) against `all_components_max_confidence`
   (diagnostic-only, still switching because it reads code-capacity
   confidence) as a positive demonstration of the intended exclusion,
   rather than asserting an unconditional "must switch".

## Current implementation

The legacy repository remains fixed-round: its protocols build a complete
static Stim circuit, precompute correction-to-measurement maps, sample in
batches of 256, and return the historical two-count tuple.  Phase 1 provides
`DecodeResult`, decoder protocols/adapters, and `ModuleDecodeResult`
normalization.  Phase 2 adds `SimulationSummary`, `AdaptiveStatePrepStats`,
and `SimulationResult`.  Phase 3 adds the separate fixed-round
`StatefulFlipSimulatorBackend`.

The new `knill_online_offline_adaptive(...)` entry point uses the separate
stateful adaptive executor.  It performs short decoding, policy evaluation,
same-shot continuation for selected shots, full-history long decoding, and
event/result aggregation.  The legacy protocol entry points and static backend
are unchanged.  `ClusterLLRPolicy` is an example policy; the executor does
not assume BP-LSD or a particular confidence metric.

For each teleportation, adaptive Knill now runs the Z and X ancilla short
prefixes before evaluating either policy.  If either patch requests extension,
both continue their own existing `FlipSimulator` state and both long decoders
consume their complete round-1..long histories.  Pair decisions are exposed
through `SimulationResult.bell_pair_stats`; analysis payloads include patch
confidence, patch would-extend values, pair risk, synchronized `used_long`,
and final logical-error arrays.  The surface-code ordering is opt-in through
`surface_code=True` on both protocol entry points.

The stateful backend reconstructs physical records with
`Circuit.reference_sample() XOR get_measurement_flips().T`, while maintaining
decoder corrections in a separate software measurement-flip frame.  It
executes each module on one physical simulator state and does not apply
decoded corrections to that state.

The adaptive state-preparation executor runs `short_circuit` first. It calls
the policy with the short `DecodeResult`, continues only selected shots on
the same `FlipSimulator` instance with the exact `extra_circuit` suffix, and
decodes the complete long record. It verifies that the reconstructed long
record retains the short prefix. The short correction is committed only for
short shots; the long correction is committed only for long shots.

The source checkout is not installed as a `hex-qec` distribution in the test
environment, so smoke tests use `PYTHONPATH=src`.  `stimbposd` was missing at
the initial environment check; the declared dependency was installed as
`stimbposd==0.2.0` to execute the unmodified baseline.  Other observed
versions are Stim 1.15.0, PyMatching 2.3.1, ldpc 2.1.2, and Python 3.12.7.

## Baseline results

For surface code `d=3`, `physical_error=0.0`, `max_shots=256`, and
`max_errors_before_halting=1`:

- Knill, one teleportation: `(samples_performed, logical_errors) = (256, 0)`;
  runtime 0.1024 s.
- Knill, two teleportations: `(256, 0)`; runtime 0.1392 s.
- Steane, one teleportation: `(256, 0)`; runtime 0.1249 s.

For surface code `d=3`, `physical_error=0.001`, the same limits and PyMatching
decoders:

- Knill, one teleportation: `(256, 0)`; runtime 0.1465 s.
- Knill, two teleportations: `(256, 1)`; runtime 0.2358 s.

These are smoke-test observations, not statistically meaningful LER estimates.

## Verified dimensions

For surface `d=3`, the four loaded matrices have shapes
`(4, 9), (4, 9), (1, 9), (1, 9)` and load as integer SciPy COO matrices.
The three-round both-detector state-preparation circuit has 17 qubits, 24
measurements, and 20 detectors.  The Z-preparation CSS module has 8 X
detectors, 12 Z detectors, and matchable DEM check shapes `(8, 21)` and
`(12, 41)`; its local measurement maps have shapes `(21, 24)` and `(41, 24)`.

## Uncertainties and limitations

- The checked-in tests are focused adapter/result/backend tests; broader
  evidence is from the smoke commands recorded in `TEST.md`.
- `simulate` samples whole 256-shot batches and can exceed `max_shots`.
- Direct `css_detector_module.c_func` calls must use a normal boolean/int
  measurement array with Stim 1.15.0; `uint8` is interpreted as bit-packed by
  Stim's converter and was not accepted in the un-packed probe.
- `only_postselection_module._change_support` is incomplete and the class is
  not used by the bundled protocols.
- The existing package-level `__all__` lists fewer names than are imported by
  `__init__.py`.
- No larger-shot numerical fixed-round regression baseline beyond the Phase 3
  d=3 noisy comparison has been established yet.
- The synchronized reference path interleaves physical segments as
  Z-short/X-short/Z-extra/X-extra and strips local detector annotations from
  the interleaved suffix; long decoder histories are reconstructed explicitly.
  Downstream detector-module use after such an interleaved event needs further
  causal-detector validation before this becomes a general dynamic executor.
- The notebook records and passes stable parameter-derived seeds to both engines; Stim
  documents seeded results as version- and machine-dependent, so seeds provide
  reproducible local provenance rather than a cross-version guarantee.
- A notebook that was previously executed can retain the old diagnostic text
  in its saved output cells; clearing outputs or rerunning the cells is needed
  to remove stale captured output. The notebook itself was not rewritten as
  part of this source-only change.

## Phase 3 validation

The installed Stim 1.15.0 API was inspected directly.  `do()` mutates state
and returns `None`; `get_measurement_flips()` returns `(measurements, shots)`;
`copy(copy_rng=True)` preserves state and continuation randomness; and
stabilizer randomization must remain enabled for physical sampling.  The
deterministic reconstruction tests and fixed-round Knill comparisons pass for
surface distances 3 and 5 with one and two teleportations.  Independent
noisy d=3 Monte Carlo LER checks also pass within the documented finite-shot
uncertainty bound.

## Phase 3 design issue

`DecodeResult` can carry confidence, convergence, and metrics, but the current
module callback and static simulation APIs intentionally discard those fields
after extracting `correction`; `SimulationResult` reserves their future
locations but does not fabricate them for fixed-round circuits.  The protocol
functions also continue to return their legacy two-count tuple, while direct
`modularised_circuit` users can request the new wrapper.  A future protocol
level result path will need an explicit result-plumbing design if adaptive
event identity is to be exposed without changing existing protocol returns.
The stateful backend currently mirrors the static module-processing loop so it
can preserve the static path untouched; a future refactor may consolidate
that logic only after compatibility coverage remains stable.  The legacy
detector module still constructs its decoder during each callback, preserving
historical behavior but leaving a future performance question.

## Phases 4 and 5 validation

`AdaptiveSERounds` and `AdaptiveStatePrepModule` expose the short circuit,
exact extra suffix, and full long circuit/decoder.  Endpoint tests pass for
both X and Z state preparation; short/long decoder outputs match the ordinary
fixed-round builders exactly; and long execution preserves the short physical
prefix on the same `FlipSimulator` instance.  A real cluster-LLR threshold
test produces both short and long shots.  Adaptive Knill smoke tests cover
both bases, two teleportations, and confidence-result fields.

The reference implementation intentionally executes one shot at a time and
does not compact branch states.  Confidence calibration, circuit-derived
code-capacity priors, and optimized branch execution remain future work.

## Latest validation

The focused BP-LSD/adaptive file passes 12 tests and the complete local suite
passes 47 tests, with only the existing eight dependency deprecation warnings.
Notebook JSON parsing and compilation of all code cells also pass.
The validation covers final-cluster membership, surface-code builder
propagation, fixed/adaptive endpoint preservation, same-shot prefix checks,
confidence switching, synchronized one-patch fallback, and two Knill
teleportations. No production sweep has been run. The BP-LSD regression logic
covers four small syndromes and explicitly exercises a case where final
cluster membership is larger than the selected recovery support.
Adaptive schedules now reject `short_rounds >= long_rounds` at construction and
the notebook preflight rejects all invalid configured points before simulation.

## Confidence-workflow audit validation

`PYTHONPATH=src pytest -q` passes 57 tests (49 previous + 8 new confidence-
workflow tests) with the existing eight dependency deprecation warnings.  The
new tests in `tests/test_phase5_confidence_adaptive.py` cover:
`CSSInnerDecodeResults` list-compatibility; `dem_only_max_confidence`
excluding poor mocked code-capacity confidence while still responding to
poor DEM confidence; the four zero/plus patch-confidence combinations
(parametrized) reducing to a synchronized OR decision with
`selected_rounds_zero == selected_rounds_plus`; and a dummy inverted-
direction (`smaller == less confident`) policy still combining correctly at
the pair level via OR, proving the executor never assumes a Cluster-LLR-style
raw `max(...) > threshold` rule.  `python -m compileall -q src tests
examples`, notebook JSON/cell-compilation checks, and `git diff --check` also
pass.  The notebook's `validate_small_configuration()` was re-executed
directly (cells 0-7, i.e. through the benchmark cell; the opt-in production
sweep and plot cells were not run) and printed "All small fixed/adaptive
validation checks passed."; `examples/bplsd_adaptive_knill.py` was also run
directly and produced real DEM-only-driven long shots (2/256) at
`physical_error=0.01`.

## Next recommended task

The next recommended step is separate statistical validation of confidence
calibration, now specifically for the DEM-only default established by this
session's audit (previous sweep numbers using the old
`worst_css_cluster_llr`-style all-components aggregator are not directly
comparable). Do not change the static backend or decoder mathematics.
Circuit-derived code-capacity priors and confidence-threshold selection
policy remain experimental and are documented in `FUTURE.md`, including the
new "Code-capacity confidence for adaptive state preparation" subsection.

## Reproducibility validation infrastructure

Added the opt-in `validation/` package for two statistical suites and saved
plot generation.  Validation 1 captures the exact modular circuit built by
`knill_online_offline(...)` and compares its legacy static execution with
`StatefulFlipSimulatorBackend`.  Validation 2 compares fixed `d` rounds with
`knill_online_offline_adaptive(...)` using
`AdaptiveSERounds(short_rounds=1, long_rounds=d, policy=AlwaysLongPolicy())`;
the adaptive result is checked to have pair fallback rate 1 and effective
round count `d`.

The runners support stable derived seeds, configurable distances/errors/shots/
replicates/pauli/output, checkpoint-resume, JSON metadata, Wilson intervals,
Fisher tests, Holm correction, underpowered labels, and PNG/PDF plots.  The
production d=5/7 matrix has not been run.  A d=3, p=0, 256-shot smoke run for
both suites completed, produced raw/comparison CSVs and figures, and was
rerun successfully without adding duplicate raw rows.  The full local test
suite now passes 65 tests.

Added executable `validation/run_knill_repro.sh`, which runs both validation
runners sequentially and forwards all command-line options to each. Its
combined smoke invocation completed successfully.  The launcher now embeds
the requested production defaults: distances 5/7, physical errors
0.001/0.003, 4096 shots, and 3 replicates.

Added `--verbose` progress reporting to both runners. Messages are flushed
immediately and include point number, parameters, seed, workflow completion,
runtime, checkpoint status, and adaptive fallback statistics.

Added post-processing reports in `validation/analyze_knill_repro.py`.  The
analyzer is simulation-free, rejects mixed configuration signatures unless
one is selected explicitly, reuses `comparison_rows(...)` for Fisher/Holm
results, and adds Newcombe risk-difference intervals plus CI-based
equivalence decisions.  JSON and Markdown reports were generated from the
available fixed and adaptive CSVs with an explicit ±0.001 margin.

The combined `validation/run_knill_repro.sh` launcher now runs
`validation.plot_knill_repro --all` only after both validation suites complete
successfully, forwarding any selected `--output-dir`.  Its smoke path was
verified to create both suite PNG and PDF figures.

The launcher now separates sampling and post-processing arguments. It runs the
fixed and adaptive samplers first, then invokes
`validation.analyze_knill_repro --all --equivalence-margin 0.001`, and finally
generates both figure sets. The integrated smoke workflow completed with JSON,
Markdown, PNG, and PDF outputs; no simulation runner receives the analysis
margin option.

## Adaptive wall-time profiling

Date: 2026-08-31

Added the opt-in lightweight profiler in `src/hex_qec/simulation/profiling.py`
and the dedicated runner under `profiling/`. The runner records setup,
warm-up, and measured phases separately using `perf_counter_ns`; the adaptive
executor remains one-shot and no optimization, batching change, decoder
change, or simulator algorithm change was made. It records physical short and
long continuation, reconstruction, correction-map cache hits/misses and
generation, `reference_sample`, decoder sub-stages, policy decisions,
correction commits, downstream Knill modules, and result bookkeeping.

The requested profile was run with distance 5, physical error 0.003,
short/long rounds 1/5, one teleportation, `pauli="z"`, surface-code ordering,
BP-LSD (`max_iter=30`, `bp_method="minimum_sum"`, `lsd_method="LSD_0"`,
`lsd_order=0`, `always_run_lsd=True`), DEM-only confidence aggregation,
`AlwaysLongPolicy`, seed 1234, one warm-up shot, five measured shots, and
`batch_size=1`. Mean measured end-to-end time was 0.181446721 s/shot;
measured logical errors were 0/5. The non-overlapping report stages accounted
for 86.14% of measured wall time, leaving 13.86% as explicit other/
uninstrumented time. The largest inclusive diagnostic was correction-map
generation at 0.618240641 s total (30 misses), while `reference_sample()`
was called 35 times for 0.007417561 s total. Downstream Knill processing was
0.452209777 s total (49.84%), state-preparation measurement/reference/
correction processing was 0.192014948 s (21.16%), adaptive state-prep
physical execution was 0.119472667 s (13.17%), decoder work was 0.018326952 s
(2.02%), and policy/control was 0.01%.

The report suggests measuring/shared deterministic correction maps first,
then reference-sample reuse if confirmed across broader runs. These are
recorded opportunities only; they were not implemented. A d=3 two-shot
`AlwaysLongPolicy` smoke profile and a d=3 two-shot `ClusterLLRPolicy` profile
also completed successfully. The new profiling tests and full suite pass.

## Open issue / next action

The current report's top-level downstream stage is intentionally inclusive of
its measurement reconstruction and software-frame work, while the detailed
`corrected_measurements.*` and decoder rows are inclusive diagnostics. Keep
these accounting conventions explicit when comparing future profiles. The
next action is to review the measured bottleneck ranking before requesting any
optimization; no optimization should be made as part of this profiling
checkpoint.

## Shared correction-map cache optimization

Date: 2026-08-31

Implemented only the requested correction-map lifetime optimization. The
previous `_AdaptiveShotRunner._map_cache` was shot-local; correction maps are
now owned by one `_CorrectionMapCache` per `StatefulAdaptiveKnillExecutor` and
passed by shared reference to every shot runner. Entries are keyed by the
existing tuple of logical module identities, so short and long logical paths
remain distinct and the software-frame propagation logic is unchanged.

For one teleportation, both short and long branch plans are eagerly prepared
before warm-up or measured shots. For multiple teleportations, all-short and
all-long common plans are eagerly prepared without exponential path
enumeration; an unseen mixed path uses an explicit executor-level one-time
fallback and is then reused by later shots.

Focused cache tests cover shared map-object reuse, distinct prepared paths,
three-shot no-fallback behavior, and a two-teleportation smoke run. The full
local suite passes 73 tests.

The unchanged d=5 profile (p=0.003, short/long 1/5, AlwaysLong, z basis,
one teleportation, seed 1234, one warm-up and five measured shots) was rerun
after all tests passed. Mean measured E2E time is 0.059968956 s/shot versus
the preserved pre-cache 0.181446721 s/shot, a measured 3.026x speedup. Offline
map preparation took 0.158809057 s for 9 unique path sets; measured shots had
35 lookups, 0 misses, and 0 s fallback generation, versus the old 30 misses
and 0.618240641 s total generation. The approximate break-even is 1.31 shots
using the observed means.

After caching, adaptive suffix preparation is the dominant measured stage at
84.20% of E2E; actual physical Stim execution is 0.16%, downstream Knill
processing 7.35%, decoder work 6.00%, and measurement/reference/correction
processing 0.93%. Policy/control is 0.03%. The top-level accounting covers
98.72%, leaving 1.28% explicit other/uninstrumented time. BP-LSD is not the
dominant cost in this profile. `reference_sample()` remains 35 calls totaling
0.007543083 s. No further optimization was implemented.

## Open issue / next action

Review the post-cache profile's suffix-preparation cost before requesting a
separate optimization. Do not implement suffix or any other optimization as
part of this checkpoint.

## Detector-stripped adaptive suffix precomputation

Date: 2026-08-31

Implemented only the requested second optimization. Previously, the adaptive
shot runner called `_without_detectors(description.extra_circuit)` on every
selected long branch. `StatefulAdaptiveKnillExecutor` now creates one
detector-stripped suffix per adaptive-description object during setup and
passes the executor-lifetime read-only mapping to each shot runner. Both
single-event and synchronized zero/plus pair paths now execute the stored
suffix directly. Short/long circuit decomposition, same-shot continuation,
measurement ordering, and long decoder inputs are unchanged.

The d=5 profile was rerun with the same configuration as the earlier reports:
p=0.003, short/long 1/5, AlwaysLong, z basis, one teleportation, surface-code
ordering, seed 1234, one warm-up and five measured shots, BP-LSD current
defaults, and DEM-only confidence. Mean measured E2E time fell from the
preserved shared-map value of 0.059968956 s/shot to 0.009330932 s/shot, a
6.427x suffix-stage speedup and 19.446x total speedup versus the original
0.181446721 s/shot profile. Suffix setup took 0.049518417 s total: zero
0.024678919 s and plus 0.025007403 s. Measured-shot suffix preparation was
0 s; actual long Stim execution was 0.000059508 s/shot.

Measured map behavior remained unchanged: 35 lookups, zero misses, zero
measured generation, and 0.158099623 s offline map generation across 9 path
sets. `reference_sample()` remained 35 calls totaling 0.007259222 s. The new
largest non-overlapping stage is downstream Knill processing at 48.55%,
followed by decoder work at 37.92%; physical Stim execution is 0.85% and
measurement/reference/correction processing is 5.17%. Accounted time is
92.75%, with 7.25% explicit other/uninstrumented time. The run produced 0/5
logical errors and all relevant regression tests passed. No further
optimization was implemented.

## Optional parallel adaptive simulation

Date: 2026-09-01

Implementation branch: `hex-parallel`, based on `hex-adaptive` commit
`5de58f2f80791054411ad3c0885a4fe3671ed56a`.

Added the QEC-independent `hex_qec.parallel` package with validated options,
global shot leases, interval reconstruction, sticky scheduling, dynamic
wall-time chunk sizing, spawn workers, manager-owned JSONL checkpoints,
progress snapshots, CPU affinity handling, and parent-side worker error
propagation. Workers prepare one factory result per worker/job and reuse it
across chunks. Explicit seeds use `(seed_base + global_shot_index) % 2**64`.

Added `protocols/parallel_adapters.py` and extracted the shared adaptive Knill
executor builder. The optional `parallel_options` hook is summary-only and
preserves the serial adaptive path when omitted. The adapter temporarily
sets executor seed and batch size per lease, verifies exact shot count, and
restores both fields while retaining executor caches. Parent reduction merges
only additive state-preparation and Bell-pair sufficient counts.

Phase gates completed: pure scheduler/chunking (15 tests), fake spawn workers
(9 tests), checkpoint/resume (5 tests), exact executor chunk seed behavior and
real adaptive chunk partitioning (6 focused adaptive tests), and worker-count
invariance for 1/2/4 workers. The full suite passes with 134 tests and 8
existing dependency deprecation warnings.

Current limitations are summary-only parallel adaptive results, no parallel
profiler merge, no legacy static parallel adapter, no detailed per-shot merge,
no work stealing/distributed execution, and no support for non-pickleable
decoder-generator closures in multiprocessing. Validation and diagnostics
were not migrated.

## Independent forced-long consistency diagnostic

Date: 2026-09-01

Added the independent `diagnostics.forced_long_consistency` program and
`tests/test_forced_long_consistency_diagnostic.py`. The diagnostic does not
import or modify `validation/` and defines three workflows: legacy static A,
stateful contiguous-long B using ordinary fixed-depth modules through
`StatefulAdaptiveKnillExecutor`, and production adaptive forced-long C using
`knill_online_offline_adaptive` with `AlwaysLongPolicy`.

It checks exact state-preparation and short-plus-extra circuits, full physical
instruction order, shared-record decoder endpoints, correction maps, the
production synchronized permutation and correction round trips, final
software-frame behavior, and exact reference-sample cache consistency. It
also writes independent-binomial Wilson/Newcombe intervals, Fisher tests with
one Holm family, optional 90% equivalence intervals, conservative
classification, and resumable base/extended/pooled CSV/JSON/Markdown reports.

The focused diagnostic tests passed (11 tests), the full suite passed (96
tests), and the required smoke run passed all structural checks with 256 d=3,
p=0 shots. The smoke classification was `statistically_inconclusive`, as no
equivalence margin was supplied and the run was intentionally underpowered.
No production source file or existing validation file was modified.

## Diagnostic noisy-criterion repair

Date: 2026-09-01

Repaired the independent diagnostic's false structural failures at nonzero
physical error. Structural success now depends on deterministic checks and
successful completion of the executor's final detector/software-frame
validation, represented explicitly by `final_software_frame.B.passed` and
`.C.passed`. Observed logical-error counts remain metadata only; this branch
does not impose an additional p=0 logical-error requirement.

Nested Markdown results now render explicit booleans for permutation,
reference-cache, final software-frame, and point-level `all_passed`, with
failure details and parameter points included in structural diagnosis
evidence.

Focused tests passed (14), full pytest passed (99), the p=0 smoke passed, and
a small real d=3, p=0.005, 256-shot run passed structural checks despite
observing 5 B and 6 C probe logical errors. That noisy run produced all 3
base workflow rows and all 3 pairwise rows, confirming Monte Carlo proceeds
after genuine structural success. No production source or validation file was
modified.

## Open issue / next action

The remaining measured cost is downstream Knill processing and decoder work;
reference sampling is 15.56% as an inclusive diagnostic. Do not implement
reference-sample, decoder, batching, or any other optimization as part of this
checkpoint. Preserve the original and shared-map profile artifacts for future
comparisons.

## Lazy reference-sample cache optimization

Date: 2026-09-01

Implemented only executor-lifetime lazy caching of Stim `reference_sample()`
results. The cache is owned by `StatefulAdaptiveKnillExecutor`, shared by all
of its `_AdaptiveShotRunner` instances, and keyed by the ordered physical
Stim circuit path. This includes per-shot continuation wrappers by their
shared executor-owned suffix circuit identity. Cache misses retain the
existing circuit assembly and `reference_sample()` call; hits reuse only the
deterministic reference trajectory. Physical simulator state, measurement
flips, decoder inputs, and adaptive decisions remain per-shot and unchanged.

Focused and full test suites passed after the change. A small d=3 profile
(one warm-up and three measured AlwaysLong shots) observed six reference
sample misses during warm-up and 21 measured cache hits; measured E2E time was
0.009555058 s/shot. The requested d=5 profile (one warm-up and five measured
AlwaysLong shots) observed six warm-up misses and 35 measured hits, with
0.011149359 s/shot measured E2E time. The cache report intentionally keeps
warm-up calls out of the measured-shot reference-sample total. No unrelated
optimization was implemented.
