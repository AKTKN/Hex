# Auxiliary-system specification status

**Current checkpoint: H2, 2026-10-16.** Fixed multi-stage two-support reuse,
compiled batch sampling, causal frame decoding, and last-oracle labels are
implemented and tested. See [logical_zero_factory_h2.md](logical_zero_factory_h2.md)
for current execution APIs and [logical_zero_factory_h1.md](logical_zero_factory_h1.md)
for the original primitive. H3 has not started.

[auxiliary_factory_theory.md](auxiliary_factory_theory.md) is an unchanged copy
of the user-supplied scientific specification. Homology gap, projected priors,
and experiment contracts remain proposed / untested. H0 established the
baseline; H1/H2 validate the explicitly documented circuit/frame/execution
boundaries and make no general fault-tolerance claim.

Read [STATUS.md](../STATUS.md#auxiliary-system-h2-batched-factory) for H2
evidence and the [H0 audit](../STATUS.md#auxiliary-system-h0-baseline-audit) for the audited
revision, environment, checks, and limitations, and
[the package map](../src/hex_qec/DOCS.md) for current APIs. The original
[THEORY.md](../THEORY.md), [PLAN.md](../PLAN.md), and package `DESCRIPTION.md`
files remain historical context for the earlier adaptive-SE development.
