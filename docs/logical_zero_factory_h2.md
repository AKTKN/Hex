# H2: static batched logical-zero factory

This page records the H2 checkpoint. [H3](logical_zero_factory_h3.md) now
populates `gaps` with per-stage float64 Hamming scores and adds `gap_units`;
the other execution/frame/label semantics described here remain unchanged.

H2 adds fixed multi-stage execution, causal batch decoding, and terminal
logical-error labels to the [H1 primitive](logical_zero_factory_h1.md).
Only two complete physical supports are allocated for any positive `T_tel`.
Confidence/gaps, projected priors, selection, and benchmark output are later
phases; `gaps` is currently `None`.

## Build, compile, and reuse

```python
from hex_qec.modularisation import PreparationPlan
from hex_qec.protocols import FactoryCircuitBuilder, RotatedSurfaceCodeAdapter
from hex_qec.simulation import CompiledFactory

bundle = FactoryCircuitBuilder(
    RotatedSurfaceCodeAdapter(distance=3),
    PreparationPlan(r_0=2, r_plus=2),
    physical_error=0.001,
    T_tel=3,
).build()
factory = CompiledFactory.from_bundle(bundle, seed=1729)
first = factory.sample(64, shot_id_start=0)
second = factory.sample(64, shot_id_start=64)

# Alternatively retain raw records and decode them repeatedly without sampling.
raw = factory.sample_measurements(32)
result = factory.decode(raw, shot_id_start=128)
operational = factory.decode_operational(
    raw[:, :bundle.oracle.measurements.start], shot_id_start=128,
)
```

`FactoryCircuitBuilder(..., *, T_tel=1)` preserves H1's default circuit and
record layout. Initially A is prepared in Z for `r_0` rounds and B in X for
`r_plus` rounds. Each stage uses `CX(fresh_plus, memory)` and noisy destructive
Z measurement of memory. The consumed support is reset/reprepared in X for
the next stage; roles alternate A-to-B, B-to-A, A-to-B. SE ancillas are reset
before reuse. There is no post-CNOT SE and no intermediate oracle. The single
final ideal Z readout is on the last survivor (B for odd stage counts, A for
even counts). Gates, SE, preparation and operational readout keep the existing
`hex_uniform` noise model; only this oracle is noiseless. Full Knill retains
its existing noisy final readout.

Every physical trajectory is sampled once by one precompiled Stim sampler.
No decoder decision modifies physical sampling or causes retries. Later
threshold/first-rejection analysis must select from these fixed trajectories.
`sample` and `sample_measurements` require positive integral shot counts.

## Result fields

`hex_qec.simulation` exports frozen `FactoryOperationalBatch`,
`FactoryBatchResult`, `FactoryCacheKey`, `CompiledFactory`, and the ordinary
worker-local `FactoryBatchDecoder` class. Let S be shots, T stages, n data
qubits per block, and m_z the number of Z checks.

| Field | Shape / type | Meaning |
| --- | --- | --- |
| `shot_id` | `(S,) uint64` | Caller-supplied start plus row index; overflow is rejected |
| `stage_ids` | tuple `0..T-1` | Chronological stage identifiers |
| `corrected_syndromes` | `(S,T,m_z) bool` | Prep/frame-corrected consumed-block syndrome, before online recovery |
| `raw_logical_byproducts` | `(S,T) bool` | Logical Z parity of the untouched physical consumed-block readout |
| `logical_byproducts` | `(S,T) bool` | Inferred byproducts after prep/frame interpretation and online recovery |
| `frame_resolved` | `(S,T) bool` | Prep repaired signs and online recovery equations closed successfully |
| `output_frame_x`, `output_frame_z` | `(S,T,n) bool` | Inferred output Pauli correction frame after each stage |
| `logical_error` | `(S,) bool` | Evaluation-only last-oracle logical Z mismatch against zero |
| `gaps` | `None` | Reserved for H3; no score or threshold is computed |

`FactoryOperationalBatch` contains only the first eight fields, excluding
`logical_error` and `gaps`. Frozen dataclasses prevent attribute reassignment;
returned NumPy arrays are ordinary caller-owned arrays. `frame_resolved`
reports consistency of decoder estimates, not physical error-free preparation,
logical success, a confidence score, or certification. A nonzero repaired
syndrome raises an error rather than silently marking that shot successful.

Inputs to `decode` must be nonempty binary arrays `(S, full_measurements)`.
Inputs to `decode_operational` must have exactly the operational prefix width;
passing oracle columns is rejected. Inputs are never modified. Unique IDs
across chunks require explicit `shot_id_start` offsets; the default is zero
on each call, with no implicit counter.

## Causal software frame

All expressions below are over GF(2), using row-oriented shot batches.
`PreparationFramePlan.resolve` uses only its local preparation record. It
reuses the legacy full-history DEM repair, corrects local history, then infers
pure errors repairing both families of final check signs. Its `x,z` outputs
are inferred corrections, never actual sampled faults. At a refresh reset,
both components of the previous frame on that support are discarded.

For current memory frame `(x_t,z_t)`, freshly prepared plus frame `(x_c,z_c)`,
and raw target Z readout `m`, the stage computes:

```text
interpreted readout = m XOR x_t XOR x_c
s = interpreted readout @ H_Z.T mod 2
e = Hamming_MWPM(s), requiring e @ H_Z.T = s
b = (interpreted readout XOR e) @ L_Z mod 2
new memory frame x = x_c XOR b * L_X
new memory frame z = z_c XOR z_t
```

The X contributions reflect control-to-target propagation under CNOT; the
old target Z frame propagates to the new control. As in the legacy module
callbacks, online recovery determines the logical byproduct; inferred
corrections are applied once through software interpretation. No correction
is physically inserted into the sampled circuit. The stage loop is over T;
all shot transforms are NumPy/SciPy batch operations. Surface-specific
Hamming matching lives in `decoders/factory_surface.py`, outside the stage
loop. Unsupported code families are rejected by that boundary.

Raw signed detector expressions in the circuit retain their physical record
semantics. They must not be evaluated on partly frame-corrected history as
though they were repaired signs. The builder verifies signed check flows on
their own prefixes and a strict operational DEM. Stage roles, preparation
boundaries, own-readout byproducts, contiguous IDs, and final survivor are
validated. Stage j only reads its prep/current readout and the previously
committed frame. No full-circuit m2d converter is used for inference.

The terminal evaluator runs after all operational results are fixed. It uses
the last ideal Z record XOR the last inferred X frame, a separate spatial
Hamming recovery, and logical Z parity. This convention is recorded as
`codecapacity_recovery_then_logical_Z`; the oracle never updates an operational
frame, decoder, score, or prior.

## Reset convention and legacy replay

The frame convention is `canonical_reset_xz_at_stage_boundaries_v1`.
Hex's legacy deterministic correction propagator can retain an invisible X
component through an X reset, whereas the new boundary representation clears
both components. Exact frame coordinates and later corrected byproduct bits
can consequently differ between conventions even with identical physical
action. The production physical reset circuit is unchanged.

Tests compare against independent legacy callbacks and global correction
maps. For exact coordinates, the reference map construction alone inserts a
noiseless R before RX: `R;RX` and RX implement the same state-preparation
channel, and the extra reference sentinel clears the deterministic frame.
It is never inserted into physical sampling or the production circuit.
Additional tests replay the unmodified legacy maps and check equal terminal
labels and frames differing only by stabilizers (zero syndrome and logical
action for this k=1 CSS code). This distinction was found by initially failing
frame comparisons and is recorded in [TEST.md](../TEST.md#auxiliary-system-h2-batched-factory).

## Cache identity and lifetime

Build once and retain one `CompiledFactory` per case/worker. Its frozen
configuration owns a copied circuit, one compiled sampler, one causal decoder,
and a hashable key covering code supports/distance, p/noise, both preparation
depths, T, circuit hash, frame convention, prep prior, terminal-label convention,
decoder policy, seed, and Stim/PyMatching versions. A changed circuit hash is
rejected. `factory.circuit` returns a copy. There is no process-global cache;
callers can index their own worker-local cache with `cache_key`.

Preparation templates are cached by physical support, basis, and depth.
Repeated plus preparations bind the same local circuit, four CSS decoder
handles, m2d converters, and sparse end-frame maps to a later record region.
At most three templates are needed: A-zero, B-plus, A-plus. The surface
readout adapter additionally caches H_Z/logical transforms and separate online
and terminal matching objects. Sampling/decoding never constructs new
circuits, samplers, matching graphs, deterministic simulators, or frame maps.
No weights are changed per shot. Constructor-count tests enforce this
boundary without timing assertions.

Native RNG and decoder handles remain mutable private state. Use synchronously
within one worker, do not mutate source bundle plans after compilation, and
construct independently in other workers. This object is not a thread-safe
shared handle or a pickle transport. Reusing it advances the sampler RNG.
Equal seeds reproduce equal raw records for the same Stim version/platform
and identical sampling chunk partition; different partitions/backends are not
promised to realize the same faults. Decoding the same records/configuration
is deterministic and agrees for scalar, whole-batch, and partitioned input.

## Tested scope and limits

The final targeted H2/H1/legacy run passed 111 tests (34 H2, 41 H1, 36 legacy),
with two inherited statistical tests excluded. H2 tests include d=3 zero
noise T=1/2/3, a d=5 T=2 smoke case, role/reset reuse, oracle/future isolation,
both Pauli frame maps, injected faults on both roles at each stage, persisting
logical faults, reproducibility, dtypes/IDs, scalar/batch equality, causal and
decoder failure guards, cache keys and constructor counts. New physical
batches contain at most 64 seeded shots; exact runs are in [TEST.md](../TEST.md).

Legacy preparation projection/weight conventions are preserved and not
certified as optimal post-repair priors. Online/terminal recovery uses spatial
Hamming weights. No logical gap, projected circuit prior,
`create_codecapacity_dem` option, postselection, YAML/Parquet runner, full test
suite, large Monte Carlo, speed benchmark, general fault-tolerance proof, or
paper reproduction is supplied by H2. H3 has not started.
