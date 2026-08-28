"""Policies used by the two-level adaptive state-preparation scaffold."""

from dataclasses import dataclass
from typing import Protocol

import numpy as np

from hex_qec.decoders import DecodeResult


@dataclass(frozen=True)
class AdaptivePolicyContext:
    """Context passed to a policy for one state-preparation batch."""

    batch_size: int
    event_id: str | None = None
    teleportation_index: int | None = None
    state_basis: str | None = None


class AdaptivePolicy(Protocol):
    """Select shots that should continue from short to long."""

    def should_extend(
        self,
        decode_result: DecodeResult | None,
        *,
        context: AdaptivePolicyContext,
    ) -> np.ndarray:
        """Return a boolean mask with one entry per shot."""


class AlwaysShortPolicy:
    """Diagnostic policy that always commits the short result."""

    def should_extend(
        self,
        decode_result: DecodeResult | None,
        *,
        context: AdaptivePolicyContext,
    ) -> np.ndarray:
        return np.zeros(context.batch_size, dtype=bool)


class AlwaysLongPolicy:
    """Diagnostic policy that always continues to the long result."""

    def should_extend(
        self,
        decode_result: DecodeResult | None,
        *,
        context: AdaptivePolicyContext,
    ) -> np.ndarray:
        return np.ones(context.batch_size, dtype=bool)
