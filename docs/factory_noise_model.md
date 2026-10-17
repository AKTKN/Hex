# Configurable factory physical noise

HEX-N1 introduces frozen validated configuration objects in
`hex_qec.circuit_generation.factory_noise` (also exported from
`hex_qec.circuit_generation`). HEX-N2 integrates them into the logical-zero
factory only. Full Knill, Fig. 4(d), Steane and adaptive protocols keep their
existing noise interfaces and physics.

`CircuitNoiseModel(one_qubit=1, two_qubit=1, idle=1, measurement=1, reset=1)`
contains reusable nonnegative finite multipliers relative to physical rate p.
`FactoryNoiseModel` extends it with `post_cnot_control=IdleWindow(duration=0,
rate_multiplier=1)` and `during_plus_preparation=PlusPreparationIdle(enabled=False,
se_round_duration=1, rate_multiplier=1)`. Dictionaries and duration expressions
such as `"d"` are rejected. Configuration objects are immutable and hashable;
`as_dict()` returns an independent JSON-compatible copy, and
`configuration_sha256` hashes canonical parameters, independently of p.

## Channels and idle mathematics

Custom one-qubit gates use `DEPOLARIZE1(p*one_qubit)`; two-qubit gates use
`DEPOLARIZE2(p*two_qubit)`. Measurements use the complementary Pauli flip
before the measurement, and resets use the complementary Pauli after reset:
X for Z-basis operations, Z for X-basis operations. Multipliers do not denote
probabilities themselves: each resolved channel probability must be in [0,1].
Parameters are never clipped. Preparation decoding must be built from the
same noisy preparation circuit, before any decoder/repair map is compiled.

`idle_depolarizing_probability(p, idle, duration, rate_multiplier=1)` computes

\[
q=p\,m_{idle}\,m_{window},\qquad
p_{eff}(\tau)=\frac34[1-(1-4q/3)^\tau].
\]

All inputs are finite nonnegative real numbers (booleans are rejected), with
p and q in [0,1]. Fractional duration requires q<=3/4 so the power is real.
Integer durations also support q>3/4. Zero duration has zero effective noise;
even then the base probability is validated. Stable `log1p`/`expm1`
evaluation retains tiny positive exposures. No arbitrary per-instruction idle
channel is implied. One aggregated channel composes the identical independent
depolarizing channels on a stored qubit over the specified idle interval.

The model intentionally distinguishes `noise_model=None` (legacy
`hex_uniform`, including its absence of one-qubit depolarizing channels) from
an all-one custom object. Neither window is enabled by default in the custom
object. No `additional_wait` option, threshold-dependent circuit or dynamic
retry is provided.

## Placement contract for factory integration

After the complete transversal CNOT, the surviving fresh-plus control's data
qubits receive the post-CNOT idle channel, before destructive Z target
readout. Neither target nor ancillas receives that special channel. It must
be within the identified coupling region so a downstream local DEM can
include it.

For stages j>=1, the old survivor stores logical zero while the consumed
support resets and prepares plus for r_plus rounds. Its idle duration is
`r_plus*se_round_duration`. An aggregated channel at the end of preparation
is equivalent because the stored block does not interact with the preparing
block in that interval. Initial zero/plus preparations are assumed parallel;
there is no initial storage wait. These two windows are disjoint, with no
generic idle layer counting either interval twice.

Physical simulation includes both windows. A downstream module-local prior
starting just before CNOT includes post-CNOT control idle, and may exclude
inter-stage storage idle along with preparation/earlier residuals. Such a
prior is approximate and is not the posterior conditioned on offline repair.
Hex H5 itself retains its full-prefix fixed-reference projected prior; it
does not silently switch to a module-local model. Structural DEM/graph checks
and complete detector/logical signatures must remain strict in either case.

The sole ideal terminal evaluation oracle is outside every operational
model; no oracle information is a decoder input or confidence score.

## Implemented factory API (HEX-N2)

```python
from hex_qec.circuit_generation import FactoryNoiseModel, IdleWindow, PlusPreparationIdle
from hex_qec.modularisation import PreparationPlan
from hex_qec.protocols import FactoryCircuitBuilder, RotatedSurfaceCodeAdapter
from hex_qec.simulation import CompiledFactory

noise = FactoryNoiseModel(
    one_qubit=.5, two_qubit=1, idle=1, measurement=2, reset=1,
    post_cnot_control=IdleWindow(duration=.75, rate_multiplier=1),
    during_plus_preparation=PlusPreparationIdle(
        enabled=True, se_round_duration=1, rate_multiplier=1),
)
bundle = FactoryCircuitBuilder(
    RotatedSurfaceCodeAdapter(3), PreparationPlan(2, 2), .001,
    T_tel=2, noise_model=noise,
).build()
factory = CompiledFactory.from_bundle(bundle, seed=31,
                                      create_codecapacity_dem=False)
result = factory.sample(3)
```

The existing base-p domain [0,.5] is preserved. Resolved operation and idle
channels are validated before preparation begins, including inactive window
parameters. `noise_model=None` follows the original builder without a new
channel, altered ordering or additional metadata. Custom all-one multipliers
are a new model, labelled `factory_operation_specific_v1`.

`RotatedSurfaceCodeAdapter.prepare(..., *, noise_model=None)` creates its
custom preparation from the native zero-noise surface instruction skeleton.
It replaces the zero placeholders **before** Stim can fuse gates across them,
so each two-qubit channel remains immediately after its own gate. It then
constructs the native CSS detector module, DEM priors, four matching handles,
representative corrections, local history maps and boundary frames from that
same physical circuit. The original hook ordering and signed check ledger
are retained. No previously compiled uniform module is patched.

Ancilla `R; H; ...; H; MR` uses X reset error after R, depolarization after
both H gates, X readout error immediately before the physical Z measurement
MR, and X reset error after MR. The post-MR reset error is overwritten by the
next explicit R and has no data effect; it is not another idle interval.
Data initialization uses X after R or Z after RX. Native instruction RX is
treated as an X reset, not an extra noisy H gate. No other gate set or
arbitrary instruction schedule is supported by this factory adapter.

Custom preparations opt into
`css_detector_module(..., allow_pauli_products=True)`; the default is False.
If Stim selects a joint Pauli representative, all factors propagate together
in one fault lane through both local-history and global-frame maps. This
changes no event probability or graph decomposition. Legacy single-Pauli
propagation, the existing matchable preparation edge projection and legacy
weight formula are preserved; these priors are not claimed exact or optimal.

`TeleportationStage.post_cnot_control_idle` is a subregion at the end of
`coupling`; `storage_idle` is a separate region between refresh preparation
and coupling. Each has no measurements and exactly one DEPOLARIZE1 on the
specified data support. Zero effective channels have no region. Bundle
validation checks support, causal ordering, alternating roles, signed flows
and strict operational Stim DEM without gauge/disjoint-error approximations.

Custom metadata includes canonical `noise_model_json`, `noise_model_sha256`,
`physical_noise_sha256` (including p), resolved window probabilities, scheduling
and native/full-prefix versus downstream/module-local prior scope. The literal
Stim-text `circuit_sha256` retains its original meaning. `FactoryCacheKey`
adds `noise_model_sha256` (empty for legacy), so even different inactive
parameters at p=0 remain distinguishable. Actual noisy preparation maps/
weights, circuit, metadata and preceding policies already enter projected
cache identities. Graphs/maps/converters/sampler compile once per complete
case/worker; no sampling state is shared across different compiled cases.

False keeps Hamming online matching and Hamming min-sum gap, including finite
p=0 scores. True keeps Hex H5's existing full-prefix reference projection,
with both physical idle sources retained and correctly owned by the stage
ledger. Downstream **module-local** DEMs slice at `stage.coupling`, include
post-control idle, and exclude preceding preparation/storage residuals under
their explicitly different approximation. No new local inference mode is
silently installed in Hex. Both paths must pass their original structural
checks: unsupported hyperedges/logical terms, over-mixing factorization or
nonfinite weights raise, with no lossy fallback. True at zero active noise
explicitly requests the finite Hamming baseline instead.

Control errors after the complete CNOT can change the survivor without
changing that stage's destructive target record. A logical X in this window
flips the final evaluation label while leaving its already determined
operational syndrome/byproduct/gap unchanged. The tests explicitly check this
causal limit; the gap is not a certificate of survivor correctness. No exact
posterior, fault-tolerance, threshold, retry or performance claim follows.

Deterministic tests are in `tests/test_factory_noise_model.py` and
`tests/test_factory_custom_noise.py`; physical batches use d=3 and <=7 shots.
The latter includes pre-edit H5 golden circuits/records/XZ frames/gaps,
operation placement, disjoint windows/role swaps, strict signed DEM gates,
actual preparation priors and independently replayed global frame maps,
paired survivor logical faults, both prior modes, oracle exclusion, native
reuse, parameter identities and explicit unsupported-domain errors. Exact
commands/results and the reproduced pre-existing adaptive test failure belong
to [TEST.md](../TEST.md) and [STATUS.md](../STATUS.md).
