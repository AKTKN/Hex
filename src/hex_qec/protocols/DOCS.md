# Protocols: full Knill baseline and factory separation

Detailed call signatures and examples: [DESCRIPTION.md](DESCRIPTION.md).

## Implemented today

`knill_online_offline(matrices, syndrome_measurement_rounds,
online_decoder_generator, offline_decoder_generator,
matchable_offline_decoding, physical_error, max_shots,
max_errors_before_halting, pauli, num_teleportations, results_path="",
surface_code=False, seed=None)` returns the legacy two-count tuple.

For `T` teleportations it allocates `2*T+1` complete block supports. The input
data is encoded ideally in the selected X/Z basis. Each cycle prepares fresh
noisy zero and plus resources, applies `CX(plus, zero)`, then Bell coupling
`CX(data, zero)` and noisy destructive X/Z measurements. The plus block
becomes the new data. Both resources use the same supplied SE depth. Final
readout is noisy at `physical_error`; there is no ideal factory oracle.

For Bell records `m_x, m_z` of shape `(shots, n)`, the online decoder infers
`e_z` from `H_X m_x` and `e_x` from `H_Z m_z`. Corrected logical parities
`L_X(m_x+e_z)` and `L_Z(m_z+e_x)` drive logical Z and X corrections on the
survivor. Online generators receive check matrices without explicit weights;
with PyMatching this retains default unit/Hamming weights. Offline CSS repair
uses the full preparation record and its separate legacy prior convention.

`knill_online_offline_adaptive(...)` instead takes `AdaptiveSERounds`, optional
`confidence_aggregator`, detail level, batch size, seed, surface ordering,
profiler, and warm-up count. It returns `SimulationResult`. Zero/plus policies
are evaluated separately and combined by boolean OR, extending both patches
if either requests it. Analysis arrays have shot/event or shot/pair axes;
they describe adaptive preparation, not proposed factory stages.

`steane_online_offline(...)` remains a fixed-round tuple-returning entry point
without the Knill-only surface-ordering or seed options. All use module
gadgets and software correction propagation. Static Knill compiles once per
simulation call and samples 256-shot batches; it may exceed requested shots.
Adaptive execution is still a per-shot reference implementation. Input
validation and general causal cross-module detector support remain limited.

Existing fixed/adaptive endpoint tests are listed in
[tests/DOCS.md](../../../tests/DOCS.md); H0 did not rerun protocol Monte Carlo
or establish agreement with a paper figure.

## H2 fixed multi-stage factory

`FactoryCircuitBuilder(adapter, PreparationPlan(r_0,r_plus), physical_error, *, T_tel=1)`
and `FactoryCircuitBundle` are exported alongside `RotatedSurfaceCodeAdapter`.
`logical_zero_factory.py` builds a positive fixed number of stages: initial
noisy zero A and plus B preparation, `CX(B,A)`, noisy destructive Z readout of
A, then reset/plus-reprepare A and exchange roles. Only the same two complete
supports and their reset ancillas are reused. Exactly one final ideal Z oracle
reads the last survivor; no intermediate oracle, third block, or post-gate SE
is inserted. Default T=1 preserves H1's circuit/ledger/flows.

The bundle carries raw record/stage ranges, a signed CSS check ledger,
prep-only frame-resolution plans, oracle indices, and read-only metadata.
`build()` verifies signed flows on each prefix, a strict operational DEM,
alternating roles, causal prep/readout ranges, own-readout byproducts, and
the last-survivor oracle. Prep templates share native decoders, local
converters and sparse frame maps across repeated uses on the same support.
`operational_circuit` excludes the oracle and has no observable annotations;
raw logical A parity is random and only records the byproduct source.

For the initial raw records the terminal check sign is
`H_Z*m_A XOR last_Z_A XOR last_Z_B`. Later stages use the propagated signed
checks of memory and the new plus preparation. After preparation repair, use the
inferred Pauli frames and repaired signs described in
[the H1 guide](../../../docs/logical_zero_factory_h1.md). Circuit building
remains separate from execution: `hex_qec.simulation.CompiledFactory` now
samples/decodes batches and supplies evaluation labels. See
[the H2 guide](../../../docs/logical_zero_factory_h2.md) for the causal frame
equations and result shapes.

Full Knill and Fig. 4(d) retain noisy final readout. H3's
[spatial sector gap](../../../docs/logical_zero_factory_h3.md) is now supplied
by the separate decoder/executor. H4 supplies an explicit
[projected-prior builder](../../../docs/logical_zero_factory_h4.md), preserving
physical builders and default execution. The public `create_codecapacity_dem`
option remains H5 work and is not implemented here.
