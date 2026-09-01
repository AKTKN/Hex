"""Adapters from the adaptive Knill executor to the generic parallel core."""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from typing import Any

import numpy as np

from hex_qec.modularisation.results import (
    AdaptiveBellPairStats,
    AdaptiveStatePrepStats,
    SimulationResult,
    SimulationSummary,
)
from hex_qec.parallel import ChunkResult, ParallelJobSpec, ParallelRunResult


def _matrix_fingerprint(matrix: Any) -> str:
    if hasattr(matrix, "tocsr"):
        matrix = matrix.tocsr()
        payload = b"|".join(
            [
                repr(matrix.shape).encode(),
                np.asarray(matrix.indptr).tobytes(),
                np.asarray(matrix.indices).tobytes(),
                np.asarray(matrix.data).tobytes(),
            ]
        )
    else:
        array = np.asarray(matrix)
        payload = repr(array.shape).encode() + array.tobytes()
    return hashlib.sha256(payload).hexdigest()[:16]


def _callable_name(value: Any) -> str:
    stable_name = getattr(value, "__hex_parallel_name__", None)
    if stable_name is not None:
        return str(stable_name)
    return f"{getattr(value, '__module__', type(value).__module__)}.{getattr(value, '__qualname__', type(value).__qualname__)}"


def run_adaptive_executor_chunk(executor: Any, shot_start: int, shot_count: int, seed_base: int | None):
    """Run exactly one global shot range while preserving executor caches.

    The executor's internal batch index is zero for every call.  Temporarily
    setting its seed to ``seed_base + shot_start`` and its batch size to the
    lease size makes its local shot ``i`` use the global seed for
    ``shot_start + i``.  Both attributes are restored even when execution
    fails, so the worker keeps the prepared executor alive for later chunks.
    """

    original_seed = executor.seed
    original_batch_size = executor.batch_size
    try:
        executor.seed = (
            None
            if seed_base is None
            else (seed_base + shot_start) % (2**64)
        )
        executor.batch_size = shot_count
        result = executor.simulate_result(
            max_shots=shot_count,
            max_errors_before_halting=shot_count + 1,
            detail_level="summary",
        )
        if result.shots != shot_count:
            raise RuntimeError(
                f"adaptive executor returned {result.shots} shots for a "
                f"{shot_count}-shot lease"
            )
        return result
    finally:
        executor.seed = original_seed
        executor.batch_size = original_batch_size


@dataclass
class AdaptiveKnillPreparedJob:
    factory: "AdaptiveKnillParallelJobFactory"

    def __post_init__(self) -> None:
        from .knill_online_offline import _build_knill_online_offline_adaptive_executor

        self.executor = _build_knill_online_offline_adaptive_executor(
            self.factory.parity_check_tuple,
            self.factory.adaptive_schedule,
            self.factory.online_decoder_generator,
            self.factory.offline_decoder_generator,
            self.factory.matchable_offline_decoding,
            self.factory.physical_error,
            self.factory.pauli,
            self.factory.num_teleportations,
            confidence_aggregator=self.factory.confidence_aggregator,
            batch_size=1,
            seed=None,
            surface_code=self.factory.surface_code,
            profiler=None,
        )

    def run_chunk(self, shot_start: int, shot_count: int, seed_base: int | None) -> ChunkResult:
        result = run_adaptive_executor_chunk(
            self.executor, shot_start, shot_count, seed_base
        )
        return ChunkResult(
            job_id=self.factory.job_id_for(seed_base),
            lease_id="worker-assigned",
            shot_start=shot_start,
            shots=result.shots,
            logical_errors=result.logical_errors,
            runtime_seconds=float(result.summary.runtime_seconds or 0.0),
            custom_counts=_adaptive_custom_counts(result),
        )


@dataclass(frozen=True)
class AdaptiveKnillParallelJobFactory:
    """Pickleable construction recipe for one worker-local Knill session."""

    parity_check_tuple: tuple[Any, ...]
    adaptive_schedule: Any
    online_decoder_generator: Any
    offline_decoder_generator: Any
    matchable_offline_decoding: bool
    physical_error: float
    pauli: str
    num_teleportations: int
    confidence_aggregator: Any = None
    surface_code: bool = False

    @property
    def _configuration(self) -> dict[str, Any]:
        return {
            "protocol": "knill_adaptive",
            "matrices": [_matrix_fingerprint(matrix) for matrix in self.parity_check_tuple],
            "physical_error": self.physical_error,
            "pauli": self.pauli.lower(),
            "num_teleportations": self.num_teleportations,
            "matchable_offline_decoding": self.matchable_offline_decoding,
            "short_rounds": self.adaptive_schedule.short_rounds,
            "long_rounds": self.adaptive_schedule.long_rounds,
            "policy": _callable_name(self.adaptive_schedule.policy),
            "policy_state": repr(vars(self.adaptive_schedule.policy)),
            "online_decoder": _callable_name(self.online_decoder_generator),
            "offline_decoder": _callable_name(self.offline_decoder_generator),
            "confidence_aggregator": _callable_name(self.confidence_aggregator)
            if self.confidence_aggregator is not None
            else None,
            "surface_code": self.surface_code,
        }

    def job_id_for(self, seed_base: int | None) -> str:
        payload = {**self._configuration, "seed_base": seed_base}
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, default=str).encode()
        ).hexdigest()[:16]
        return f"knill-adaptive-{digest}"

    @property
    def job_id(self) -> str:
        return self.job_id_for(None)

    def metadata(self, seed: int | None) -> dict[str, Any]:
        try:
            git_sha = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
            ).strip()
        except (OSError, subprocess.CalledProcessError):
            git_sha = "unknown"
        return {**self._configuration, "seed_base": seed, "git_sha": git_sha}

    @property
    def config_fingerprint(self) -> str:
        return hashlib.sha256(
            json.dumps(self._configuration, sort_keys=True, default=str).encode()
        ).hexdigest()

    def config_fingerprint_for(self, seed: int | None) -> str:
        payload = {**self._configuration, "seed_base": seed}
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, default=str).encode()
        ).hexdigest()

    def prepare(self) -> AdaptiveKnillPreparedJob:
        return AdaptiveKnillPreparedJob(self)


def _adaptive_custom_counts(result: SimulationResult) -> dict[str, int]:
    counts: dict[str, int] = {}
    for stat in result.state_prep_stats:
        prefix = f"state_prep:{stat.event_id}"
        counts[f"{prefix}:short_count"] = int(stat.short_count or 0)
        counts[f"{prefix}:long_count"] = int(stat.long_count or 0)
        counts[f"{prefix}:effective_rounds_sum"] = int(
            round((stat.average_se_rounds or 0.0) * result.shots)
        )
    for stat in result.bell_pair_stats:
        prefix = f"bell_pair:{stat.pair_id}"
        counts[f"{prefix}:short_count"] = int(stat.short_count or 0)
        counts[f"{prefix}:long_count"] = int(stat.long_count or 0)
        counts[f"{prefix}:z_only_count"] = int(stat.z_only_count or 0)
        counts[f"{prefix}:x_only_count"] = int(stat.x_only_count or 0)
        counts[f"{prefix}:both_count"] = int(stat.both_count or 0)
        counts[f"{prefix}:effective_rounds_sum"] = int(
            round((stat.mean_effective_rounds or 0.0) * result.shots)
        )
    return counts


def merge_adaptive_parallel_result(
    parallel_result: ParallelRunResult,
    spec: ParallelJobSpec,
) -> SimulationResult:
    """Rebuild exact additive adaptive summary fields in the parent."""

    job = next(item for item in parallel_result.jobs if item.job_id == spec.job_id)
    factory = spec.factory
    counts = job.custom_counts
    state_stats: list[AdaptiveStatePrepStats] = []
    for index in range(factory.num_teleportations):
        for basis in ("z", "x"):
            # The shared one-support builder appends ``[0]`` to its event
            # prefix; retain that exact identity in the parent reduction.
            event_id = f"teleportation={index},state={basis}[0]"
            prefix = f"state_prep:{event_id}"
            long_count = counts.get(f"{prefix}:long_count", 0)
            state_stats.append(
                AdaptiveStatePrepStats(
                    event_id=event_id,
                    teleportation_index=index,
                    state_basis=basis,
                    short_rounds=factory.adaptive_schedule.short_rounds,
                    long_rounds=factory.adaptive_schedule.long_rounds,
                    short_count=counts.get(f"{prefix}:short_count", 0),
                    long_count=long_count,
                    fallback_rate=long_count / job.shots if job.shots else 0.0,
                    confidence_metric="DecodeResult.confidence",
                    average_se_rounds=(
                        counts.get(f"{prefix}:effective_rounds_sum", 0) / job.shots
                        if job.shots
                        else 0.0
                    ),
                    logical_error_count=job.logical_errors,
                )
            )
    pair_stats: list[AdaptiveBellPairStats] = []
    for index in range(factory.num_teleportations):
        pair_id = f"teleportation={index}"
        prefix = f"bell_pair:{pair_id}"
        short_count = counts.get(f"{prefix}:short_count", 0)
        long_count = counts.get(f"{prefix}:long_count", 0)
        z_only = counts.get(f"{prefix}:z_only_count", 0)
        x_only = counts.get(f"{prefix}:x_only_count", 0)
        both = counts.get(f"{prefix}:both_count", 0)
        denominator = job.shots or 1
        pair_stats.append(
            AdaptiveBellPairStats(
                pair_id=pair_id,
                teleportation_index=index,
                short_rounds=factory.adaptive_schedule.short_rounds,
                long_rounds=factory.adaptive_schedule.long_rounds,
                short_count=short_count,
                long_count=long_count,
                pair_fallback_rate=long_count / denominator,
                pair_short_fraction=short_count / denominator,
                pair_long_fraction=long_count / denominator,
                mean_effective_rounds=counts.get(
                    f"{prefix}:effective_rounds_sum", 0
                ) / denominator,
                z_only_count=z_only,
                x_only_count=x_only,
                both_count=both,
                z_only_fallback_fraction=z_only / denominator,
                x_only_fallback_fraction=x_only / denominator,
                both_fallback_fraction=both / denominator,
            )
        )
    return SimulationResult(
        summary=SimulationSummary(
            shots=job.shots,
            logical_errors=job.logical_errors,
            logical_error_rate=job.logical_errors / job.shots if job.shots else 0.0,
        ),
        state_prep_stats=state_stats,
        bell_pair_stats=pair_stats,
        metadata={
            **dict(spec.metadata),
            "execution_backend": "parallel_spawn_workers",
            "parallel": True,
            "job_id": spec.job_id,
            **dict(parallel_result.metadata),
        },
        detail_level="summary",
    )
