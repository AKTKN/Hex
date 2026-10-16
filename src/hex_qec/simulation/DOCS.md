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
`(shots,) bool` logical-error labels and `gaps=None`. Frame consistency is not
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
and constructor counts. H3 gap, projected priors and threshold/cost analysis
remain future work. No benchmark filesystem/YAML/Parquet behavior is included.
