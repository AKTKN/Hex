"""Causal full-Knill contexts for the shared projected-prior service.

Only complete fixed-round prefixes are supported. X and Z sector priors
are separate min-sum approximations; their cross-sector correlations are
retained in mechanism provenance, not used as a joint likelihood.
"""

import hashlib

import numpy as np
import pymatching
from scipy import sparse
import stim

from hex_qec.decoders.codecapacity_dem import (
    EffectivePriorBuilder, OnlineMeasurementContext, PreparationDecoderConvention,
    UnsupportedProjectedModel, _digest, _enumerate_prefix_faults,
)
from .modularised_circuit import css_detector_module, measurement_module
from .results import normalize_module_decode_output


def _matrix_identity(matrix):
    m = sparse.csc_matrix(matrix)
    return m.shape, m.indptr.tolist(), m.indices.tolist(), m.data.tolist()


def _preparation_identity(module):
    graphs = []
    for name in ("x_dem_decoder", "z_dem_decoder", "x_decoder", "z_decoder"):
        native = getattr(getattr(module, name), "decoder", None)
        if not module.matchable or not isinstance(native, pymatching.Matching):
            raise UnsupportedProjectedModel("full Knill projected priors require legacy matchable PyMatching preparation")
        graphs.append(tuple((a, b, tuple(sorted(data["fault_ids"])), float(data["weight"]))
                            for a, b, data in native.edges()))
    return tuple(graphs)


def configure_bell_projected_priors(module, parity_check_tuple, contexts):
    """Install two validated sector decoders without changing the physical gadget.

    Contexts must end at this already-remapped Bell module. A standalone Bell
    gadget cannot infer preceding preparation context by itself.
    """
    if contexts is None or len(contexts) != 2:
        raise ValueError("True Bell decoding requires complete X and Z OnlineMeasurementContext objects")
    x_pcm, z_pcm, x_logical, z_logical = parity_check_tuple
    if x_logical.shape[0] != 1 or z_logical.shape[0] != 1:
        raise UnsupportedProjectedModel("projected Bell decoding supports exactly one logical qubit")
    n = x_pcm.shape[1]
    services = []
    for context, sector, h, logical in zip(contexts, ("x", "z"), (x_pcm, z_pcm), (x_logical, z_logical)):
        if (not isinstance(context, OnlineMeasurementContext) or context.sector != sector
                or context.check_matrix.shape != h.shape or (context.check_matrix != h).nnz
                or not np.array_equal(context.logical, logical.toarray().ravel())
                or context.circuit[-len(module.circuit):] != module.circuit):
            raise ValueError("Bell context code/sector or complete physical prefix disagrees with the module")
        service = EffectivePriorBuilder(context)
        service.compile_gap()  # Strict: no silent Hamming fallback or lost logical terms.
        services.append(service)
    gaps = tuple(service.compile_gap() for service in services)
    logicals = (x_logical, z_logical)
    checks = (x_pcm, z_pcm)

    def decode(measurements):
        records = np.asarray(measurements)
        if records.ndim != 2 or records.shape[1] != 2 * n or not np.all((records == 0) | (records == 1)):
            raise ValueError("Bell readout needs binary (shots,2*n) records")
        values = []
        for index, (gap, h, logical) in enumerate(zip(gaps, checks, logicals)):
            readout = records[:, index * n:(index + 1) * n]
            syndrome = (readout @ h.T % 2).astype(bool)
            error_class = gap.decode_batch(syndrome).best_class
            values.append(((readout @ logical.T % 2).ravel().astype(bool) ^ error_class.astype(bool))[:, None])
        # First bit applies logical Z, second logical X, as in legacy Bell EC.
        return np.hstack(values).astype(np.int8)

    module.c_func = decode
    module.projected_priors = tuple(service.build() for service in services)


def configure_knill_projected_priors(protocol, parity_check_tuple):
    """Configure chronologically after legacy correction-map construction.

    Each interpreter replays actual preparation and earlier Bell corrections,
    restricted to the current prefix. It never calls a final logical module.
    Later contexts identify and use the earlier projected policies.
    """
    modules = protocol.circuit_modules
    prepared = {}
    for module in modules:
        if isinstance(module, css_detector_module):
            prepared[id(module)] = _preparation_identity(module)
            module.cache_m2d_converters()
    prefix, regions, history = stim.Circuit(), [], []
    stage, offset = 0, 0
    for index, module in enumerate(modules):
        start = len(prefix)
        prefix += module.circuit
        regions.append((stage, f"{type(module).__name__}_{index}", start, len(prefix)))
        # Fixed Knill has only CSS preparations, pure gates, Bell measurements
        # and its final logical readout. Final readout is deliberately skipped.
        if isinstance(module, measurement_module):
            width = prefix.num_measurements
            steps = tuple((previous, record_slice, previous.correction_to_measurement_flips[:, :width].copy())
                          for previous, record_slice in history)
            identity = _digest((
                "knill_legacy_maps_projected_prefix_v1", str(prefix),
                tuple((record_slice.start, record_slice.stop,
                       prepared.get(id(previous)),
                       tuple((p.model_sha256, p.configuration_sha256)
                             for p in getattr(previous, "projected_priors", ())),
                       _matrix_identity(mapping)) for previous, record_slice, mapping in steps),
            ))
            faults = _enumerate_prefix_faults(prefix, tuple(regions))
            contexts = []
            for sector_index, (h, logical) in enumerate(((parity_check_tuple[0], parity_check_tuple[2]),
                                                        (parity_check_tuple[1], parity_check_tuple[3]))):
                if logical.shape[0] != 1:
                    raise UnsupportedProjectedModel("projected Bell decoding supports exactly one logical qubit")
                n = h.shape[1]
                readout_slice = slice(offset + sector_index * n, offset + (sector_index + 1) * n)

                def interpret(records, *, steps=steps, readout_slice=readout_slice, width=width):
                    working = np.asarray(records)
                    if working.ndim != 2 or working.shape[1] != width:
                        raise ValueError("Knill interpreter requires exactly its causal prefix")
                    working = working.astype(bool, copy=True)
                    for previous, record_slice, mapping in steps:
                        correction = normalize_module_decode_output(previous.c_func(working[:, record_slice])).corrections
                        working ^= (sparse.csc_matrix(correction) @ mapping).toarray().astype(np.uint8) % 2 != 0
                    return working[:, readout_slice]

                contexts.append(OnlineMeasurementContext(
                    prefix, stage, "x" if sector_index == 0 else "z", h, logical.toarray().ravel(),
                    interpret, faults,
                    tuple(tuple((np.flatnonzero(row) + readout_slice.start).tolist()) for row in h.toarray()),
                    tuple((np.flatnonzero(logical.toarray().ravel()) + readout_slice.start).tolist()),
                    identity, hashlib.sha256(str(prefix).encode()).hexdigest(),
                    PreparationDecoderConvention(frame="hex_legacy_global_measurement_maps_v1",
                                                 prefix_online="knill_causal_projected_v1"),
                ))
            configure_bell_projected_priors(module, parity_check_tuple, tuple(contexts))
            stage += 1
        if isinstance(module, (css_detector_module, measurement_module)):
            history.append((module, slice(offset, offset + module.num_measurements)))
        offset += module.num_measurements
