# AGENTS.md

## Purpose

This file is the primary repository guide for coding agents working on the local `Hex` clone.

The immediate development goal is to extend Hex so that it can simulate **adaptive syndrome-extraction (SE) rounds** during noisy encoded state preparation while preserving the existing fixed-round Knill/Steane workflows and their numerical behavior.

The first adaptive target is deliberately narrow:

- only two state-preparation choices: `short` and `long`;
- run `short` SE first;
- decode the short record and obtain a decoder-specific confidence value;
- accept/commit the short preparation if confidence is sufficient;
- otherwise continue the *same physical shot* with extra SE until the `long` depth and decode the full long history;
- support one or multiple Knill teleportation/QEC rounds;
- keep the legacy fixed-round API functional.

Do not jump directly to a fully general multi-stage adaptive scheduler. Build and validate the infrastructure incrementally.

## Repository snapshot

Upstream repository: https://github.com/ewanmurphy/Hex

- package name: `hex-qec`
- upstream branch inspected: `master`
- upstream HEAD inspected on 2026-08-28: `2a3a309968d0f764510e076a70d0fa1e20d29da7`
- latest upstream commit at that snapshot: `Add Knill paper to README` (2026-04-21)

Before making changes in the local clone, always run:

```bash
git status
git log -10 --oneline --decorate
```

The local clone may contain changes newer than the upstream snapshot recorded above. Treat the local working tree as authoritative and update this file if the project structure or public API changes materially.

## Upstream recent history

Recent upstream changes relevant to understanding the baseline:

- `2a3a309` (2026-04-21): Add Knill paper to README.
- `e66ea09` (2026-04-17): Update README.
- `1e75699` (2026-04-16): Add licence.
- `a840ef5` (2026-04-16): Add missing experiment config files.
- `537064a` (2026-04-16): Add Steane error-correction protocol.
- `0b812c8` (2026-04-16): Add experiment dependencies.
- `c765f90` (2026-04-08): Add control over matchable offline decoding.

These are upstream changes, not the adaptive-SE extension described in this repository documentation.

## Existing package structure

At the inspected upstream snapshot:

```text
Hex/
├── README.md
├── LICENCE
├── pyproject.toml
├── examples/
│   ├── knill_example.py
│   ├── steane_example.py
│   └── experiments/
│       ├── knill_offline_online/
│       └── steane_offline_online/
└── src/
    └── hex_qec/
        ├── __init__.py
        ├── circuit_generation/
        │   ├── __init__.py
        │   ├── circuit_generation.py
        │   └── parity_check_matrices/
        ├── modularisation/
        │   ├── __init__.py
        │   ├── modularised_circuit.py
        │   ├── module_generation.py
        │   └── results.py
        ├── decoders/
        │   ├── __init__.py
        │   ├── base.py
        │   ├── adapters.py
        │   └── DESCRIPTION.md
        ├── protocols/
        │   ├── __init__.py
        │   ├── knill_online_offline.py
        │   └── steane_online_offline.py
        └── simulation/
            ├── __init__.py
            ├── stateful.py
            ├── adaptive.py
            ├── policies.py
            └── DESCRIPTION.md
```

The repository also contains an opt-in top-level `profiling/` package. Its
`adaptive_walltime_profile.py` runner writes small adaptive wall-clock
profiles under `profiling/results/`; it is intentionally outside the normal
pytest path and does not replace or optimize the simulation backend.

### `circuit_generation`

Main low-level circuit/code utilities. Current responsibilities include:

- loading parity-check and logical-operator data;
- creating CSS-code block layouts;
- generating data/ancilla block supports;
- noiseless encoded-state preparation;
- noisy repeated stabilizer-measurement circuits;
- transversal Clifford components and basic measurement primitives.

The package currently expects CSS-style code data, usually passed as:

```python
(x_pcm, z_pcm, x_logical, z_logical)
```

In the current local implementation these are normally SciPy sparse matrices
loaded by `scipy.io.mmread` (the checked-in Matrix Market files load as COO
matrices), with shape `(number_of_checks, number_of_data_qubits)` for the two
parity-check matrices and `(number_of_logical_operators, number_of_data_qubits)`
for the two logical-operator matrices.  The public package import exposes the
main loader and two circuit builders; additional helpers are imported into the
module but are not all listed in `circuit_generation.__all__`.

Do not change the mathematical meaning or ordering of this tuple without a repository-wide migration.

### `modularisation/modularised_circuit.py`

This is the current core execution/modularization layer.

Existing module types include:

- `no_measurement_module`
- `measurement_module`
- `detector_module`
- `css_detector_module`
- `logical_measurement_module`
- `only_postselection_module`
- `modularised_circuit`

Current static simulation semantics:

1. concatenate all module circuits into one Stim circuit;
2. sample the full physical circuit with `compile_sampler()`;
3. walk through modules in order;
4. decode module-local measurements/detectors;
5. convert inferred corrections into updates of future measurement records using precomputed correction-to-measurement-flip maps;
6. evaluate final logical measurements.

Important: the existing static engine samples the entire circuit before any adaptive decision is made.

### `modularisation/module_generation.py`

Helper constructors for reusable gadgets. Important current helpers include:

- `generate_logical_measurement_module(...)`
- `generate_state_prep_modules(...)`
- `generate_state_prep_module_no_noise(...)`
- `generate_transversal_cnot_module(...)`
- `generate_bell_measurement_and_correction_module(...)`
- `generate_steane_correction_module(...)`

Prefer extending this layer with new adaptive-state-preparation builders instead of duplicating protocol construction logic inside experiment scripts.

### `protocols/knill_online_offline.py`

Builds the Knill protocol as a sequence of modules. For each teleportation/QEC step the high-level structure is:

```text
noisy |0_L> state preparation
noisy |+_L> state preparation
transversal CNOT to make encoded Bell pair
Bell measurement + logical feed-forward correction
```

The initial data block is prepared ideally. The final output block is measured logically. The current code already supports `num_teleportations > 1`.

Adaptive SE should therefore be integrated primarily by replacing/wrapping the offline state-preparation modules and by adding a stateful execution backend; the Bell-measurement and final logical-measurement semantics should not be rewritten unless tests show this is necessary.

### `examples`

Contains end-user scripts and experiment configuration. At the current snapshot decoder selection is performed by local decoder-generator callables, e.g. PyMatching, BP, or BP-OSD. This is duck-typed rather than implemented through a formal Hex decoder base class.

## Current dependencies

From the inspected `pyproject.toml`:

```text
numpy>=1.26
scipy>=1.11
stim>=1.13
stimbposd>=0.1.0
ldpc>=2,<3
pymatching>2.0
```

Optional experiment dependencies include:

- `pandas>=2.0`
- https://github.com/ewanmurphy/Experiments
- https://github.com/ewanmurphy/plotting_lib

Do not add a new required dependency unless it is needed by the core library. Record any added external package and URL in `PLAN.md`, and update `pyproject.toml` only after deciding whether it is a core or optional dependency.

## Important current decoder semantics

The existing Hex code uses `decoder_generator` callables. A generator is given a parity/check matrix (and sometimes weights) and returns an object that is expected to provide either `decode_batch(...)` or `decode(...)`.

`css_detector_module` internally creates:

- X-DEM decoder;
- Z-DEM decoder;
- X code-capacity decoder;
- Z code-capacity decoder.

The current abstraction is therefore functional/duck-typed, not a formal Hex decoder API.

### Notebook confidence-selection policy

The surface-code adaptive benchmarking notebook intentionally exposes only
`max_dem_only` as a selectable confidence aggregator.  It uses the repeated
syndrome-extraction DEM confidence (`x_dem`/`z_dem`) for adaptive stopping.
`max_all_components` remains implemented internally for future post-selection
work involving code-capacity confidence, but it must not be reintroduced as a
notebook benchmark choice until that confidence is calibrated.  Notebook code
that attempts to select `max_all_components` should raise `AssertionError`.

Phase 1 now provides a common result object and protocol/adapters so that a decoder can return:

- correction;
- confidence;
- convergence information;
- decoder-specific auxiliary metrics.

The legacy module callbacks still unwrap this result to correction arrays in
the static engine.  Phase 2 now provides `SimulationSummary` and
`SimulationResult` through `modularised_circuit.simulate_result(...)`; the
legacy `simulate(...)` tuple and protocol workflows remain unchanged.
Fixed-round runs populate aggregate counts/LER/runtime and metadata only.
Adaptive runs can additionally populate event statistics, confidence/decision
fields, decoder diagnostics, and optional per-shot/debug records.

The two-level state-preparation layer now defines `AdaptiveSERounds`,
`AdaptiveStatePrepModule`, `AdaptivePolicy`, `AlwaysShortPolicy`,
`AlwaysLongPolicy`, and the example `ClusterLLRPolicy`.  Its stateful
executor supports per-shot short/long masks by continuing low-confidence
shots on their existing `FlipSimulator` states.  Confidence direction and
metric selection are policy responsibilities; the simulator consumes only
`DecodeResult.confidence`.

The adaptive Knill executor synchronizes the adjacent `|0_L>` and `|+_L>`
events for each teleportation: both short records are decoded first, and an
extension requested by either patch sends both patches through their own
same-shot extra suffix. `SimulationResult.bell_pair_stats` records the
pair-level fallback and `z_only`/`x_only`/`both` diagnostic partition, while
analysis per-shot data retain patch confidence and would-extend values.

The fixed and adaptive Knill entry points accept `surface_code=False`; when
true it is propagated to every state-preparation builder and selects the
surface-code-specific stabilizer interaction ordering. The default remains
the historical ordering. The fixed Knill entry point also accepts an optional
`seed`, passed to Stim's compiled sampler; `None` preserves historical
entropy-seeded behavior.

Do not force third-party decoder classes to inherit from a Hex class. Use adapters/protocols/factories where possible.

## Important current state-preparation decoding semantics

`css_detector_module` already performs the key state-preparation logic that must be preserved:

```text
raw local measurement record
    ↓
measurement-to-detector conversion
    ↓
X/Z detector decoding
    ↓
estimated DEM corrections
    ↓
correct the local measurement history
    ↓
extract final X/Z stabilizer signs
    ↓
code-capacity decode final stabilizer signs
    ↓
produce repair corrections
```

The module contains local mappings of the form:

```text
DEM correction variables → local measurement flips
```

These are important and should be reused.

For adaptive long decoding, the decoder must use the **full record from round 1 through the long round**. Do not decode the extra rounds as an independent standalone experiment.

## Physical state versus software correction

Keep these concepts separate.

### Physical simulation state

Represents faults and intrinsic measurement/stabilizer randomness actually sampled from the physical circuit.

The Phase 3 stateful fixed-round backend uses `stim.FlipSimulator`, with
stabilizer randomization enabled for actual physical sampling.  It reconstructs
Hex records from `Circuit.reference_sample()` and
`get_measurement_flips()`, then keeps decoder/software corrections separate
from the physical simulator state.  It does not make adaptive decisions.

### Software/decoder state

Represents inferred corrections and repair-frame interpretation. The existing Hex implementation propagates these corrections as changes to future measurement records. Preserve this semantic distinction.

Never apply the same decoder correction both physically into the stateful `FlipSimulator` and through Hex's software correction propagation unless one of those paths has explicitly been removed. Otherwise the correction is double-counted.

## Why `FlipSimulator` is required for adaptive SE

Using two independently compiled static circuits with the same random seed does **not** guarantee that their common circuit prefix has the same sampled faults.

Adaptive simulation requires the low-confidence long branch to continue the *same physical shot* that produced the short record.

The stateful design therefore uses:

```python
sim.do(short_circuit)
```

followed by a confidence decision and, for the long branch, continuation from the same simulator state (or an exact copy of it):

```python
long_sim = sim.copy(...)
long_sim.do(extra_se_circuit)
```

This is a core correctness requirement.

## Adaptive scope for the first implementation

Implement only:

```text
short SE depth
    ↓
short decode + confidence
    ↓
high confidence ──→ stop at short
low confidence  ──→ continue to long
```

Definitions:

- `short_rounds`: small fixed number, usually `O(1)`;
- `long_rounds`: larger number, initially typically `d` or a fixed function of code distance;
- `extra_rounds = long_rounds - short_rounds`;
- long decoding sees all `long_rounds` measurement history.

The current implementation requires `1 <= short_rounds < long_rounds` and
rejects equal-depth schedules before adaptive circuit construction.

Do not implement arbitrary repeated decisions (`r1 -> r2 -> r3 -> ...`) until the two-level implementation has passed compatibility and correctness tests.

## Planned architectural additions

The exact filenames can change after inspecting the local clone, but the
intended separation of responsibilities is:

```text
src/hex_qec/
├── decoders/
│   ├── base.py
│   └── adapters.py
├── simulation/
│   ├── stateful.py
│   ├── results.py
│   └── policies.py
└── modularisation/
    └── adaptive_state_prep.py
```

Do not create these directories blindly. First inspect the local repository and choose names consistent with existing style. The architectural boundaries are more important than the exact paths.

Phases 4 and 5 add `simulation/policies.py`, `simulation/adaptive.py`, and
`modularisation/adaptive_state_prep.py` for two-level state preparation and
confidence-driven short/long execution.  Result classes remain in
`modularisation/results.py`.  The adaptive path is a correctness-first,
one-shot reference implementation and is separate from the legacy static
backend. Pair execution uses a physical order of Z-short, X-short, Z-extra,
X-extra and translates that record into logical Z/X decoder order.

## Result-data design principles

The current static engine still returns `samples_performed` and
`logical_errors`; `simulate_result(...)` additionally wraps those counts in a
`SimulationResult`. This is the aggregate foundation for adaptive
experiments.

Phase 3 also provides `hex_qec.simulation.StatefulFlipSimulatorBackend` for
fixed-round module-by-module execution.  The static compiled backend remains
the default protocol path.

The extension must eventually support:

- total shots and LER;
- per-state-preparation event identity;
- Knill teleportation/QEC round index;
- logical basis / prepared state;
- short/long round counts;
- confidence metric name and value;
- short/long decision;
- fallback/switch rate;
- decoder convergence/failure flags;
- optional decoder-specific metrics;
- effective average SE rounds;
- final logical-error label;
- optional shot-level tracing for debugging.

Do not store full raw measurement histories for every shot by default. Use configurable result detail levels.

## Compatibility requirements

The adaptive extension must preserve existing behavior.

Required compatibility targets:

1. existing fixed-round Knill examples continue to run;
2. existing Steane examples continue to run;
3. existing third-party decoder-generator callables remain usable;
4. fixed-round static simulation remains available;
5. new result objects may wrap legacy return values, but do not silently break existing callers;
6. no change to the physical noise model unless explicitly requested;
7. no change to X/Z detector conventions or correction orientation without dedicated tests.

A recommended public API pattern is:

```python
state_prep_rounds = distance
```

for legacy fixed-round use, and an object such as:

```python
AdaptiveSERounds(
    short_rounds=...,
    long_rounds=...,
    policy=...,
)
```

for adaptive use.

Avoid adding many unrelated top-level keyword arguments such as `adaptive=True`, `short_rounds=`, `long_rounds=`, `threshold=`, etc. Prefer configuration objects.

## Implementation discipline for coding agents

Before editing:

1. read `AGENTS.md`;
2. read `STATUS.md` if it exists;
3. read `PLAN.md`;
4. read `TEST.md` if it exists;
5. inspect the relevant module's `DESCRIPTION.md` if present;
6. run `git status`;
7. identify the smallest implementation step currently requested.

After editing:

1. run the narrowest unit tests first;
2. run compatibility tests;
3. update `TEST.md` with what was actually run and the outcome;
4. update `STATUS.md` with completed work, open issues, and next action;
5. update module `DESCRIPTION.md` if API/semantics changed;
6. update `AGENTS.md` if repository structure or global conventions changed.

Do not claim a test passed unless it was actually run.

## Validation strategy

Do not validate adaptive logic first.

Validation order:

1. establish baseline fixed-round outputs with the original static engine;
2. implement new decoder/result interfaces without changing numerical behavior;
3. implement the stateful `FlipSimulator` backend for a fixed-round circuit;
4. show statistical agreement between static and stateful fixed-round simulations;
5. implement forced-short adaptive policy and reproduce the fixed-short result;
6. implement forced-long adaptive policy and reproduce the fixed-long result;
7. only then enable confidence-based switching;
8. then test multiple Knill teleportations.

This staged validation is mandatory because the adaptive result is otherwise difficult to interpret.

## Numerical/statistical comparison

Monte Carlo results from two stochastic implementations should not be compared by exact equality unless the same physical realization is intentionally replayed.

For LER comparisons use confidence intervals or an agreed tolerance based on shot count.

For deterministic internal maps, use exact GF(2) equality.

Examples of deterministic quantities that should match exactly:

- detector check-matrix dimensions;
- correction-to-local-measurement maps;
- X/Z correction orientation;
- measurement-record slicing;
- noiseless expected logical values.

## Code-style guidance

For new infrastructure:

- use type hints;
- use `dataclass` for structured return values/configuration;
- keep decoder, policy, simulator, and result concerns separate;
- keep GF(2) shapes documented explicitly;
- assert dimensions at API boundaries;
- avoid converting large sparse matrices to dense arrays unnecessarily;
- preserve batch decoding;
- avoid per-shot Python loops in performance-critical code unless implementing a temporary reference path;
- write comments about semantic meaning, not obvious syntax.

When a matrix is introduced, document the axis convention. Example:

```text
shape = (num_decoder_variables, num_measurements)
row j = correction/fault variable j
column k = local measurement record entry k
```

## Important references

Hex:

- https://github.com/ewanmurphy/Hex
- https://github.com/ewanmurphy/Hex/blob/master/README.md

Stim:

- https://github.com/quantumlib/Stim
- https://github.com/quantumlib/Stim/wiki/Stim-v1.13-Python-API-Reference
- https://github.com/quantumlib/Stim/blob/main/src/stim/simulators/frame_simulator.pybind.cc

Knill/Hex paper named by the upstream README:

- “Simplified circuit-level decoding using Knill error correction”
- https://arxiv.org/abs/2603.05320

Theory and research-specific references should be maintained in `THEORY.md`.

## Documentation files expected in this development branch

```text
AGENTS.md
PLAN.md
FUTURE.md
STATUS.md
TEST.md
THEORY.md
<module>/DESCRIPTION.md
```

Meanings:

- `AGENTS.md`: repository-wide map, conventions, agent instructions;
- `PLAN.md`: detailed implementation plan for the current objective;
- `FUTURE.md`: broader later work after the current plan;
- `STATUS.md`: latest implementation checkpoint, open problems, next task;
- `TEST.md`: chronological record of tests actually executed;
- `THEORY.md`: mathematical/physical assumptions and literature;
- `DESCRIPTION.md`: detailed documentation local to a package/module.

The present task creates `AGENTS.md`, `PLAN.md`, and `FUTURE.md`. The remaining documents should be added before or during implementation as specified in `PLAN.md`.

## Local Phase 0 facts

The local branch was checked on 2026-08-28.  Its Phase 0 `HEAD` was
`2a3a309968d0f764510e076a70d0fa1e20d29da7`, matching the upstream snapshot
recorded above.  Subsequent Phase 1–3 source changes are now present in
commits `03d512c`, `cc26813`, and `762a9f1`; the synchronized-pair,
surface-code, BP-LSD validation, notebook, and documentation changes remain
local working-tree changes. The source
checkout is not installed as a `hex-qec` distribution in the baseline Python
environment, so source-level smoke tests use `PYTHONPATH=src`.  The checked-in
package requires `stimbposd`, which was initially absent from that environment
and was installed for baseline testing; the observed installed versions are
Stim 1.15.0, PyMatching 2.3.1, stimbposd 0.2.0, and ldpc 2.1.2.

## Optional parallel simulation package

`src/hex_qec/parallel/` contains the generic spawn-based manager, persistent
workers, leases, chunk controller, checkpoint store, and aggregate result
types. It remains independent of QEC-specific imports. Adaptive Knill
construction is adapted in `protocols/parallel_adapters.py`; the public
adaptive function uses this path only when `parallel_options` is non-`None`.
The default `parallel_options=None` path remains the existing serial adaptive
executor. Parallel adaptive results are summary-only, and factories must be
pickleable under `spawn`.
