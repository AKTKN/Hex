"""Protocol and result types for decoder integration.

The protocols deliberately describe the behavior Hex needs instead of making
third-party decoder classes inherit from a Hex base class.
"""

from dataclasses import dataclass, field
from typing import Any, NamedTuple, Protocol

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


class CSSInnerDecodeResults(NamedTuple):
    """The four inner decode results produced by ``css_detector_module``.

    ``css_detector_module`` decodes state preparation in two conceptually
    different stages (see ``modularisation/DESCRIPTION.md``):

    - ``x_dem`` / ``z_dem``: circuit-level DEM decoding of the repeated
      syndrome-extraction history (the spacetime detectors).  This is the
      only confidence source currently used for adaptive SE-round
      switching.
    - ``x_capacity`` / ``z_capacity``: code-capacity decoding of the final
      X/Z stabilizer signs after DEM correction (the "stabilizer repair"
      step).  Its decoder currently uses a uniform code-capacity prior
      rather than a circuit-derived effective prior, so its confidence is
      not yet theoretically justified for adaptive control (see
      ``FUTURE.md``, "Code-capacity confidence for adaptive state
      preparation").

    This is a plain 4-tuple in ``(x_dem, z_dem, x_capacity, z_capacity)``
    order, so it remains iterable/indexable/``len() == 4`` exactly like the
    historical bare list a ``confidence_aggregator`` receives.  The named
    fields let an aggregator select DEM-only or code-capacity-only results
    explicitly instead of relying on positional order/slicing.
    """

    x_dem: DecodeResult
    z_dem: DecodeResult
    x_capacity: DecodeResult
    z_capacity: DecodeResult


class Decoder(Protocol):
    """Behavior required from a batch decoder adapter."""

    def decode_batch(self, syndromes: np.ndarray) -> DecodeResult:
        """Decode a two-dimensional batch of syndrome rows."""


class DecoderFactory(Protocol):
    """Factory for constructing a decoder for one check matrix."""

    def create(self, check_matrix: Any, *, weights: Any = None) -> Decoder:
        """Create a decoder for ``check_matrix`` and optional weights."""
