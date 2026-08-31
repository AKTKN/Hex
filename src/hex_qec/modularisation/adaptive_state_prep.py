"""Two-level fixed-policy state-preparation descriptions.

This module describes short and long syndrome-extraction circuits.  It does
not make execution decisions; those are handled by the simulation policies
and stateful executor.
"""

from dataclasses import dataclass
import copy
import re
from typing import Callable, List, Tuple

import numpy as np
from numpy import ndarray
import stim

from hex_qec.circuit_generation import stabilizer_measurement_circuit_both_detectors
from hex_qec.decoders import CSSInnerDecodeResults
from hex_qec.simulation.policies import AdaptivePolicy

from .modularised_circuit import css_detector_module


@dataclass(frozen=True)
class AdaptiveSERounds:
    """Configuration for a two-level short/long SE schedule."""

    short_rounds: int
    long_rounds: int
    policy: AdaptivePolicy

    def __post_init__(self) -> None:
        if self.short_rounds < 1:
            raise ValueError("short_rounds must be at least 1")
        if self.short_rounds >= self.long_rounds:
            raise ValueError("short_rounds must be strictly less than long_rounds")


@dataclass
class AdaptiveStatePrepModule:
    """Composed short/extra/long description for one prepared block."""

    schedule: AdaptiveSERounds
    short_module: css_detector_module
    long_module: css_detector_module
    short_circuit: stim.Circuit
    extra_circuit: stim.Circuit
    long_circuit: stim.Circuit
    event_id: str | None = None
    teleportation_index: int | None = None
    state_basis: str | None = None

    def __post_init__(self) -> None:
        if self.short_circuit.num_qubits != self.long_circuit.num_qubits:
            raise ValueError("short and long circuits must use the same qubit count")
        if self.short_circuit.num_measurements > self.long_circuit.num_measurements:
            raise ValueError("short circuit cannot measure more than long circuit")
        if self.short_circuit.num_detectors > self.long_circuit.num_detectors:
            raise ValueError("short circuit cannot have more detectors than long circuit")
        if self.short_circuit + self.extra_circuit != self.long_circuit:
            raise ValueError(
                "extra_circuit must be the exact suffix of long_circuit after short_circuit"
            )
        if self.short_module.circuit != self.short_circuit:
            raise ValueError("short_module must be built from short_circuit")
        if self.long_module.circuit != self.long_circuit:
            raise ValueError("long_module must be built from long_circuit")

    @property
    def short_decoder(self) -> Callable[[np.ndarray], object]:
        return self.short_module.c_func

    @property
    def short_rich_decoder(self) -> Callable[[np.ndarray], object]:
        if (
            hasattr(self.short_module, "_legacy_c_func")
            and self.short_module.c_func is not self.short_module._legacy_c_func
        ):
            return self.short_module.c_func
        return getattr(self.short_module, "c_func_rich", self.short_module.c_func)

    @property
    def long_decoder(self) -> Callable[[np.ndarray], object]:
        return self.long_module.c_func

    @property
    def long_rich_decoder(self) -> Callable[[np.ndarray], object]:
        if (
            hasattr(self.long_module, "_legacy_c_func")
            and self.long_module.c_func is not self.long_module._legacy_c_func
        ):
            return self.long_module.c_func
        return getattr(self.long_module, "c_func_rich", self.long_module.c_func)


def _detector_partition(
    parity_check_tuple: Tuple[ndarray, ...],
    pauli: str,
    syndrome_measurement_rounds: int,
) -> tuple[list[int], list[int]]:
    num_x_stab = parity_check_tuple[0].shape[0]
    num_z_stab = parity_check_tuple[1].shape[0]
    detector_count = 0
    x_detectors: list[int] = []
    z_detectors: list[int] = []
    for syndrome_round in range(syndrome_measurement_rounds):
        if syndrome_round == 0:
            if pauli.lower() == "x":
                x_detectors.extend(range(detector_count, detector_count + num_x_stab))
                detector_count += num_x_stab
            elif pauli.lower() == "z":
                z_detectors.extend(range(detector_count, detector_count + num_z_stab))
                detector_count += num_z_stab
            else:
                raise ValueError("pauli must be 'x' or 'z'")
        else:
            x_detectors.extend(range(detector_count, detector_count + num_x_stab))
            detector_count += num_x_stab
            z_detectors.extend(range(detector_count, detector_count + num_z_stab))
            detector_count += num_z_stab
    return x_detectors, z_detectors


def _remap_circuit_support(circuit: stim.Circuit, support: List[int]) -> stim.Circuit:
    if len(support) == 0:
        support = list(range(circuit.num_qubits))
    if len(support) != circuit.num_qubits:
        raise ValueError("support length must equal the circuit qubit count")
    replacements = {f" {original}": f" {new}" for original, new in enumerate(support)}

    def replace(match: re.Match[str]) -> str:
        return replacements.get(match.group(0), match.group(0))

    pattern = "|".join(rf"{key}\b" for key in replacements)
    return stim.Circuit(re.sub(pattern, replace, str(circuit)))


def _split_state_prep_circuits(
    parity_check_tuple: Tuple[ndarray, ...],
    pauli: str,
    short_rounds: int,
    long_rounds: int,
    physical_error: float,
    surface_code: bool,
) -> tuple[stim.Circuit, stim.Circuit, stim.Circuit]:
    short_circuit = stabilizer_measurement_circuit_both_detectors(
        parity_check_tuple,
        pauli,
        short_rounds,
        physical_error,
        surface_code=surface_code,
    )
    long_circuit = stabilizer_measurement_circuit_both_detectors(
        parity_check_tuple,
        pauli,
        long_rounds,
        physical_error,
        surface_code=surface_code,
    )
    if len(short_circuit) > len(long_circuit):
        raise ValueError("short circuit has more instructions than long circuit")
    if long_circuit[: len(short_circuit)] != short_circuit:
        raise ValueError(
            "long circuit does not have the short circuit as an exact instruction prefix"
        )
    extra_circuit = long_circuit[len(short_circuit) :]

    # The generated suffix resets only syndrome ancillas between rounds.  It
    # must never reset one of the first data-qubit positions.
    num_data_qubits = parity_check_tuple[0].shape[1]
    for instruction in extra_circuit:
        if instruction.name not in {"R", "RX", "RY"}:
            continue
        if any(
            target.is_qubit_target and target.qubit_value < num_data_qubits
            for target in instruction.targets_copy()
        ):
            raise ValueError("extra_circuit reinitializes an encoded data qubit")
    return short_circuit, extra_circuit, long_circuit


def generate_adaptive_state_prep_modules(
    parity_check_tuple: Tuple[ndarray, ...],
    schedule: AdaptiveSERounds,
    pauli: str,
    physical_error: float,
    supports: List[List[int]],
    decoder_generator: Callable,
    matchable: bool,
    surface_code: bool = False,
    event_id_prefix: str | None = None,
    teleportation_index: int | None = None,
    confidence_aggregator: Callable[[CSSInnerDecodeResults], ndarray | None] | None = None,
) -> list[AdaptiveStatePrepModule]:
    """Build adaptive descriptions for one or more encoded-block supports."""

    short_local, extra_local, long_local = _split_state_prep_circuits(
        parity_check_tuple,
        pauli,
        schedule.short_rounds,
        schedule.long_rounds,
        physical_error,
        surface_code,
    )
    short_x, short_z = _detector_partition(
        parity_check_tuple, pauli, schedule.short_rounds
    )
    long_x, long_z = _detector_partition(
        parity_check_tuple, pauli, schedule.long_rounds
    )
    short_template = css_detector_module(
        short_local,
        decoder_generator,
        parity_check_tuple,
        short_x,
        short_z,
        matchable=matchable,
        confidence_aggregator=confidence_aggregator,
    )
    long_template = css_detector_module(
        long_local,
        decoder_generator,
        parity_check_tuple,
        long_x,
        long_z,
        matchable=matchable,
        confidence_aggregator=confidence_aggregator,
    )

    modules: list[AdaptiveStatePrepModule] = []
    for support_index, support in enumerate(supports):
        short_module = copy.deepcopy(short_template)
        long_module = copy.deepcopy(long_template)
        short_module.set_support(support)
        long_module.set_support(support)
        event_id = None
        if event_id_prefix is not None:
            event_id = f"{event_id_prefix}[{support_index}]"
        modules.append(
            AdaptiveStatePrepModule(
                schedule=schedule,
                short_module=short_module,
                long_module=long_module,
                short_circuit=short_module.circuit,
                extra_circuit=_remap_circuit_support(extra_local, support),
                long_circuit=long_module.circuit,
                event_id=event_id,
                teleportation_index=teleportation_index,
                state_basis=pauli.lower(),
            )
        )
    return modules


def generate_adaptive_state_prep_module(
    parity_check_tuple: Tuple[ndarray, ...],
    schedule: AdaptiveSERounds,
    pauli: str,
    physical_error: float,
    support: List[int],
    decoder_generator: Callable,
    matchable: bool,
    surface_code: bool = False,
    event_id: str | None = None,
    teleportation_index: int | None = None,
    confidence_aggregator: Callable[[CSSInnerDecodeResults], ndarray | None] | None = None,
) -> AdaptiveStatePrepModule:
    """Build one adaptive state-preparation description."""

    return generate_adaptive_state_prep_modules(
        parity_check_tuple,
        schedule,
        pauli,
        physical_error,
        [support],
        decoder_generator,
        matchable,
        surface_code=surface_code,
        event_id_prefix=event_id,
        teleportation_index=teleportation_index,
        confidence_aggregator=confidence_aggregator,
    )[0]
