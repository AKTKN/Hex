# `simulation`

This package contains the Phase 3 stateful fixed-round backend and the
stateful two-level adaptive state-preparation/Knill execution paths.

## Policies

`AdaptivePolicy` is a `Protocol` whose `should_extend(...)` method receives a
short `DecodeResult` and `AdaptivePolicyContext`, then returns a boolean array
with shape `(batch_size,)`. `AlwaysShortPolicy` returns all false values and
`AlwaysLongPolicy` returns all true values. `ClusterLLRPolicy` is an example
metric-specific policy that interprets `DecodeResult.confidence` as the
risk-like BP-LSD cluster LLR and extends when it exceeds a threshold. The
simulator itself does not inspect a metric name or impose a confidence
direction.

## `StatefulFlipSimulatorBackend`

`StatefulFlipSimulatorBackend(circuit, batch_size=256, seed=None)` accepts an
existing `modularised_circuit`. `iter_module_measurements()` executes each
module's physical `stim.Circuit` in order on one
`stim.FlipSimulator(disable_stabilizer_randomization=False)` and yields
`StatefulMeasurementBatch` records. The yielded physical arrays use shape
`(batch_size, measurements_so_far)`; their first axis is the shot axis.

The backend reconstructs each prefix as:

```text
Hex raw record = Circuit.reference_sample() XOR get_measurement_flips().T
```

Stim's `get_measurement_flips()` has shape `(measurements, batch_size)`, so the
transpose is required. `reference_sample()` removes noise and deterministically
biases collapse outcomes toward `+Z`. This conversion is exposed as
`reconstruct_measurement_records(...)` and is independently testable.

`simulate(...)` preserves the static engine's aggregate tuple and module-local
decoding sequence. It maintains a full software measurement-flip frame for
decoded corrections. At each module, the physical prefix is XORed with that
frame before detector conversion and decoding. The frame is updated from the
existing `correction_to_measurement_flips` maps; no decoded correction is
written into the physical `FlipSimulator`. This keeps physical state and
software interpretation separate and avoids double application.

`simulate_result(...)` returns the Phase 2 `SimulationResult` wrapper with
stateful-backend metadata. Fixed-round runs still do not populate adaptive
event statistics or per-shot/debug payloads.

## Two-level state-preparation diagnostics

`AdaptiveSERounds(short_rounds, long_rounds, policy)` validates
`1 <= short_rounds <= long_rounds`. `AdaptiveStatePrepModule` composes:

```text
short_circuit: initialization + rounds 1..short_rounds
extra_circuit: rounds short_rounds+1..long_rounds
long_circuit: initialization + rounds 1..long_rounds
```

The short and long circuits are built from separate
`css_detector_module` instances. The long decoder therefore receives the
complete long measurement array with shape
`(shots, long_circuit.num_measurements)`, while the short decoder receives
`(shots, short_circuit.num_measurements)`. `extra_circuit` is an exact Stim
instruction suffix of `long_circuit` and is checked not to reset data-qubit
positions.

`StatefulAdaptiveStatePrepExecutor.execute(...)` runs the short circuit for
each one-shot simulator, evaluates the policy, and continues only selected
shots with the exact extra suffix on their existing simulator. It verifies
that every long reconstructed record has the identical short prefix. The
short correction is not committed on a long branch. Mixed batches expose
per-shot selected results because short and long correction vectors can have
different widths.

`StatefulAdaptiveKnillExecutor` executes a sequence containing ordinary Hex
modules and `AdaptiveStatePrepModule` events. Adjacent `|0_L>`/`|+_L>` events
with the same teleportation index form one synchronized pair: both short
patches are decoded before either policy decision is committed, and either
patch requesting extension forces both patches to long. It maintains a separate
software correction frame, dynamically reconstructs correction-to-measurement
maps for the selected path, and keeps physical simulator state separate from
decoder corrections. `knill_online_offline_adaptive(...)` is the protocol
builder using this executor. It records one event for each `|0_L>` and
`|+_L>` preparation at every teleportation index.

`SimulationResult.state_prep_stats` contains patch-level aggregate short/long counts,
fallback rate, confidence summaries, average effective SE rounds, event
identity, basis, teleportation index, and logical-error counts. With
`detail_level="analysis"` or `"debug"`, `per_shot` additionally contains
confidence, patch-level would-extend values, patch risk, synchronized
`used_long`, pair decisions, event metadata, postselection, and final
logical-error arrays.
`SimulationResult.bell_pair_stats` contains pair-level fallback fractions and
the `z_only`, `x_only`, and `both` diagnostic partition.

For a synchronized pair, physical execution is ordered as Z-short, X-short,
Z-extra, X-extra.  The extra circuits are executed on the two existing
`FlipSimulator` states and are not independently sampled or reinitialized.
Their detector annotations are omitted from the interleaved physical circuit
because those annotations have local contiguous-record references; each
selected long decoder still receives its complete, correctly reconstructed
round-1..long measurement history.  Correction maps are generated in the
logical Z-then-X order and translated to the interleaved physical measurement
record, keeping physical state separate from the software correction frame.

## Limitations

- The original `StatefulFlipSimulatorBackend` remains fixed-round; adaptive
  execution uses the separate `StatefulAdaptiveKnillExecutor`.
- Adaptive execution is deliberately unoptimized: it uses one
  `FlipSimulator(batch_size=1)` per shot and recomputes deterministic
  correction maps for paths as needed.
- It uses the existing 256-shot batch convention by default, but accepts a
  configurable batch size for tests and experiments.
- `reference_sample()` is computed for the complete concatenated circuit and
  sliced as prefixes. Stim circuit measurement records are causal, so current
  detector slices depend only on the prefix already executed.
- `copy(copy_rng=True)` is not needed by the reference adaptive path because
  each shot retains its own simulator. Branch compaction and batch-state
  copying remain future optimizations.
