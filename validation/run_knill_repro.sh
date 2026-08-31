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
    --distances 5 7
    --physical-errors 0.001 0.003
    --shots 4096
    --replicates 3
    --verbose
)

python -m validation.fixed_workflow_repro "${VALIDATION_ARGS[@]}" "$@"
python -m validation.adaptive_forced_long_repro "${VALIDATION_ARGS[@]}" "$@"
