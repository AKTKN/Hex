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

## Proposed only

Future [factory execution](../../../docs/README.md) will sample fixed unrolled
circuits in chunks and decode stages vectorially with reusable samplers,
graphs, sparse maps, and decoders. Stage `j` must exclude future records and
the terminal ideal oracle, even when the whole shot was sampled in advance.
Threshold rejection/cost accounting is post-processing of fixed trajectories.
No `CompiledFactory`, `FactoryBatchDecoder`, multi-stage two-block reuse, or
factory confidence result was added in H0. Cache configuration must eventually
include circuit/noise/preparation/depth/prior/frame conventions explicitly.
