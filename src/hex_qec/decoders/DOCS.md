# Decoders: current interfaces and confidence limits

Detailed adapter usage: [DESCRIPTION.md](DESCRIPTION.md).

## Implemented today

`base.py` defines `DecodeResult(correction, confidence=None, converged=None,
metrics={})`, `CSSInnerDecodeResults`, and structural `Decoder` /
`DecoderFactory` protocols. `LegacyDecoderAdapter` wraps `decode_batch` or a
scalar `decode`; `LegacyDecoderGeneratorAdapter.create(H, weights=None)`
preserves existing generator calls and optional dtype casts. Third-party
decoders need no Hex inheritance.

For `H.shape == (checks, variables)`, input syndromes are `(shots, checks)`
and corrections `(shots, variables)`. Optional scalar confidences/convergence
have shot axes; metrics remain decoder-specific. A valid correction satisfies
`H e = s` over GF(2); satisfying the syndrome does not establish logical
success. Legacy adapters add no confidence to array-only decoder outputs.

`HexBPLSDDecoder` and `make_bplsd_decoder_generator(p, alpha=2.0, **options)`
reuse one LDPC decoder and process its mutable per-shot statistics serially.
They return `uint8` corrections and float cluster confidence `(shots,)`.
For active final LSD clusters `C_i` and prior LLRs `w_e=log((1-p_e)/p_e)`,
the metric is `(sum_i (sum_{e in C_i} w_e)^alpha)^(1/alpha) / sum_e w_e`
over the supported finite-weight statistics. No active cluster yields zero;
larger values are risk-like. Final membership, including absorbed clusters,
must not be confused with recovery support. This is not a homology-sector gap
or a calibrated posterior probability.

`dem_only_max_confidence` combines X/Z DEM confidences and excludes final
code-capacity repair confidence. `all_components_max_confidence` is retained
for diagnostics. Both are optional metric-specific examples. Neither the CSS
constructor nor the protocol automatically selects an aggregator. Code-capacity
BP-LSD calls use uniform `p`; DEM calls with `matchable=False` receive DEM
probabilities. Legacy `matchable=True` arguments are weights, not a probability
channel; do not mix those conventions with the BP-LSD factory.

Adapter tests passed in H0 (part of the 15-test adapter/result command).
Cluster-statistics and confidence-policy tests exist but were not rerun in H0;
see [tests/DOCS.md](../../../tests/DOCS.md). H0 changed no decoder source.

## H2 surface factory readout

`factory_surface.py` provides `SurfaceFactoryReadout(code,z_checks)` for the
causal factory executor. This surface-specific boundary rejects other code
families, caches H_Z/logical transforms, and builds separate online/terminal
PyMatching Hamming decoders. It does not change weights per shot or expose
terminal data to the online handle.

`syndrome(m)` returns `m @ H_Z.T mod 2`; `recover(s)` returns a boolean
`(shots,n)` correction and rejects nonzero residual syndromes.
`logical_parity(m)` returns `(shots,) bool`, and `byproduct_frame(b)` returns
`b[:,None] & L_X`. `evaluate_terminal(oracle,frame_x)` interprets the ideal
readout, uses only the evaluation decoder, checks recovery consistency and
returns logical-Z mismatch. These are deterministic batch transforms with
cached handles and no physical sampling. The stage loop and production
result API live in [simulation](../simulation/DOCS.md); the
[H2 guide](../../../docs/logical_zero_factory_h2.md) specifies the full frame
equations, noise and label convention. H3 adds a separate cached sector graph
and `score_gap(syndrome)` returning `(shots,) float64` in `gap_units`, fixed
to `hamming_weight`. The original recovery handles remain unchanged.

## H3 surface homology gap

`surface_gap.py` exports `SurfaceMWPMHomologyGap` and `HomologyGapBatch`.
The [scientific specification](../../../docs/README.md) defines
`W_b(s)=min_{He=s, Le=b} sum_f w_f e_f` and `gap=abs(W_1-W_0)`.
This min-sum sector difference is not posterior log-odds, which sum over
patterns. Hamming and log-weight thresholds use different units.

The required `decoder-confidence` `_forced_gap.py`, `_constraints.py`,
`_decoder_adapter.py` and `FUTURE.md` were reviewed. They remain unverified
references: their unsplit path appends L, may produce degree-three columns,
and rebuilds matching on per-shot constrained calls. No code is copied or
dependency imported from that checkout. H3 uses the validated lift instead.

For `H.shape=(m,n)` and one L row, the constructor solves internal potentials
`L[e]=u[a] XOR u[b]`; one-endpoint edges attach to B1 when `L[e] XOR u[a]=1`,
otherwise B0. `H_ext=[H;B0;B1]` has exactly two ones in every column. Set
`t1=b XOR u.dot(s)` and `t0=parity(s) XOR t1`; one cached Matching decodes both
sectors in two native batch calls. B0/B1 are constrained detector vertices,
never free native boundary nodes. The identity `L=u^T H XOR B1` establishes
the sector correspondence. Setup validates binary/shape/degree, potential,
connected lift and planar topology; zero-detector events/hyperedges fail.

`decode_batch(syndromes)` requires nonempty binary `(shots,m)`, returning
`sector_costs (shots,2) float64`, `corrections (shots,2,n) bool`, `gap (shots,)
float64`, `best_class (shots,) uint8` (zero wins exact ties), and `score_units`.
`W0/W1` are cost-column properties. Units are `weight`, `log_weight`, or unit
`hamming_weight`; no prior is estimated. Weights must be positive finite,
<=`2**24-1`, and min/max>=`1/(2**24-1)`. Native rounding of noninteger weights
and absolute normalization overflow are checked explicitly. Rounding
can obscure near ties; original-weight costs are recomputed and validated
with a rounding allowance. Integral factory weights avoid that ambiguity.
The factory explicitly retains finite Hamming scoring at p=0 (zero syndrome
gap d); infinite/zero weights are rejected. This is not posterior certainty.

Matrix/potential inspection returns copies; topology/L/weight/units/lift/native
version determine `cache_identity`. Native handles stay synchronous per
worker, with no rebuilding/reweighting inside batch calls. NetworkX, already
a PyMatching dependency, is now declared directly for setup-time planarity.
See [the H3 guide](../../../docs/logical_zero_factory_h3.md) for the proof,
API example, scientific/numerical limits, causal integration and tests.

## H4 circuit-informed projected priors

`codecapacity_dem.py` adds `ProjectedDEMBuilder(bundle, *,
convention=PreparationDecoderConvention(), fault_batch_size=1024)` and frozen
`ProjectedDEMResult`, `ProjectedDEMDiagnostics`, `ProjectedErrorModel`,
`FaultMechanism`, `ProjectedFault`, `FaultSignature`, `ProjectedEvent` contracts.
All are exported from `hex_qec.decoders`, together with
`merge_independent_events` and `UnsupportedProjectedModel`.

The full bundle supplies the noisy circuit, code/logical supports, signed
stage/preparation/destructive-readout ledger and existing prep/frame plans.
For stage j, the builder propagates controlled model faults through only the
prefix ending at j's destructive readout, including both preparations and
earlier stages. One deterministic lane per model term is processed in bounded
chunks. Canonical reset sentinels affect maps only. The actual full-history
prep decoder and Hamming prefix frame processor turn each faulted reference
into interpreted target records before current online recovery. Only H_Z's
final m_z checks and L_Z parity enter the event signature; prep histories are
not concatenated into online H. Oracle/future bits are never supplied.

X/Y/Z errors and exactly factored independent generators of DEPOLARIZE1/2
are supported. The latter have `q=(1-(1-4^k*p/(4^k-1))^(1/2^(2k-1)))/2`;
exclusive physical Pauli branches are not incorrectly treated as independent
p/15 events. Each mechanism retains original gate p, generator q, absolute
location/support and origin stage/region. Unknown noise, noisy measurement
arguments and unrolled-layout violations fail; zero-probability instructions
are counted without decoding impossible hypothetical records. Underflow fails.

Identical complete `(detector,logical)` signatures combine by XOR probability,
never sum. Different logical labels remain separate, including logical-only
events. No-op events and all nonzero mechanisms retain provenance. The model
exports a fresh Stim DEM; `matching_matrices()` returns sparse `(m_z,E)` H,
`(E,)` L and natural-log weights `log1p(-q)-log(q)`. E indexes merged events,
not data qubits. H3 gap corrections therefore have `(shots,2,E)` axes.

`build(j)` returns cached supported results, `inspect(j)` retains diagnostics
even when the event model cannot compile, and `compile_gap(j)` returns the
same cached validated H3 graph. Hyperedges, detector-free logical terms,
q>=1/2, unsupported weights/potential/topology raise before lossy matching.
At p=0 the empty prior is inspectable/buildable; compilation explicitly asks
for the Hamming baseline instead of inventing infinite weights or fallback.

Results record `prior_convention="circuit_informed_projected"`, the named
single-fault/noiseless-reference approximation, prep convention, graphlike /
lift-valid flags, diagnostics, batch size and full/prefix/config/reference/model
hashes. Configuration includes actual prep weights/maps and native versions.
Construct/cache synchronously per worker; no shot-dependent priors, graphs or
weights are created. H4's default prior API remains available; H5 adds the public flag below.

The approximation has observed limits: raw vs prep-resolved signatures differ
for 375/1,666 and 280/2,571 mechanisms in the d=3 two-stage fixture. A plus
SE fault's logical response also differs from the reference on 13/16 paired
physical records, and two-fault responses can be nonlinear. These are retained
limitations, not exact marginal/conditional priors or validated LER gains.
See [the H4 guide](../../../docs/logical_zero_factory_h4.md) for exact equations,
API usage, scope/caching semantics, counters and test evidence.

## H5 shared effective priors

`OnlineMeasurementContext` is a frozen sector boundary carrying the entire
causal physical prefix, code H/L, all mechanisms, raw parities, actual
pre-recovery interpreter and configuration/convention identity.
`EffectivePriorBuilder(context, *, fault_batch_size=1024)` provides cached
`inspect()`, strict `build()` and `compile_gap()` using H4's single-fault
algorithm and H3's complete validation. `ProjectedDEMResult.sector` defaults
to "z" for H4 compatibility. Factory and both full-Knill Bell sectors use
the same service. `ProjectedDEMBuilder.context(j)` exposes the default Hamming
prefix or an explicitly identified alternative; cache hits never re-enumerate.

True public paths use the sector best class to correct the raw logical parity;
event-column corrections cannot be treated as data-position corrections.
Gap units are `log_weight`. Full Knill's X/Z marginals retain joint mechanism
provenance but do not perform joint correlated inference. Supported/rejected
fixtures, p=0 explicit Hamming request, actual policy/native-weight/map hashes,
rounding limits and callback responsibilities are in
[the H5 guide](../../../docs/logical_zero_factory_h5.md). That guide also
explains why observed prep-context/nonlinear responses prevent exact marginal,
conditional-posterior or LER-gain claims. The fast repository selection passes
261 tests; larger statistical cases are intentionally excluded.


## HEX-N2 factory custom noise

Factory projected fault enumeration now assigns the separate inter-stage
storage_idle region to its stage. Post-CNOT control idle already belongs to
the coupling region. Native H5 True keeps full-prefix projection and strict
complete-signature/graph checks; it therefore retains both physical sources.
Custom preparation priors/maps are rebuilt from the actual noisy preparation
before any projected model. Downstream module-local DEM consumers may exclude
pre-coupling storage/preparation residuals under their declared approximation;
no such inference change is made to Hex itself. False recovery and both gap
metrics retain their existing meanings; survivor post-CNOT faults can be
invisible to the target syndrome. See the
[noise guide](../../../docs/factory_noise_model.md); this is not a conditional
posterior or a confidence certificate for survivor correctness.
