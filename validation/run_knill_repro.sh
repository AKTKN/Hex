#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [[ -n "${PYTHONPATH:-}" ]]; then
    export PYTHONPATH="$REPO_ROOT/src:$PYTHONPATH"
else
    export PYTHONPATH="$REPO_ROOT/src"
fi

# Production validation parameters. Extra arguments can still override these
# values, or select --smoke for a small local check.
VALIDATION_ARGS=(
    --distances 3 5 7
    --physical-errors 0.002 0.003 0.005
    --shots 51200
    --replicates 3 
    --verbose 
    --num-workers 8 
    --parallel-verbose 1
)

# Resolve the output directory once so analysis and plotting consume the same
# CSVs as the sampling runners.  Runner-only flags are not forwarded to either
# post-processing command.
OUTPUT_DIR="validation/results"
for arg in "$@"; do
    if [[ "$arg" == --output-dir=* ]]; then
        OUTPUT_DIR="${arg#--output-dir=}"
    fi
done
for ((index = 1; index <= $#; index++)); do
    if [[ "${!index}" == "--output-dir" ]]; then
        next_index=$((index + 1))
        OUTPUT_DIR="${!next_index}"
    fi
done

python -m validation.fixed_workflow_repro "${VALIDATION_ARGS[@]}" "$@"
python -m validation.adaptive_forced_long_repro "${VALIDATION_ARGS[@]}" "$@"

# Statistical analysis requires an explicit absolute LER equivalence margin.
# Keep this in a separate argument list: the sampling runners do not accept
# post-processing options.
ANALYSIS_ARGS=(
    --equivalence-margin 0.001
    --alpha 0.05
)
python -m validation.analyze_knill_repro \
    --all --output-dir "$OUTPUT_DIR" "${ANALYSIS_ARGS[@]}"

# Plot only after both validation and analysis complete successfully.
python -m validation.plot_knill_repro --all --output-dir "$OUTPUT_DIR"
