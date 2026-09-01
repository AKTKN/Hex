# Forced-long consistency diagnosis

`forced_long_consistency.py` performs deterministic structural checks followed
by A/B/C Monte Carlo consistency checks:

- A: legacy compiled Knill workflow;
- B: stateful contiguous-long workflow;
- C: adaptive forced-long workflow.

The structural phase remains in the parent process. The Monte Carlo phase can
use persistent spawn workers for all three workflows:

```bash
PYTHONPATH=src python -m diagnostics.forced_long_consistency \
  --smoke --overwrite --num-workers 2 \
  --initial-chunk-shots 1 --max-chunk-shots 32
```

Diagnostic A uses the legacy 256-shot compiled batch, so parallel leases are
automatically raised to at least `--batch-size` even when smaller adaptive
chunk values are requested. Parallel output retains the existing structural,
Monte Carlo, pairwise-statistics, JSON, and Markdown report formats and adds
an `execution` section with the selected backend and stage wall times.

Use `--checkpoint-path` to resume worker leases after interruption and
`--parallel-verbose 1` or `2` for scheduler progress. Base and extended stages
automatically use `<checkpoint stem>_base` and `<checkpoint stem>_extended`
files so their job namespaces cannot collide. Parallel scheduling settings do
not change the diagnostic configuration signature.
