# H3: surface MWPM homology-sector gap

H3 supplies `SurfaceMWPMHomologyGap` and adds causal per-stage `float64`
`gaps[shot,stage]` to the [H2 factory result](logical_zero_factory_h2.md).
The implemented score is a min-sum sector difference in a spatial
independent-edge model. The factory uses unit Hamming weights. Circuit-informed
priors and threshold/abort analysis remain later phases; H4 has not started.

## Standalone API and units

```python
import numpy as np
from hex_qec.decoders import SurfaceMWPMHomologyGap
from hex_qec.protocols import RotatedSurfaceCodeAdapter

adapter = RotatedSurfaceCodeAdapter(3)
_, H_Z, _, L_Z = adapter.matrices
decoder = SurfaceMWPMHomologyGap(
    H_Z, L_Z, np.ones(H_Z.shape[1]), score_units="hamming_weight",
)
scores = decoder.decode_batch(np.zeros((16, H_Z.shape[0]), dtype=np.uint8))
assert np.all(scores.W0 == 0)
assert np.all(scores.W1 == 3)
assert np.all(scores.gap == 3)
```

`SurfaceMWPMHomologyGap(check_matrix, logical_z, weights, *, score_units="weight")`
receives binary H of shape `(m,n)`, one logical row L of shape `(n,)` or
`(1,n)`, and one positive finite weight per input edge, shape `(n,)`.
`decode_batch` requires a nonempty binary array `(S,m)`, without truth data or
measurement histories. `HomologyGapBatch` is a frozen result dataclass:

| Field | Shape/type | Meaning |
| --- | --- | --- |
| `sector_costs` | `(S,2) float64` | Minimum correction costs for `L e=0,1` |
| `W0`, `W1` | `(S,) float64` properties | Views of the two cost columns |
| `corrections` | `(S,2,n) bool` | Edge corrections satisfying each sector |
| `gap` | `(S,) float64` | `abs(W1-W0)`, nonnegative |
| `best_class` | `(S,) uint8` | Lower-cost correction class; exact cost ties choose zero |
| `score_units` | string | `weight`, `hamming_weight`, or `log_weight` |

Arrays are caller-owned. `hamming_weight` requires all weights exactly one;
`log_weight` labels caller-supplied positive log weights. No probabilities are
inferred, clipped, or transformed by this API. Corrections within a tied sector
follow the installed native solver's fixed graph/tie order; no randomization
is used. Numerical ties mean equality of recomputed float64 costs.

For each syndrome s, the definition is
`W_b(s)=min_{H e=s, L e=b} sum_j w_j e_j`. With independent Bernoulli priors
one can supply `w=log((1-p)/p)` for `0<p<1/2`; the score still compares minimum
chains. Posterior log-odds instead compare **sums** of probabilities over all
patterns in each class. They generally differ even on d=3, as a focused test
demonstrates. Thresholds in Hamming and log-weight units are not interchangeable.
`best_class` describes a correction's L parity, not the physical logical state
or the raw teleportation byproduct.

## Two-boundary construction and equivalence

1. Each input error column has one or two nonzero detector endpoints. Solve
   a binary potential u on internal two-endpoint edges `(a,c)` satisfying
   `L[e]=u[a] XOR u[c]`. A deterministic component traversal chooses root
   potential zero. An inconsistent cycle is rejected.
2. A one-endpoint edge at a connects to B1 iff `L[e] XOR u[a]=1`, otherwise
   B0. Set `H_ext=[H;B0;B1]`. Every column now has exactly two endpoints.
3. For desired class b, set `t1=b XOR (u dot s mod 2)` and
   `t0=parity(s) XOR t1`. Decode `[s,t0,t1]` on the cached lifted graph.
   Decode b=0 and b=1 in two native batch calls on that same object.
4. Check the full lifted residual, recompute each cost with the original
   float64 edge weights, compare costs, and report the absolute gap.

The identity `L = u^T H XOR B1` implies that a lifted solution with syndrome
`[s,t0,t1]` has `L e=b`. Conversely, an original correction with `(H e,L e)`
equal to `(s,b)` satisfies the lifted syndrome, because each extended column
has even degree and therefore `B0 e XOR B1 e=parity(s)`. Feasible correction
sets and their weights are unchanged by the lift. This is the sector reduction
validated against enumeration, rather than an appended logical-check heuristic.

**B0 and B1 remain constrained detector vertices.** They are not free matching
boundary nodes. The implementation never marks them with `set_boundary_nodes`.
It validates empty native boundary sets and the extended detector count.
Directly appending L to H could produce degree-three columns and is not used.
Positive-weight parallel edges with identical lifted endpoints have identical
syndrome/logical action: keeping the cheapest representative preserves these
minimum costs. `ensure_num_fault_ids(n)` preserves correction width when a
last-index parallel edge is discarded. This is not probability aggregation.

## Supported domain and numerical limits

The supported domain is a spatial planar graph with one tracked logical row,
degree-1/2 error columns, consistent internal potential, and a connected lift
including both logical boundaries and every detector. Binary input, column
degrees, potential identity, connectedness and planarity are checked at setup.
The standalone H/L interface validates one binary observable; H alone does
not establish an arbitrary CSS code's k. Factory use is limited to the bundled
k=1 rotated-surface adapter. Nonplanar graphs, disconnected lifts, degree-3+
hyperedges, zero-detector columns (including undetectable logical events), and
multiple logical rows are rejected. No unsupported event is silently dropped.

Weights must be finite, strictly positive, at most `2**24-1`, with min/max
ratio at least `1/(2**24-1)`. The latter conservative guard rejects dynamic
ranges below the native weight resolution. Zero/infinite/negative weights
are rejected, rather than treating p=0 or p=1/2 as an ordinary finite prior.
An absolute scale too small for finite native normalization is also rejected.
The **factory's explicit p=0 rule is to retain the same finite unit Hamming
model**, independent of physical p. Its noiseless zero syndrome has gap d,
not an infinite posterior certainty. No log of zero is evaluated.

The graph reduction is exact; the native solver is numerical. Installed
PyMatching 2.3.1 rounds noninteger weights internally, so nearly degenerate
weighted chains below its resolution need not be distinguished. Returned
costs are recomputed from original weights; native reported costs are checked
with an n-edge rounding allowance, not mistaken for exact original sums.
The factory's integral unit weights avoid this rounding ambiguity. Exhaustive
weighted tests compare to brute force within float64 tolerance; they do not
certify arbitrary ill-conditioned real-valued inputs. See the official
[PyMatching batch API](https://pymatching.readthedocs.io/en/stable/api.html#pymatching.Matching.decode_batch)
and its version-pinned [weight conversion](https://github.com/oscarhiggott/PyMatching/blob/v2.3.1/src/pymatching/sparse_blossom/driver/user_graph.h)
and [normalization](https://github.com/oscarhiggott/PyMatching/blob/v2.3.1/src/pymatching/sparse_blossom/driver/user_graph.cc).

## Factory integration and lifetime

The existing H2 build/compile/sample calls now return `FactoryBatchResult`
with `gaps.shape==(shots,T_tel)`, dtype `float64`, and
`gap_units=="hamming_weight"`. Other record/frame/label meanings are unchanged.
The old constructor default `gaps=None` is retained for compatibility with
callers directly constructing result dataclasses; production decode fills it.
`FactoryOperationalBatch` retains its old fields and oracle-free interface.

`SurfaceFactoryReadout` owns a third matching graph solely for gap evaluation.
Each stage scores its own prep/frame-corrected syndrome **before** online
recovery. It does not use raw byproducts, future records, final oracle,
sampled faults, or terminal labels. H2's independent online recovery and
byproduct/frame update remain unchanged; score tie policy does not replace
legacy correction tie choices. The terminal recovery handle remains separate.
`decode_operational` also executes the causal loop but returns its original
operational fields. No score controls sampling, retries, cuts, or branches.

One graph, sparse lift, logical transforms, potential and weights are cached
per decoder. `cache_identity` includes H topology, L, weights, units, lift
version and native version. Inspection properties return copies. Factory
keys add `gap_policy="surface_two_boundary_hamming_v1"`; weights are always
ones in this phase. Construction counts increase from 14 to 15 matching
objects for a fresh T=3 factory, with one sampler; none are built during
sampling/decoding. The sector loop has length two, the factory loop length T,
and shots remain native/NumPy batches. Handles are synchronous and worker-local.

NetworkX is now declared directly for setup-time connectedness/planarity
validation. Version 3.3 was already installed as a required PyMatching
dependency; no installation was needed. No new sampler or physical circuit
was introduced. Full Knill retains its noisy final readout.

## Validation and remaining scope

The H3 tests enumerate all `2^9` d=3 X errors as a classical oracle for both
sector minima at every syndrome. Four weight vectors (three nonuniform) and
two logical-row gauges cover nonzero potentials and parity conventions.
They also cover a hand graph, exact ties, parallel-edge width, graph/weight/
input/native failure guards, posterior-vs-min-sum distinction, cache identity,
two batch calls, scalar/batch equality, causal factory scores, and finite
p=0 behavior at d=3 T=1/2/3 and d=5 T=2. Physical fixtures use <=32 shots.
See [TEST.md](../TEST.md#auxiliary-system-h3-surface-logical-gap) for commands,
initial failures/fixes, and final regression evidence.

The score is exact for the specified spatial Hamming model, not an exact
conditional noise model after nonlinear preparation repair. H4 projected
priors, `create_codecapacity_dem`, threshold/cost analysis, benchmark output,
large Monte Carlo, a general fault-tolerance proof, and paper reproduction
remain outside H3.
