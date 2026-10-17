"""HEX-N1: inexpensive deterministic parameter and semigroup checks."""

from dataclasses import FrozenInstanceError, replace
import math

import pytest

from hex_qec.circuit_generation.factory_noise import (
    CircuitNoiseModel, FactoryNoiseModel, IdleWindow, PlusPreparationIdle,
    idle_depolarizing_probability as idle_probability,
)


@pytest.mark.parametrize("field", ["one_qubit", "two_qubit", "idle", "measurement", "reset"])
@pytest.mark.parametrize("bad", [-1, float("inf"), float("nan"), True, "1"])
def test_operation_multipliers_are_validated(field, bad):
    with pytest.raises(ValueError, match=field):
        CircuitNoiseModel(**{field: bad})


def test_frozen_canonical_noise_configuration():
    model = FactoryNoiseModel(one_qubit=0, post_cnot_control=IdleWindow(2, .5),
                              during_plus_preparation=PlusPreparationIdle(True, .25, 3))
    assert model == FactoryNoiseModel(**{k: v for k, v in vars(model).items()})
    assert model.configuration_sha256 == replace(model, two_qubit=1).configuration_sha256
    for field in ("one_qubit", "two_qubit", "idle", "measurement", "reset"):
        assert replace(model, **{field: 4}).configuration_sha256 != model.configuration_sha256
    assert replace(model, post_cnot_control=IdleWindow(3, .5)).configuration_sha256 != model.configuration_sha256
    assert replace(model, during_plus_preparation=PlusPreparationIdle(True, .5, 3)).configuration_sha256 != model.configuration_sha256
    copy = model.as_dict()
    copy["post_cnot_control"]["duration"] = 9
    assert model.post_cnot_control.duration == 2
    with pytest.raises(FrozenInstanceError):
        model.reset = 2


def test_operation_probabilities_validate_products_without_clipping():
    model = CircuitNoiseModel(one_qubit=2, two_qubit=3, measurement=4, reset=5)
    assert model.operation_probabilities(.1) == dict(one_qubit=.2, two_qubit=.1*3, measurement=.4, reset=.5)
    assert model.operation_probabilities(0) == dict(one_qubit=0, two_qubit=0, measurement=0, reset=0)
    with pytest.raises(ValueError, match="p\\*reset"):
        model.operation_probabilities(.21)


@pytest.mark.parametrize("duration", [0, .25, 1, 2, 3.5, 100])
def test_idle_formula(duration):
    q = .02 * 2 * 3
    assert idle_probability(.02, 2, duration, 3) == pytest.approx(.75 * (1 - (1 - 4*q/3)**duration))


def test_idle_composition_and_small_probability_precision():
    q = .003
    a, b = idle_probability(q, 1, .3), idle_probability(q, 1, 2.4)
    assert idle_probability(q, 1, 2.7) == pytest.approx(a + b - 4*a*b/3)
    assert idle_probability(1e-30, 1, .25) == pytest.approx(2.5e-31, rel=1e-14, abs=0)
    assert idle_probability(.75, 1, .25) == .75
    assert idle_probability(1, 1, 1) == 1
    assert idle_probability(1, 1, 2) == pytest.approx(2/3)
    assert idle_probability(1, 1, 0) == 0
    assert idle_probability(0, 1, 12.5) == 0


@pytest.mark.parametrize("args", [(-1,1,1), (math.nan,1,1), (1.1,1,1), (.1,-1,1),
    (.1,1,-1), (.1,1,math.inf), (.1,1,"d"), (.1,1,True), (.1,1,1,-1),
    (.1,20,1), (.1,20,0), (.8,1,.5), (.1,1e308,1,1e308)])
def test_invalid_idle_parameters_raise(args):
    with pytest.raises(ValueError):
        idle_probability(*args)


@pytest.mark.parametrize("constructor,kwargs", [(IdleWindow, {"duration": "d"}),
    (IdleWindow, {"rate_multiplier": -1}), (PlusPreparationIdle, {"enabled": 1}),
    (PlusPreparationIdle, {"se_round_duration": "d"}),
    (FactoryNoiseModel, {"post_cnot_control": {}}),
    (FactoryNoiseModel, {"during_plus_preparation": None})])
def test_invalid_window_objects_raise(constructor, kwargs):
    with pytest.raises(ValueError):
        constructor(**kwargs)


def test_resolved_windows_and_overflow():
    model = FactoryNoiseModel(post_cnot_control=IdleWindow(2, 3),
                              during_plus_preparation=PlusPreparationIdle(True, .5, 2))
    assert model.idle_probabilities(.001, 3) == (idle_probability(.001,1,2,3), idle_probability(.001,1,1.5,2))
    assert replace(model, during_plus_preparation=PlusPreparationIdle()).idle_probabilities(.001, 3)[1] == 0
    with pytest.raises(ValueError, match="finite"):
        FactoryNoiseModel(during_plus_preparation=PlusPreparationIdle(True,1e308)).idle_probabilities(.001,3)
    with pytest.raises(ValueError, match="positive integer"):
        model.idle_probabilities(.001, True)
