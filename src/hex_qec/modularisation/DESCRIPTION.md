# `modularisation`

This package defines the current module objects, common gadget constructors,
structured module-output normalization, and the static execution engine.  The
module objects are ordinary Python classes, not dataclasses or a formal module
interface hierarchy.  Decoder result protocols and legacy decoder adapters
live in `hex_qec.decoders`.

## Module inputs and support remapping

Every module stores a `stim.Circuit`, `num_measurements`, and
`num_detectors`.  Most modules are built on local qubit indices and remapped
onto a protocol support list by rewriting the circuit's Stim text.  A support
list has one global qubit index per local circuit qubit.  It is expected to
have exactly `circuit.num_qubits` entries; an empty list means the identity
range in most classes.

The decoder functions are batch functions.  A raw-measurement function
receives an array with shape `(shots, module.num_measurements)`.  A detector
function receives `(shots, module.num_detectors)`.  Correction outputs use
shape `(shots, number_of_correction_variables)`.  The first axis is always
the shot axis; the second axis indexes correction variables in the order
defined by the module's correction array or decoder output.

## Structured module outputs

`ModuleDecodeResult` records `corrections`, optional per-shot
`postselection`, an optional underlying `DecodeResult`, and decoder-specific
`metrics`.  `normalize_module_decode_output` accepts all current callback
forms: a correction ndarray, `(corrections, postselection)`, a `DecodeResult`,
or a `ModuleDecodeResult` (and also a `(DecodeResult, postselection)` pair).

The static engine uses this normalization at the correction boundary.  It
still extracts only `corrections` for measurement-map multiplication, so the
legacy ndarray behavior and correction orientation remain unchanged.  Phase 1
and the current fixed-round path do not collect confidence or metrics into a
simulation result.

## Simulation result infrastructure

`SimulationSummary` is the lightweight aggregate result. It stores `shots`,
`logical_errors`, `logical_error_rate`, and optional measured
`runtime_seconds`. `SimulationResult` wraps a summary and provides future
adaptive fields: a list of `AdaptiveStatePrepStats`, metadata, and separate
optional `per_shot` and `debug_data` payloads. The state-preparation record
can later identify a state-preparation event and teleportation index, record
short/long counts and confidence summaries, carry decoder diagnostics, and
store average SE rounds. `AdaptiveBellPairStats` stores the synchronized
pair-level decision, fallback-cause counts (`z_only`, `x_only`, `both`),
effective rounds, and optional risk means. These adaptive fields are empty
for the current fixed-round engine; confidence, decisions, and event
identities are not inferred from static circuits.

The supported detail levels are `summary`, `analysis`, and `debug`. The
current static engine accepts all three labels for API stability but populates
none of the optional per-shot/debug data because it does not retain those
records. No adaptive branch is made at any detail level.

`SimulationResult` exposes `shots`, `samples_performed`, `logical_errors`,
and `logical_error_rate` convenience properties plus `to_legacy_tuple()`.
`SimulationResult.from_legacy(...)` wraps the existing two-count return value
without rerunning a simulation.

Adaptive Knill runs additionally fill `bell_pair_stats` with one
`AdaptiveBellPairStats` per teleportation.  Its `short_count` and `long_count`
are counts of synchronized Bell-pair decisions, so
`long_count == z_only_count + x_only_count + both_count`; the latter three
fields classify which patch first requested extension.  `mean_effective_rounds`
is the measured mean of the selected short/long depth over pair shots.

## Module classes

### `no_measurement_module`

Constructor: `no_measurement_module(circuit, new_support)`.

It requires zero measurements and zero detectors and only contributes a
remapped circuit.  It is used for ideal encoded preparation and transversal
CNOT fragments.

### `measurement_module`

Constructor:
`measurement_module(circuit, c_func, correction_array, new_support=None)`.

`c_func` maps raw local measurements to one bit per entry of
`correction_array`.  It may return a legacy correction ndarray or any of the
structured forms accepted by `normalize_module_decode_output`.  Each
correction entry is `(pauli_string, instruction_offset)`.
For a 1-bit correction, a value of one means that the Pauli correction is
inserted at that local circuit offset; Pauli strings may contain `*`-joined
factors.  `generate_measurement_flip_map` uses a deterministic
`stim.FlipSimulator` to calculate how each correction changes all measurements
and detectors in the complete surrounding circuit.  The resulting
`correction_to_measurement_flips` is stored as a sparse matrix with shape
`(number_of_correction_variables, total_measurements_in_protocol)`.

### `detector_module`

Constructor:
`detector_module(circuit, c_func_generator, new_support, matchable=False)`.

It builds a detector error model, converts it with
`stimbposd.detector_error_model_to_check_matrices`, and creates representative
fault/correction entries from Stim error explanations.  For a non-matchable
DEM, `dem_check_matrix` has shape `(detectors, DEM variables)` and the priors
are used as decoder weights.  For a matchable DEM, the edge check matrix and
hyperedge-to-edge matrix are used, and weights are
`log1p(prior) - log(prior)`.  The detector decoder is expected to provide
`decode_batch`; unlike `css_detector_module`, this class does not include a
fallback to a scalar `decode` method.

`generate_measurement_flip_map` stores correction-to-detector and
correction-to-measurement arrays whose rows index representative corrections.
Its local detector slice is asserted to equal the DEM check matrix transpose.

### `css_detector_module`

Constructor:
`css_detector_module(circuit, decoder_generator, parity_check_tuple,
x_detectors, z_detectors, new_support=[], matchable=True,
confidence_aggregator=None)`.

The X and Z detector lists must be disjoint and together cover every detector.
The constructor splits the circuit into X- and Z-detector circuits, builds
separate DEMs and check matrices, and creates four decoders:

```text
X DEM decoder, Z DEM decoder,
X code-capacity decoder from x_pcm,
Z code-capacity decoder from z_pcm
```

The decoder generator is called with a check matrix and, for DEM decoders,
`weights`.  Objects with `decode_batch` are used directly; otherwise the
implementation wraps a scalar `decode` method in a Python per-shot loop.

For a batch of raw local measurements, `c_func` performs:

```text
raw measurements
 -> separate X/Z measurement-to-detector conversion
 -> X/Z DEM decode
 -> sparse DEM-correction-to-local-measurement updates
 -> take final X and Z stabilizer results
 -> X/Z code-capacity decode
 -> concatenate corrections
```

The returned correction columns are ordered as
`[X DEM variables, Z DEM variables, X-stabilizer repair variables,
Z-stabilizer repair variables]`.  The exact counts are decoder/DEM dependent;
for surface `d=3`, three rounds, the Z-preparation module has 8 X-detectors,
12 Z-detectors, and local DEM check shapes `(8, 21)` and `(12, 41)` in the
matchable configuration.  Its local DEM measurement maps have shapes
`(21, 24)` and `(41, 24)`: rows are decoder variables and columns are local
measurement entries.

`generate_measurement_flip_map` additionally computes full-protocol maps for
DEM and final stabilizer corrections and stores their stacked form as
`correction_to_measurement_flips`.  This attribute is created by the map
generation step, not by the constructor alone.

The legacy `c_func` returns only the correction ndarray. `c_func_rich` runs
the same correction calculation and returns a `ModuleDecodeResult`, retaining
decoder-specific metrics under namespaced keys such as
`x_dem.cluster_llr` and `z_dem.cluster_llr`. When supplied, the optional
`confidence_aggregator` combines the four inner `DecodeResult.confidence`
arrays into the module-level confidence passed to an adaptive policy. The
static engine continues using `c_func` and therefore does not consume these
fields.

### `logical_measurement_module`

Constructor:
`logical_measurement_module(circuit, c_func, c_func_expected_output,
new_support=None)`.

Its `c_func` maps local raw measurements to logical values with shape
`(shots, number_of_expected_logical_values)`.  The static engine compares
these values bitwise with `c_func_expected_output`; any nonzero count in a
shot is later reduced to one logical error.

### `only_postselection_module`

Constructor: `only_postselection_module(circuit, c_func, new_support=None)`.

It is intended to return one postselection bit per shot.  In the current
snapshot its support-remapping method is incomplete and the class is not
used by the bundled Knill or Steane protocol builders.

## Static engine

`modularised_circuit(circuit_modules)` concatenates every module circuit into
one Stim circuit and records logical-measurement modules.  It does not sample
module by module.

`generate_correction_to_measurement_flip_map()` walks all modules, constructs
noise-free circuits before and after each module, and asks measurement/detector
modules to compute their global correction maps.  The map-generation calls
use `stim.FlipSimulator(disable_stabilizer_randomization=True)` because the
maps represent deterministic Pauli propagation, not physical sampling.

`simulate(max_shots, max_errors_before_halting, results_path="", seed=None)` then:

1. compiles a global measurement-to-detector converter and sampler;
2. samples fixed batches of 256 shots from the concatenated circuit;
3. walks through modules, slicing the global measurement and detector arrays;
4. decodes each module, normalizes its output, and applies sparse
   correction-map updates modulo two;
5. evaluates logical measurement modules and postselection flags;
6. asserts that all final detector flips are zero;
7. returns `(samples_performed, total_logical_errors)`.

When provided, `seed` is passed to Stim's compiled sampler. The default
`None` retains the historical entropy-seeded behavior.

The loop stops based on postselected errors and the batch-count condition.  It
can therefore perform a full extra batch beyond `max_shots`.  When
`results_path` is nonempty, cumulative counts are written as JSON after each
batch with keys for total and postselected samples/errors and logical error
rate.

`simulate_result(max_shots, max_errors_before_halting, results_path="",
detail_level="summary", seed=None)` delegates directly to `simulate`, measures wrapper
runtime, and returns a `SimulationResult`. Therefore it uses the same
compiled sampler, 256-shot batching, stopping condition, correction
propagation, detector assertion, and optional JSON output. The legacy
`simulate` method and the protocol functions that call it remain unchanged
and continue to return `(samples_performed, logical_errors)`.

The separate `hex_qec.simulation.StatefulFlipSimulatorBackend` executes the
same fixed module list sequentially, but is not selected by `simulate` and
does not change the static backend.

## Two-level state-preparation descriptions

`AdaptiveSERounds(short_rounds, long_rounds, policy)` is a frozen configuration
with the invariant `1 <= short_rounds <= long_rounds`. `AdaptivePolicy`,
`AlwaysShortPolicy`, and `AlwaysLongPolicy` live in `hex_qec.simulation`.

`generate_adaptive_state_prep_module(...)` and
`generate_adaptive_state_prep_modules(...)` compose separate short and long
`css_detector_module` objects. An `AdaptiveStatePrepModule` exposes
`short_circuit`, `extra_circuit`, and `long_circuit`, plus the corresponding
short/long decoders. The short circuit contains initialization and SE rounds
1 through `short_rounds`; `extra_circuit` is the exact suffix through
`long_rounds`; and `long_circuit` contains the complete history used by the
long decoder. The suffix is checked not to reinitialize data-qubit positions.

`StatefulAdaptiveStatePrepExecutor` executes mixed masks using independent
one-shot `stim.FlipSimulator` states. Short shots stop after the short circuit;
long shots continue their own simulator with the exact extra suffix. The
selected result is per-shot when a batch contains both choices. The full
Knill entry point `knill_online_offline_adaptive(...)` composes these events
for both `|0_L>` and `|+_L>` preparations across multiple teleportations.

## Gadget constructors and call flow

`module_generation.py` provides the protocol-facing builders:

- `generate_logical_measurement_module` builds noisy `M`/`MX` circuits,
  decodes raw measurements against the selected logical/check matrices, and
  returns a `logical_measurement_module`.
- `generate_state_prep_modules` builds one both-detector repeated-SE circuit,
  partitions detector indices by preparation basis and round, constructs one
  `css_detector_module` template, deep-copies it for each support, and returns
  a list of remapped modules.
- `generate_state_prep_module_no_noise` builds a one-round, zero-noise
  measurement module and returns physical X then Z corrections from separate
  code-capacity decodes.
- `generate_transversal_cnot_module` builds a no-measurement module on the
  concatenated first/second block supports.
- `generate_bell_measurement_and_correction_module` builds a 3-block circuit,
  measures the current data and first Bell block in X/Z bases, decodes both,
  and returns logical Pauli-feed-forward bits for the second Bell block.
- `generate_steane_correction_module` measures an ancilla block in one basis,
  decodes its syndrome, and maps the resulting physical corrections onto the
  data block.

Protocol call flow is:

```text
protocol builder
 -> module_generation builders
 -> modularised_circuit
 -> generate_correction_to_measurement_flip_map
 -> static compile/sample/decode loop
```

## Dependencies and known limitations

The layer depends on Stim, NumPy, SciPy sparse matrices, stimbposd, and (for
one gadget) PyMatching.  It now has a common decoder result type and legacy
adapters, but still assumes decoder generators accept the historical
duck-typed calling convention. The original static backend remains fixed-round
and unchanged. Adaptive execution is an unoptimized per-shot reference path
and does not compact branches. Its aggregate result records event statistics;
`detail_level="analysis"` additionally stores confidence, `used_long`, event
identity, basis, teleportation index, postselection, and final logical-error
arrays. Several constructors use
mutable list defaults, support remapping is text-based, and some validation is
done by printing rather than raising.  Stim's converter treats `uint8` input
as bit-packed in this installed version; the current engine's boolean arrays
are the compatible direct input type.
