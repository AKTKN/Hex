"""Rotated surface-code adapter for the geometry-independent factory builder."""

from numbers import Integral

import numpy as np
import stim

from .circuit_generation import (
    create_stabilizers_and_block_template,
    generate_blocks,
    get_parity_check_matrices,
    stabilizer_measurement_circuit_both_detectors,
)
from .factory_noise import FactoryNoiseModel
from hex_qec.modularisation.factory import BlockSupport, CodeSpec, _positive_integer
from hex_qec.modularisation.module_generation import generate_state_prep_modules
from hex_qec.modularisation.modularised_circuit import css_detector_module


class RotatedSurfaceCodeAdapter:
    """Bundled odd-distance, k=1 surface matrices and Hex hook ordering."""

    def __init__(self, distance: int):
        if isinstance(distance, bool) or not isinstance(distance, Integral) or distance < 3 or distance % 2 == 0:
            raise ValueError("surface distance must be an odd integer >= 3")
        try:
            self.matrices = tuple(matrix.tocsc() for matrix in get_parity_check_matrices("surface", distance))
        except IndexError as error:
            raise ValueError(f"surface distance {distance} has no bundled matrices") from error
        hx, hz, lx, lz = self.matrices
        n = hx.shape[1]
        if hz.shape[1] != n or lx.shape != (1, n) or lz.shape != (1, n) or n != distance * distance:
            raise ValueError("expected a single-logical rotated surface code")
        for matrix in self.matrices:
            if not np.all((matrix.data == 0) | (matrix.data == 1)):
                raise ValueError("CSS matrices must be binary")
        for first, second in ((hx, hz), (hx, lz), (hz, lx)):
            if np.any((first @ second.T).toarray() % 2):
                raise ValueError("CSS checks/logicals must commute")
        if (lx @ lz.T).toarray()[0, 0] % 2 != 1:
            raise ValueError("logical X and Z must anticommute")

        def rows(matrix):
            return tuple(tuple(int(index) for index in matrix.getrow(row).nonzero()[1])
                         for row in range(matrix.shape[0]))

        self.code = CodeSpec("rotated_surface", n, rows(hx), rows(hz), rows(lx)[0], rows(lz)[0], int(distance))
        self._template = create_stabilizers_and_block_template(*self.matrices)[0]

    def blocks(self) -> tuple[BlockSupport, BlockSupport]:
        blocks = generate_blocks(2, self._template)
        return tuple(BlockSupport(name, *(tuple(block[key]) for key in
                     ("data_qubits", "x_ancillas", "z_ancillas")))
                     for name, block in zip(("A", "B"), blocks))

    def prepare(self, block: BlockSupport, basis: str, rounds: int, physical_error: float,
                *, noise_model: FactoryNoiseModel | None = None):
        _positive_integer(rounds, "preparation rounds")
        if basis.upper() not in {"X", "Z"}:
            raise ValueError("preparation basis must be X or Z")
        if noise_model is not None:
            if not isinstance(noise_model, FactoryNoiseModel):
                raise ValueError("noise_model must be FactoryNoiseModel or None")
            circuit = _custom_preparation_circuit(self.matrices, basis, rounds,
                                                   physical_error, noise_model)
            # Compile *after* all operation channels are placed. Hex derives
            # DEM priors, representative faults and local repair maps together
            # from this circuit; no precompiled uniform module is modified.
            mx, mz = len(self.code.x_checks), len(self.code.z_checks)
            x_detectors, z_detectors = [], []
            for se_round in range(rounds):
                if se_round or basis.upper() == "X":
                    start = len(x_detectors) + len(z_detectors)
                    x_detectors.extend(range(start, start + mx))
                if se_round or basis.upper() == "Z":
                    start = len(x_detectors) + len(z_detectors)
                    z_detectors.extend(range(start, start + mz))
            module = css_detector_module(circuit, _matching, self.matrices,
                                         x_detectors, z_detectors, matchable=True,
                                         allow_pauli_products=True)
            module.set_support(list(block.qubits))
            return module
        return generate_state_prep_modules(
            self.matrices, rounds, basis.lower(), physical_error, [list(block.qubits)],
            _matching, matchable=True, surface_code=True,
        )[0]


def _custom_preparation_circuit(matrices, basis, rounds, p, model):
    """Reuse native surface gate/detector ordering before any compilation.

    Start with the native zero-noise skeleton, then attach operation-specific
    channels. This factory-only path deliberately has no implicit idle noise.
    MR is Z measurement followed by reset: separate pre/post Pauli channels
    describe its two operations (the next explicit R erases its reset error).
    """
    probabilities = model.operation_probabilities(p)
    skeleton = stabilizer_measurement_circuit_both_detectors(
        matrices, basis.lower(), rounds, 0, surface_code=True,
    )
    circuit = stim.Circuit()

    def noise(gate, targets, operation):
        probability = probabilities[operation]
        if probability:
            circuit.append(gate, targets, probability)

    for instruction in skeleton:
        name, targets = instruction.name, instruction.targets_copy()
        # Keep the original instruction stream until replacement is complete:
        # without_noise() would fuse adjacent CX operations and move each
        # inserted error across later noncommuting interactions.
        if name in {"X_ERROR", "Z_ERROR", "DEPOLARIZE2"}:
            if instruction.gate_args_copy() != [0.]:
                raise ValueError("factory preparation skeleton must have zero noise")
            continue
        if name == "MR":
            noise("X_ERROR", targets, "measurement")
        elif name not in {"R", "RX", "H", "CX", "CZ", "DETECTOR"}:
            raise ValueError(f"unsupported factory preparation operation {name}")
        circuit.append(instruction)
        if name in {"R", "RX", "MR"}:
            noise("Z_ERROR" if name == "RX" else "X_ERROR", targets, "reset")
        elif name == "H":
            noise("DEPOLARIZE1", targets, "one_qubit")
        elif name in {"CX", "CZ"}:
            noise("DEPOLARIZE2", targets, "two_qubit")
    return circuit


def _matching(check_matrix, weights=None):
    import pymatching

    if weights is None:
        return pymatching.Matching.from_check_matrix(check_matrix)
    return pymatching.Matching.from_check_matrix(check_matrix, weights=weights)
