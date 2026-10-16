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
equations, noise and label convention. This is ordinary spatial recovery;
no homology-sector gap or circuit-informed prior is implemented here.

## Proposed only: gap and priors

The [proposed/untested specification](../../../docs/README.md) defines
`W_b(s)=min_{He=s, Le=b} sum_f w_f e_f` and `gap=abs(W_1-W_0)`.
This min-sum sector difference is not posterior log-odds, which sum over
patterns. Hamming and log-weight thresholds use different units.

The separate `decoder-confidence` checkout's `FUTURE.md` records unresolved
gap correctness concerns. Its unsplit constrained path appends an observable
row, and its MWPM builder calls `Matching.from_check_matrix`. An appended row
can turn degree-two columns into degree-three hyperedges. Neither correctness
nor graphlikeness is assumed here; no code was imported or copied from it.

Future `SurfaceMWPMHomologyGap` requires a validated two-boundary lift,
positive finite weights, explicit zero-noise handling, and d=3 exhaustive
sector checks. Future projected priors must retain complete detector/logical
signatures (including detector-free logical events), combine identical
independent events with `q1+q2-2*q1*q2`, and reject unsupported hyperedges.
Nonlinear offline repair prevents calling a raw circuit projection an exact
conditional posterior. Graphs, mappings, and decoders must be cached per
complete configuration, with no oracle or later-stage data in inference.
None of these new APIs or validations exists in H0.
