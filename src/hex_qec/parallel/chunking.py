"""Small, independently testable controllers for shot chunk allocation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ChunkSizeController:
    """Conservative wall-time-based chunk-size ramp controller."""

    target_seconds: float
    initial_shots: int = 1
    max_shots: int = 1024

    def __post_init__(self) -> None:
        if self.target_seconds <= 0:
            raise ValueError("target_seconds must be positive")
        if self.initial_shots < 1 or self.max_shots < 1:
            raise ValueError("chunk sizes must be positive")
        if self.initial_shots > self.max_shots:
            raise ValueError("initial_shots cannot exceed max_shots")
        self.current_shots = min(self.initial_shots, self.max_shots)

    def observe(self, runtime_seconds: float) -> int:
        if runtime_seconds < 0:
            raise ValueError("runtime_seconds must be non-negative")
        if runtime_seconds < 0.3 * self.target_seconds:
            self.current_shots = min(self.max_shots, self.current_shots * 2)
        elif runtime_seconds > 1.3 * self.target_seconds:
            self.current_shots = max(1, self.current_shots // 2)
        return self.current_shots

    def next_size(self, remaining: int) -> int:
        if remaining < 0:
            raise ValueError("remaining must be non-negative")
        return min(self.current_shots, remaining)


def merge_intervals(
    intervals: list[tuple[int, int]], new_interval: tuple[int, int]
) -> list[tuple[int, int]]:
    """Insert and coalesce half-open intervals, rejecting invalid ranges."""

    start, end = new_interval
    if start < 0 or end <= start:
        raise ValueError("interval must be a non-empty half-open range")
    result: list[tuple[int, int]] = []
    for left, right in sorted([*intervals, new_interval]):
        if right <= left:
            raise ValueError("interval must be a non-empty half-open range")
        if result and left <= result[-1][1]:
            if left < result[-1][1]:
                raise ValueError("overlapping intervals are not allowed")
            result[-1] = (result[-1][0], max(result[-1][1], right))
        else:
            result.append((left, right))
    return result


def first_missing_index(
    intervals: list[tuple[int, int]], limit: int
) -> int | None:
    """Return the first index not covered by sorted disjoint intervals."""

    if limit < 0:
        raise ValueError("limit must be non-negative")
    cursor = 0
    for start, end in sorted(intervals):
        if start > cursor:
            return cursor
        cursor = max(cursor, end)
        if cursor >= limit:
            return None
    return cursor if cursor < limit else None

