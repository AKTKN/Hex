# Auxiliary-system specification status

**Current checkpoint: H3, 2026-10-16.** A validated two-boundary surface MWPM
sector gap and causal per-stage factory scores are implemented and tested.
See [logical_zero_factory_h3.md](logical_zero_factory_h3.md) for the metric,
domain, numerical limits and integration;
[logical_zero_factory_h2.md](logical_zero_factory_h2.md) for execution APIs and
[logical_zero_factory_h1.md](logical_zero_factory_h1.md) for the original
primitive. H4 has not started.

[auxiliary_factory_theory.md](auxiliary_factory_theory.md) is an unchanged copy
of the user-supplied scientific specification. Projected priors and experiment
contracts remain proposed / untested. H0 established the
baseline; H1/H2/H3 validate the documented circuit/frame/execution/sector
boundaries and make no general fault-tolerance claim.

Read [STATUS.md](../STATUS.md#auxiliary-system-h3-surface-logical-gap) for H3
evidence and the [H0 audit](../STATUS.md#auxiliary-system-h0-baseline-audit) for the audited
revision, environment, checks, and limitations, and
[the package map](../src/hex_qec/DOCS.md) for current APIs. The original
[THEORY.md](../THEORY.md), [PLAN.md](../PLAN.md), and package `DESCRIPTION.md`
files remain historical context for the earlier adaptive-SE development.
