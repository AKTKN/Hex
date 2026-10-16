# Modularisation: decoding and frame contract

Detailed class descriptions: [DESCRIPTION.md](DESCRIPTION.md).

## Implemented today

`modularised_circuit.py` defines `no_measurement_module`, `measurement_module`,
`detector_module`, `css_detector_module`, `logical_measurement_module`,
`only_postselection_module`, and `modularised_circuit`. `module_generation.py`
builds state preparations, transversal CNOT, Bell/Steane correction, and final
logical measurements. `results.py` supplies `ModuleDecodeResult`,
`SimulationSummary`, `SimulationResult`, patch/pair statistics, and output
normalization; legacy correction arrays and `(corrections, postselection)`
remain accepted.

Batch callbacks take `(shots, local_measurements)` or `(shots, detectors)` and
produce `(shots, correction_variables)`. A correction-to-measurement map has
shape `(correction_variables, total_protocol_measurements)`. With correction
batch `C` and map `M`, the software update is `records ^= (C @ M) mod 2`.
Deterministic propagation disables stabilizer randomization; physical sampling
does not. Corrections must affect subsequent decoding exactly once.

`css_detector_module.c_func` converts local raw records to X/Z detector
batches, infers DEM corrections, corrects the local history, and decodes the
final X/Z check signs. It returns columns in order `[X DEM, Z DEM, X-check
repair, Z-check repair]`. X-check repair is physical Z and Z-check repair is
physical X. `c_func_rich` returns the same correction and optional aggregated
confidence/metrics through `ModuleDecodeResult`. The aggregator receives
`CSSInnerDecodeResults(x_dem, z_dem, x_capacity, z_capacity)`; omission leaves
confidence `None`.

`generate_correction_to_measurement_flip_map()` must precede static execution.
`simulate(max_shots, max_errors_before_halting, results_path="", seed=None)`
compiles one global sampler/converter, samples batches of 256, applies module
corrections chronologically, checks final detector residuals, and returns
`(samples_performed, logical_errors)`. A partial last batch is not supported.
`simulate_result(..., detail_level="summary", seed=None)` wraps those counts;
fixed runs expose no per-shot records even at `analysis`/`debug` detail.

`AdaptiveSERounds(short_rounds, long_rounds, policy)` enforces
`1 <= short_rounds < long_rounds`. `AdaptiveStatePrepModule` holds short,
extra, and full-long circuits/decoders; long decoding uses the full history.
Execution lives in [simulation](../simulation/DOCS.md).

## Baseline limitations and reuse

CSS, Bell, and final-readout decoders are created during module setup; copied
CSS templates share native decoder handles for synchronous use. CSS m2d
converters are still compiled inside each decode callback. Generic
`detector_module`, noiseless-preparation, and Steane callbacks construct
decoders during calls. These are existing costs, not a compliant future
factory cache design. Legacy matchable priors use `log1p(q)-log(q)` and an
edge-projection sum; H0 preserves that behavior without certifying it as
`log((1-q)/q)` or an exact independent-event marginal.

Support remapping is text-based, some constructors use mutable defaults, and
`only_postselection_module` remapping is incomplete. The CSS constructor's
`new_support` handling is unreachable after `_profile_section` returns;
existing builders explicitly call `set_support` instead. Representative CSS
fault propagation asserts single-Pauli faults. No new guarantee is made for
arbitrary hyperedges, signed factory flows, or general dynamic circuits.

H0 ran `test_phase1_decoder_adapters.py` and `test_phase2_results.py`: 15
passed. See [TEST.md](../../../TEST.md#auxiliary-system-h0-documentation-baseline).

## H1 contracts and preparation-frame maps

`factory.py` adds frozen `CodeSpec`, `PreparationPlan`, `BlockSupport`,
`CircuitRegion`/`IndexRange`, `MeasurementLedger`/`MeasurementRecord`,
`RecordParity`, `SignedCheckFlow`, `TeleportationStage`, and `PreparationFrame`
contracts plus the `FactoryCodeAdapter` protocol. Supports and signed parity
indices are immutable tuples; repeated parity indices cancel over GF(2).

`PreparationFramePlan(module,block,region)` caches X/Z m2d converters, reuses
the existing four CSS decoder handles/local history maps, and builds sparse
end-frame maps `(legacy_variables,n)` once. `resolve(local_measurements)`
requires exactly `(shots,prep_measurements)` binary values. It performs the
existing DEM-history correction and final sign repair, returning inferred
`x,z` Pauli frames `(shots,n)` and repaired X/Z signs `(shots,m_x/m_z)`.
Nonzero repaired signs raise `ValueError`. It neither samples nor reads any
online/oracle record. Native handles are for synchronous worker-local reuse.

`corrected_history` includes DEM corrections but does not retroactively apply
end-of-prep pure errors to past check measurements. Pure errors are included
in `x,z` and the separate repaired signs. With `CX(B,A)`, future measurements
must use `x_A'=x_A XOR x_B` and `z_B'=z_B XOR z_A`; raw terminal detector
expressions and repaired check signs must not be mixed. H1 validates both
frame maps exactly against the legacy Pauli-to-measurement machinery and
legacy CSS correction arrays, including p=0 intrinsic sign randomness.

See [the H1 guide](../../../docs/logical_zero_factory_h1.md) for preparation
equations and field semantics. H2 adds `PreparationFramePlan.bind(region)`:
a shallow view changing only the absolute record range, validating its width,
and sharing local circuit, decoders, converters and sparse frame maps. It
does not recompile or remap the same physical support. Use synchronously
within one worker and do not mutate plans after compilation.

The H2 frame convention `canonical_reset_xz_at_stage_boundaries_v1` discards
both components on refresh reset. Legacy deterministic RX propagation may
retain an invisible X component; exact canonical-map and unmodified physical
equivalence tests cover the distinction. Sampling/stage processing lives in
`simulation/factory.py`, with [equations, cache/result semantics and limits](../../../docs/logical_zero_factory_h2.md).

## H5 complete Bell contexts

`generate_bell_measurement_and_correction_module` keeps all six positional
arguments and adds keyword-only `create_codecapacity_dem=False` and
`online_contexts=None`. False retains native Hamming callbacks. True requires
complete `(x_context,z_context)` objects ending at that remapped physical
Bell gadget; a local gadget cannot infer preceding preparations. Missing,
mismatched or unsupported contexts raise before use.

`online_context.py` installs validated `EffectivePriorBuilder` models and
logical parity callbacks, preserving the logical Z/X correction ordering and
`(shots,2)` shape for its supported one-logical-qubit case. The fixed-Knill
orchestrator first builds the legacy physical circuit/maps, then configures
stages chronologically. Interpreters replay actual prep and earlier Bell
corrections on prefix-only cached sparse maps; no current recovery, final
readout noise or label enters the prior. Each module exposes inspectable
`projected_priors`. X/Z correlations are not jointly decoded.

CSS modules add idempotent `cache_m2d_converters()`, enabled only by True
Knill setup. Template callbacks share their two cached native converters.
False retains historical per-callback converter construction and all seeded
behavior. Cached handles are synchronous/worker-local and must not be mutated.
See [the H5 guide](../../../docs/logical_zero_factory_h5.md) for exact equations,
prior validity, hashes, supported/rejected settings and whole-audit evidence.
