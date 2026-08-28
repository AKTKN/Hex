import importlib

import numpy as np
import pymatching
import pytest
import stim

from hex_qec.circuit_generation import get_parity_check_matrices
from hex_qec.modularisation import (
    measurement_module,
    modularised_circuit,
    no_measurement_module,
)
from hex_qec.simulation import (
    StatefulFlipSimulatorBackend,
    reconstruct_measurement_records,
)
from hex_qec.protocols import knill_online_offline


def test_reconstruct_measurement_records_uses_stim_axis_convention():
    reference = np.array([True, False, True])
    # Stim's shape is (measurements, shots).
    flips = np.array(
        [
            [False, True],
            [True, False],
            [False, True],
        ]
    )

    actual = reconstruct_measurement_records(reference, flips)

    np.testing.assert_array_equal(
        actual,
        np.array([[True, True, True], [False, False, False]]),
    )
    assert actual.shape == (2, 3)


def test_stateful_backend_reconstructs_deterministic_chunked_record():
    def no_corrections(measurements):
        return np.zeros((measurements.shape[0], 0), dtype=np.uint8)

    modules = [
        no_measurement_module(stim.Circuit("X 0"), [0]),
        measurement_module(
            stim.Circuit("M 0"), no_corrections, [], new_support=[0]
        ),
    ]
    protocol = modularised_circuit(modules)
    backend = StatefulFlipSimulatorBackend(protocol, batch_size=4, seed=3)

    records = list(backend.iter_module_measurements())

    assert [record.module_index for record in records] == [0, 1]
    assert records[0].measurements.shape == (4, 0)
    np.testing.assert_array_equal(records[1].measurements, np.ones((4, 1)))


def test_stateful_backend_includes_deterministic_noise_in_reconstructed_record():
    def no_corrections(measurements):
        return np.zeros((measurements.shape[0], 0), dtype=np.uint8)

    module = measurement_module(
        stim.Circuit("X_ERROR(1) 0\nM 0"),
        no_corrections,
        [],
        new_support=[0],
    )
    protocol = modularised_circuit([module])
    backend = StatefulFlipSimulatorBackend(protocol, batch_size=4, seed=4)

    record = next(backend.iter_module_measurements()).measurements

    np.testing.assert_array_equal(record, np.ones((4, 1)))


def test_stateful_result_wrapper_preserves_legacy_counts():
    def no_corrections(measurements):
        return np.zeros((measurements.shape[0], 1), dtype=np.uint8)

    module = measurement_module(
        stim.Circuit("M 0"), no_corrections, [("X0", 1)], new_support=[0]
    )
    protocol = modularised_circuit([module])
    protocol.generate_correction_to_measurement_flip_map()

    result = StatefulFlipSimulatorBackend(protocol, seed=5).simulate_result(1, 1)

    assert result.to_legacy_tuple() == (256, 0)
    assert result.metadata["execution_backend"] == "stateful_flip_simulator"
    assert result.metadata["adaptive"] is False


def _capture_knill_circuit(monkeypatch):
    knill_module = importlib.import_module(
        "hex_qec.protocols.knill_online_offline"
    )
    original_constructor = knill_module.modularised_circuit
    captured = []

    def capture(modules):
        circuit = original_constructor(modules)
        captured.append(circuit)
        return circuit

    monkeypatch.setattr(knill_module, "modularised_circuit", capture)
    return captured


@pytest.mark.parametrize("distance", [3, 5])
@pytest.mark.parametrize("num_teleportations", [1, 2])
def test_stateful_knill_matches_static_noiseless_result(
    monkeypatch, distance, num_teleportations
):
    captured = _capture_knill_circuit(monkeypatch)
    parity_checks = get_parity_check_matrices("surface", distance)
    kwargs = dict(
        syndrome_measurement_rounds=distance,
        online_decoder_generator=pymatching.Matching.from_check_matrix,
        offline_decoder_generator=pymatching.Matching.from_check_matrix,
        matchable_offline_decoding=True,
        physical_error=0.0,
        max_shots=256,
        max_errors_before_halting=1,
        pauli="z",
        num_teleportations=num_teleportations,
    )

    static_result = knill_online_offline(parity_checks, **kwargs)
    stateful_result = StatefulFlipSimulatorBackend(
        captured[0], seed=100 + num_teleportations
    ).simulate(256, 1)

    assert static_result == (256, 0)
    assert stateful_result == static_result


@pytest.mark.parametrize("num_teleportations", [1, 2])
def test_stateful_knill_ler_is_statistically_compatible_with_static(
    monkeypatch, num_teleportations
):
    captured = _capture_knill_circuit(monkeypatch)
    parity_checks = get_parity_check_matrices("surface", 3)
    kwargs = dict(
        syndrome_measurement_rounds=3,
        online_decoder_generator=pymatching.Matching.from_check_matrix,
        offline_decoder_generator=pymatching.Matching.from_check_matrix,
        matchable_offline_decoding=True,
        physical_error=0.001,
        max_shots=2048,
        max_errors_before_halting=10_000,
        pauli="z",
        num_teleportations=num_teleportations,
    )

    static_result = knill_online_offline(parity_checks, **kwargs)
    stateful_result = StatefulFlipSimulatorBackend(
        captured[0], seed=200 + num_teleportations
    ).simulate(2048, 10_000)

    static_ler = static_result[1] / static_result[0]
    stateful_ler = stateful_result[1] / stateful_result[0]
    standard_error = np.sqrt(
        max(static_ler * (1 - static_ler), 1 / static_result[0])
        / static_result[0]
    )
    standard_error += np.sqrt(
        max(stateful_ler * (1 - stateful_ler), 1 / stateful_result[0])
        / stateful_result[0]
    )

    # These are independent Monte Carlo samples, so compare rates using a
    # broad finite-shot uncertainty bound rather than exact equality.
    assert abs(static_ler - stateful_ler) <= 5 * standard_error + 0.005
