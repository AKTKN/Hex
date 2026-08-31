# Adaptive wall-time profiling

`adaptive_walltime_profile.py` measures the current, correctness-first
adaptive Knill executor with a small `time.perf_counter_ns()` section recorder.
The correction-to-measurement-flip maps and detector-stripped adaptive
long-suffix circuits are deterministic setup data prepared once by the
executor before repeated shot execution; adaptive physical simulation remains
stateful and per-shot. It does not batch shots differently, add simulator
calls, change decoder inputs, or make any adaptive decision itself.

Run from the repository root:

```bash
python -m profiling.adaptive_walltime_profile
```

The default run is deliberately small: surface-code distance 5, physical
error `0.003`, one short round, five measured shots, one warm-up shot, one
teleportation, `pauli="z"`, and `AlwaysLongPolicy`.  Use `--help` for the
available configuration flags.  `--policy cluster-llr` enables the current
BP-LSD Cluster-LLR policy and records the selected short/long pair for each
shot.

Construction is recorded in `phase=setup`, separately from warm-up and
measured shot execution.  Warm-up rows are retained in the raw CSV but are
excluded from measured-shot averages.  The primary report uses non-overlap
stage wrappers such as `shot.physical.short.total` and
`shot.downstream.bell_measurement`; decoder and
`corrected_measurements.*` rows are inclusive diagnostic children and are
therefore not summed into the primary percentage table.

Outputs are written to `profiling/results/` by default:

By default the optimized run writes distinct shared-map/suffix files so the
previous profiling results are preserved:

* `adaptive_walltime_shared_map_suffix_raw.csv`: per-phase, per-shot/per-section aggregates;
* `adaptive_walltime_shared_map_suffix_summary.csv`: measured and warm-up section summaries;
* `adaptive_walltime_shared_map_suffix_report.md`: configuration, timing tables,
  suffix/map setup costs, and measured lookup counts;
* `adaptive_walltime_shared_map_suffix_breakdown.png`: optional major-stage bar chart;
* `adaptive_walltime_optimization_comparison.md`: comparison against the
  original and shared-map profiles.

Use `--output-prefix` to choose another filename prefix.

This profiler is intentionally lightweight. It is meant to identify where a
few current one-shot executions spend time before the next optimization is
attempted; it is not an LER-estimation workflow.
