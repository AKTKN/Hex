# FUTURE.md

## Purpose

This file records development directions that are expected to become useful after the current two-level adaptive-SE implementation is working.

`PLAN.md` is the detailed near-term implementation contract.

`FUTURE.md` is intentionally broader. Items here should not be implemented merely because they are listed; promote an item into `PLAN.md` when it becomes the next validated objective.

# Near future: validate the infrastructure before adding more adaptivity

The first priority after the new stateful backend exists is **not** to add
more features.  The fixed-round, forced-endpoint, and two-level confidence
switching checks are now implemented and recorded in `TEST.md`; the adaptive
path remains a correctness-first reference implementation.

The immediate sequence should be:

```text
stateful fixed-round execution
    ↓
reproduce existing Hex results
    ↓
forced-short endpoint
    ↓
forced-long endpoint
    ↓
two-level confidence switching
    ↓
multiple Knill rounds
```

The first five entries are complete for the current reference path.  Multiple
Knill rounds are covered by the adaptive smoke test, but larger statistical
validation and performance work remain separate tasks.

Large simulations should wait until the above compatibility checks are documented in `TEST.md`.

The current surface-code experiment driver is
`notebooks/surface_code_knill_fixed_adaptive_sweeps.ipynb`. It records the
installed decoder versions, uses explicit BP-LSD settings and uniform
code-capacity priors, and checkpoints scalar aggregate rows. It is intentionally
smoke-sized by default; production sweeps still need independent statistical
validation.

The synchronized pair executor interleaves physical suffix execution as
Z-short, X-short, Z-extra, X-extra and removes local detector annotations from
the interleaved suffix. The long decoders still consume complete per-patch
histories. A future general stateful executor should replace this
protocol-specific record permutation with an explicit causal detector-record
model and test downstream detector modules before broadening the scope.

# 1. Improve the adaptive execution engine

The current adaptive executor intentionally uses one `FlipSimulator` per shot
and recomputes correction maps as paths grow.  This makes state continuation
and software-frame semantics explicit, but is not a production performance
design.  Optimize only after preserving the endpoint and confidence-switching
tests.

## 1.1 Branch compaction

The first correct implementation may keep separate simulator branches for short/long outcomes.

With multiple state preparations and multiple Knill teleportations, the number of branch combinations can increase.

Future optimization should investigate:

- pruning empty masks;
- compacting active shots;
- merging branches after they reach an equivalent module boundary;
- recreating a batch simulator from selected Pauli-frame states;
- grouping shots by control-flow state.

Any branch merge must preserve:

- physical Pauli/error state;
- required measurement history;
- intrinsic stabilizer randomness;
- software correction frame;
- logical-state convention.

Do not merge branches solely because they are at the same circuit location.

## 1.2 Dynamic batch sizing

Low-confidence fallback may be rare.

Running the long continuation on a full batch wastes work when only a small fraction of shots require it.

Potential future strategies:

- compact low-confidence shots into a smaller batch;
- maintain fixed SIMD-friendly batch sizes;
- amortize long-branch simulation across several incoming batches.

Benchmark before optimizing; Stim's SIMD behavior can make naive small batches inefficient.

## 1.3 General stateful module executor

After the adaptive state-prep use case is stable, generalize the stateful backend so arbitrary Hex modules can request:

```text
execute
decode
branch
commit
continue
```

without protocol-specific branching logic in Knill code.

This could become a general dynamic-protocol engine for Hex.

# 2. Multi-stage adaptive syndrome extraction

Only after the two-level short/long design is validated, consider:

```text
r0
 ↓
confidence
 ├─ accept
 └─ r1
      ↓
    confidence
      ├─ accept
      └─ r2
           ...
```

The schedule API should then evolve from:

```python
AdaptiveSERounds(short_rounds, long_rounds, policy)
```

to a more general object containing candidate stopping points.

Do not redesign the initial API prematurely; preserve a migration path.

Potential future schedule:

```python
AdaptiveSERounds(
    checkpoints=[2, 4, 6, d],
    policy=...,
)
```

Required future research questions:

- how confidence should be updated with new rounds;
- whether decoder state can be warm-started;
- whether re-decoding the full history is necessary;
- whether confidence latency changes the useful stopping point.

# 3. Decoder confidence ecosystem

The base decoder API should support many confidence definitions.

Potential decoder/metric integrations include:

- PyMatching logical/complementary-gap style metrics;
- forced gap;
- anchored forced gap;
- BP posterior-based confidence;
- Relay-BP confidence;
- convergence state;
- multi-metric confidence vectors.

Future work should support:

```text
decoder correction
+
multiple named confidence metrics
```

rather than choosing one universal scalar.

Possible external packages should be integrated only through adapters.

If used later, record exact repository and version in `PLAN.md`/`STATUS.md`.

# 3.1 Circuit-derived priors for code-capacity decoding

The initial BP-LSD integration may use a uniform code-capacity channel: one
per-data-qubit error probability, supplied through `error_channel` (or the
equivalent decoder option), with length equal to the code PCM's number of
columns.  This is a deliberate baseline and should be kept while validating
the original simulation and result plumbing.

Later, implement an effective code-capacity prior model derived from the
state-preparation circuit rather than reusing the state-preparation DEM
priors directly.  The planned approach is:

1. include the destructive data measurement and relevant stabilizer records
   in an explicit detector model;
2. convert that DEM into check matrices and fault priors with
   `detector_error_model_to_check_matrices`;
3. backpropagate each circuit fault to the data-error variables used by the
   final code-capacity decoder;
4. marginalize or otherwise combine faults that induce the same effective
   data correction variable; and
5. pass the resulting per-column probabilities to the X/Z code-capacity
   decoders, with exact axis and basis conventions documented and tested.

The state-preparation DEM priors and the final code-capacity priors must not
be conflated: they generally have different numbers and meanings of columns.
The future implementation should expose the decoder role and the effective
prior source explicitly, while preserving the legacy
`decoder_generator(check_matrix, weights=...)` interface.

# 3.2 Code-capacity confidence for adaptive state preparation

The current implementation may compute confidence for the final code-capacity
repair decoders (`x_capacity`/`z_capacity` in `CSSInnerDecodeResults`), but
this confidence is intentionally excluded from the adaptive SE-round stopping
decision: `hex_qec.decoders.dem_only_max_confidence` is the current default
`confidence_aggregator` and reads only the `x_dem`/`z_dem` results.

Future work should investigate whether code-capacity confidence contains
useful information about:

- reliability of the selected repair frame;
- ambiguity of the inferred stabilizer sector;
- downstream logical failure probability;
- joint confidence combining spacetime DEM decoding and final repair decoding.

The `max_all_components` aggregator is retained as an internal future
component for this investigation. It must not be used as the stopping metric
in the current adaptive-SE benchmark: code-capacity confidence is not yet
calibrated against the circuit-level DEM confidence. The intended future use
is to integrate this signal with post-selection decisions, after the effective
code-capacity priors, confidence calibration, and post-selection semantics
have been implemented and validated. Until then, the benchmarking notebook
offers only `max_dem_only` and raises `AssertionError` for an attempted
`max_all_components` selection.

This requires a principled definition/calibration before it is used for
adaptive control. In particular, the current uniform code-capacity error
prior (see 3.1 above) is not a circuit-derived effective prior, so directly
combining its confidence with DEM confidence is not yet theoretically
justified. `hex_qec.decoders.all_components_max_confidence` exists only as a
diagnostic/experimental comparison point against the DEM-only default -- it
folds in the code-capacity results with an unweighted `max` and should not be
treated as a validated stopping metric.

Potential future designs include:

- calibrated combination of DEM and code-capacity confidence;
- confidence conditioned on repair-frame class;
- a confidence metric directly targeting competing state-preparation
  interpretations / repair frames.

Do not implement these future-work ideas without a dedicated task; this
section only records the exclusion and the open questions around it.

# 4. Post-hoc threshold and policy sweeps

If per-shot short confidence and final outcome are recorded, many policies can be evaluated without rerunning all physical simulations.

Future analysis tools should support:

```text
confidence threshold
    → fallback rate
    → mean SE rounds
    → LER
```

Useful plots:

- LER versus confidence threshold;
- fallback probability versus threshold;
- mean SE rounds versus threshold;
- LER versus mean SE rounds;
- confidence-conditioned LER;
- confidence histograms for success/failure;
- per-Knill-round fallback rate.

Be careful: a post-hoc change of a policy is valid only when the stored physical trajectory contains the information required for that alternative policy. A trajectory that physically stopped at the short branch does not automatically contain counterfactual long-round noise.

# 5. More complete result/analysis package

Potential future result classes:

```text
ExperimentResult
SimulationResult
AdaptiveEventResult
DecoderMetricSeries
ShotTrace
```

Possible serialization:

- JSON for aggregate metadata;
- NPZ/Parquet for large per-shot arrays;
- optional pandas interface for analysis.

Do not serialize large dense arrays into JSON.

Future result metadata should include:

- git commit;
- Stim version;
- decoder package/version;
- physical-error model;
- code/distance;
- random seed;
- short/long schedule;
- confidence metric/policy;
- number of teleportations;
- matchable/non-matchable DEM setting.

This is important for reproducible research.

# 6. Physical ground-truth/fault tracing

The stateful `FlipSimulator` gives access to the current propagated Pauli-flip state, but this is not the same thing as a full log of which stochastic circuit instruction fired.

A future debugging/research mode may explicitly record:

```text
fault location
Pauli fault
time/round
affected block
```

Potential uses:

- identify minimum harmful state-preparation mechanisms;
- compare true physical faults with decoder confidence;
- classify temporal versus spatial failures;
- validate analytical effective-distance arguments.

This should be a debug/research backend, not the default Monte Carlo path.

# 7. Theory-driven state-preparation experiments

After the adaptive simulator is validated, revisit the round-scaling experiments.

Relevant families:

```text
r = constant
r = ceil(alpha d)
r = d
```

with multiple `alpha`.

Questions:

- does fixed `r = O(1)` lose asymptotic suppression under patch-wise decoding?
- for `r = alpha d`, how does the effective exponent depend on `alpha`?
- where is the crossover at which state-prep temporal faults stop being the dominant failure mode?
- how code-dependent is that crossover?
- how does the noise model change it?

The simulator should eventually report enough mechanism-level information to compare numerical scaling with the theoretical model documented in `THEORY.md`.

# 8. Other codes

The architecture should not hard-code surface-code geometry.

After the surface-code implementation is stable, test adaptive state preparation on other CSS codes already supported by Hex.

Longer-term candidates include:

- lifted-product codes already represented in Hex data;
- other qLDPC CSS codes;
- color codes if a compatible circuit generator is added.

Code-dependent quantities of interest include:

- repair-frame spread caused by wrong stabilizer-sector interpretation;
- temporal detector structure;
- effective state-preparation fault distance;
- useful `alpha` in `r = alpha d`.

# 9. More realistic noise/timing models

The current Hex model is a simplified circuit-level Pauli model.

Future extensions may include:

- explicit idle errors;
- asymmetric gate/readout error;
- different gate durations;
- hardware-specific timing;
- leakage approximations;
- correlated physical faults.

Adaptive stopping becomes particularly interesting when classical decision latency is included.

Do not mix noise-model changes into the initial adaptive implementation. They make compatibility testing much harder.

# 10. Classical decoder latency and real-time constraints

The initial adaptive simulator makes an idealized immediate decision after the short decode.

A later model should include:

```text
short measurement completes
    ↓
decoder runs for tau_decode
    ↓
control decision arrives
```

During that time the quantum hardware may need to:

- continue syndrome extraction;
- idle;
- speculatively execute;
- buffer measurement data.

A useful parameter is approximately:

\[
\ell = \lceil \tau_{\rm decode}/\tau_{\rm SE} \rceil,
\]

the number of extra code cycles elapsed before the decision becomes actionable.

Future throughput metrics should distinguish:

- number of SE rounds logically requested by policy;
- actual physical rounds executed because of control latency.

# 11. Speculative execution

If real-time decision latency makes stopping immediately impossible, investigate speculative continuation.

Concept:

```text
start extra SE while confidence is being computed
    ↓
if short was accepted:
    decide how/if speculative measurements are discarded
if short was rejected:
    keep them as part of the long history
```

This requires careful physical and decoder semantics and should not be added until the non-speculative implementation is trusted.

# 12. Decoder warm start / incremental decoding

The initial long branch can re-decode the complete `1..long` history from scratch.

Future optimization can consider:

- reusing the short decoder state;
- streaming MWPM;
- incremental BP;
- sliding-window decoding;
- cached graph structures.

Correctness reference remains full long re-decoding.

# 13. Correlated/algorithmic fault-tolerance extensions

The current adaptive-state-preparation project is deliberately patch-wise/modular.

Longer-term work may compare it with algorithmic/correlated decoding approaches where `O(1)` rounds can be tolerated through later global reinterpretation.

Potential integration topics:

- correlated decoding across transversal gates;
- logical-operator-measurement (LOM) decoding;
- reliable logical Pauli products;
- local versus global decoding volume;
- deciding adaptively when heavy correlated decoding is necessary.

Possible packages mentioned for later investigation:

- `lomatching`
- `surface_sim`

Do not add these to the core adaptive state-prep implementation until the local modular baseline is established.

# 14. General adaptive protocol policies

Eventually the stopping decision may depend on more than one scalar confidence.

Possible policy inputs:

```text
confidence
decoder convergence
syndrome weight
estimated correction weight
number of detection events
previous Knill-round history
hardware latency budget
target logical reliability
```

Keep policy logic separate from decoder logic so these can be explored without rewriting decoders.

# 15. Testing infrastructure

Future test improvements:

- pytest-based unit suite if not already present;
- deterministic Stim circuits with probabilities 0/1;
- snapshot tests for matrix shapes;
- regression seeds for debugging only;
- statistical tests for sampler equivalence;
- CI across supported Python/Stim versions.

The test log remains in `TEST.md`; automated tests should live in a standard `tests/` tree.

# 16. Documentation automation

As the package grows, consider generating API documentation from docstrings.

However, retain the hand-written files:

```text
AGENTS.md
PLAN.md
FUTURE.md
STATUS.md
TEST.md
THEORY.md
DESCRIPTION.md
```

because they record design intent and experimental history that API docs do not capture.

# 17. Performance profiling

Once results are correct, profile:

- physical Stim execution;
- measurement-record reconstruction;
- `compile_m2d_converter` calls;
- sparse correction-map multiplication;
- X/Z decoder cost;
- confidence calculation;
- branch copying;
- long-branch fraction.

Do not optimize based on intuition alone.

The adaptive scheme is only useful if the reduced physical SE work is not overwhelmed by classical simulation/decoder overhead in the intended architecture.

# 18. Scientific milestone after implementation

A natural first research-quality dataset after the software milestone is:

```text
surface code
d = several odd distances
p = several circuit-level error rates
short_rounds = constant
long_rounds = d (or another validated linear rule)
confidence threshold sweep
num_teleportations = 1 and >1
```

Measure:

```text
LER
fallback rate
mean SE rounds
confidence-conditioned LER
per-preparation failure/switch statistics
```

This directly tests whether confidence can retain the reliability of a long preparation while reducing the average state-preparation time.
