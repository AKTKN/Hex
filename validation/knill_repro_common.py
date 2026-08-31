"""Shared configuration, statistics, and output helpers for Knill validation."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import platform
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from scipy.stats import fisher_exact


DEFAULT_DISTANCES = (5, 7)
DEFAULT_PHYSICAL_ERRORS = (0.001, 0.003)
DEFAULT_SHOTS = 256
DEFAULT_REPLICATES = 1
DEFAULT_BASE_SEED = 20260831
DEFAULT_ALPHA = 0.05
DEFAULT_MIN_TOTAL_ERRORS_FOR_INFERENCE = 10
NO_EARLY_STOP_ERRORS = 10**18
STATIC_BATCH_SIZE = 256


@dataclass(frozen=True)
class ValidationConfig:
    """Configuration shared by both reproducibility suites."""

    distances: tuple[int, ...] = DEFAULT_DISTANCES
    physical_errors: tuple[float, ...] = DEFAULT_PHYSICAL_ERRORS
    shots: int = DEFAULT_SHOTS
    replicates: int = DEFAULT_REPLICATES
    base_seed: int = DEFAULT_BASE_SEED
    pauli: str = "z"
    output_dir: Path = Path("validation/results")
    overwrite: bool = False
    verbose: bool = False
    smoke: bool = False
    alpha: float = DEFAULT_ALPHA
    min_total_errors: int = DEFAULT_MIN_TOTAL_ERRORS_FOR_INFERENCE
    num_teleportations: int = 1
    surface_code: bool = True
    state_prep_rounds_are_distance: bool = True

    def __post_init__(self) -> None:
        if not self.distances or any(distance < 3 for distance in self.distances):
            raise ValueError("distances must contain values >= 3")
        if not self.physical_errors or any(
            error < 0 or error > 1 for error in self.physical_errors
        ):
            raise ValueError("physical errors must be in [0, 1]")
        if self.shots <= 0 or self.shots % STATIC_BATCH_SIZE:
            raise ValueError(f"shots must be a positive multiple of {STATIC_BATCH_SIZE}")
        if self.replicates <= 0:
            raise ValueError("replicates must be positive")
        if self.pauli.lower() not in {"x", "z"}:
            raise ValueError("pauli must be 'x' or 'z'")
        if not 0 < self.alpha < 1:
            raise ValueError("alpha must be strictly between 0 and 1")
        if self.min_total_errors < 0:
            raise ValueError("min_total_errors must be non-negative")
        if self.num_teleportations <= 0:
            raise ValueError("num_teleportations must be positive")

    def as_json(self) -> dict[str, object]:
        values = asdict(self)
        values["distances"] = list(self.distances)
        values["physical_errors"] = list(self.physical_errors)
        values["output_dir"] = str(self.output_dir)
        return values


def add_common_arguments(parser: argparse.ArgumentParser) -> None:
    """Add the common runner options to an argument parser."""

    parser.add_argument("--distances", nargs="+", type=int, default=list(DEFAULT_DISTANCES))
    parser.add_argument(
        "--physical-errors",
        nargs="+",
        type=float,
        default=list(DEFAULT_PHYSICAL_ERRORS),
    )
    parser.add_argument("--shots", type=int, default=DEFAULT_SHOTS)
    parser.add_argument("--replicates", type=int, default=DEFAULT_REPLICATES)
    parser.add_argument("--base-seed", type=int, default=DEFAULT_BASE_SEED)
    parser.add_argument("--pauli", choices=("x", "z"), default="z")
    parser.add_argument("--output-dir", type=Path, default=Path("validation/results"))
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="print flushed progress for every parameter point and workflow",
    )
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--alpha", type=float, default=DEFAULT_ALPHA)
    parser.add_argument(
        "--min-total-errors",
        type=int,
        default=DEFAULT_MIN_TOTAL_ERRORS_FOR_INFERENCE,
        help="minimum pooled error events before a comparison can be conclusive",
    )


def config_from_args(args: argparse.Namespace) -> ValidationConfig:
    """Construct validated configuration, applying the deliberately tiny smoke preset."""

    if args.smoke:
        distances = (3,)
        physical_errors = (0.0,)
        shots = STATIC_BATCH_SIZE
        replicates = 1
    else:
        distances = tuple(args.distances)
        physical_errors = tuple(args.physical_errors)
        shots = args.shots
        replicates = args.replicates
    return ValidationConfig(
        distances=distances,
        physical_errors=physical_errors,
        shots=shots,
        replicates=replicates,
        base_seed=args.base_seed,
        pauli=args.pauli,
        output_dir=args.output_dir,
        overwrite=args.overwrite,
        verbose=args.verbose,
        smoke=args.smoke,
        alpha=args.alpha,
        min_total_errors=args.min_total_errors,
    )


def stable_seed(
    base_seed: int,
    validation_name: str,
    distance: int,
    physical_error: float,
    replicate_index: int,
) -> int:
    """Derive a reproducible unsigned 63-bit seed from validation parameters."""

    payload = json.dumps(
        [base_seed, validation_name, distance, repr(float(physical_error)), replicate_index],
        separators=(",", ":"),
    ).encode()
    # Keep the result in the range accepted by all supported Stim versions.
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") % (2**63 - 1)


def configuration_signature(validation_name: str, config: ValidationConfig) -> str:
    # Output location and the control flag are operational details, not part
    # of the sampled parameter point.  Excluding them makes a rerun with
    # ``--overwrite`` or a different output directory identify the same run.
    values = config.as_json()
    values.pop("output_dir", None)
    values.pop("overwrite", None)
    values.pop("verbose", None)
    payload = json.dumps(
        {"validation": validation_name, **values},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode()
    return hashlib.sha256(payload).hexdigest()[:16]


def wilson_interval(
    errors: int,
    shots: int,
    confidence: float = 0.95,
) -> tuple[float, float]:
    """Return a Wilson score interval for a binomial proportion."""

    if shots <= 0 or errors < 0 or errors > shots:
        raise ValueError("require 0 <= errors <= shots and shots > 0")
    if not 0 < confidence < 1:
        raise ValueError("confidence must be strictly between 0 and 1")
    # scipy is already a core dependency through the decoder stack, but avoid
    # importing its normal distribution object for this small closed form.
    from scipy.stats import norm

    z = float(norm.ppf(0.5 + confidence / 2))
    p = errors / shots
    denominator = 1 + z * z / shots
    centre = (p + z * z / (2 * shots)) / denominator
    radius = z * math.sqrt(p * (1 - p) / shots + z * z / (4 * shots * shots)) / denominator
    return max(0.0, centre - radius), min(1.0, centre + radius)


def fisher_table(legacy_errors: int, legacy_shots: int, new_errors: int, new_shots: int) -> list[list[int]]:
    """Build the 2x2 error/no-error table used by Fisher's exact test."""

    return [
        [legacy_errors, legacy_shots - legacy_errors],
        [new_errors, new_shots - new_errors],
    ]


def pooled_counts(rows: Iterable[Mapping[str, object]], workflow: str) -> tuple[int, int]:
    """Pool shot and logical-error counts for one workflow."""

    selected = [row for row in rows if str(row["workflow"]) == workflow]
    shots = sum(int(row["shots"]) for row in selected)
    errors = sum(int(row["logical_errors"]) for row in selected)
    return shots, errors


def holm_bonferroni(p_values: Sequence[float]) -> list[float]:
    """Return Holm-Bonferroni adjusted p-values in input order."""

    if not p_values:
        return []
    indexed = sorted(enumerate(float(p) for p in p_values), key=lambda item: item[1])
    adjusted = [0.0] * len(p_values)
    running_max = 0.0
    count = len(p_values)
    for rank, (index, p_value) in enumerate(indexed):
        running_max = max(running_max, min(1.0, (count - rank) * p_value))
        adjusted[index] = running_max
    return adjusted


def comparison_rows(
    raw_rows: Sequence[Mapping[str, object]],
    *,
    legacy_workflow: str,
    new_workflow: str,
    distances: Sequence[int],
    physical_errors: Sequence[float],
    alpha: float,
    min_total_errors: int,
) -> list[dict[str, object]]:
    """Pool raw replicate rows and add Fisher/Holm comparison statistics."""

    pending: list[dict[str, object]] = []
    for distance in distances:
        for physical_error in physical_errors:
            point_rows = [
                row
                for row in raw_rows
                if int(row["distance"]) == distance
                and math.isclose(float(row["physical_error"]), physical_error)
            ]
            legacy_shots, legacy_errors = pooled_counts(point_rows, legacy_workflow)
            new_shots, new_errors = pooled_counts(point_rows, new_workflow)
            if not legacy_shots or not new_shots:
                continue
            legacy_ler = legacy_errors / legacy_shots
            new_ler = new_errors / new_shots
            table = fisher_table(legacy_errors, legacy_shots, new_errors, new_shots)
            _, raw_p = fisher_exact(table, alternative="two-sided")
            if legacy_ler == 0:
                ratio = math.nan if new_ler == 0 else math.inf
            else:
                ratio = new_ler / legacy_ler
            pending.append(
                {
                    "distance": distance,
                    "physical_error": physical_error,
                    "legacy_shots": legacy_shots,
                    "legacy_errors": legacy_errors,
                    "legacy_ler": legacy_ler,
                    "legacy_ci_low": wilson_interval(legacy_errors, legacy_shots)[0],
                    "legacy_ci_high": wilson_interval(legacy_errors, legacy_shots)[1],
                    "new_shots": new_shots,
                    "new_errors": new_errors,
                    "new_ler": new_ler,
                    "new_ci_low": wilson_interval(new_errors, new_shots)[0],
                    "new_ci_high": wilson_interval(new_errors, new_shots)[1],
                    "absolute_ler_difference": new_ler - legacy_ler,
                    "ler_ratio": ratio,
                    "raw_p_value": raw_p,
                    "total_error_events": legacy_errors + new_errors,
                    "statistical_status": "pending",
                }
            )
    adjusted = holm_bonferroni([float(row["raw_p_value"]) for row in pending])
    for row, adjusted_p in zip(pending, adjusted):
        row["adjusted_p_value"] = adjusted_p
        if int(row["total_error_events"]) < min_total_errors:
            row["statistical_status"] = "underpowered"
        elif adjusted_p < alpha:
            row["statistical_status"] = "difference_detected"
        else:
            row["statistical_status"] = "compatible"
    return pending


def _version(package: str) -> str:
    try:
        from importlib.metadata import version

        return version(package)
    except Exception:
        return "unavailable"


def git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return "unknown"


def environment_metadata() -> dict[str, str]:
    return {
        "git_sha": git_sha(),
        "python_version": platform.python_version(),
        "stim_version": _version("stim"),
        "pymatching_version": _version("pymatching"),
    }


def prepare_output(config: ValidationConfig, raw_filename: str, comparison_filename: str) -> None:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    (config.output_dir / "metadata").mkdir(parents=True, exist_ok=True)
    (config.output_dir / "figures").mkdir(parents=True, exist_ok=True)
    if config.overwrite:
        for filename in (raw_filename, comparison_filename):
            target = config.output_dir / filename
            if target.exists():
                target.unlink()


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv_rows(path: Path, rows: Sequence[Mapping[str, object]], fieldnames: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: ("" if row.get(key) is None else row.get(key)) for key in fieldnames})


def raw_row_key(row: Mapping[str, object]) -> tuple[str, int, float, int, str]:
    return (
        str(row["workflow"]),
        int(row["distance"]),
        float(row["physical_error"]),
        int(row["replicate"]),
        str(row.get("config_signature", "")),
    )


def parameter_complete(
    rows: Iterable[Mapping[str, object]],
    *,
    distance: int,
    physical_error: float,
    replicate: int,
    config_signature: str,
    workflows: Sequence[str],
) -> bool:
    """Return whether all workflow rows for one point are checkpointed."""

    keys = {raw_row_key(row) for row in rows}
    return all(
        (workflow, distance, float(physical_error), replicate, config_signature) in keys
        for workflow in workflows
    )


def write_invocation_metadata(config: ValidationConfig, validation_name: str, argv: Sequence[str]) -> Path:
    timestamp = datetime.now(timezone.utc)
    metadata = {
        "validation": validation_name,
        "timestamp": timestamp.isoformat(),
        "command_line": [sys.executable, *argv],
        **config.as_json(),
        "decoder": "PyMatching MWPM (Matching.from_check_matrix)",
        "state_prep_rounds": "distance",
        "minimum_error_threshold": config.min_total_errors,
        **environment_metadata(),
    }
    path = config.output_dir / "metadata" / f"{validation_name}_{timestamp.strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")
    return path


def progress(config: ValidationConfig, validation: str, message: str) -> None:
    """Print a real-time runner message when verbose mode is enabled."""

    if config.verbose:
        print(f"[{validation}] {message}", flush=True)


def add_common_row_fields(
    *,
    validation: str,
    workflow: str,
    distance: int,
    physical_error: float,
    replicate: int,
    seed: int,
    config: ValidationConfig,
    shots: int,
    logical_errors: int,
    runtime_seconds: float,
) -> dict[str, object]:
    errors = int(logical_errors)
    low, high = wilson_interval(errors, shots)
    return {
        "validation": validation,
        "workflow": workflow,
        "distance": distance,
        "physical_error": physical_error,
        "state_prep_rounds": distance,
        "num_teleportations": config.num_teleportations,
        "pauli": config.pauli,
        "surface_code": config.surface_code,
        "replicate": replicate,
        "seed": seed,
        "shots": shots,
        "logical_errors": errors,
        "logical_error_rate": errors / shots if shots else math.nan,
        "wilson_95_low": low,
        "wilson_95_high": high,
        "runtime_seconds": runtime_seconds,
        **environment_metadata(),
    }
