# PLAN.md

## Goal

Extend the local Hex clone with a **stateful, confidence-aware, two-level adaptive syndrome-extraction simulator** for noisy encoded state preparation used inside Knill error correction.

The first target protocol is:

```text
prepare encoded ancilla
    ↓
measure `short_rounds` SE rounds
    ↓
decode short history
    ↓
obtain decoder confidence
    ↓
confidence sufficient?
    ├── yes: finish state preparation at `short_rounds`
    └── no: continue the SAME physical shot
            with extra SE rounds until `long_rounds`
            ↓
            decode full rounds 1..long_rounds
```

This must work for both Bell-state ancilla halves (`|0_L>` and `|+_L>`) and for one or multiple Knill teleportation/QEC rounds.

The implementation must preserve the current fixed-round Hex interface and numerical behavior.

## Non-goals of the first implementation

Do not initially implement:

- arbitrary multi-stage schedules such as `r1 -> r2 -> r3 -> ...`;
- online decoder-latency models;
- hardware control latency;
- arbitrary circuit-level dynamic classical feedback;
- confidence calibration/learning;
- optimized branch compaction;
- correlated/global algorithmic-FT decoding;
- new physical noise models.

The first objective is correctness and compatibility.

# Phase 0 — Freeze and document the baseline

Before changing core code, characterize the local clone.

## 0.1 Record repository state

Run and record in `STATUS.md`:

```bash
git status
git rev-parse HEAD
git log -10 --oneline --decorate
python --version
pip show hex-qec stim pymatching stimbposd ldpc
```

If the local clone differs from upstream commit `2a3a309968d0f764510e076a70d0fa1e20d29da7`, update `AGENTS.md` with the local facts.

## 0.2 Add documentation skeleton

Create:

```text
STATUS.md
TEST.md
THEORY.md
```

and one `DESCRIPTION.md` per major source package/module.

Suggested locations:

```text
src/hex_qec/circuit_generation/DESCRIPTION.md
src/hex_qec/modularisation/DESCRIPTION.md
src/hex_qec/protocols/DESCRIPTION.md
```

If new `decoders/` or `simulation/` packages are created, add corresponding `DESCRIPTION.md`.

## 0.3 Baseline tests

Run the unmodified existing Knill fixed-round experiment for a small configuration, for example:

```text
surface code
d = 3
state-prep rounds = d
num_teleportations = 1
small shot count suitable for a smoke test
```

Record:

- command;
- package versions;
- shots;
- logical errors;
- runtime;
- random seed if supported.

Also run a small `num_teleportations = 2` case.

The purpose is not a high-precision LER estimate; it is to have compatibility checkpoints.

# Phase 1 — Formalize decoder outputs without changing behavior

## Motivation

Current Hex uses decoder-generator callables and duck typing. A decoder returns correction arrays only.

Adaptive state preparation requires decoder-specific confidence and diagnostic information.

Do not replace third-party decoders. Add an adapter layer.

## 1.1 Define a common decoder result

Introduce a dataclass conceptually equivalent to:

```python
@dataclass
class DecodeResult:
    correction: np.ndarray
    confidence: np.ndarray | None = None
    converged: np.ndarray | None = None
    metrics: dict[str, np.ndarray] = field(default_factory=dict)
```

Required semantics:

- first axis is batch/shot;
- `correction[i]` is the decoder correction for shot `i`;
- `confidence[i]` is a scalar primary confidence if the adapter defines one;
- `metrics` contains decoder-specific values without forcing all decoders to use the same notion of confidence;
- `converged` is optional and does not automatically imply accept/reject.

Do not encode the adaptive threshold into the decoder.

## 1.2 Define decoder interface/factory

Use a `Protocol`, ABC, or light adapter pattern.

Desired behavior:

```python
decoder = decoder_factory.create(check_matrix, weights=...)
result = decoder.decode_batch(syndromes)
```

or an equivalent API.

Compatibility requirement: existing callables such as

```python
pymatching.Matching.from_check_matrix
generate_bp_decoder
generate_bposd_decoder
```

must remain usable via a legacy adapter.

## 1.3 Separate confidence from policy

Add a separate policy abstraction:

```python
class AdaptivePolicy(Protocol):
    def should_extend(
        self,
        decode_result: DecodeResult,
        *,
        context: ...,
    ) -> np.ndarray:
        ...
```

For the first implementation use a threshold policy.

Example:

```python
GapThresholdPolicy(threshold=t, extend_if_below=True)
```

The policy must return a boolean mask over shots.

A decoder can produce logical/complementary gap, forced gap, anchored gap, BP-based confidence, or another metric. The simulator should not need to know which one it is.

## 1.4 Formalize module decoding return values

Current `c_func` may return:

```python
corrections
```

or:

```python
(corrections, postselection_mask)
```

Introduce a structured result, for example:

```python
@dataclass
class ModuleDecodeResult:
    corrections: np.ndarray
    postselection: np.ndarray | None = None
    decode_result: DecodeResult | None = None
    metrics: dict[str, np.ndarray] = field(default_factory=dict)
```

Add a normalization helper that accepts all legacy return types. This allows the core engine to migrate incrementally.

## 1.5 Tests

Before moving on:

- legacy PyMatching fixed-round Knill output runs;
- BP/BP-OSD adapters run if installed;
- decoder adapter correction exactly equals legacy correction for deterministic input syndromes;
- `confidence=None` is handled without failure;
- module output normalization accepts old and new formats.

Record all tests in `TEST.md`.

# Phase 2 — Introduce result classes before adaptive behavior

## Motivation

Adaptive experiments require far more information than the current `(samples_performed, logical_errors)` tuple.

Introduce result infrastructure before adaptive switching so later changes are observable.

## 2.1 Suggested result hierarchy

A minimal design:

```python
@dataclass
class SimulationSummary:
    shots: int
    logical_errors: int
    logical_error_rate: float
    runtime_seconds: float | None = None

@dataclass
class AdaptiveStatePrepStats:
    event_id: str
    teleportation_index: int
    state_basis: str
    short_rounds: int
    long_rounds: int
    short_count: int
    long_count: int
    fallback_rate: float
    confidence_metric: str | None
    confidence_summary: dict[str, float]

@dataclass
class SimulationResult:
    summary: SimulationSummary
    state_prep_stats: list[AdaptiveStatePrepStats]
    metadata: dict[str, Any]
    per_shot: dict[str, np.ndarray] | None = None
```

Exact names can differ.

## 2.2 Detail levels

Support at least:

```text
summary
analysis
debug
```

Suggested semantics:

- `summary`: aggregate counts and LER only;
- `analysis`: retain lightweight per-shot fields such as confidence, short/long decision, final logical-error bit;
- `debug`: optionally retain records needed for tracing individual failures.

Do not store full measurement history at `summary` or `analysis` level.

## 2.3 Backward compatibility

Legacy callers should still be able to obtain:

```python
samples_performed, logical_errors
```

Possible options:

- keep legacy `simulate(...)`;
- add `simulate_result(...)`;
- or add an explicit compatibility flag.

Prefer the least disruptive option after inspecting call sites.

## 2.4 Tests

Check that fixed-round simulations produce both the new result object and legacy-compatible values.

# Phase 3 — Build a stateful FlipSimulator sampling backend for fixed circuits

Do **not** add adaptive behavior yet.

The goal is to reproduce the existing fixed-round Knill experiment using module-by-module stateful physical simulation.

## 3.1 Backend abstraction

Separate the execution engine from circuit/module definitions.

A possible interface:

```python
class SimulationBackend(Protocol):
    def run(...):
        ...
```

Implement conceptually:

```text
StaticCompiledBackend   # current behavior
StatefulFlipBackend     # new behavior
```

Do not remove the static backend.

## 3.2 Stateful physical simulator

Use `stim.FlipSimulator` to execute noisy circuit chunks sequentially.

Physical sampling must preserve intrinsic stabilizer/measurement randomness. Do not disable stabilizer randomization for the actual physical simulation.

References:

- https://github.com/quantumlib/Stim
- https://github.com/quantumlib/Stim/blob/main/src/stim/simulators/frame_simulator.pybind.cc

## 3.3 Raw measurement reconstruction

`FlipSimulator.get_measurement_flips()` returns measurement flips relative to a reference trajectory, not automatically the same user-facing record as `Circuit.compile_sampler().sample()`.

Implement one well-tested conversion layer that returns Hex-format raw measurement records.

Conceptually:

```text
raw measurement
    = reference measurement
      XOR physical measurement flip
```

Do not scatter reference-XOR logic throughout modules.

Determine and document the exact Stim API used for reference records in the local installed Stim version.

Write a direct test comparing measurement distributions produced by `compile_sampler()` and the new stateful conversion for the same fixed circuit.

Exact shot-by-shot equality is not required unless the same RNG path is intentionally used; distribution and deterministic cases must agree.

## 3.4 Preserve existing local decoding

Once a module-local raw measurement array has been reconstructed, continue to use existing Hex logic:

```text
measurement-to-detector converter
X/Z DEM decode
correction-to-local-measurement map
final stabilizer-sign extraction
code-capacity repair decode
```

Do not rewrite this algorithm in Phase 3.

## 3.5 Software correction propagation

Initially preserve the existing Hex correction semantics.

If the static global `correction_to_measurement_flips` mechanism cannot be used with module-by-module execution, introduce a local/stateful software-frame representation, but do so only after writing a failing compatibility test that demonstrates the need.

Preferred long-term invariant:

```text
physical FlipSimulator state != decoder/software frame
```

Never double-count a correction.

## 3.6 Fixed-round compatibility tests

For at least:

```text
d = 3, 5
num_teleportations = 1
num_teleportations = 2
r = d
```

compare static versus stateful:

- detector/measurement dimensions;
- final logical measurement convention;
- LER within statistical uncertainty;
- no unexpected detector inconsistency;
- X and Z logical preparations separately if feasible.

Only after these pass should adaptive branching be implemented.

# Phase 4 — Refactor state preparation into short and long descriptions

Still do not make the decision adaptive at first.

## 4.1 Configuration

Add a schedule/config object conceptually like:

```python
@dataclass(frozen=True)
class AdaptiveSERounds:
    short_rounds: int
    long_rounds: int
    policy: AdaptivePolicy
```

Validate:

```text
1 <= short_rounds <= long_rounds
```

For the first implementation `short_rounds < long_rounds` should be the normal adaptive case.

Legacy use remains:

```python
state_prep_rounds = distance
```

## 4.2 State-prep circuit decomposition

An adaptive state-prep description must expose:

```text
short circuit:
    initialization + rounds 1..short

extra circuit:
    rounds short+1..long

full long decoding circuit:
    initialization + rounds 1..long
```

Critical requirement: the extra circuit must continue the same data state; it must not reinitialize the encoded data block.

The long decoder must be constructed from the full long circuit so that temporal detectors spanning the short/extra boundary are included.

## 4.3 Reuse `css_detector_module`

Prefer composition:

```python
AdaptiveStatePrepModule(
    short_module=css_detector_module(...short...),
    long_module=css_detector_module(...long...),
    extra_circuit=...,
)
```

rather than embedding confidence logic directly into `css_detector_module`.

This keeps ordinary state preparation unchanged.

## 4.4 Forced policies

Implement two diagnostic policies before real confidence:

```text
AlwaysShortPolicy
AlwaysLongPolicy
```

Use these to test the adaptive execution path.

Expected invariants:

- AlwaysShort = fixed short-round simulation.
- AlwaysLong = fixed long-round simulation.

These are the strongest early correctness tests.

# Phase 5 — Implement two-level shot-wise adaptive branching

Now enable the actual decision.

## 5.1 Physical-prefix requirement

For every shot, `initialization + short SE` must be sampled once.

The low-confidence long branch must continue exactly that physical realization.

Do not attempt to synchronize independently sampled short and long circuits by seed.

Use an exact simulator state copy or another state-preserving mechanism.

## 5.2 Short decision flow

For each adaptive state-prep event:

1. execute short noisy circuit;
2. collect local raw short record;
3. short decode;
4. obtain `DecodeResult`;
5. compute `extend_mask = policy.should_extend(...)`;
6. store confidence/switch statistics in the result recorder.

Do not immediately commit a short correction for shots in `extend_mask`.

## 5.3 Long continuation

For low-confidence shots:

1. continue the same physical simulator state with extra noisy SE rounds;
2. reconstruct the full measurement history from round 1 through `long_rounds`;
3. decode with the long module/DEM;
4. commit only the long result for those shots.

High-confidence shots commit/use the short result.

## 5.4 Branch representation

The simplest correct reference implementation may represent execution as branches:

```python
@dataclass
class ExecutionBranch:
    active_mask: np.ndarray
    physical_sim: stim.FlipSimulator
    software_state: Any
    metadata: dict[str, Any]
```

After a short/long decision:

```text
branch
├── high-confidence branch
└── low-confidence branch
```

Prune empty branches.

This is acceptable for the initial two-level implementation. Do not optimize branch merging before correctness is established.

## 5.5 Branch-specific measurement records

Do not assume all shots have the same global measurement cursor once branches diverge.

Store measurement records locally per module/branch or introduce explicit record buffers.

Future detectors should not accidentally index measurements from another branch.

Document any assumption that module boundaries do not use cross-module `rec[...]` references.

## 5.6 Correction commit

Explicitly define what “commit” means in the new engine.

At minimum, the correction selected for the accepted state-prep branch must affect all later measurements exactly once.

Possible implementation mechanisms:

- existing correction-to-future-measurement maps;
- a stateful software Pauli-frame simulator;
- a module-end Pauli-frame representation.

Choose one after Phase 3 compatibility work.

Whichever mechanism is used, document it in `modularisation/DESCRIPTION.md`.

# Phase 6 — Multiple adaptive state preparations and multiple Knill rounds

The existing protocol already supports multiple teleportations, but adaptive branching changes execution.

## 6.1 Required functional coverage

Support `num_teleportations >= 1` and, for each teleportation, adaptive preparation of both:

```text
|0_L> Bell half
|+_L> Bell half
```

Each state-preparation event has its own confidence, short/long decision, and result record.

## 6.2 Event identifiers

Use stable identifiers, for example:

```text
teleportation=0,state=z
teleportation=0,state=x
teleportation=1,state=z
teleportation=1,state=x
```

Do not infer event identity from list position during analysis.

## 6.3 Branch growth

Two adaptive preparations per Knill teleportation can create several branch combinations.

Initial implementation may keep explicit branches for correctness.

Record in profiling:

- number of live branches;
- number of active shots per branch;
- runtime and memory.

Branch-compaction/merging is a future optimization and belongs in `FUTURE.md`.

# Phase 7 — Confidence-aware experiment API

After the stateful adaptive path is validated, expose a clean protocol API.

A target style:

```python
schedule = AdaptiveSERounds(
    short_rounds=2,
    long_rounds=distance,
    policy=GapThresholdPolicy(threshold=threshold),
)

result = knill_online_offline(
    parity_check_tuple=...,
    state_prep_rounds=schedule,
    online_decoder_generator=...,
    offline_decoder_generator=...,
    ...
)
```

Legacy:

```python
state_prep_rounds=distance
```

must remain valid.

If the existing positional API makes this unsafe, add a new keyword while preserving the old positional signature.

# Phase 8 — Detailed analysis outputs

Once correctness is established, expose the statistics required for research.

## 8.1 Required aggregate outputs

At minimum:

```text
total shots
logical errors
LER
short selections
long selections
fallback/switch rate
mean effective SE rounds
```

For two-level adaptive preparation:

\[
E[r] = r_{\rm short}P(\text{short}) + r_{\rm long}P(\text{long}).
\]

If the two Bell halves are counted separately, also report per-preparation and per-Knill-round averages.

## 8.2 Confidence statistics

Record enough information to later plot:

- confidence histogram;
- confidence-conditioned LER;
- fallback probability versus threshold;
- average rounds versus threshold;
- LER versus average rounds;
- decoder convergence versus confidence;
- confidence distribution conditioned on logical success/failure.

Do not hard-code one metric name.

Use metadata such as:

```python
confidence_metric="complementary_gap"
```

or:

```python
metrics={
    "forced_gap": ...,
    "anchored_gap": ...,
}
```

## 8.3 Optional per-shot data

For analysis mode retain lightweight arrays such as:

```text
shot_id
event_id
confidence
used_long
decoder_converged
final_logical_error
```

This enables post-hoc threshold sweeps.

Avoid storing full sparse decoder internals unless debug mode is enabled.

# Phase 9 — Regression and scientific validation

## 9.1 Fixed-round regression

Run the same parameter sweep used before the adaptive work.

Required check: new fixed-round path reproduces the original Hex behavior within statistical uncertainty.

## 9.2 Adaptive endpoint checks

For a fixed `(d, p)`:

```text
policy = always short
```

must reproduce the fixed short-depth experiment.

```text
policy = always long
```

must reproduce the fixed long-depth experiment.

## 9.3 Zero-noise checks

At `p = 0`:

- no logical errors;
- correction conventions consistent;
- adaptive result independent of irrelevant stochastic noise;
- confidence behavior is documented rather than assumed.

## 9.4 Small deterministic fault tests

Construct small circuits with controlled fault probabilities such as `0` or `1` where possible.

Use them to verify:

- measurement flip reconstruction;
- temporal detector across short/extra boundary;
- short versus long record slicing;
- correction orientation;
- correction propagation through transversal CNOT.

## 9.5 Multiple teleportations

Run at least one smoke test with `num_teleportations = 2` before large simulations.

# Proposed file-level implementation map

This is a recommendation, not a requirement.

After inspecting the local tree, a clean layout would be:

```text
src/hex_qec/
├── decoders/
│   ├── __init__.py
│   ├── base.py
│   ├── adapters.py
│   └── DESCRIPTION.md
├── simulation/
│   ├── __init__.py
│   ├── backend.py
│   ├── stateful.py
│   ├── policies.py
│   ├── results.py
│   └── DESCRIPTION.md
├── modularisation/
│   ├── modularised_circuit.py
│   ├── module_generation.py
│   ├── adaptive_state_prep.py
│   └── DESCRIPTION.md
└── protocols/
    ├── knill_online_offline.py
    └── DESCRIPTION.md
```

A more conservative alternative is to keep new files under `modularisation/` initially.

Choose the structure that minimizes circular imports and core-file churn.

# External references and packages

No additional required dependency is currently planned.

Core existing packages:

- Hex: https://github.com/ewanmurphy/Hex
- Stim: https://github.com/quantumlib/Stim
- PyMatching: https://github.com/oscarhiggott/PyMatching
- stimbposd: https://github.com/quantumgizmos/stimbposd
- LDPC: https://github.com/quantumgizmos/ldpc

Stim references relevant to the stateful backend:

- API reference: https://github.com/quantumlib/Stim/wiki/Stim-v1.13-Python-API-Reference
- FlipSimulator implementation: https://github.com/quantumlib/Stim/blob/main/src/stim/simulators/frame_simulator.pybind.cc

Hex/Knill reference named in the upstream README:

- https://arxiv.org/abs/2603.05320

If a new decoder package such as `lomatching`, `surface_sim`, Relay-BP code, or another external confidence implementation is added later, record:

- repository URL;
- pinned commit/tag;
- license;
- adapter file;
- expected correction/confidence semantics.

Do not make those packages core dependencies until the base adaptive infrastructure works with existing PyMatching/BP adapters.

# Documentation maintenance during implementation

`STATUS.md` must be updated at the end of each implementation session with:

```text
current branch/commit
completed work
files changed
tests run
known failures
open design questions
next concrete task
```

`TEST.md` must contain only tests actually run.

Each package-level `DESCRIPTION.md` should document:

- public classes/functions;
- important private helpers;
- inputs and outputs;
- array/matrix shapes;
- correction semantics;
- dependencies;
- call graph;
- invariants;
- known limitations.

`THEORY.md` should document the QEC interpretation and equations, not software implementation details.

# Definition of done for the first adaptive implementation

The first milestone is complete when all of the following hold:

1. existing fixed-round Knill simulation still runs;
2. existing fixed-round Steane simulation still runs;
3. stateful FlipSimulator backend reproduces fixed-round Knill results;
4. decoder outputs can carry confidence without breaking legacy decoders;
5. result objects record adaptive statistics;
6. two-level short/long state-prep execution is implemented shot-wise;
7. low-confidence long continuation uses the same physical prefix state;
8. long decoding uses the complete long syndrome history;
9. AlwaysShort reproduces fixed-short;
10. AlwaysLong reproduces fixed-long;
11. confidence-threshold switching works;
12. `num_teleportations = 2` works;
13. all executed tests are recorded in `TEST.md`;
14. remaining performance issues are recorded in `STATUS.md`/`FUTURE.md`.

Only after this milestone should the project focus on large-scale confidence/round-count physics studies.
