# Hex package and auxiliary factory

Audited source: `5de58f2f80791054411ad3c0885a4fe3671ed56a` (`hex-adaptive`).
H0 added documentation on `auxiliary-system`; H1/H2 add an independent factory
primitive and batched execution without changing legacy circuit/decoder paths. The package-root
`__init__.py` is empty; import APIs from the child packages.

## Implemented today

| Directory | Responsibility and API entry points |
| --- | --- |
| [circuit_generation](circuit_generation/DOCS.md) | CSS matrices, block supports, noisy SE circuits, ideal encoders |
| [modularisation](modularisation/DOCS.md) | Module classes, gadget builders, sparse correction propagation, result dataclasses |
| [decoders](decoders/DOCS.md) | Decoder protocols/adapters, BP-LSD confidence, surface factory Hamming readout |
| [protocols](protocols/DOCS.md) | Fixed/adaptive Knill, Steane, fixed two-support factory builder |
| [simulation](simulation/DOCS.md) | Stateful/adaptive execution, compiled factory batches, policies, profiling |

Code matrices are `(H_X, H_Z, L_X, L_Z)`, with operators as rows and data
qubits as columns. Shot batches are `(shots, measurements/checks/variables)`.
For a check matrix `H`, correction inference targets `H e = s` over GF(2).
Software corrections change the interpretation of recorded measurements via
precomputed maps; they are not additional physical fault samples or gates.

The fixed engine samples a complete compiled Stim circuit, then processes
module records chronologically. The adaptive reference path instead continues
each selected shot's existing `FlipSimulator` state. Its deterministic maps,
suffixes, and reference samples have executor lifetime caches, but physical
states and observations remain per-shot. The separate H2 factory path samples
one fixed unrolled circuit and processes stages across batch arrays.

The legacy noise parameter covers preparation/readout flips and two-qubit
depolarization. No separate idle/gate-duration model is supplied. See
[STATUS.md](../../STATUS.md#auxiliary-system-h0-baseline-audit) and
[tests/DOCS.md](../../tests/DOCS.md) for current versions, checks, and source
limitations; older detailed descriptions are linked from each child guide.

## H2 factory and remaining proposals

`FactoryCircuitBuilder(RotatedSurfaceCodeAdapter(d), PreparationPlan(r_0,
r_plus), physical_error=p, T_tel=T).build()` returns `FactoryCircuitBundle`.
Import builder/bundle/adapter from `hex_qec.protocols` and contracts from
`hex_qec.modularisation`. It reuses two complete supports for T positive
CNOT/destructive-Z stages, with a signed ledger and one final ideal oracle.
`PreparationFramePlan.resolve(local_records)` resolves each preparation using
cached Hex decoders/converters and sparse end-frame maps. See the
[H1 API guide](../../docs/logical_zero_factory_h1.md) for preparation details.
From `hex_qec.simulation`, `CompiledFactory.from_bundle(bundle, seed=...)`
owns a cached sampler/decoder, exposes `sample`, `sample_measurements`,
`decode`, and oracle-free `decode_operational`, and returns shot-first boolean
stage records and terminal labels. See the [H2 API guide](../../docs/logical_zero_factory_h2.md)
for equations, shapes, reset convention, cache keys, lifetime, and tests.

The [proposed/untested specification](../../docs/README.md) separates a
two-block one-bit logical-zero factory from full Knill EC. `CodeSpec`,
`PreparationPlan`, `TeleportationStage`, `FactoryCircuitBundle`, ledger and
prep-frame contracts are implemented in H1. `CompiledFactory`,
`FactoryBatchDecoder`, `FactoryOperationalBatch`, `FactoryBatchResult`, and
`FactoryCacheKey` are implemented in H2. `SurfaceMWPMHomologyGap` and
projected-prior APIs remain future targets; `gaps=None` reserves the result
slot without a score algorithm. Circuit
building, signed-frame processing, decoding, and analysis must remain distinct;
surface-specific graph assumptions belong in a surface adapter. Hex must not
gain YAML, Parquet, or filesystem experiment runners for this extension.

Stage decodes read only causally available operational records.
The factory's final ideal Z oracle is evaluation-only; full Knill retains noisy
final readout. No oracle/fault truth may enter recovery, confidence, priors, or
resource certification. See [AGENTS.md](../../AGENTS.md#auxiliary-system-development-contract-h0).
