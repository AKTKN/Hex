"""Min-sum logical-sector costs on a validated spatial two-boundary lift.

The extra two rows are constrained vertices, not PyMatching boundary nodes.
No observable row is appended directly to an existing degree-two column.
This computes minimum chain costs, not posterior sums over error patterns.
"""

from dataclasses import dataclass
import hashlib

import networkx as nx
import numpy as np
import pymatching
from scipy import sparse


@dataclass(frozen=True)
class HomologyGapBatch:
    """Shot-first sector costs (S,2), corrections (S,2,n), and scores (S,).

    best_class is uint8 with class zero winning exact cost ties. Costs/gap
    are float64 in score_units; corrections are bool. Arrays are caller-owned.
    """

    sector_costs: np.ndarray
    corrections: np.ndarray
    gap: np.ndarray
    best_class: np.ndarray
    score_units: str

    @property
    def W0(self) -> np.ndarray:
        return self.sector_costs[:, 0]

    @property
    def W1(self) -> np.ndarray:
        return self.sector_costs[:, 1]


def _binary_matrix(value, name: str) -> sparse.csc_matrix:
    matrix = sparse.csc_matrix(value, copy=True)
    matrix.sum_duplicates()
    matrix.eliminate_zeros()
    if not np.all((matrix.data == 0) | (matrix.data == 1)):
        raise ValueError(f"{name} must be binary")
    matrix = matrix.astype(np.uint8)
    matrix.sort_indices()
    return matrix


class SurfaceMWPMHomologyGap:
    """One cached graph, two native batch calls, one logical observable.

    Domain: connected planar spatial graph after the lift, degree-1/2 input
    columns, consistent internal XOR potential, positive finite weights up to
    PyMatching's 2**24-1 limit. Zero-detector events are unsupported. The
    factory uses unit Hamming weights even at physical p=0; infinite priors
    are never passed to this class. Use synchronously within one worker.
    """

    def __init__(self, check_matrix, logical_z, weights, *, score_units: str = "weight"):
        h = _binary_matrix(check_matrix, "check matrix")
        m, n = h.shape
        if m < 1 or n < 1:
            raise ValueError("check matrix must have nonempty detector and edge axes")
        logical = _binary_matrix(logical_z, "logical observable")
        if logical.shape != (1, n):
            raise ValueError("expected exactly one logical observable row of length n")
        l = logical.toarray()[0]
        degree = np.diff(h.indptr)
        if np.any(degree == 0):
            raise ValueError("zero-detector edges, including logical mechanisms, are unsupported")
        if np.any(degree > 2):
            raise ValueError("graphlike input requires degree-1/2 error columns")
        w = np.asarray(weights, dtype=np.float64)
        if (w.shape != (n,) or not np.all(np.isfinite(w)) or np.any(w <= 0)
                or np.any(w > 2**24 - 1)):
            raise ValueError("weights must be n positive finite values <= 2**24-1")
        if (np.min(w) / np.max(w) < 1 / (2**24 - 1)
                or np.max(w) < (2**24 - 1) / np.finfo(np.float64).max):
            raise ValueError("weight dynamic range exceeds supported native precision")
        if score_units not in {"weight", "hamming_weight", "log_weight"}:
            raise ValueError("unknown score units")
        if score_units == "hamming_weight" and not np.all(w == 1):
            raise ValueError("hamming_weight units require unit weights")

        adjacency: list[list[tuple[int, int]]] = [[] for _ in range(m)]
        for edge in np.flatnonzero(degree == 2):
            a, b = h.indices[h.indptr[edge]:h.indptr[edge + 1]]
            adjacency[a].append((int(b), int(l[edge])))
            adjacency[b].append((int(a), int(l[edge])))
        potential = np.full(m, -1, dtype=np.int8)
        # Components and neighbours have fixed ascending input order. The
        # arbitrary root gauge changes boundary naming but not sector costs.
        for root in range(m):
            if potential[root] != -1:
                continue
            potential[root] = 0
            todo = [root]
            while todo:
                a = todo.pop()
                for b, bit in adjacency[a]:
                    expected = int(potential[a]) ^ bit
                    if potential[b] == -1:
                        potential[b] = expected
                        todo.append(b)
                    elif potential[b] != expected:
                        raise ValueError("inconsistent logical potential on an internal cycle")
        u = potential.astype(np.uint8)
        boundary_rows, boundary_columns = [], []
        for edge in np.flatnonzero(degree == 1):
            a = h.indices[h.indptr[edge]]
            boundary_rows.append(int(l[edge] ^ u[a]))
            boundary_columns.append(int(edge))
        boundaries = sparse.csc_matrix(
            (np.ones(len(boundary_rows), dtype=np.uint8), (boundary_rows, boundary_columns)),
            shape=(2, n),
        )
        extended = sparse.vstack((h, boundaries), format="csc")
        if not np.all(np.diff(extended.indptr) == 2):
            raise ValueError("lift must give every edge exactly two endpoints")
        if np.any(((np.asarray(u @ h).ravel() % 2) ^ boundaries.getrow(1).toarray()[0]) != l):
            raise ValueError("lift does not preserve the logical observable")
        graph = nx.Graph()
        graph.add_nodes_from(range(m + 2))
        for edge in range(n):
            graph.add_edge(*extended.indices[extended.indptr[edge]:extended.indptr[edge + 1]])
        if not nx.is_connected(graph):
            raise ValueError("lift must connect all detectors and both logical boundaries")
        if not nx.check_planarity(graph)[0]:
            raise ValueError("only planar spatial graphs are supported")

        self._h, self._l, self._u = h, l, u
        self._extended, self._weights = extended, w.copy()
        self.score_units = score_units
        self._matching = pymatching.Matching.from_check_matrix(
            extended, weights=self._weights, merge_strategy="smallest-weight",
        )
        # Parallel edges have identical lifted syndrome/logical action; the
        # cheapest representative suffices for positive-weight min-sum costs.
        self._matching.ensure_num_fault_ids(n)
        if self._matching.boundary or self._matching.num_detectors != m + 2:
            raise ValueError("lift vertices must all remain constrained detectors")
        # PyMatching scales/rounds nonintegral edge weights internally. This
        # conservative n-edge allowance validates its returned weight without
        # confusing native discretization with a wrong correction map.
        self._native_cost_atol = n * np.max(w) / (2**24 - 1)
        digest = hashlib.sha256()
        for values in (np.asarray(h.shape, dtype=np.int64), h.indptr, h.indices, l, self._weights):
            digest.update(values.tobytes())
        digest.update(("two_boundary_v1:" + score_units).encode())
        digest.update(pymatching.__version__.encode())
        self.cache_identity = digest.hexdigest()

    @property
    def extended_check_matrix(self) -> sparse.csc_matrix:
        return self._extended.copy()

    @property
    def potential(self) -> np.ndarray:
        return self._u.copy()

    def decode_batch(self, syndromes: np.ndarray) -> HomologyGapBatch:
        """Decode both constrained sectors of a nonempty binary (S,m) batch."""
        syndrome = np.asarray(syndromes)
        if (syndrome.ndim != 2 or syndrome.shape[1] != self._h.shape[0]
                or syndrome.shape[0] < 1):
            raise ValueError("expected a nonempty syndrome batch with m columns")
        if not np.all((syndrome == 0) | (syndrome == 1)):
            raise ValueError("syndromes must be binary")
        syndrome = syndrome.astype(np.uint8, copy=False)
        shots, n = len(syndrome), self._h.shape[1]
        lifted = np.empty((shots, self._h.shape[0] + 2), dtype=np.uint8)
        lifted[:, :-2] = syndrome
        parity = np.bitwise_xor.reduce(syndrome, axis=1)
        offset = syndrome @ self._u % 2
        costs = np.empty((shots, 2), dtype=np.float64)
        corrections = np.empty((shots, 2, n), dtype=bool)
        for sector in (0, 1):
            lifted[:, -1] = sector ^ offset
            lifted[:, -2] = parity ^ lifted[:, -1]
            correction, native_cost = self._matching.decode_batch(lifted, return_weights=True)
            if (correction.shape != (shots, n)
                    or np.any((correction @ self._extended.T % 2) != lifted)):
                raise ValueError("matching did not satisfy the lifted sector constraints")
            # Recompute in the original float64 edge weights, retaining their
            # units instead of exposing native solver weight discretization.
            cost = correction @ self._weights
            if (not np.all(np.isfinite(cost))
                    or not np.all(np.isfinite(native_cost))
                    or not np.allclose(cost, native_cost, rtol=1e-12, atol=self._native_cost_atol)):
                raise ValueError("matching weights disagree with returned edge corrections")
            costs[:, sector] = cost
            corrections[:, sector] = correction
        return HomologyGapBatch(costs, corrections, np.abs(costs[:, 1] - costs[:, 0]),
                                (costs[:, 1] < costs[:, 0]).astype(np.uint8), self.score_units)
