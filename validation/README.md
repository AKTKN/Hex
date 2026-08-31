# Knill reproducibility validation

This package contains opt-in Monte Carlo checks for the adaptive Hex branch.
The runners are not part of the ordinary fast pytest suite.

Validation 1 (`fixed_workflow_repro.py`) builds the preserved legacy Knill
module sequence once per parameter point, runs it through the legacy static
compiled backend, and then runs that same `modularised_circuit` through
`StatefulFlipSimulatorBackend`.  It checks backend compatibility rather than
comparing independently written protocol constructors.

Validation 2 (`adaptive_forced_long_repro.py`) compares the legacy fixed-depth
workflow with `knill_online_offline_adaptive` configured as:

```text
short_rounds = 1
extra_rounds = distance - 1
long_rounds = distance       # total final depth, not extra depth
policy = AlwaysLongPolicy()
```

Thus every adaptive shot continues its existing physical short-prefix shot
through `distance - 1` extra rounds, and the full history is decoded.

Equal seeds make run configurations reproducible, but do not imply shot-wise
identical noise: compiled Stim sampling and per-shot `FlipSimulator` sampling
consume randomness differently.  Noisy workflows are therefore compared with
pooled binomial counts, Wilson intervals, and Fisher's exact test.  Holm-
Bonferroni adjustment is applied over the parameter points.

Comparison statuses mean:

- `compatible`: no statistically significant difference was detected at the
  selected sample size and alpha;
- `difference_detected`: the adjusted p-value is below alpha;
- `underpowered`: too few pooled logical-error events support a meaningful
  inference, regardless of the p-value.

## Smoke run

Use a tiny d=3, zero-noise, 256-shot run:

```bash
PYTHONPATH=src python -m validation.fixed_workflow_repro --smoke --overwrite
PYTHONPATH=src python -m validation.adaptive_forced_long_repro --smoke --overwrite
PYTHONPATH=src python -m validation.plot_knill_repro --all
```

The two runners can also be launched together:

```bash
bash validation/run_knill_repro.sh
```

With no arguments, the launcher uses the production parameter set: distances
5 and 7, physical errors 0.001 and 0.003, 4096 shots, and 3 replicates. Extra
runner options are forwarded to both validations, so a smoke run is:

```bash
bash validation/run_knill_repro.sh --smoke --overwrite
```

Add `--verbose` to see flushed per-point progress, completion counts,
runtimes, and adaptive fallback statistics while the script is running:

```bash
bash validation/run_knill_repro.sh --verbose
```

Runners checkpoint their raw CSV after every completed workflow row and skip
completed rows on rerun.  `--overwrite` starts that suite's raw and comparison
files over.  Metadata for every invocation is stored under
`validation/results/metadata/`.

## Full validation

The requested surface-code matrix is supported with configurable shot count
and independent replicates; it is intentionally not run automatically:

```bash
PYTHONPATH=src python -m validation.fixed_workflow_repro \
  --distances 5 7 --physical-errors 0.001 0.003 \
  --shots 4096 --replicates 3
PYTHONPATH=src python -m validation.adaptive_forced_long_repro \
  --distances 5 7 --physical-errors 0.001 0.003 \
  --shots 4096 --replicates 3
PYTHONPATH=src python -m validation.plot_knill_repro --all
```

Choose the shot count for the desired precision; it must be a positive
multiple of the legacy 256-shot batch size.  Use `--pauli x` to validate the
other logical basis.
