# H5 public projected decoding and implementation audit

H5 adds `create_codecapacity_dem: bool = False` to fixed Knill EC,
`generate_bell_measurement_and_correction_module`,
`FactoryBatchDecoder` and `CompiledFactory.from_bundle`. All older positional
arguments retain their meaning. Circuit building remains separate from
decoder configuration. The option changes classical inference only.

## Stable factory imports

```python
from hex_qec.protocols import FactoryCircuitBuilder, RotatedSurfaceCodeAdapter
from hex_qec.modularisation import PreparationPlan
from hex_qec.simulation import CompiledFactory

bundle = FactoryCircuitBuilder(
    RotatedSurfaceCodeAdapter(3), PreparationPlan(2, 2), .001, T_tel=2,
).build()
factory = CompiledFactory.from_bundle(
    bundle, seed=511, create_codecapacity_dem=True,
)
raw = factory.sample_measurements(32)
result = factory.decode(raw)
assert result.gaps.shape == (32, 2)
assert result.gap_units == "log_weight"
priors = factory.projected_priors  # immutable model/diagnostic/provenance results
```

`FactoryCircuitBundle`, `FactoryBatchDecoder`, `FactoryOperationalBatch`,
`FactoryBatchResult`, `FactoryCacheKey`, and the contracts described in the
[H2 guide](logical_zero_factory_h2.md) remain public. `decode_operational`
accepts only the operational record prefix and returns the same operational
fields; terminal labels are produced separately. No YAML, filesystem runner,
Parquet, cuts, retries or resource certifier is added to Hex.

False uses the original spatial Hamming recovery/tie decisions and Hamming
gap. True uses stage-specific projected sector minima to choose the logical
byproduct and to score its gap. It keeps the same physical circuit, noise,
single final ideal oracle, preparation convention and terminal Hamming label
definition. A changed inferred frame can change that terminal error label.

Results retain the H2/H3 shot-first shapes and dtypes: corrected syndromes
`(S,T,m_z) bool`, raw/corrected byproducts and estimated frame consistency
`(S,T) bool`, X/Z frames `(S,T,n) bool`, shot IDs `(S,) uint64`, stage ID tuple,
terminal error `(S,) bool`, and gaps `(S,T) float64`. Gaps in True mode have
units `log_weight`; Hamming cuts and log-weight cuts are not interchangeable.
Frame consistency remains a decoder residual check, not physical truth.

## Full Knill API

```python
import pymatching
from hex_qec.circuit_generation import get_parity_check_matrices
from hex_qec.protocols import knill_online_offline

counts = knill_online_offline(
    get_parity_check_matrices("surface", 3),
    syndrome_measurement_rounds=1,
    online_decoder_generator=pymatching.Matching.from_check_matrix,
    offline_decoder_generator=pymatching.Matching.from_check_matrix,
    matchable_offline_decoding=True, physical_error=.001,
    max_shots=256, max_errors_before_halting=100,
    pauli="z", num_teleportations=1, surface_code=True, seed=1021,
    create_codecapacity_dem=True,
)
```

The static engine still returns the legacy `(samples_performed,logical_errors)`
tuple and samples batches of 256, potentially exceeding `max_shots`. This
example is not a large sweep; tests decode saved batches of at most 64 shots
instead. The noisy final X/Z readout remains unchanged. Online generator
behavior is unchanged in False mode, including custom generators. True
selects the validated native projected sector decoder for Bell inference;
the supplied online generator still handles the final noisy logical readout.
The adaptive/stateful public entry point has no new True mode in H5.

**Fig. 4(d) reproduction convention: `create_codecapacity_dem=False`.** H5
does not perform that reproduction or establish agreement with a paper.

Full Knill True is tested at d=3, p=.001, one teleportation, one SE round,
for both initial/final Pauli bases. A two-teleportation Z-basis case also
checks actual preceding projected feed-forward against manual prefix replay. Both the X and Z sectors pass H3's lift.
Each retains 1,058 controlled independent generators from the complete prefix,
including preparation, Bell-resource CNOT, Bell coupling and noisy readouts.
The two sectors have 12 and 10 complete-signature events respectively,
including no-ops. They are separate marginal approximations. Shared mechanism
IDs/Paulis preserve cross-sector provenance; inference does not exploit joint
X/Z correlations and is not joint MAP decoding.

**Important supported-domain boundary:** at d=3, p=.001, one teleportation
and two or three SE rounds, the projected X sector contains detector-free
logical mechanisms. H4/H3 cannot represent these with their validated lift.
True therefore raises `UnsupportedProjectedModel`, identifying stage/sector
and the retained logical terms; False remains available unchanged. Do not
delete the terms, report those settings as supported, or silently fall back.
Other distances/depths/longer full-Knill sequences must pass the same checks;
they are not certified by the small supported fixture. At zero noise, True
explicitly requests the finite Hamming baseline because the projected model
has no finite-weight active edges. Choose False at p=0.

## Context and service boundary

`hex_qec.decoders` exports `OnlineMeasurementContext` and
`EffectivePriorBuilder(context, *, fault_batch_size=1024)`. A context carries:

- the exact circuit prefix ending at the current destructive readout;
- stage and X/Z sector, check matrix `(m,n)` and exactly one logical row `(n,)`;
- every nonzero independent fault mechanism and raw parity supports;
- an interpreter from prefix records `(S,prefix_measurements)` to current
  pre-recovery readouts `(S,n)`;
- actual preparation/earlier-policy identities and declared frame convention.

The built-in producers include the complete relevant preparations and gates.
A standalone Bell gadget cannot infer its predecessors. Its optional
`online_contexts=(x_context,z_context)` is required when its flag is True;
code, sector and the physical suffix must agree. The ordinary fixed-Knill
orchestrator installs both contexts after global correction-map construction.
`modularisation/online_context.py` replays actual prep and earlier Bell
callbacks with cached correction maps restricted to the current prefix. It
does not call the current Bell recovery or final logical module while making
that sector's pre-recovery records. Changing final measurement noise cannot
change the prior or its configuration key.

H4's `ProjectedDEMBuilder.context(j)` produces the default factory context
with Hamming prefix recovery. H5 supplies its actual decoder plus the complete
earlier model/configuration hashes and labels the convention
`factory_causal_projected_v1`. It builds stages in chronological order, then
freezes the graph list. Later priors do not borrow H4's Hamming-prefix label.
H4's `inspect/build/compile_gap(j)` interfaces remain available and now use the
same `EffectivePriorBuilder` algorithm as full Knill and True factory decoding.

Custom contexts must specify their full interpretation and configuration
faithfully. Frozen containers do not freeze native callback state: do not
mutate source decoders, matrices or plans after setup. No generic callback
can independently certify an arbitrary external context's causal provenance.

## Inference, validity checks and caching

The approximation remains
`single_fault_at_noiseless_reference_independent_superposition_v1`:

`delta_m_f = interpret(reference XOR physical_delta_f) XOR interpret(reference)`

`signature_f = (H * delta_m_f, L * delta_m_f)` over GF(2).

Independent generators with identical complete signatures XOR-merge their
probabilities. The H4 depolarizing factorization, no-op/logical provenance,
natural-log weights `w_e=log((1-q_e)/q_e)`, and all structural/numerical
checks remain in force. Hyperedges, invisible logical terms, q>=1/2,
unsupported lift/topology and unsupported noise raise. No model component is
silently dropped or decomposed to obtain a matching graph.

For measured syndrome s, H3 computes
`W_b(s)=min_{H e=s, L e=b} sum_e w_e e_e`. True chooses class one only if
`W_1<W_0`; an exact tie chooses zero. A current raw logical parity a becomes
`a XOR chosen_class`. In full Knill these inferred X and Z parities drive
logical Z and X corrections respectively. In the factory the Z parity drives
the survivor's logical X frame. Event columns are **not data qubits**; they
cannot be XORed directly into n-bit physical readouts. H3's float64 cost
recomputation, native noninteger rounding and near-tie limits still apply.

Per worker/case, setup caches the sampler, sparse maps, preparation native
decoders and m2d converters, reference projection results and both-sector
matching graph for each stage. Full Knill enables cached prep converters only
in True mode; False retains its historical callbacks. Two native calls score
each syndrome batch. No new graph/simulator/converter is built per physical
shot or by the configured callbacks. Full static execution still uses its
existing global converter and prepares some unused legacy native decoders;
H5 makes no wall-clock speed claim.

Factory cache keys add the flag, projected decoder/gap policy and per-stage
configuration hashes. False-mode keys retain all prior values with new fields
defaulting to False/empty. Context hashes identify actual prep graph weights,
maps, earlier projected models/policies, prefix, code/sector, mechanisms,
conventions, approximation, chunk size and native versions. H4 cache hits
return before enumerating faults. Objects remain synchronous and worker-local.
Seed equality requires the same Stim version/platform and chunk partition.
Setup memory is bounded by projection chunks times prefix measurement width;
setup CPU still scales with mechanisms and prefix history.

## Whole-implementation assessment

H0–H5 now have regression checks for the documented circuit construction,
signed flows, two-support refresh, local/global frame maps, causal decoding,
oracle isolation, H3 enumerated minima, H4 complete fault provenance and H5
public compatibility/context boundaries. See [TEST.md](../TEST.md#auxiliary-system-h5-public-options-and-whole-implementation-audit)
for actual commands, failures corrected and final results.

This is implementation validation within tested domains. It is not a physical
accuracy certificate for the projected prior: H4's plus-SE paired-state
counterexample disagrees with the fixed-reference logical response on 13/16
records, and 18/36 two-fault reset pairs have logical responses absent from
individual reference responses. Those tests remain, with the mechanisms
retained. See [the H4 limitations](logical_zero_factory_h4.md).

Consequently True is an optional controlled decoder experiment, not an exact
intrinsic-randomness-marginal, conditional likelihood, posterior confidence,
validated LER improvement, threshold result or fault-tolerance proof. Evaluate
it against False on shared physical records before scientific comparisons.
Do not apply Hamming thresholds to log-weight gaps. No large Monte Carlo or
paper reproduction was run. Bench integration, parameter sweeps, posterior
models and supported generalizations are separate future tasks.


## Post-H5 custom factory physical noise

HEX-N1/N2 add optional FactoryNoiseModel to the factory builder only; all
examples above still use exact legacy hex_uniform. Native H5 True retains
its full-prefix approximation and strict rejection rules, now including both
explicit idle windows. Downstream local priors have a different declared
scope. See [factory noise](factory_noise_model.md) for operation channels,
preparation decoding consistency, timing, metadata and causal tests. No full
Knill/Fig.4(d) custom-noise extension is implemented.
