import numpy as np
import pymatching
import stim

from hex_qec.decoders import (
    DecodeResult,
    LegacyDecoderAdapter,
    LegacyDecoderGeneratorAdapter,
)
from hex_qec.modularisation import (
    ModuleDecodeResult,
    normalize_module_decode_output,
    measurement_module,
    modularised_circuit,
)


class BatchDecoder:
    def __init__(self):
        self.inputs = []

    def decode_batch(self, syndromes):
        self.inputs.append(syndromes.copy())
        return syndromes[:, :2].astype(np.int8)


class ScalarDecoder:
    def __init__(self):
        self.inputs = []

    def decode(self, syndrome):
        self.inputs.append(syndrome.copy())
        return np.array([syndrome[0], syndrome[1]], dtype=np.uint8)


def test_legacy_batch_adapter_preserves_uint8_cast_and_correction():
    decoder = BatchDecoder()
    adapter = LegacyDecoderAdapter(
        decoder,
        np.zeros((2, 2), dtype=np.uint8),
        cast_batch_to_uint8=True,
    )
    syndromes = np.array([[0, 1], [1, 0]], dtype=np.int64)

    result = adapter.decode_batch(syndromes)

    np.testing.assert_array_equal(result.correction, syndromes.astype(np.int8))
    assert result.confidence is None
    assert decoder.inputs[0].dtype == np.uint8


def test_legacy_scalar_adapter_matches_historical_batch_shape():
    decoder = ScalarDecoder()
    adapter = LegacyDecoderAdapter(
        decoder,
        np.zeros((2, 2), dtype=np.uint8),
        cast_scalar_to_uint8=True,
        correction_dtype=np.int8,
    )
    syndromes = np.array([[0, 1], [1, 0]], dtype=np.int64)

    result = adapter.decode_batch(syndromes)

    np.testing.assert_array_equal(result.correction, syndromes.astype(np.int8))
    assert result.correction.shape == (2, 2)
    assert result.correction.dtype == np.int8
    assert all(item.dtype == np.uint8 for item in decoder.inputs)


def test_legacy_generator_adapter_preserves_weighted_and_unweighted_calls():
    calls = []

    def generator(check_matrix, weights=None):
        calls.append((check_matrix, weights))
        return BatchDecoder()

    factory = LegacyDecoderGeneratorAdapter(generator)
    pcm = np.zeros((2, 2), dtype=np.uint8)
    weights = np.array([0.2, 0.3])

    factory.create(pcm)
    factory.create(pcm, weights=weights)

    assert calls[0][1] is None
    np.testing.assert_array_equal(calls[1][1], weights)


def test_legacy_adapter_preserves_rich_decoder_result():
    class RichDecoder:
        def decode_batch(self, syndromes):
            return DecodeResult(
                correction=syndromes.copy(),
                confidence=np.full(syndromes.shape[0], 0.75),
                converged=np.ones(syndromes.shape[0], dtype=bool),
                metrics={"iterations": np.ones(syndromes.shape[0], dtype=int)},
            )

    adapter = LegacyDecoderAdapter(
        RichDecoder(), np.zeros((2, 2), dtype=np.uint8)
    )
    result = adapter.decode_batch(np.array([[0, 1]], dtype=np.uint8))

    np.testing.assert_array_equal(result.correction, np.array([[0, 1]], dtype=np.uint8))
    np.testing.assert_array_equal(result.confidence, np.array([0.75]))
    assert result.converged.tolist() == [True]
    assert result.metrics["iterations"].tolist() == [1]


def test_pymatching_adapter_correction_matches_direct_decoder():
    pcm = np.array([[1, 1], [0, 1]], dtype=np.uint8)
    syndromes = np.array([[0, 0], [1, 1], [0, 1]], dtype=np.uint8)
    direct_decoder = pymatching.Matching.from_check_matrix(pcm)
    adapter = LegacyDecoderGeneratorAdapter(pymatching.Matching.from_check_matrix)

    expected = direct_decoder.decode_batch(syndromes)
    actual = adapter.create(pcm).decode_batch(syndromes).correction

    np.testing.assert_array_equal(actual, expected)


def test_module_decode_normalization_supports_legacy_and_structured_outputs():
    corrections = np.array([[0, 1], [1, 0]], dtype=np.uint8)
    postselection = np.array([0, 1], dtype=np.uint8)
    decoder_result = DecodeResult(
        correction=corrections,
        confidence=np.array([0.4, 0.9]),
        converged=np.array([True, False]),
        metrics={"iterations": np.array([2, 3])},
    )

    array_result = normalize_module_decode_output(corrections)
    tuple_result = normalize_module_decode_output((corrections, postselection))
    decoder_module_result = normalize_module_decode_output(decoder_result)
    structured = ModuleDecodeResult(corrections=corrections)

    np.testing.assert_array_equal(array_result.corrections, corrections)
    assert array_result.postselection is None
    np.testing.assert_array_equal(tuple_result.postselection, postselection)
    assert decoder_module_result.decode_result is decoder_result
    np.testing.assert_array_equal(
        decoder_module_result.metrics["iterations"], np.array([2, 3])
    )
    assert normalize_module_decode_output(structured) is structured


def test_module_decode_normalization_supports_decode_result_tuple():
    corrections = np.array([[1, 0]], dtype=np.uint8)
    postselection = np.array([1], dtype=np.uint8)
    decoder_result = DecodeResult(correction=corrections)

    result = normalize_module_decode_output((decoder_result, postselection))

    assert result.decode_result is decoder_result
    np.testing.assert_array_equal(result.corrections, corrections)
    np.testing.assert_array_equal(result.postselection, postselection)


def test_measurement_module_accepts_structured_decode_result_callback():
    def c_func(measurements):
        return ModuleDecodeResult(
            corrections=np.zeros((measurements.shape[0], 1), dtype=np.uint8)
        )

    module = measurement_module(
        stim.Circuit("M 0"), c_func, [("X0", 0)], new_support=[0]
    )

    assert module.num_measurements == 1


def test_static_engine_normalizes_structured_module_result():
    def c_func(measurements):
        return ModuleDecodeResult(
            corrections=np.zeros((measurements.shape[0], 1), dtype=np.uint8),
            postselection=np.zeros(measurements.shape[0], dtype=np.uint8),
        )

    module = measurement_module(
        stim.Circuit("M 0"), c_func, [("X0", 1)], new_support=[0]
    )
    protocol = modularised_circuit([module])
    protocol.generate_correction_to_measurement_flip_map()

    assert protocol.simulate(max_shots=1, max_errors_before_halting=1) == (256, 0)
