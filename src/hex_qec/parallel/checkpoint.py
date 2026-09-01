"""Manager-owned append-only checkpoint support."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from .types import ChunkResult, ParallelJobSpec


CHECKPOINT_SCHEMA_VERSION = 1
_REQUIRED_KEYS = {
    "schema_version",
    "job_id",
    "lease_id",
    "shot_start",
    "shot_count",
    "logical_errors",
    "runtime_seconds",
    "custom_counts",
    "config_fingerprint",
}


class CheckpointError(ValueError):
    """Raised when checkpoint contents cannot safely be resumed."""


class CheckpointStore:
    """Read completed leases and append new ones from the manager process."""

    def __init__(self, path: Path | None) -> None:
        self.path = Path(path) if path is not None else None

    def load(self, specs: Iterable[ParallelJobSpec]) -> list[ChunkResult]:
        if self.path is None or not self.path.exists():
            return []
        specs_by_id = {spec.job_id: spec for spec in specs}
        seen_leases: dict[str, ChunkResult] = {}
        seen_ranges: dict[str, list[tuple[int, int, str]]] = {}
        try:
            lines = self.path.read_text().splitlines()
        except OSError as error:
            raise CheckpointError(f"could not read checkpoint {self.path}: {error}") from error
        for line_number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise CheckpointError(
                    f"malformed checkpoint line {line_number}: {error.msg}"
                ) from error
            if not isinstance(record, dict) or not _REQUIRED_KEYS.issubset(record):
                missing = sorted(_REQUIRED_KEYS - set(record) if isinstance(record, dict) else _REQUIRED_KEYS)
                raise CheckpointError(
                    f"checkpoint line {line_number} is missing keys: {missing}"
                )
            if record["schema_version"] != CHECKPOINT_SCHEMA_VERSION:
                raise CheckpointError(
                    f"unsupported checkpoint schema on line {line_number}: "
                    f"{record['schema_version']}"
                )
            job_id = record["job_id"]
            spec = specs_by_id.get(job_id)
            if spec is None:
                raise CheckpointError(
                    f"checkpoint line {line_number} references unknown job {job_id!r}"
                )
            if record["config_fingerprint"] != spec.config_fingerprint:
                raise CheckpointError(
                    f"checkpoint configuration fingerprint mismatch for job {job_id!r}"
                )
            try:
                shot_start = int(record["shot_start"])
                shot_count = int(record["shot_count"])
                result = ChunkResult(
                    job_id=job_id,
                    lease_id=str(record["lease_id"]),
                    shot_start=shot_start,
                    shots=shot_count,
                    logical_errors=int(record["logical_errors"]),
                    runtime_seconds=float(record["runtime_seconds"]),
                    custom_counts={
                        str(name): int(value)
                        for name, value in dict(record["custom_counts"]).items()
                    },
                )
            except (TypeError, ValueError, KeyError) as error:
                raise CheckpointError(
                    f"invalid checkpoint values on line {line_number}: {error}"
                ) from error
            if result.shot_start + result.shots > spec.max_shots:
                raise CheckpointError(
                    f"checkpoint lease {result.lease_id!r} exceeds max_shots for job {job_id!r}"
                )
            previous = seen_leases.get(result.lease_id)
            if previous is not None:
                if previous != result:
                    raise CheckpointError(
                        f"conflicting duplicate checkpoint lease {result.lease_id!r}"
                    )
                continue
            for start, end, lease_id in seen_ranges.setdefault(job_id, []):
                if result.shot_start < end and start < result.shot_start + result.shots:
                    raise CheckpointError(
                        f"checkpoint leases {lease_id!r} and {result.lease_id!r} overlap"
                    )
            seen_leases[result.lease_id] = result
            seen_ranges[job_id].append(
                (result.shot_start, result.shot_start + result.shots, result.lease_id)
            )
        return list(seen_leases.values())

    def append(self, result: ChunkResult, spec: ParallelJobSpec) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "schema_version": CHECKPOINT_SCHEMA_VERSION,
            "job_id": result.job_id,
            "lease_id": result.lease_id,
            "shot_start": result.shot_start,
            "shot_count": result.shots,
            "logical_errors": result.logical_errors,
            "runtime_seconds": result.runtime_seconds,
            "custom_counts": dict(result.custom_counts),
            "config_fingerprint": spec.config_fingerprint,
        }
        with self.path.open("a") as stream:
            stream.write(json.dumps(record, sort_keys=True) + "\n")
            stream.flush()

