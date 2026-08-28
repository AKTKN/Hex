"""Adapters for Hex's historical decoder-generator convention."""

from typing import Any, Callable

import numpy as np

from .base import DecodeResult


def coerce_decode_result(output: DecodeResult | np.ndarray) -> DecodeResult:
    """Wrap a legacy correction array without changing its values or dtype."""

    if isinstance(output, DecodeResult):
        return output
    return DecodeResult(correction=output)


class LegacyDecoderAdapter:
    """Adapt an object exposing ``decode_batch`` or scalar ``decode``.

    ``cast_batch_to_uint8`` and ``cast_scalar_to_uint8`` are explicit because
    the historical Hex call sites do not all pass the same input dtype.  The
    defaults preserve an unmodified decoder input; callers that previously
    cast to ``uint8`` can opt into that exact behavior.
    """

    def __init__(
        self,
        decoder: Any,
        check_matrix: Any,
        *,
        cast_batch_to_uint8: bool = False,
        cast_scalar_to_uint8: bool = False,
        correction_dtype: Any = np.uint8,
    ) -> None:
        self.decoder = decoder
        self.check_matrix = check_matrix
        self.num_correction_variables = check_matrix.shape[1]
        self.cast_batch_to_uint8 = cast_batch_to_uint8
        self.cast_scalar_to_uint8 = cast_scalar_to_uint8
        self.correction_dtype = correction_dtype

        self._decode_batch = getattr(decoder, "decode_batch", None)
        self._decode_scalar = getattr(decoder, "decode", None)
        if not callable(self._decode_batch) and not callable(self._decode_scalar):
            raise TypeError("Decoder must provide decode_batch(...) or decode(...)")

    def decode_batch(self, syndromes: np.ndarray) -> DecodeResult:
        """Decode a batch and return a ``DecodeResult``.

        The scalar fallback uses the same `(batch, check_matrix.shape[1])`
        allocation shape used by the legacy helpers; its dtype is configurable
        because the historical helpers used both `uint8` and `int8`.
        """

        syndrome_batch = np.asarray(syndromes)
        if syndrome_batch.ndim != 2:
            raise ValueError("syndromes must be a two-dimensional batch")

        if callable(self._decode_batch):
            decoder_input = syndrome_batch
            if self.cast_batch_to_uint8:
                decoder_input = decoder_input.astype(np.uint8)
            return coerce_decode_result(self._decode_batch(decoder_input))

        errors = np.zeros(
            (syndrome_batch.shape[0], self.num_correction_variables),
            dtype=self.correction_dtype,
        )
        for shot_index in range(syndrome_batch.shape[0]):
            syndrome = syndrome_batch[shot_index, :]
            if self.cast_scalar_to_uint8:
                syndrome = syndrome.astype(np.uint8)
            errors[shot_index, :] = self._decode_scalar(syndrome)
        return DecodeResult(correction=errors)


class LegacyDecoderGeneratorAdapter:
    """Adapt a historical ``decoder_generator(check_matrix, weights=...)``."""

    def __init__(
        self,
        decoder_generator: Callable[..., Any],
        *,
        cast_batch_to_uint8: bool = False,
        cast_scalar_to_uint8: bool = False,
        correction_dtype: Any = np.uint8,
    ) -> None:
        self.decoder_generator = decoder_generator
        self.cast_batch_to_uint8 = cast_batch_to_uint8
        self.cast_scalar_to_uint8 = cast_scalar_to_uint8
        self.correction_dtype = correction_dtype

    def create(self, check_matrix: Any, *, weights: Any = None) -> LegacyDecoderAdapter:
        """Construct an adapted legacy decoder.

        Omitting ``weights`` preserves the old one-argument generator call;
        supplying it preserves the old keyword call used by DEM decoders.
        """

        if weights is None:
            decoder = self.decoder_generator(check_matrix)
        else:
            decoder = self.decoder_generator(check_matrix, weights=weights)
        return LegacyDecoderAdapter(
            decoder,
            check_matrix,
            cast_batch_to_uint8=self.cast_batch_to_uint8,
            cast_scalar_to_uint8=self.cast_scalar_to_uint8,
            correction_dtype=self.correction_dtype,
        )


def adapt_decoder_generator(
    decoder_generator: Callable[..., Any],
    *,
    cast_batch_to_uint8: bool = False,
    cast_scalar_to_uint8: bool = False,
    correction_dtype: Any = np.uint8,
) -> LegacyDecoderGeneratorAdapter:
    """Convenience constructor for ``LegacyDecoderGeneratorAdapter``."""

    return LegacyDecoderGeneratorAdapter(
        decoder_generator,
        cast_batch_to_uint8=cast_batch_to_uint8,
        cast_scalar_to_uint8=cast_scalar_to_uint8,
        correction_dtype=correction_dtype,
    )
