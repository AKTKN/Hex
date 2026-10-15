# Validation utilities: opt-in workflow comparisons

See [README.md](README.md) for the historical workflow explanation and
[STATUS.md](../STATUS.md#auxiliary-system-h0-baseline-audit) for current facts.
This directory is a Python package separate from the installable core API.

## Implemented today

`fixed_workflow_repro.run_validation(config)` captures the exact legacy Knill
module sequence and compares static execution with `StatefulFlipSimulatorBackend`.
`adaptive_forced_long_repro.run_validation(config)` compares fixed `d`-round
preparation with `AdaptiveSERounds(1, d, AlwaysLongPolicy())`, verifying pair
fallback 1 and total selected depth `d`. Both use surface-specific ordering,
PyMatching, ideal initial data, and noisy final readout. They preserve the
existing full Knill circuit and do not build a one-bit factory.

`knill_repro_common.ValidationConfig` requires positive shot counts divisible
by 256. `stable_seed(base_seed, suite, d, p, replicate)` hashes parameters to
an unsigned 63-bit seed; it does not depend on scheduling. Raw CSV rows record
aggregate workflow/point/replicate counts, seeds, dimensions/decisions,
versions, and configuration signatures. Checkpoints deduplicate workflow keys.
They are not per-shot arrays or atomic streamed Parquet transactions.

`comparison_rows(...)` pools counts per point, computes Wilson proportion
intervals and independent-binomial Fisher tests, and applies Holm adjustment.
`analyze_knill_repro.analyze_suite(...)` reads existing CSVs only, checks
signatures/incomplete workflow sides, and reports `RD = new_ler - legacy_ler`
and the implemented Newcombe-style intervals. Equivalence requires an explicit
margin and interval containment; a non-significant Fisher test alone is not
equivalence. `plot_knill_repro.plot_comparison(...)` writes PNG/PDF from saved
comparison rows. These APIs do not establish scientific equivalence without
adequate data, and H0 does not independently certify the statistical formulas.

**Actual launcher defaults at the audited revision:**
`run_knill_repro.sh` uses distances 3/5, p=0.002/0.003/0.005, 25,600 shots,
and three replicates, then analysis with margin 0.001 and plotting. The older
README's no-argument d=5/7, 4096-shot description is stale. Direct Python runner
defaults differ again (d=5/7, p=0.001/0.003, 256 shots, one replicate).
Inspect the script before launching it. H0 did not run either Monte Carlo CLI
or generate experiment outputs.

The fixed runner temporarily wraps a protocol module constructor to capture
its circuit; this is a serial validation technique, not a thread-safe builder
API. CSV helpers read/rewrite whole row lists. Decoder/module reuse follows the
existing engines; it does not establish future factory object-lifetime rules.

H0 ran `test_validation_infrastructure.py` and `test_knill_repro_analysis.py`:
14 passed in 2.70 s with eight dependency deprecation warnings. Fixtures use
synthetic counts/checkpoints/plots; see [TEST.md](../TEST.md#auxiliary-system-h0-documentation-baseline).

## Proposed only

The [factory scientific gates](../docs/README.md) require signed-flow/single-fault
checks, two-support reuse, causal oracle isolation, and exact d=3 gap
enumeration in later phases. The Fig. 4(d) Agresti-Coull plotting and streamed
experiment schema belong to future bench work. None is validated by these
legacy workflow tests or implemented in H0.
