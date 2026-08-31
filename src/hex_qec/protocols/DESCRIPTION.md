# `protocols`

This package contains the fixed-round Knill and Steane builders plus a
separate stateful two-level adaptive Knill builder. The legacy builders still
return `(samples_performed, logical_errors)`.

## Common inputs and outputs

`knill_online_offline` has the following backward-compatible signature (the
new options are intended to be passed by keyword):

```python
(
    parity_check_tuple,
    syndrome_measurement_rounds,
    online_decoder_generator,
    offline_decoder_generator,
    matchable_offline_decoding,
    physical_error,
    max_shots,
    max_errors_before_halting,
    pauli,
    num_teleportations,
    results_path="",
    surface_code=False,
    seed=None,
)
```

The matrix tuple is `(x_pcm, z_pcm, x_logical, z_logical)` with operator rows
and physical-qubit columns.  Decoder generators are callables returning
objects with `decode_batch`; the CSS state-preparation path also wraps an
object exposing only scalar `decode`.  The online generator is used for
teleportation/correction and final logical measurement.  The offline
generator is used for noisy encoded-state preparation.  `pauli` selects the
initial/final logical basis (`"x"` or `"z"`).

`steane_online_offline` retains its historical signature and does not expose
the Knill-only `surface_code` or `seed` options.

The optional `seed` is passed to Stim's static compiled sampler; it is
`None` by default, preserving entropy-seeded historical behavior. The return
value is the static engine's two-integer tuple. The number of
performed samples is normally a multiple of 256 because the engine samples
fixed-size batches and may exceed `max_shots`.  `results_path` is passed to
the static engine, which writes cumulative JSON statistics when nonempty.
The legacy protocol functions do not expose a protocol-level
`SimulationResult`; callers that construct a `modularised_circuit` directly
can use its `simulate_result(...)` wrapper. The separate
`knill_online_offline_adaptive(...)` entry point returns `SimulationResult`
with adaptive event statistics.

## Knill protocol

`knill_online_offline` allocates `2 * num_teleportations + 1` blocks.  Each
block dictionary has data, X-ancilla, and Z-ancilla supports.  Block 0 is the
initial data block.  For every teleportation index, one block is prepared as
noisy `|0_L>` and the next as noisy `|+_L>`.

The constructed module order is:

```text
ideal initial data preparation (selected by pauli)
for each teleportation:
    noisy |0_L> state preparation (offline decoder)
    noisy |+_L> state preparation (offline decoder)
    transversal CNOT: |+_L> control -> |0_L> target
    Bell measurement/correction (online decoder)
final logical measurement in the selected basis (online decoder)
```

The Bell module performs a transversal CNOT between the current data block and
the first Bell block, measures those two blocks in X and Z bases, decodes the
measurements using the code check matrices, and emits logical correction bits
that are represented in the software measurement-update frame.  On later
teleportations, the second Bell block from the previous step is the current
data support.  The protocol does not run a dynamic decision between state
preparation rounds; `syndrome_measurement_rounds` is fixed for every prepared
ancilla.

`knill_online_offline_adaptive(...)` accepts an `AdaptiveSERounds` object
instead of a fixed integer. For every teleportation it creates adaptive
`|0_L>` and `|+_L>` events. The stateful executor decodes both short records
before making one synchronized Bell-pair decision: each patch's confidence is
evaluated by its own `AdaptivePolicy.should_extend(...)` independently, and
the pair decision is the boolean OR of those two per-patch booleans -- never
a raw max/min comparison of their confidence values. This is the generic
pair-level control rule regardless of metric/policy direction; if either
patch requests extension, both patches continue on their existing physical
simulator state and decode their full long histories. The optional
`confidence_aggregator` receives one `CSSInnerDecodeResults` (the four inner
CSS `DecodeResult` objects, named `x_dem`/`z_dem`/`x_capacity`/`z_capacity`)
per patch and returns the module-level confidence array, keeping metric
selection out of the simulator. `hex_qec.decoders.dem_only_max_confidence`
(DEM-only) is the current default for the adaptive-SE experiment;
`all_components_max_confidence` also folds in code-capacity confidence and is
diagnostic-only -- see `decoders/DESCRIPTION.md` and `FUTURE.md`,
"Code-capacity confidence for adaptive state preparation".

Both `knill_online_offline(...)` and `knill_online_offline_adaptive(...)`
accept `surface_code=False`. Passing `True` selects the surface-code-specific
stabilizer interaction ordering for all generated state-preparation patches;
the default preserves the historical ordering.

The adaptive result's `state_prep_stats` are patch-level records, while
`SimulationResult.bell_pair_stats` records the synchronized decision per
teleportation.  A pair extends when either patch policy requests extension;
therefore both ancillas always enter the Bell CNOT at the same selected depth.
The analysis payload preserves each patch confidence and would-extend value,
as well as the pair-level decision and `z_only`/`x_only`/`both` cause counts.

For opt-in diagnostics, the adaptive entry point also accepts a
`hex_qec.simulation.WallTimeProfiler` and `warmup_shots`. These optional
arguments only collect wall-clock sections around existing construction and
execution calls; they do not alter seeds, batching, decoder inputs,
correction propagation, or policy decisions. The dedicated runner in
`profiling/adaptive_walltime_profile.py` uses `batch_size=1` and writes raw,
summary, and Markdown outputs outside the normal test run.

The standalone wrapper in `examples/knill_example.py` selects one of
PyMatching, BP, or BP-OSD by name, loads matrices by code and distance, sets
`syndrome_measurement_rounds = distance`, and returns the protocol tuple.

## Steane protocol

`steane_online_offline` uses the same block allocation and ideal initial data
preparation.  For each teleportation index it appends:

```text
noisy |0_L> preparation
transversal CNOT: |0_L> control -> current data target
Steane correction in Z basis
noisy |+_L> preparation
transversal CNOT: current data control -> |+_L> target
Steane correction in Z basis
```

The Steane correction helper measures an ancilla block, decodes its syndrome
with the online generator, and maps the physical correction bits to the data
block.  The final logical measurement is on block 0 rather than the final
Bell-block support used by Knill.

The bundled wrapper in `examples/steane_example.py` uses the same decoder
selection and fixed-round convention as the Knill wrapper.

## Dependencies and call graph

The protocol modules depend on the circuit-generation and modularisation
packages, Stim, NumPy, PyMatching, and `ldpc` for the example wrappers' BP
and BP-OSD decoder factories.  The core call graph is:

```text
protocol function
 -> create_stabilizers_and_block_template
 -> generate_blocks / noiseless_unitary_state_prep
 -> module_generation gadget builders
 -> modularised_circuit(module_list)
 -> generate_correction_to_measurement_flip_map
 -> simulate
```

The protocol functions themselves do not construct decoder objects; they
receive generators.  The example wrappers are where the named PyMatching,
BP, and BP-OSD choices are converted into generators.

The adaptive call graph is:

```text
knill_online_offline_adaptive
 -> adaptive state-preparation descriptions
 -> ordinary Knill gadget modules
 -> StatefulAdaptiveKnillExecutor
 -> per-shot physical execution and software correction maps
 -> SimulationResult
```

## Current limitations

- The legacy API is fixed-round and positional. A separate
  `StatefulFlipSimulatorBackend` can execute an already-built fixed circuit
  with `stim.FlipSimulator`; legacy protocol functions still use the static
  backend and return legacy tuples.
- Decoder protocols and legacy adapters now exist in `hex_qec.decoders`.
  Adaptive CSS modules retain rich decoder results through `c_func_rich`; the
  legacy callbacks still expose correction arrays.
- No explicit validation enforces positive teleportation count, valid basis,
  compatible matrix dimensions, or `syndrome_measurement_rounds` bounds.
- The static engine's batch semantics and final detector assertion apply to
  both protocols.  A decoder that fails to remove all detector flips can
  therefore terminate the simulation with an assertion.
- The code preserves the existing software correction convention by updating
  future sampled measurement records through precomputed maps; it does not
  physically apply decoded corrections while sampling.
- Adaptive execution is an unoptimized one-shot reference path and does not
  compact branches.
