"""Rotated surface-code adapter for the geometry-independent factory builder."""

from numbers import Integral

import numpy as np

from .circuit_generation import (
    create_stabilizers_and_block_template,
    generate_blocks,
    get_parity_check_matrices,
)
from hex_qec.modularisation.factory import BlockSupport, CodeSpec, _positive_integer
from hex_qec.modularisation.module_generation import generate_state_prep_modules


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

    def prepare(self, block: BlockSupport, basis: str, rounds: int, physical_error: float):
        _positive_integer(rounds, "preparation rounds")
        if basis.upper() not in {"X", "Z"}:
            raise ValueError("preparation basis must be X or Z")
        return generate_state_prep_modules(
            self.matrices, rounds, basis.lower(), physical_error, [list(block.qubits)],
            _matching, matchable=True, surface_code=True,
        )[0]


def _matching(check_matrix, weights=None):
    import pymatching

    if weights is None:
        return pymatching.Matching.from_check_matrix(check_matrix)
    return pymatching.Matching.from_check_matrix(check_matrix, weights=weights)
