# Auxiliary-system specification status

**Current checkpoint: H5, 2026-10-16.** Public optional projected decoding
is implemented for fixed Knill and compiled factories. False preserves legacy
behavior; True has explicit graph/model restrictions and reference-context
approximation limits. See [logical_zero_factory_h5.md](logical_zero_factory_h5.md)
for stable imports, supported/rejected cases and the whole-implementation audit;
[logical_zero_factory_h4.md](logical_zero_factory_h4.md) for projection,
[logical_zero_factory_h3.md](logical_zero_factory_h3.md) for the sector metric,
[logical_zero_factory_h2.md](logical_zero_factory_h2.md) for execution and
[logical_zero_factory_h1.md](logical_zero_factory_h1.md) for the primitive.

[auxiliary_factory_theory.md](auxiliary_factory_theory.md) is an unchanged copy
of the user-supplied scientific specification. Exact conditional priors and
experiment contracts remain proposed / untested. H0 established the
baseline; H1/H2/H3/H4/H5 validate the documented circuit/frame/execution/sector/projection
boundaries and make no general fault-tolerance claim.

Read [STATUS.md](../STATUS.md#auxiliary-system-h5-public-options-and-whole-implementation-audit) for H5
evidence and the [H0 audit](../STATUS.md#auxiliary-system-h0-baseline-audit) for the audited
revision, environment, checks, and limitations, and
[the package map](../src/hex_qec/DOCS.md) for current APIs. The original
[THEORY.md](../THEORY.md), [PLAN.md](../PLAN.md), and package `DESCRIPTION.md`
files remain historical context for the earlier adaptive-SE development.


## Factory configurable physical noise (HEX-N1 / HEX-N2)

The post-H5 [noise-model guide](factory_noise_model.md) documents frozen
operation multipliers, the two explicit idle windows, factory-only opt-in
construction, consistent preparation DEM/maps, cache identities and local/full
prior distinction. The default hex_uniform and all other protocol physics
remain unchanged. Exact test evidence and known baseline failures are in
[TEST.md](../TEST.md) and [STATUS.md](../STATUS.md).
