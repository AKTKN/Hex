# Simulation: physical records, software frame, and caching

Detailed execution discussion: [DESCRIPTION.md](DESCRIPTION.md).

## Implemented today

- `StatefulFlipSimulatorBackend(circuit, batch_size=256, seed=None)` executes
  an existing fixed modular circuit on `stim.FlipSimulator`, exposes
  `iter_module_measurements()`, and offers tuple/result-returning simulation.
- `reconstruct_measurement_records(reference, flips)` computes
  `reference[None, :] XOR flips.T`. Stim flips use `(measurements, shots)`;
  reconstructed boolean records use `(shots, measurements)`. Physical
  stabilizer randomization stays enabled.
- `StatefulAdaptiveStatePrepExecutor` samples a short preparation, evaluates
  its policy, and continues the same physical shot for a long choice. Long
  decoding reads rounds `1..long`, never the extra suffix alone.
- `StatefulAdaptiveKnillExecutor` synchronizes adjacent zero/plus events by
  OR-ing their separate policy decisions. Physical pair order is Z-short,
  X-short, Z-extra, X-extra; explicit permutations recover contiguous local
  decoder histories. `SimulationResult` reports patch and pair statistics;
  analysis/debug add confidence/decision/error arrays with shot first axes.
- `AdaptivePolicy.should_extend(result, context=...)` returns a boolean
  `(shots,)` mask. `AlwaysShortPolicy`, `AlwaysLongPolicy`, and risk-like
  `ClusterLLRPolicy` are supplied. `WallTimeProfiler` records optional nested
  setup/warm-up/measured timing; inclusive times must not be summed twice.

Inferred corrections change a separate software measurement-flip frame, not
the physical simulator. Corrected prefixes are decoded chronologically;
resampling long histories independently with the same seed would violate
same-shot continuation. Reference samples are deterministic reconstruction
data, not sampled fault truth or logical-error labels.

The adaptive Knill executor owns shared correction-map and lazy
reference-sample caches, plus precomputed detector-stripped suffixes. Cache
keys reflect ordered logical module identities or physical paths. Single-stage
short/long and common multi-stage paths are prepared once; unseen mixed paths
can incur a one-time map-generation miss. Shot state, flips, and confidence
remain uncached. This reference executor still creates a `batch_size=1`
simulator per shot; it does not implement production factory batching.

Existing tests cover reconstruction, endpoints, pair synchronization, cache
identity, and profiling. H0 only collected those tests; its executed subset is
recorded in [TEST.md](../../../TEST.md#auxiliary-system-h0-documentation-baseline).
General dynamic causal-detector support and branch compaction remain limited.
Equal seeds across compiled and stateful backends do not imply paired faults.

## H2 compiled factory batches

`factory.py` supplies public lazy exports `CompiledFactory`,
`FactoryBatchDecoder`, `FactoryOperationalBatch`, `FactoryBatchResult`, and
`FactoryCacheKey`. `CompiledFactory.from_bundle(bundle, seed=None)` copies and
hash-checks a validated factory circuit, builds one cached decoder and one
native sampler. `sample(shots, shot_id_start=0)` draws and decodes one batch;
`sample_measurements(shots)` and `decode(records, shot_id_start=0)` separate
those operations. The RNG advances on each sampling call; IDs use explicit
caller offsets with uint64 overflow guards.

`decode_operational(records, shot_id_start=0)` accepts exactly the oracle-free
prefix. Stage j reads only its local prep/readout slices and prior frame,
using batch arrays rather than per-shot objects. It resolves legacy full-history
prep repair, applies CNOT frame propagation, infers the spatial Hamming logical
byproduct, then commits the output frame. Resets clear old X/Z frames. The
surface transforms/matching assumptions live in the decoder adapter.
`decode` fixes these operational fields before a separate terminal evaluator
reads the sole last ideal Z oracle. No physical correction or resampling is
performed. Raw detectors retain their original physical sign semantics.

Results contain `(shots,T,m_z)` corrected pre-recovery syndromes, `(shots,T)`
raw/corrected byproducts and frame consistency, `(shots,T,n)` X/Z output frames,
tuple stage IDs and `(shots,) uint64` shot IDs. Full results add
`(shots,) bool` logical-error labels. Frame consistency is not
truth/confidence. Inputs are binary, nonempty, exact-width, and unmodified.

The key covers code/d/p/noise/depth/T/circuit hash/frame/prior/label policy,
seed and native-library versions. Local preparation converters/maps and
decoder handles are shared across repeated same-support refreshes; spatial
matrices and separate online/terminal matchings are cached. No expensive
objects are created inside sampling/decoding. Frozen configuration owns
mutable native handles: keep it synchronous and worker-local, do not mutate
source plans, and construct independently per worker. Equal seeds require
the same Stim version/platform and sampling chunk partition for repeatability;
scalar/batch equivalence concerns decoding identical saved records.

See [the H2 guide](../../../docs/logical_zero_factory_h2.md) for exact frame
equations, reset-gauge reference tests, fields and lifecycle. Tests cover
future/oracle isolation, fault propagation, all dtypes, scalar/batch equality,
and constructor counts. Projected priors and threshold/cost analysis remain
future work. No benchmark filesystem/YAML/Parquet behavior is included.

## H3 causal stage scores

Full `FactoryBatchResult` now fills `gaps` with `(shots,T) float64` and adds
`gap_units="hamming_weight"`. H2's `gaps=None` constructor default is retained
for compatibility; production decode always fills it. `FactoryOperationalBatch`
keeps its existing fields. The private causal loop returns operational fields
and scores before terminal evaluation; the oracle-free public method returns
the original operational object. Each stage scores its current corrected
syndrome before recovery. Changing future/oracle bits cannot change an earlier
score; raw logical branches with the same syndrome have the same score.

The surface readout adapter caches a separate `SurfaceMWPMHomologyGap` graph,
calling native matching twice per stage batch. No constructor or weight update
occurs per shot. H2 recovery/byproduct/frame tie choices and terminal labels
are unchanged; the standalone score's best class does not replace them.
`FactoryCacheKey.gap_policy="surface_two_boundary_hamming_v1"` versions this
unit-weight policy, including at p=0 (finite zero-syndrome gap d). Existing
case/native-version/worker lifecycle rules continue to apply. A new T=3 case
builds 15 matching objects (12 prep, online, terminal, gap), one sampler.

The metric compares sector minima in a spatial independent-edge model, not
posterior sums or an exact circuit-conditioned probability after nonlinear
prep repair. No threshold decision changes physical sampling. See
[the H3 guide](../../../docs/logical_zero_factory_h3.md) for the lift,
standalone result, native precision and tested limits.

## H4 causal stage-input boundary

`FactoryBatchDecoder.decode_stage_input(records, stage_index)` returns
interpreted `(shots,n) bool` target Z records before that stage's online
recovery. It requires a nonempty binary batch of exactly that stage's prefix
width and a valid chronological index. It reuses the existing prep/frame loop
and Hamming recovery on earlier stages, without gap evaluation or terminal
oracle/labels. Full `decode` and `decode_operational` retain their previous
shape, meaning and results; default sampling/scoring remains Hamming.

The H4 [projected-prior builder](../../../docs/logical_zero_factory_h4.md)
uses this boundary only during model setup on controlled noiseless-reference
fault records, never on hidden fault truth from actual shots. Priors, graphs
and diagnostics live in the decoder package, separately cached per complete
case/stage. Its fixed-reference approximation is not an exact conditional
model: observed prep-context and nonlinear multi-fault mismatches are recorded
in the H4 guide/STATUS. No public full-Knill option, simulator feedback,
postselection, filesystem output or H5 work is introduced.

## H5 optional projected factory execution

`FactoryBatchDecoder(bundle, *, create_codecapacity_dem=False)` and
`CompiledFactory.from_bundle(bundle, *, seed=None, create_codecapacity_dem=False)`
add the public policy without changing circuits. False retains H2/H3 behavior.
True builds complete causal contexts/validated graphs in stage order, using
actual earlier projected recoveries and their hashes for later priors. A raw
logical parity is XORed with the chosen error class, while frames retain their
original data-position shapes. Terminal evaluation stays separate and Hamming.

True full results have `gap_units="log_weight"`; False has "hamming_weight".
Public `projected_priors` is an immutable tuple of inspectable per-stage results.
Keys add the flag, projected decoder/gap policy and configuration hashes;
False defaults remain False/empty. `decode_stage_input` now uses the configured
earlier policy. Native graphs/sampler/converters/maps are reused; unsupported
models and zero-noise finite-weight requests raise with no silent fallback.

The d=3 p=.001 depths (2,2) T=1/2 True cases pass batch/scalar, frames,
future/oracle isolation and constructor checks. The complete fast repository
selection passes 261 tests, two larger statistical cases excluded. See
[the H5 guide](../../../docs/logical_zero_factory_h5.md) for precise context,
numerical/probabilistic limits and full-Knill coverage. No physical prior
accuracy certificate, speedup, threshold or posterior-confidence claim follows.
