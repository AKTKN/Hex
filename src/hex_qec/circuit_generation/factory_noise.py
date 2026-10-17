"""Validated circuit-level noise parameters; factory integration is opt-in.

Durations are normalized real times. No generic instruction-by-instruction
idle schedule is implied by these objects.
"""

from dataclasses import asdict, dataclass, field
import hashlib
import json
import math
from numbers import Real


def _nonnegative(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a nonnegative finite real number")
    try:
        value = float(value)
    except (OverflowError, ValueError) as error:
        raise ValueError(f"{name} must be a nonnegative finite real number") from error
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be a nonnegative finite real number")
    return value


def _probability(value: float, name: str) -> float:
    value = _nonnegative(value, name)
    if value > 1:
        raise ValueError(f"{name} must be in [0, 1]")
    return value


def idle_depolarizing_probability(p: float, idle: float, duration: float,
                                  rate_multiplier: float = 1.0) -> float:
    """Return 3/4 * (1 - (1 - 4*p*idle*rate_multiplier/3)**duration).

    Validate the base channel even for zero duration. A negative base has a
    real value only for integer durations in this API. No clipping is used.
    log1p/expm1 retain small exposures that direct subtraction would lose.
    """
    p = _probability(p, "p")
    idle = _nonnegative(idle, "idle")
    duration = _nonnegative(duration, "duration")
    rate_multiplier = _nonnegative(rate_multiplier, "rate_multiplier")
    q = _probability(p * idle * rate_multiplier, "idle window probability")
    if q > .75 and not duration.is_integer():
        raise ValueError("fractional idle duration requires p*idle*rate_multiplier <= 3/4")
    if duration == 0 or q == 0:
        return 0.0
    if q == .75:
        return .75
    if q < .75:
        result = -.75 * math.expm1(duration * math.log1p(-4 * q / 3))
    else:
        result = .75 * (1 - (1 - 4 * q / 3) ** duration)
    return _probability(result, "effective idle probability")


@dataclass(frozen=True)
class CircuitNoiseModel:
    """Reusable operation multipliers relative to physical error rate p.

    Gate channels are depolarizing. Measurement/reset channels are basis-
    appropriate Pauli flips. Idle applies only at explicitly chosen windows.
    """

    one_qubit: float = 1.0
    two_qubit: float = 1.0
    idle: float = 1.0
    measurement: float = 1.0
    reset: float = 1.0

    def __post_init__(self) -> None:
        for name in ("one_qubit", "two_qubit", "idle", "measurement", "reset"):
            object.__setattr__(self, name, _nonnegative(getattr(self, name), name))

    def operation_probabilities(self, p: float) -> dict[str, float]:
        p = _probability(p, "p")
        return {name: _probability(p * getattr(self, name), f"p*{name}")
                for name in ("one_qubit", "two_qubit", "measurement", "reset")}


@dataclass(frozen=True)
class IdleWindow:
    duration: float = 0.0
    rate_multiplier: float = 1.0

    def __post_init__(self) -> None:
        for name in ("duration", "rate_multiplier"):
            object.__setattr__(self, name, _nonnegative(getattr(self, name), name))


@dataclass(frozen=True)
class PlusPreparationIdle:
    enabled: bool = False
    se_round_duration: float = 1.0
    rate_multiplier: float = 1.0

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise ValueError("enabled must be bool")
        for name in ("se_round_duration", "rate_multiplier"):
            object.__setattr__(self, name, _nonnegative(getattr(self, name), name))


@dataclass(frozen=True)
class FactoryNoiseModel(CircuitNoiseModel):
    """Custom factory noise, distinct from the legacy noise_model=None path.

    Even all-one operation multipliers introduce one-qubit gate errors, so
    this object deliberately does not claim to reproduce ``hex_uniform``.
    """

    post_cnot_control: IdleWindow = field(default_factory=IdleWindow)
    during_plus_preparation: PlusPreparationIdle = field(default_factory=PlusPreparationIdle)

    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(self.post_cnot_control, IdleWindow):
            raise ValueError("post_cnot_control must be IdleWindow")
        if not isinstance(self.during_plus_preparation, PlusPreparationIdle):
            raise ValueError("during_plus_preparation must be PlusPreparationIdle")

    def idle_probabilities(self, p: float, r_plus: int) -> tuple[float, float]:
        if isinstance(r_plus, bool) or not isinstance(r_plus, int) or r_plus < 1:
            raise ValueError("r_plus must be a positive integer")
        post, prep = self.post_cnot_control, self.during_plus_preparation
        post_p = idle_depolarizing_probability(p, self.idle, post.duration, post.rate_multiplier)
        try:
            duration = r_plus * prep.se_round_duration
        except OverflowError as error:
            raise ValueError("preparation idle duration must be finite") from error
        prep_p = idle_depolarizing_probability(p, self.idle, duration, prep.rate_multiplier)
        return post_p, prep_p if prep.enabled else 0.0

    def as_dict(self) -> dict:
        """Fresh JSON-compatible copy; editing it cannot mutate this model."""
        return asdict(self)

    @property
    def configuration_sha256(self) -> str:
        canonical = json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False)
        return hashlib.sha256(canonical.encode()).hexdigest()
