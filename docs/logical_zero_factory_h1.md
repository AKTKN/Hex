# H1: single-stage logical-zero factory

This is the H1 checkpoint description. [H2](logical_zero_factory_h2.md) now
provides sampling, stage decoding, terminal labels, and repeated support reuse;
the default single-stage physical circuit and ledger remain unchanged.

H1 implements a circuit primitive and preparation-frame boundaries for
`T_tel=1`. It does not provide a factory sampling runner, online stage decoder,
production logical-error labels, multi-stage reuse, confidence, or projected
priors. Those remain later phases of the
[scientific specification](auxiliary_factory_theory.md).

## Build once per configuration

```python
from hex_qec.modularisation import PreparationPlan
from hex_qec.protocols import FactoryCircuitBuilder, RotatedSurfaceCodeAdapter

bundle = FactoryCircuitBuilder(
    RotatedSurfaceCodeAdapter(distance=3),
    PreparationPlan(r_0=2, r_plus=3),
    physical_error=0.001,
).build()
```

`RotatedSurfaceCodeAdapter` is the only supplied family adapter. It loads the
existing matrices, checks CSS/logical commutation and logical anticommutation,
allocates blocks through `generate_blocks`, and reuses the surface-specific
SE/`css_detector_module` builders. It accepts bundled odd distances >=3.
`CodeSpec` describes check/logical supports as immutable tuples of data
positions; the generic interfaces do not assume `n=d*d`. Physical support IDs
are separate ordered tuples including each block's check ancillas.

Depths must be positive integers; `physical_error` must be finite in [0,0.5].
The noise is Hex's existing uniform preparation/readout flips and two-qubit
depolarization, with no added idle or one-qubit noise. Matchable preparation
priors retain the audited legacy formula/projection. No legacy API changed.

## Physical circuit and record regions

The circuit has exactly two complete disjoint supports, A and B:

1. Noisy Z reset of A and exactly `r_0` X/Z SE rounds.
2. Noisy X reset of B and exactly `r_plus` X/Z SE rounds.
3. Transversal `CX(B, A)` using Hex's interleaved CNOT/noise fragment.
4. Noisy destructive Z measurement of A and deterministic terminal Z checks.
5. One ideal destructive Z readout of B, exclusively for evaluation.

There is no data block D, post-gate SE, extra preparation round, physical
software-repair gate, feed-forward gate, or intermediate oracle. B survives the
operational circuit. H1 uses two supports for this single stage; recycling them
over additional stages is not implemented yet.

`FactoryCircuitBundle` exposes:

| Field | Meaning |
| --- | --- |
| `circuit` | Complete physical Stim circuit, including the final ideal readout |
| `operational_circuit` | Copy of the prefix excluding that readout |
| `code`, `preparation`, `blocks` | Code supports, independent depths, full physical block IDs |
| `ledger.records` | Absolute measurement index, physical qubit/basis, block, operation, stage, SE round/check basis, evaluation flag |
| `stages[0]` | Preparation/coupling/readout instruction and record ranges, input/output signed checks, terminal checks, raw logical parity |
| `preparation_frames` | Two reusable prep-only decoder/map plans, in A/B order |
| `detector_flows` | Every declared deterministic detector with its signed record expression and prefix boundary |
| `oracle`, `oracle_record_indices` | Terminal evaluation region and exact reserved indices |
| `metadata` | Read-only mapping of immutable configuration/convention/hash values |

Ranges are half-open; use `region.measurements.slice` or
`region.instructions.slice`. SE ancillas are physically read with `MR` in Z;
`check_basis` distinguishes the X/Z checks they measure. `se_round` is one-based;
stage index is zero-based. All data readout is Z. Stim circuits and native
decoder objects themselves are mutable; copy a circuit before fault injection,
and use a bundle's decoder handles synchronously within one worker.

## Signed checks and inferred frames

`RecordParity` represents `XOR(records) XOR constant`, cancelling repeated
indices. `SignedCheckFlow` associates such a sign with a CSS check on a block
at an instruction boundary; empty qubit support denotes a detector closure.
Input signs are the corresponding last preparation check records. Under
`CX(B,A)`, single-block signs transform as

```text
sigma_X(A)' = sigma_X(A)             sigma_X(B)' = sigma_X(B) XOR sigma_X(A)
sigma_Z(A)' = sigma_Z(A) XOR sigma_Z(B)  sigma_Z(B)' = sigma_Z(B)
```

The raw terminal detector is `H_Z*m_A XOR sigma_Z(A) XOR sigma_Z(B)`.
These expressions describe the raw physical record, before inferred repairs.
The raw logical Z parity of A is random and appears only as
`stage.raw_logical_outcome`; it is neither a detector nor an observable.

`PreparationFramePlan.resolve(local_measurements)` accepts exactly one local
preparation batch `(shots, prep_measurements)`. It reuses Hex's four decoder
handles and DEM correction-to-local-measurement maps with cached X/Z m2d
converters. It first corrects the history using DEM inference, then infers pure
errors from both final check families. Unresolved repair signs raise an error.
The result is a `PreparationFrame`:

- `corrected_history`: DEM-corrected record; end-of-preparation pure errors do
  not retroactively overwrite these past measurements.
- `corrections`: `(shots, variables)` in legacy `[X DEM, Z DEM, X-check repair,
  Z-check repair]` order.
- `x`, `z`: inferred full physical Pauli frame at the prep boundary, each
  `(shots, n)` boolean; these are estimates, never sampled fault truth.
- `x_signs`, `z_signs`: repaired check signs, shapes `(shots,m_x/m_z)`.
  For example `z_signs = last_Z(corrected_history) XOR H_Z*x_repair`.

Setup-only deterministic Pauli propagation turns Hex's representative DEM
corrections into sparse end-frame maps `(variables,n)`, including the legacy
hyperedge-to-edge projection and pure-error repairs. Zero-mechanism DEMs at
p=0 have empty DEM columns; sign repair still handles intrinsic randomness.

For later online processing the CNOT frame is
`x_A'=x_A XOR x_B`, `z_A'=z_A`, `x_B'=x_B`, `z_B'=z_B XOR z_A`.
Thus use `m_A'=m_A XOR x_A XOR x_B` and the **repaired** signs in the online
syndrome. Do not run a raw detector expression on partially frame-updated
records without also updating its sign terms. Tests perform this boundary
calculation and confirm both logical byproduct branches; a public stage
decoder and production terminal-label path are deferred to H2.

## Oracle isolation, checks, and limits

No detector or observable uses the oracle; the bundle contains no observable
annotations at all. Prep resolution rejects full-circuit records rather than
silently accepting oracle/future columns. The final label convention reserved
in metadata is ideal Z readout followed by spatial code-capacity recovery and
logical Z parity after the inferred byproduct. Only test helpers calculate
that label in H1. Full Knill/Fig. 4(d) final readout remains noisy.

`build()` validates signed input/output/detector flows on their causal prefixes
with Stim `unsigned=False` and extracts a strict operational DEM with gauge
detectors and approximate disjoint errors disabled. `bundle.validate()` can
repeat these structural checks. This validates noiseless signs, record access,
and deterministic detector structure; it does not prove gadget fault tolerance
or exactness of nonlinear decoded priors. Strict extraction is undecomposed,
so it does not assert graphlikeness of circuit faults.

`tests/test_factory_circuit.py` covers zero-noise d=3/5, both random byproducts,
pure-error signs from both preparations, reversed-CNOT rejection, exact depths
and supports, noise/oracle boundaries, eight injected fault cases,
an output logical fault, legacy frame-map equality, local-only decoder access,
batch partition equivalence, object reuse, and invalid inputs. New physical
batches contain at most 128 shots. See [TEST.md](../TEST.md#auxiliary-system-h1-single-stage-factory)
for exact executed commands and outcomes.
