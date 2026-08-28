import numpy as np
import pytest
import stim

from hex_qec.modularisation import (
    SimulationResult,
    SimulationSummary,
    measurement_module,
    modularised_circuit,
)


def make_zero_correction_protocol():
    def c_func(measurements):
        return np.zeros((measurements.shape[0], 1), dtype=np.uint8)

    module = measurement_module(
        stim.Circuit("M 0"), c_func, [("X0", 1)], new_support=[0]
    )
    protocol = modularised_circuit([module])
    protocol.generate_correction_to_measurement_flip_map()
    return protocol


def test_simulation_result_wraps_legacy_counts_and_keeps_future_data_empty():
    result = SimulationResult.from_legacy(
        256,
        3,
        runtime_seconds=0.25,
        metadata={"execution_backend": "test"},
    )

    assert isinstance(result.summary, SimulationSummary)
    assert result.shots == 256
    assert result.samples_performed == 256
    assert result.logical_errors == 3
    assert result.logical_error_rate == pytest.approx(3 / 256)
    assert result.to_legacy_tuple() == (256, 3)
    assert result.state_prep_stats == []
    assert result.per_shot is None
    assert result.debug_data is None
    assert result.metadata == {"execution_backend": "test"}


def test_simulate_result_matches_existing_fixed_round_return_shape():
    protocol = make_zero_correction_protocol()

    legacy = protocol.simulate(max_shots=1, max_errors_before_halting=1)
    result = protocol.simulate_result(max_shots=1, max_errors_before_halting=1)

    assert result.to_legacy_tuple() == legacy
    assert result.summary.logical_error_rate == 0.0
    assert result.summary.runtime_seconds is not None
    assert result.metadata["execution_backend"] == "static_compiled"
    assert result.metadata["adaptive"] is False
    assert result.detail_level == "summary"


@pytest.mark.parametrize("detail_level", ["summary", "analysis", "debug"])
def test_fixed_round_result_does_not_claim_unavailable_detail_data(detail_level):
    protocol = make_zero_correction_protocol()

    result = protocol.simulate_result(
        max_shots=1,
        max_errors_before_halting=1,
        detail_level=detail_level,
    )

    assert result.detail_level == detail_level
    assert result.per_shot is None
    assert result.debug_data is None
    assert result.state_prep_stats == []


def test_simulation_result_rejects_unknown_detail_level():
    with pytest.raises(ValueError, match="detail_level"):
        SimulationResult.from_legacy(0, 0, detail_level="full")
