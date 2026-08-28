"""Protocol and result types for decoder integration.

The protocols deliberately describe the behavior Hex needs instead of making
third-party decoder classes inherit from a Hex base class.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol

import numpy as np


@dataclass
class DecodeResult:
    """Decoder output for a batch of syndrome inputs.

    The first axis of every array is the shot/batch axis.  ``correction`` is
    the decoder's correction-variable array.  ``confidence`` and
    ``converged`` are optional because existing decoders do not provide them;
    no adaptive policy is applied here.  ``metrics`` preserves decoder-
    specific diagnostics without imposing a common metric definition.
    """

    correction: np.ndarray
    confidence: np.ndarray | None = None
    converged: np.ndarray | None = None
    metrics: dict[str, np.ndarray] = field(default_factory=dict)


class Decoder(Protocol):
    """Behavior required from a batch decoder adapter."""

    def decode_batch(self, syndromes: np.ndarray) -> DecodeResult:
        """Decode a two-dimensional batch of syndrome rows."""


class DecoderFactory(Protocol):
    """Factory for constructing a decoder for one check matrix."""

    def create(self, check_matrix: Any, *, weights: Any = None) -> Decoder:
        """Create a decoder for ``check_matrix`` and optional weights."""
