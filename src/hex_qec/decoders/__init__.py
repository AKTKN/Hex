"""Small decoder interfaces and adapters used by Hex."""

from .base import CSSInnerDecodeResults, DecodeResult, Decoder, DecoderFactory
from .adapters import (
    LegacyDecoderAdapter,
    LegacyDecoderGeneratorAdapter,
    adapt_decoder_generator,
    coerce_decode_result,
    HexBPLSDDecoder,
    make_bplsd_decoder_generator,
)
from .aggregators import all_components_max_confidence, dem_only_max_confidence
from .surface_gap import HomologyGapBatch, SurfaceMWPMHomologyGap
from .codecapacity_dem import (
    FaultMechanism, FaultSignature, PreparationDecoderConvention,
    ProjectedDEMBuilder, ProjectedDEMDiagnostics, ProjectedDEMResult,
    ProjectedErrorModel, ProjectedEvent, ProjectedFault,
    UnsupportedProjectedModel, merge_independent_events,
)

__all__ = [
    "CSSInnerDecodeResults",
    "DecodeResult",
    "Decoder",
    "DecoderFactory",
    "LegacyDecoderAdapter",
    "LegacyDecoderGeneratorAdapter",
    "adapt_decoder_generator",
    "coerce_decode_result",
    "HexBPLSDDecoder",
    "make_bplsd_decoder_generator",
    "dem_only_max_confidence",
    "all_components_max_confidence",
    "HomologyGapBatch",
    "SurfaceMWPMHomologyGap",
    "FaultMechanism", "FaultSignature", "PreparationDecoderConvention",
    "ProjectedDEMBuilder", "ProjectedDEMDiagnostics", "ProjectedDEMResult",
    "ProjectedErrorModel", "ProjectedEvent", "ProjectedFault",
    "UnsupportedProjectedModel", "merge_independent_events",
]
