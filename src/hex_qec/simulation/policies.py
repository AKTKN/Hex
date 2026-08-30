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


class ClusterLLRPolicy:
    """Continue shots whose BP-LSD cluster-LLR risk exceeds a threshold.

    BP-LSD's cluster LLR is stored in ``DecodeResult.confidence`` by the
    adapter, but its convention is risk-like: zero means highest confidence.
    The simulator does not interpret this convention; this policy does.
    """

    def __init__(self, threshold: float) -> None:
        self.threshold = threshold

    def should_extend(
        self,
        decode_result: DecodeResult | None,
        *,
        context: AdaptivePolicyContext,
    ) -> np.ndarray:
        if decode_result is None or decode_result.confidence is None:
            raise ValueError("decode_result.confidence must be provided")
        confidence = np.asarray(decode_result.confidence, dtype=float)
        if confidence.shape != (context.batch_size,):
            raise ValueError(
                "decode_result.confidence must have shape (batch_size,)"
            )
        return confidence > self.threshold
