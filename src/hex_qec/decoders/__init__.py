"""Small decoder interfaces and adapters used by Hex."""

from .base import DecodeResult, Decoder, DecoderFactory
from .adapters import (
    LegacyDecoderAdapter,
    LegacyDecoderGeneratorAdapter,
    adapt_decoder_generator,
    coerce_decode_result,
)

__all__ = [
    "DecodeResult",
    "Decoder",
    "DecoderFactory",
    "LegacyDecoderAdapter",
    "LegacyDecoderGeneratorAdapter",
    "adapt_decoder_generator",
    "coerce_decode_result",
]
