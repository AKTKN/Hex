"""Small wall-clock timing recorder used by opt-in profiling runs.

The recorder deliberately stores only timing events and scalar metadata.  It
does not inspect or alter simulator state, decoder inputs, random seeds, or
results.  Section names are hierarchical when a section is opened inside
another section; callers can use ``absolute=True`` for non-overlapping report
stages whose diagnostic children should retain their own names.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from time import perf_counter_ns
from typing import Any, Iterator


@dataclass(frozen=True)
class TimingEvent:
    """One inclusive wall-clock timing event."""

    section: str
    wall_time_seconds: float
    shot_index: int
    phase: str
    metadata: dict[str, Any]


class WallTimeProfiler:
    """In-memory, opt-in wall-clock section collector.

    ``section`` is intended for existing call boundaries.  With profiling
    disabled it yields without reading the clock and records no event, which
    keeps the normal execution path semantically unchanged.
    """

    def __init__(
        self,
        *,
        enabled: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.enabled = enabled
        self.metadata = dict(metadata or {})
        self._events: list[TimingEvent] = []
        self._stack: list[str] = []
        self._shot_index = -1
        self._phase = "setup"

    @contextmanager
    def context_scope(
        self,
        *,
        shot_index: int = -1,
        phase: str = "setup",
        metadata: dict[str, Any] | None = None,
    ) -> Iterator[None]:
        """Temporarily set scalar context attached to subsequent events."""

        old = (self._shot_index, self._phase, self.metadata)
        self._shot_index = shot_index
        self._phase = phase
        if metadata:
            self.metadata = {**self.metadata, **metadata}
        try:
            yield
        finally:
            self._shot_index, self._phase, self.metadata = old

    @contextmanager
    def shot(
        self,
        shot_index: int,
        *,
        phase: str,
        metadata: dict[str, Any] | None = None,
    ) -> Iterator[None]:
        """Attach context and record an outer timer for one complete shot."""

        with self.context_scope(
            shot_index=shot_index,
            phase=phase,
            metadata=metadata,
        ):
            with self.section(
                "shot.total_wall_time",
                absolute=True,
                scope=False,
            ):
                yield

    @contextmanager
    def section(
        self,
        name: str,
        *,
        absolute: bool = False,
        scope: bool = True,
    ) -> Iterator[None]:
        """Record an inclusive wall-clock section.

        Relative names are prefixed by the currently open section, allowing a
        decoder callback to report e.g. ``shot.decode.short.zero.x_dem`` while
        remaining independent of the core profiling package.
        """

        if not self.enabled:
            yield
            return

        full_name = name if absolute or not self._stack else ".".join(
            [*self._stack, name]
        )
        start = perf_counter_ns()
        if scope:
            self._stack.append(full_name)
        try:
            yield
        finally:
            elapsed = (perf_counter_ns() - start) / 1_000_000_000
            if scope:
                self._stack.pop()
            self._events.append(
                TimingEvent(
                    section=full_name,
                    wall_time_seconds=elapsed,
                    shot_index=self._shot_index,
                    phase=self._phase,
                    metadata=dict(self.metadata),
                )
            )

    @property
    def events(self) -> tuple[TimingEvent, ...]:
        return tuple(self._events)
