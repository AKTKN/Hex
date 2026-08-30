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


class HexBPLSDDecoder:
    def __init__(self, pcm, error_channel, alpha=2.0, **decoder_options):
        from ldpc.bplsd_decoder import BpLsdDecoder

        self.pcm = pcm
        options = dict(decoder_options)
        options.setdefault("input_vector_type", "syndrome")
        options.setdefault("always_run_lsd", True)
        self.decoder = BpLsdDecoder(
            pcm,
            error_channel=list(error_channel),
            **options,
        )
        self.decoder.set_do_stats(True)
        self.alpha = alpha
        self.error_channel = np.asarray(error_channel, dtype=float)
        if np.any((self.error_channel < 0) | (self.error_channel > 1)):
            raise ValueError("error_channel entries must lie in [0, 1]")
        with np.errstate(divide="ignore", invalid="ignore"):
            self.prior_llr = np.log1p(-self.error_channel) - np.log(
                self.error_channel
            )

    def _compute_cluster_llr(
        self,
        ind_cluster_stats: dict,
        w_e: np.ndarray,
        alpha: float,
    ) -> float:
        """
        Definition 2 (Lee, English, Bartlett 2026): Cluster LLR alpha-norm fraction.

        Q_LLR^(alpha) = [sum_i (sum_{e in C_i} w_e)^alpha]^(1/alpha) / sum_{e in E} w_e

        where w_e = log((1 - p_e) / p_e) is the prior LLR and {C_i} are the final
        active clusters from LSD (those not absorbed by another cluster).

        Returns 0.0 when there are no clusters (zero syndrome / no errors),
        which corresponds to maximum decoding confidence.
        """
        finite_mask = np.isfinite(w_e)
        total_w = float(np.sum(w_e[finite_mask]))
        if total_w == 0.0 or not ind_cluster_stats:
            return 0.0

        # Final clusters: active and not absorbed into another cluster
        active_clusters = [
            cs for cs in ind_cluster_stats.values()
            if cs.get("active", False) and cs.get("absorbed_by_cluster", -1) == -1
        ]
        if not active_clusters:
            return 0.0

        cluster_sums = []
        for cs in active_clusters:
            # ldpc versions expose this as ``solution``; retain support for
            # the older/alternate ``final_bits`` spelling used by the
            # original research adapter.
            bits = cs.get("solution", cs.get("final_bits", []))
            if not bits:
                continue
            csum = float(np.sum(w_e[list(bits)]))
            if np.isfinite(csum):
                cluster_sums.append(csum)

        if not cluster_sums:
            return 0.0

        arr = np.array(cluster_sums, dtype=np.float64)
        if np.isinf(alpha):
            # alpha -> inf: dominated by the largest cluster
            return float(np.max(arr) / total_w)
        return float((np.sum(arr ** alpha) ** (1.0 / alpha)) / total_w)

    def decode_batch(self, syndromes):
        syndromes = np.asarray(syndromes, dtype=np.uint8)

        corrections = np.zeros(
            (syndromes.shape[0], self.pcm.shape[1]),
            dtype=np.uint8,
        )
        cluster_llr = np.zeros(syndromes.shape[0], dtype=float)

        for shot, syndrome in enumerate(syndromes):
            recovery = self.decoder.decode(syndrome)

            corrections[shot] = recovery

            stats = self.decoder.statistics
            cluster_llr[shot] = self._compute_cluster_llr(
                stats["individual_cluster_stats"],
                self.prior_llr,
                self.alpha,
            )

        return DecodeResult(
            correction=corrections,
            # This metric is a risk score: lower values are more confident.
            confidence=cluster_llr,
            metrics={"cluster_llr": cluster_llr},
        )


def make_bplsd_decoder_generator(
    physical_error: float,
    *,
    alpha: float = 2.0,
    **decoder_options: Any,
) -> Callable[..., HexBPLSDDecoder]:
    """Create a legacy-compatible BP-LSD generator with soft output.

    Hex supplies DEM probabilities as ``weights`` when using the
    non-matchable representation.  Code-capacity decoders are constructed
    without weights, so they use a uniform channel with one probability per
    PCM column.
    """
    if not 0.0 <= physical_error < 1.0:
        raise ValueError("physical_error must be in [0, 1)")

    def generator(pcm, weights=None):
        if weights is None:
            error_channel = np.full(pcm.shape[1], physical_error, dtype=float)
        else:
            error_channel = np.asarray(weights, dtype=float)
            if error_channel.shape != (pcm.shape[1],):
                raise ValueError(
                    "BP-LSD error_channel must have one probability per PCM column"
                )
        return HexBPLSDDecoder(
            pcm,
            error_channel,
            alpha=alpha,
            **decoder_options,
        )

    return generator
