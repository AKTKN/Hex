# `simulation`

This package contains the Phase 3 stateful fixed-round backend and the
diagnostic execution pieces for the two-level adaptive state-preparation
design. It does not implement confidence-threshold switching or mixed
per-shot branching.

## Policies

`AdaptivePolicy` is a `Protocol` whose `should_extend(...)` method receives a
short `DecodeResult` and `AdaptivePolicyContext`, then returns a boolean array
with shape `(batch_size,)`. `AlwaysShortPolicy` returns all false values and
`AlwaysLongPolicy` returns all true values. Their purpose is endpoint
diagnostics; no confidence value is interpreted by either policy.

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

`StatefulAdaptiveStatePrepExecutor.execute(...)` runs the short circuit and,
for `AlwaysLongPolicy`, runs the extra suffix on the same
`stim.FlipSimulator` instance. It verifies that the long reconstructed record
has the identical short prefix. The short correction is not committed on the
long endpoint; only the selected short or long result is returned. A mixed
policy mask currently raises `NotImplementedError`, which is reserved for
the full branching phase.

## Limitations

- This backend executes the complete fixed module list and makes no adaptive
  decision.
- The adaptive executor supports only uniform AlwaysShort and AlwaysLong
  diagnostic policies; it does not yet execute mixed short/long branches or
  confidence-threshold switching.
- It uses the existing 256-shot batch convention by default, but accepts a
  configurable batch size for tests and experiments.
- `reference_sample()` is computed for the complete concatenated circuit and
  sliced as prefixes. Stim circuit measurement records are causal, so current
  detector slices depend only on the prefix already executed.
- `copy(copy_rng=True)` is not needed by the fixed-round backend; it is
  reserved for a future same-shot adaptive continuation implementation.
