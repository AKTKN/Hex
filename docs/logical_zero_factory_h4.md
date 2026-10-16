# H4: circuit-informed projected factory priors

H4 adds an opt-in prior builder in `hex_qec.decoders.codecapacity_dem`. It
uses the full noisy factory circuit, stage/preparation/measurement ledger,
code/observable supports and actual preparation decoders carried by the H1/H2
bundle. It builds a **single-fault response at one noiseless reference**, then
models those responses as independent events. It is not an exact conditional
posterior or a certified marginal over all preparation records. Measured
counterexamples are documented below. H5 has not started: default factory
and full Knill APIs, Hamming recovery/scoring and physical sampling are unchanged.

## Build and compare on saved records

```python
from hex_qec.modularisation import PreparationPlan
from hex_qec.protocols import FactoryCircuitBuilder, RotatedSurfaceCodeAdapter
from hex_qec.simulation import CompiledFactory
from hex_qec.decoders import ProjectedDEMBuilder

bundle = FactoryCircuitBuilder(
    RotatedSurfaceCodeAdapter(3), PreparationPlan(2, 2),
    physical_error=0.001, T_tel=2,
).build()
priors = ProjectedDEMBuilder(bundle, fault_batch_size=1024)
projected = priors.build(stage_index=0)
weighted = priors.compile_gap(0)  # cached SurfaceMWPMHomologyGap

factory = CompiledFactory.from_bundle(bundle, seed=620)
raw = factory.sample_measurements(32)  # sample once, independent of decoder choice
hamming = factory.decode(raw)
scores = weighted.decode_batch(hamming.corrected_syndromes[:, 0])
assert scores.gap.shape == (32,)
assert scores.score_units == "log_weight"
assert hamming.gap_units == "hamming_weight"
```

The builder never samples a physical shot or consumes its fault truth or
terminal label. Quantum gates/noise are unchanged by prior construction.
Comparisons must reuse saved raw records and respect the different units;
no quality cut, abort, retry, resampling, or LER improvement is implied here.

`ProjectedDEMBuilder(bundle, *, convention=PreparationDecoderConvention(),
fault_batch_size=1024)` copies the full circuit, checks its hash and causal
ledger, and owns worker-local result/native caches. The supported convention
is the existing matchable PyMatching prep decoder, canonical reset X/Z frame,
Hamming earlier-stage recovery, and Stim's noiseless reference. Custom
backends/conventions need separate validation and are rejected. Do not mutate
source prep plans/native handles after construction.

- `build(stage_index=0)` returns a cached `ProjectedDEMResult`; unsupported
  active models raise `UnsupportedProjectedModel`.
- `inspect(stage_index=0)` retains the complete projected events, fault
  provenance and diagnostics even if a model cannot enter H3's lift.
  Unsupported noise operations or unusable preparation decoder support still
  raise: there is no complete projection to return in those cases.
- `compile_gap(stage_index=0)` returns the same cached validated H3 graph on
  repeated calls. It never changes the default factory/Knill decoder.

## Physical mechanisms and causal projection

For stage j the window begins at initial A-zero preparation and ends at j's
noisy destructive readout, inclusive. It includes both initial preparations,
every relevant refresh, earlier CNOT/readout and the current CNOT/readout.
It does not begin at the latest fresh-plus reset and lose memory history.
Every mechanism records its original absolute instruction, operand index,
qubit/Pauli tuple, source gate probability, independent generator probability,
origin stage and preparation/coupling/readout region.

Supported noise is `X_ERROR`, `Y_ERROR`, `Z_ERROR`, `DEPOLARIZE1/2` on the
flat factory circuit. Existing Hex readout noise is an explicit Pauli channel
before M/MR. Nonzero measurement-noise arguments, arbitrary Pauli/correlated
channels and repeat blocks are rejected rather than approximated silently.
Zero-probability noise instructions are counted in diagnostics and generate
no faults; impossible fault histories are not submitted to a p=0 prep graph.
Positive generator-probability underflow is rejected.

Depolarizing Pauli alternatives at a gate are mutually exclusive. They are
**not** treated as independent branches of probability p/15. Instead each
k-qubit depolarizing channel is exactly factored into independent nonidentity
Pauli generators with

```text
q_k = [1 - (1 - 4^k p/(4^k-1))^(1/2^(2k-1))] / 2, k=1,2.
```

Stable `log1p`/`expm1` evaluation implements the same factorization used by
[Stim's error analyzer](https://github.com/quantumlib/Stim/blob/v1.15.0/src/stim/simulators/error_analyzer.cc).
Over-mixing/degenerate depolarization is rejected. These q's describe model
generators, not the exclusive physical Pauli branch probabilities; the original
gate p is retained too. Exact factorization of the physical channel does not
make the later nonlinear decoder projection exact.

Construction propagates one controlled Pauli per deterministic FlipSimulator
lane. It removes stochastic noise and uses no physical-shot sampler. Reset
maps clear both erased components (reference-only R/RX sentinels, including
MR's reset) without altering the production circuit. A lane's measurement
flip vector is combined with the fixed noiseless **operational prefix**
reference. `FactoryBatchDecoder.decode_stage_input(prefix_records,j)` runs
the actual full-history prep/frame processing and Hamming prefix recovery,
returning interpreted `(lanes,n)` target Z records before j's recovery.
It accepts exactly j's prefix width; future and oracle columns are rejected.
Gap scoring and terminal evaluation are disabled on this path.

Let `m_f` be that interpreted record for model fault f and `m_ref` its
no-fault reference. The effective signature is
`(support(H_Z*(m_f XOR m_ref)), support(L_Z*(m_f XOR m_ref)))`.
Raw signed terminal-check parities and raw logical-readout flip are also
retained separately for the same physical fault. This exposes, rather than
hides, differences introduced by preparation decoding. Online H has only
`m_z` rows; preparation history is not concatenated into the online syndrome.

Only metadata/hash validation sees the final oracle layout. Reference sampling,
propagation, frame inference and model probabilities exclude its suffix and
all later records. Changing future noise changes the full configuration hash,
but not an earlier prefix/model hash or its probabilities. Later-stage models
hold the existing **Hamming prefix policy** fixed; changing earlier recovery
requires a separately keyed/validated interpretation.

## Complete events, weights and matching

`FaultSignature(detectors,logical)` stores sorted unique supports; this phase
has one logical row, index 0. `ProjectedFault` retains the mechanism,
effective signature, raw signed signature, and interpreted X support.
`merge_independent_events` combines only identical **complete** signatures
using `q_new=q_old*(1-q)+q*(1-q_old)`, with unique provenance IDs. Equal
detector supports with different logical labels remain separate. No-op events
remain inspectable with their provenance; detector-free logical events are
retained and cannot be silently dropped for matching.

`ProjectedErrorModel` is an immutable event tuple with `num_detectors=m_z`.
`to_stim_dem()` returns a new inspectable Stim DEM, including no-op/zero-q
events and one declared logical row. `matching_matrices()` returns
`H (m_z,E)` sparse, `L (E,) uint8`, and `w (E,) float64`, where E is the number
of positive nontrivial merged events. Weights are the natural-log values
`log1p(-q)-log(q)=log((1-q)/q)`. There is no clipping or sum approximation.
E's columns are **event variables**, not data-qubit positions. H3 corrections
therefore have `(shots,2,E)` axes; its costs/gap/class retain their H3 meaning.

The compiler rejects hyperedges, detector-free logical mechanisms,
nonpositive/degenerate log weights, inconsistent potentials and unsupported
lift topology. It uses H3's validated two-boundary graph, never `[H;L]` on a
degree-three column. Graphlike alone does not prove lift validity.
H3's native weight-resolution limits continue to apply. At p=0,
`build()` returns the empty active prior and zero-noise diagnostics;
`compile_gap()` raises with an explicit instruction to use the existing finite
Hamming baseline. No infinite-weight graph or implicit fallback is created.

## Results and cache lifetime

`ProjectedDEMResult` contains stage ID, model, all projected faults,
`ProjectedDEMDiagnostics`, prep convention, graphlike/lift-valid flags,
full-circuit/prefix/configuration/reference/model SHA-256 values, projection
batch size, `prior_convention="circuit_informed_projected"`,
`approximation="single_fault_at_noiseless_reference_independent_superposition_v1"`,
and `weight_units="log_weight"`. Diagnostics count mechanisms, active terms,
merged events, raw-vs-resolved mismatches, hyperedges, logical-only/no-effect
terms, zero-probability instructions, zero noise and any lift rejection.

Configuration identity includes full code/depth/noise/stage/ledger metadata,
conventions/algorithm version, actual native prep graph topology and weights,
check/correction/frame maps, batch size and Stim/PyMatching versions. Native
handles/maps/converters are reused across all model lanes. Results and compiled
graphs are cached per builder/case/stage, never per physical shot. Each setup
chunk owns at most `fault_batch_size` controlled lanes, bounding dense record
storage by that size times prefix measurements. Chunk partition tests preserve
all signatures/probabilities. This is still a setup computation proportional
to mechanisms and prefix size; no large-code performance claim is made.
Use synchronously within one worker; reconstruct native handles per worker.

## Measured limits and validation

For d=3, p=0.001, depths `(2,2)`, T=2, stage 0 has 1,666 mechanisms and stage
1 has 2,571. Their effective model has nine active complete signatures plus
one no-op event and passes H3's lift. Raw signed and reference-resolved
signatures differ for **375** and **280** mechanisms respectively. Raw check
marginals independently agree with Stim's DEM to about `4e-15`.

The reference cannot stand in for all physical prep records. An injected
plus-block SE ancilla fault `Z30` at instruction 257 (mechanism 1518) has raw
signature `(D0,no logical)` and reference-resolved signature `(D0,L0)`.
Across 16 paired physical states at seed 341, its corrected syndrome is D0
throughout, but only **3/16** have the reference logical response: **13/16
differ**. The physical raw flip map agrees exactly, locating the difference
in nonlinear/context-dependent prep interpretation. This is an observed
single-fault limitation, not a calibrated marginal probability estimate.

There is also a nonlinear two-fault limitation: all nine individual initial-A
reset X faults have zero effective response at the reference, but **18/36**
pairs have a logical-only response after decoding. Independent superposition
of zero single responses misses those O(p^2) failures. Consequently this model
is not claimed exact even to first order after averaging intrinsic preparation
randomness, nor for multi-fault conditional decoding. Fixing that requires a
different validated marginal/conditional model, outside this phase.

Tests cover physical paired reset/SE/CNOT/readout faults, these counterexamples,
raw Stim marginal comparison, complete-signature XOR merging, probability and
log-weight numerics, zero noise, unsupported graphs/noise, causal/oracle
isolation, actual prep-weight hash changes, chunk/cache reuse and weighted
minima on identical saved data. New physical batches contain <=32 shots;
controlled setup lanes/classical enumeration are not Monte Carlo shots.
See [TEST.md](../TEST.md#auxiliary-system-h4-projected-factory-priors) for exact
commands, initial failures and final regressions. H5 public options, full
Knill changes, threshold selection, experiment output and large sweeps remain
out of scope.


H5 now adds the public option and shares this projection algorithm through
`OnlineMeasurementContext` / `EffectivePriorBuilder`. The H4 standalone API
still uses Hamming prefix recovery; True factories use actual projected prefix
policies with separate hashes. See [the H5 guide](logical_zero_factory_h5.md)
for supported full-Knill X/Z cases, rejected models and the whole audit.
