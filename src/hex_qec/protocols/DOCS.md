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

## Proposed only

The [factory specification](../../../docs/README.md) describes a different
two-block operation: prepare zero A and plus B, `CX(B,A)`, noisy destructive
Z readout of A, and a logical X byproduct on B. Repeated stages reuse/reset
the consumed support. There is one final ideal Z evaluation oracle, excluded
from operational decoding/confidence. This one-bit factory and its builder,
ledger, batch results, gap, and `create_codecapacity_dem` flag are absent.
Full Knill and Fig. 4(d) must retain noisy final readout. H0 starts no H1 work.
