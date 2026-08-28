# `simulation`

This package contains the Phase 3 stateful fixed-round backend. It does not
implement short/long branching or any adaptive policy.

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

## Limitations

- This backend executes the complete fixed module list and makes no adaptive
  decision.
- It uses the existing 256-shot batch convention by default, but accepts a
  configurable batch size for tests and experiments.
- `reference_sample()` is computed for the complete concatenated circuit and
  sliced as prefixes. Stim circuit measurement records are causal, so current
  detector slices depend only on the prefix already executed.
- `copy(copy_rng=True)` is not needed by the fixed-round backend; it is
  reserved for a future same-shot adaptive continuation implementation.
