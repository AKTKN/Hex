"""Spatial Hamming MWPM boundary for the rotated-surface factory.

Recovery and the independent H3 sector score share spatial transforms, not
mutable matching state. No projected circuit prior is used.
"""

from typing import TYPE_CHECKING

import numpy as np
import pymatching

from .surface_gap import SurfaceMWPMHomologyGap

if TYPE_CHECKING:
    from hex_qec.modularisation.factory import CodeSpec


class SurfaceFactoryReadout:
    """Cached spatial transforms and separate online/evaluation matchings."""

    def __init__(self, code: "CodeSpec", z_checks):
        if code.family != "rotated_surface":
            raise ValueError("factory Hamming readout currently supports rotated_surface only")
        self.num_data_qubits = code.num_data_qubits
        self._hz = z_checks.astype(np.uint8).tocsc(copy=True)
        self.num_z_checks = self._hz.shape[0]
        self._lx = np.zeros(self.num_data_qubits, dtype=bool)
        self._lz = np.zeros(self.num_data_qubits, dtype=np.uint8)
        self._lx[list(code.logical_x)] = True
        self._lz[list(code.logical_z)] = 1
        self._online = pymatching.Matching.from_check_matrix(self._hz)
        self._terminal = pymatching.Matching.from_check_matrix(self._hz)
        # A finite Hamming score is used for every physical p, including p=0.
        # It is not a noise-derived LLR or an infinite deterministic prior.
        self._gap = SurfaceMWPMHomologyGap(
            self._hz, self._lz, np.ones(self.num_data_qubits), score_units="hamming_weight",
        )

    @property
    def gap_units(self) -> str:
        return self._gap.score_units

    def score_gap(self, syndrome: np.ndarray) -> np.ndarray:
        return self._gap.decode_batch(syndrome).gap

    def syndrome(self, measurements: np.ndarray) -> np.ndarray:
        return (measurements @ self._hz.T % 2).astype(bool)

    def logical_parity(self, measurements: np.ndarray) -> np.ndarray:
        return (measurements @ self._lz % 2).astype(bool)

    def byproduct_frame(self, byproducts: np.ndarray) -> np.ndarray:
        return byproducts[:, None] & self._lx[None, :]

    def recover(self, syndrome: np.ndarray) -> np.ndarray:
        recovery = self._online.decode_batch(syndrome).astype(bool)
        if np.any(syndrome ^ self.syndrome(recovery)):
            raise ValueError("online decoder did not resolve the measured syndrome")
        return recovery

    def evaluate_terminal(self, oracle: np.ndarray, frame_x: np.ndarray) -> np.ndarray:
        """Evaluation-only code-capacity recovery of the final ideal Z readout."""
        corrected = oracle ^ frame_x
        syndrome = self.syndrome(corrected)
        recovery = self._terminal.decode_batch(syndrome).astype(bool)
        if np.any(syndrome ^ self.syndrome(recovery)):
            raise ValueError("terminal evaluation decoder did not resolve the syndrome")
        return self.logical_parity(corrected ^ recovery)
