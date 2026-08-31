"""Example ``css_detector_module`` confidence aggregators.

These are optional, metric-specific helpers, not part of the generic
decoder or policy protocol.  ``css_detector_module.confidence_aggregator``
accepts any ``Callable[[CSSInnerDecodeResults], ndarray | None]``; which
inner results matter and how they combine is a property of the chosen
confidence metric, not something the framework assumes.  A different
decoder/metric should bring its own aggregator rather than reuse these
verbatim.

Both functions below assume a risk-like confidence convention (larger
value means less confident), matching the BP-LSD Cluster LLR adapter and
``ClusterLLRPolicy``.  Do not pass them to a metric with the opposite
convention.
"""

from __future__ import annotations

import numpy as np
from numpy import ndarray

from .base import CSSInnerDecodeResults


def dem_only_max_confidence(results: CSSInnerDecodeResults) -> ndarray | None:
    """Conservative DEM-only aggregation: ``max(x_dem, z_dem)`` confidence.

    This is the current default aggregation for the adaptive-SE experiment
    (see ``modularisation/DESCRIPTION.md`` and ``STATUS.md``).  Code-capacity
    (final stabilizer-repair) confidence is intentionally excluded: its
    decoder currently uses a uniform code-capacity prior rather than a
    circuit-derived effective prior, so there is no established calibration
    for combining it with DEM confidence yet.  See ``FUTURE.md``,
    "Code-capacity confidence for adaptive state preparation".
    """

    values = [results.x_dem.confidence, results.z_dem.confidence]
    values = [value for value in values if value is not None]
    return np.max(np.stack(values), axis=0) if values else None


def all_components_max_confidence(results: CSSInnerDecodeResults) -> ndarray | None:
    """Diagnostic-only aggregation across all four inner decode results.

    This combines DEM and code-capacity confidence with a plain ``max``.
    It is **not** the current default and is **not** theoretically
    justified as an adaptive stopping metric: the code-capacity decoders'
    uniform prior means their confidence has no known calibration against
    the DEM confidence it would be combined with.  It is kept only for
    experimental/diagnostic comparison against the DEM-only default; see
    ``FUTURE.md``, "Code-capacity confidence for adaptive state
    preparation".
    """

    values = [result.confidence for result in results if result.confidence is not None]
    return np.max(np.stack(values), axis=0) if values else None
