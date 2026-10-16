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

## Auxiliary-system H0 baseline audit

Date: **2026-10-15 (Asia/Tokyo)**. Scope: documentation and initial audit only.
**H1 has not started.** All preceding status entries are preserved history;
the versions and checkout facts below describe this H0 session.

### Git and workspace baseline

- Hex worktree: `/home/quantum_teresheys/workspace/knilll_bench/external/Hex`.
  Initially clean on `knill-bench-integration` at
  `5de58f2f80791054411ad3c0885a4fe3671ed56a` (`Fix diagnosis code.`).
- `git fetch origin` succeeded. Neither a local nor remote `auxiliary-system`
  existed. Local `hex-adaptive`, `origin/hex-adaptive`, and the checked-out
  revision all matched the SHA above. Created `auxiliary-system` directly
  from local `hex-adaptive` after verifying ancestry; no reset/stash/rebase.
- `origin` is `https://github.com/AKTKN/Hex.git`; `upstream` is
  `https://github.com/ewanmurphy/Hex.git`. The other worktree remains on
  `hex-parallel` at `40c847e484bde7981ccfafa77a13d500e34bb1d2` under
  `temporal_confidence/external_libs/Hex`. Its branch was not switched or edited.
- The containing knill_bench repo is separate, on `main` at `b3cc72a`, with
  user-owned changes. Its `external/` and implementation prompts are ignored
  by that repo. No bench or other dependency source/config changes belong to
  H0. lomatching and surface-sim integration worktrees remain at `b55a7a6` and
  `493f800` respectively; their READMEs and bench dependency docs were read.
- The only H0 diff is Markdown. The audit revision above remains the Python
  source revision; the documentation commit and actual push result are
  reported in the phase handoff. The required target is `origin/auxiliary-system`.

### Actual environment

Interpreter: `/home/quantum_teresheys/anaconda3/bin/python`, Python **3.12.7**.
No environment installation or dependency upgrade was performed.

| Distribution | Observed version |
| --- | --- |
| NumPy | 1.26.4 |
| SciPy | 1.13.1 |
| Stim | 1.15.0 |
| PyMatching | 2.3.1 |
| stimbposd | 0.2.0 |
| ldpc | 2.1.2 |
| pytest | 7.4.4 |
| Matplotlib | 3.9.2 |
| hex-qec | Not installed; source declares 0.1.0 |

Tests use `PYTHONPATH=src` from this Hex worktree. An import probe confirmed
`hex_qec.__file__` resolves inside this worktree. LDPC resolves to the local
`/home/quantum_teresheys/workspace/color_code_project/ldpc_v2_modifiedUF/src_python/ldpc/__init__.py`
fork; the other listed numerical imports resolve inside the Anaconda
environment. lomatching/surface-sim are not installed in this interpreter.
These are not the newer versions pinned by knill_bench's lockfile, and the
bench bootstrap was not run.

### Audited code and current behavior

Read `AGENTS.md`, `STATUS.md`, `README.md`, `PLAN.md`, `TEST.md`, package
descriptions/exports, and the supplied implementation/specification documents.
Inspected `circuit_generation/circuit_generation.py`,
`modularisation/module_generation.py`, `modularisation/modularised_circuit.py`,
`protocols/knill_online_offline.py`, all decoder modules, and the validation
builders/statistics/storage/plotting paths.

- Circuit builders load sparse CSS matrices, construct SE rounds and ideal
  encoders, and allocate complete data/check supports. The d=3 probe confirmed
  matrix shapes `(4,9), (4,9), (1,9), (1,9)` and both-basis three-round
  preparation dimensions `(17 qubits, 24 measurements, 20 detectors)` for X
  and Z at p=0.001. This probe built circuits but sampled no shots.
- The static engine samples a complete circuit, then applies local DEM/final
  sign repairs and Bell logical byproducts through deterministic software
  correction maps. Fixed Knill uses `2*T+1` distinct supports, ideal initial
  data, and noisy final measurement. Its public return is still two counts.
- Adaptive SE uses short/long descriptions, synchronized pair OR decisions,
  per-shot physical continuation, and executor-owned deterministic caches.
  It is a separate reference path, not a static batched two-block factory.
- Existing decoder protocols/adapters retain batch shapes and legacy calling
  conventions. BP-LSD confidence is cluster risk; no validated factory
  homology-sector gap or projected code-capacity prior option exists here.
- Validation runners compare full Knill backends/forced-long endpoints and
  save aggregate CSV/JSON; analysis consumes saved data. They do not validate
  the proposed one-bit factory, reproduce Fig. 4(d), or write the proposed
  two-table factory schema.

### H0 deliverables

- Extended `AGENTS.md` with branch/scope, deterministic offline inference,
  causal record access, no oracle leakage, object reuse, fast tests, and
  mandatory per-directory documentation rules. Existing history is intact.
- Copied the supplied `implementation/auxiliary_factory_theory.md` unchanged
  into `docs/auxiliary_factory_theory.md`; byte comparison passed. SHA-256:
  `ca7a2748f60e05c2944cddd318c1096eedb269293280826661180b49056337b4`.
  [docs/README.md](docs/README.md) explicitly marks it **proposed / untested**.
- Added eight `DOCS.md` guides: package root, five Python child packages,
  `validation/`, and `tests/`. Current APIs/shapes/noise/caching/limitations are
  separated from proposed interfaces, with links to existing descriptions.
  Matrix-data-only subdirectories contain no Python modules.
- Appended actual baseline evidence to `TEST.md`. No algorithm, public API,
  circuit, fault boundary, dependency, or test implementation changed.

### Checks actually run

| Command (from Hex root) | Result |
| --- | --- |
| `PYTHONPATH=src python -m pytest -q tests/test_phase1_decoder_adapters.py tests/test_phase2_results.py` | 15 passed, 8 warnings, 1.86 s |
| `PYTHONPATH=src python -m pytest -q tests/test_validation_infrastructure.py tests/test_knill_repro_analysis.py` | 14 passed, 8 warnings, 2.70 s |
| `PYTHONPATH=src python -m pytest --collect-only -q tests` | 99 collected, 8 warnings, 0.88 s; not a full-suite run |

Warnings are existing LDPC/pkg_resources namespace deprecations. The selected
legacy static fixtures still sample 256 deterministic measurements despite
requesting one shot; no new tests or Monte Carlo jobs were added. No failures
occurred in these pytest checks. No full-suite or production runner was run.

Documentation integrity checks passed: eight module-directory guides are
present, local Markdown links resolve, the three historical root documents
remain exact byte prefixes, the theory copy matches, and `git diff --check`
reported no whitespace errors. The final staged diff must remain Markdown-only.

### Known issues and scientific limits (unchanged)

1. Legacy matchable DEM weights are `log1p(q)-log(q)`, not the proposed
   `log((1-q)/q)`. Edge priors use a projection sum. This is audited behavior,
   not a newly certified likelihood or a change authorized by H0.
2. CSS callbacks compile local m2d converters on every call. Generic detector,
   noiseless-preparation, and Steane callbacks construct decoders during
   calls; the adaptive reference backend creates one simulator per shot.
   These do not satisfy the proposed factory's object reuse goals.
3. `simulate` uses fixed 256-shot batches and can exceed the requested count.
   CSS source assumes single-Pauli representative faults; support remapping
   is text-based with limited validation. The CSS constructor's `new_support`
   block is unreachable after `_profile_section` returns; current builders
   use `set_support`. `only_postselection_module` remapping is incomplete.
4. `validation/run_knill_repro.sh` actually defaults to d=3/5,
   p=0.002/0.003/0.005, 25,600 shots, three replicates. Its older README states
   different launcher defaults; [validation/DOCS.md](validation/DOCS.md)
   records the source values. Historical single-basis detector counts are
   clarified against code in the circuit-generation guide.
5. The external `decoder-confidence/FUTURE.md` has unresolved logical-gap
   correctness warnings. Read-only inspection found the unsplit constrained
   path appends an observable row and its MWPM builder accepts a check matrix
   directly. This can create degree-three columns; forced-gap correctness and
   graphlikeness are **not assumed or certified**. No external code was copied
   or modified and no gap numerical study was run.
6. The proposed graph lift still requires degree/potential/domain validation,
   finite-weight/p=0 rules, and exhaustive d=3 checks. Projected circuit priors
   after nonlinear offline repair are approximations, not exact conditional
   posteriors. No oracle leakage or factory fault-tolerance claim is inferred
   from the 29 passing legacy tests.
7. Advancing this dependency worktree's HEAD will make the old bench bootstrap's
   exact-SHA check reject it. H0 deliberately does not update that bench pin;
   Python behavior is unchanged and bench dependency integration is later work.

Next boundary: stop after H0 documentation review/commit/push. H1's circuit
primitive requires a separate request; no factory implementation was started.

## Auxiliary-system H1 single-stage factory

Date: **2026-10-15 (Asia/Tokyo)**. H1 was separately requested after H0.
Base: `bceeabb4e3dad25a4cfffc92b91faf1008382747`, on clean tracked
`auxiliary-system`. `git fetch origin` succeeded and both auxiliary refs
matched before edits. No branch switch, reset, stash, or dependency/bench edit
was needed. The H0 environment above is unchanged.

### Implemented scope

- `circuit_generation/factory_surface.py`: the rotated surface adapter reuses
  bundled matrices, `generate_blocks`, surface-specific noisy SE construction,
  and `css_detector_module`. It validates code/noise/depth boundaries without
  putting d*d assumptions into generic contracts.
- `modularisation/factory.py`: frozen code/preparation/support/range/record/
  signed-check/stage dataclasses and adapter protocol. `PreparationFramePlan`
  reuses Hex's four decoder handles/local correction maps, caches both m2d
  converters, and precomputes sparse end-frame maps. Its prep-only batch
  resolver includes DEM inference and both X/Z pure-error repairs, rejecting
  unresolved check signs. No sampled truth is read by this calculation.
- `protocols/logical_zero_factory.py`: builder/bundle for exactly `T_tel=1`.
  Two noisy prepared supports use independent positive depths `r_0,r_plus`;
  transversal `CX(B_plus,A_zero)` and noisy destructive Z readout of A leave B
  as the operational survivor. One ideal Z readout of B is a separate terminal
  evaluation suffix. No third block, post-gate SE, physical software correction,
  intermediate oracle, or observable annotation is added.
- Signed last-round check expressions propagate both preparation signs across
  the CNOT. Raw A terminal checks are `H_Z*m_A XOR last_Z_A XOR last_Z_B`.
  Raw logical parity remains random and is exposed only as a byproduct source.
  The ledger stores absolute physical record IDs and explicit causal regions.
  Metadata is a read-only mapping of immutable values, including circuit hash
  and frame/oracle conventions.
- `build()` checks signed prefix flows with `unsigned=False`, strict
  operational DEM extraction without gauge/disjoint approximation allowances,
  and terminal noiseless oracle isolation. Prep inference accepts only the
  local record width. No operational decoder can consume oracle columns.
- Added public exports, 41 focused tests, an H1 API/equation guide, and updated
  affected `DOCS.md`/`DESCRIPTION.md`, README, agent guide, and test log. The
  supplied scientific specification remains byte-identical.

### Validation actually run

1. Initial `PYTHONPATH=src python -m pytest -q tests/test_factory_circuit.py`:
   **35 passed**, eight existing dependency warnings, **1.38 s**.
2. Targeted H1 + legacy regression command (see exact command in `TEST.md`),
   after structural noise/repair guards: **72 passed**, two statistical-LER
   tests deselected, eight warnings, **2.62 s**.
3. The same command after generic shape/support/input validation:
   **75 passed**, two deselected, eight warnings, **2.71 s**. This includes
   39 H1 tests and 36 existing regressions at that point.
4. Final targeted command after adding B-SE readout and correlated CNOT fault
   cases: **77 passed**, two deselected, eight warnings, **2.68 s**, including
   all **41 final H1 tests** and 36 existing regressions. No pytest failures
   occurred in these runs.
5. Fresh adapter-first and contracts-first imports both passed in separate
   Python processes. `git diff --check` passed after source edits.
6. `python -m compileall -q src tests` passed. Documentation link/anchor,
   preserved historical root-document prefixes, and byte-identical scientific
   specification checks passed.

New tests use deterministic seeds, d=3 (three small d=3/5 zero-noise fixtures),
and <=128 physical shots per batch. They cover both logical branches and wrong
byproduct sensitivity, reversed gate rejection, negative signed-flow rejection,
raw/pure-error signs from both blocks, exact reset/SE/CNOT/readout boundaries,
oracle exclusion, and legacy Pauli-to-measurement map equality for X and Z.
Eight targeted cases cover both resets, either SE readout, either block after
CNOT, a correlated CNOT pair fault, and consumed-block readout; a terminal logical fault changes only the
evaluation label. Tests compare batch partitions and legacy corrections and
forbid constructing Matching graphs during prep resolution. New prepared
signs fail clearly if a decoder refuses to repair them.

### Limits and next boundary

**H2 has not started.** There is no `CompiledFactory`, factory sampler,
`FactoryBatchDecoder/Result`, repeated two-block role swapping, online stage
decode, or production logical-error result path. The terminal code-capacity
readout convention is reserved in metadata and checked only by test helpers.
Logical gap and `create_codecapacity_dem` are absent. No Parquet/YAML or
experiment runner was added and no Monte Carlo sweep/full suite was launched.

Legacy preparation priors retain their existing matchable projection and
weight formula; they are not certified as optimal post-repair priors. Strict
DEM extraction is undecomposed and makes no graphlike-model claim. Tests
establish the stated structural/frame boundaries and selected faults, not
general gadget fault tolerance, a threshold, or paper reproduction. Native
decoder objects/Stim circuits remain mutable even though contract metadata and
support tuples are immutable; handles are for synchronous worker-local reuse.

The parent bench's old exact Hex revision pin is unchanged. Commit and push
outcome are reported in the H1 handoff; stop after that single H1 commit/push.

## Auxiliary-system H2 batched factory

Date: **2026-10-16 (Asia/Tokyo)**. H2 was separately requested after H1.
Base: `aaba359358949094c53354e15226312119b5e4c6`, clean tracked
`auxiliary-system`. Fetch succeeded and local/origin auxiliary refs matched
before edits. No reset, stash, branch replacement, installation, or bench edit
was needed. Python/native dependencies remain those recorded in H0.

### Implemented scope

- Fixed positive `T_tel` unrolling on exactly two data/ancilla supports.
  Initial A-zero/B-plus preparations use independent depths; each consumed
  support is reset/reprepared plus before its next role. Gates remain
  `CX(fresh_plus,memory)` with noisy consumed-block Z readout, no post-gate SE,
  and only one final ideal Z oracle on the actual last survivor.
- Generalized signed check propagation/record ledgers and prefix/strict-DEM
  validation. Added causal stage/role/preparation/byproduct guards. Ad hoc
  comparisons against the H1 builder confirm byte-identical T=1 circuits and
  equal ledger/stage/signed flows at three d=3/5 configurations.
- `PreparationFramePlan.bind` shares cached local preparation circuit,
  decoders, converters and sparse maps across repeated same-support refreshes;
  at most three preparation templates are built per case.
- `simulation/factory.py`: frozen compiled configuration and cache key,
  one native compiled sampler, deterministic causal batched frame decoder,
  operational/result dataclasses and sample/decode APIs. Results carry uint64
  shot IDs, boolean per-stage syndromes/raw and corrected byproducts/resolved
  frames, stage IDs, and one last-oracle logical-error label. `gaps=None`
  reserves the future confidence field without implementing H3.
- `decoders/factory_surface.py`: cached surface Hamming transforms and
  distinct online/terminal matching handles, with residual recovery guards.
  Surface assumptions are outside the generic causal stage loop. Unsupported
  families/conventions, nonbinary/wrong-width batches and ID overflow fail.
- Physical trajectories are sampled once; corrections only update software
  interpretation. Stage j reads local prep/readout and previous frame, never
  future or oracle records or sampled fault truth. No per-shot circuit,
  sampler, graph, deterministic simulator or map construction occurs.
- Explicit cache keys cover code/distance, p/noise, depths/T, full circuit
  hash, frame/prior/label/decoder conventions, seed and library versions.
  Handles are synchronous and worker-local; no global cache or new output
  runner is introduced. New guide and affected package/test documents describe
  exact fields, equations, reset convention, lifetime, and limits.

### Validation and resolved discrepancy

The initial H2 run had **9 failures and 21 passes**. Eight frame/byproduct
comparisons revealed that legacy deterministic RX propagation retains an
unobservable X component while the new boundary frame clears both X/Z.
Terminal labels already agreed; this was a coordinate convention difference,
not permission to drop frame validation. Canonical reference maps now add
reference-only R-before-RX sentinels, while additional unmodified legacy replay
tests require equal labels and frame differences with zero syndrome/logical
action. Production physical circuits/sampling remain unchanged. The ninth
failure was unsupported Stim circuit item assignment in a hash-guard test;
the test now uses circuit concatenation.

Subsequent runs passed **32 H2 tests**, then **73 combined H2/H1 tests**, then
the final **111 targeted tests**, including **34 H2**, **41 H1** and 36 legacy
regressions. Two inherited statistical-LER cases were excluded; eight existing
dependency warnings remain. Exact commands, durations, import and integrity
checks are in [TEST.md](TEST.md#auxiliary-system-h2-batched-factory).
New physical batches use <=64 seeded shots, mostly d=3 and one d=5 smoke case.
Tests cover T=1/2/3, both roles at every stage, logical faults through later
teleportations, both Pauli-frame components, oracle/future independence,
fixed-seed/fixed-partition repeatability, scalar/batch/partitioned equality,
input immutability, dtypes/ID limits, causal/failure guards and constructor
counts (14 matching objects, one sampler for a fresh T=3 case; none during
sampling/decoding).

### Limits and next boundary

**H3 has not started.** There is no logical gap algorithm, projected prior,
`create_codecapacity_dem` option, quality-dependent sampling, threshold/cost
selection, YAML/Parquet runner, large Monte Carlo, full-suite run or speed
benchmark. Spatial online/terminal matching uses Hamming weights. Legacy
preparation projections/weights remain preserved, not certified as optimal
conditional priors. Strict DEM and selected fault tests do not establish
general fault tolerance or paper reproduction.

Frozen configuration does not freeze native RNG/decoder internals or caller
arrays. Use one object synchronously per worker, leave source plans unchanged,
and supply unique shot offsets. Same-seed sampling depends on version/platform
and chunk partition; scalar/batch equality applies to identical saved records.
The parent bench's existing revision pin and user changes are untouched.
Commit/push outcome belongs to the H2 handoff; stop after the one H2 commit.

## Auxiliary-system H3 surface logical gap

Date: **2026-10-16 (Asia/Tokyo)**. H3 was separately requested after H2.
Base: `076a8345421bd47bbc7e1919fa44c91ec90d19c0`, clean tracked
`auxiliary-system`; fetch succeeded and local/origin refs agreed. No reset,
stash, branch replacement, package installation or bench edit occurred.
The H0/H2 environment is unchanged; NetworkX 3.3 was already a PyMatching
dependency and is now directly declared (`networkx>=2.8`) for planarity.

### Implemented scope

- Reviewed all required `decoder-confidence` reference files and FUTURE
  warnings. Their append-a-logical-row/per-shot rebuild approach is not reused
  or treated as verified. The new module imports no code from that checkout.
- `decoders/surface_gap.py`: public `SurfaceMWPMHomologyGap` and frozen
  `HomologyGapBatch`. A deterministic GF(2) internal potential determines
  two extra constrained detector rows B0/B1. Every lifted column has degree
  two; the lifted syndrome fixes the requested logical sector by the proven
  identity `L=u^T H XOR B1`. One cached graph handles both classes in two
  native batch calls. Returned data include both original-weight costs,
  corrections, nonnegative gap, best class and explicit units.
- Setup validates binary/shape/degree, potential, connected planar lift,
  positive finite weights, native maximum/dynamic range, and constrained
  boundary interpretation. Zero-detector events, hyperedges, inconsistent
  cycles, unsupported topology and multiple observables fail explicitly.
  Parallel-edge minimum representatives preserve sector costs/output width.
- `SurfaceFactoryReadout` caches a separate gap graph using unit Hamming
  weights for all physical p, including the explicit finite p=0 rule.
  Factory results fill `(shots,T) float64` gaps and add `gap_units`; the cache
  key adds a gap policy. Every score uses its current corrected syndrome
  before recovery. H2's other operational/frame/terminal-label semantics and
  one final oracle remain unchanged; no score influences quantum sampling.
- Added 37 focused tests, updated H2 gap/count expectations, a complete H3
  API/proof/precision guide, package/test docs and append-only history.

### Validation and resolved discrepancies

Initial H3 tests: **2 failed, 34 passed**, ten warnings, **5.97 s**. Two
weighted cases tripped an overly tight native-cost equality guard. A probe
found native discretization differences up to `2.15e-7`, while edge corrections
had the correct original-weight costs. Version-pinned PyMatching source
confirmed noninteger scaling/rounding. Costs remain recomputed in original
weights; the guard now uses a conservative n-edge rounding allowance and
rejects extreme dynamic range. A test-only unsigned negation also caused
two runtime warnings/NaN in the posterior comparison; it now sums in float64
and asserts a finite comparison. Neither issue was hidden by weakening the
exhaustive sector-cost oracle.

Then H3+H2 passed **71 tests** in **20.03 s**, eight existing warnings.
The targeted H3/H2/H1/legacy run passed **148 tests**, two statistical
cases deselected, eight warnings, **24.50 s**. The isolated H3 subset
passed **37 tests** in **6.04 s**. Final review added rejection of an absolute
weight scale too small for finite native normalization, with a focused test
case. The full targeted command then passed **148 tests**, two deselected,
eight warnings, **25.89 s**. Exact commands are in
[TEST.md](TEST.md#auxiliary-system-h3-surface-logical-gap).

The d=3 classical oracle enumerates all 512 physical error vectors for both
sector minima at all 16 syndromes, four weight vectors and two logical-row
representatives. Tests verify costs, logical class, degree/potential/parity,
ties and guards. Integration tests compare every stage to enumeration and
perturb future/oracle/raw logical records. Zero-noise d=3 T=1/2/3 and d=5 T=2
give gap d; new physical batches use <=32 shots. Constructor tests enforce
15 Matching objects/one sampler for fresh T=3, none in sampling/decoding.
Saved-record H2 probes at T=1/2/3 preserve all prior operational fields and
terminal labels. Compilation, fresh import orders, TOML and documentation
integrity checks passed as detailed in TEST.md.

### Limits and next boundary

**H4 has not started.** Factory gaps use the spatial independent-edge Hamming
model, not a circuit-informed or exact conditional posterior after nonlinear
prep repair. Min-sum sector differences are not posterior log-odds. The lift
reduction is exact, but native noninteger weights have finite resolution and
arbitrarily close weighted minima are not certified; unit factory weights
avoid that ambiguity. Native objects remain synchronous/worker-local.

No projected prior, `create_codecapacity_dem`, threshold/abort/retry path,
YAML/Parquet runner, full suite, large Monte Carlo, speed benchmark, general
fault-tolerance proof or paper reproduction was implemented/run. Scientific
specification bytes, legacy physical circuits/decoders and parent user changes
are untouched. Commit/push outcome is reported in the H3 handoff.
