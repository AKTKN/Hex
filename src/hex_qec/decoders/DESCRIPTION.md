# `decoders`

This package contains the decoder result type, compatibility adapters, and an
optional BP-LSD adapter with a cluster-LLR soft output.

## `DecodeResult`

`DecodeResult` is a dataclass with:

```text
correction: ndarray
confidence: ndarray | None
converged: ndarray | None
metrics: dict[str, ndarray]
```

The first axis of the arrays is the batch/shot axis.  `correction[i]` is the
correction-variable vector for shot `i`; the remaining axis convention is
chosen by the decoder/check matrix.  `confidence` and `converged` are optional
and are interpreted only by the selected policy.  `metrics` preserves
decoder-specific arrays without imposing a universal confidence definition.

## Protocols

`Decoder` describes an object with `decode_batch(syndromes)` returning a
`DecodeResult`.  `DecoderFactory` describes an object with
`create(check_matrix, weights=None)`.  They are `typing.Protocol` definitions;
third-party decoder classes do not need to inherit from them.

## Legacy adapters

`LegacyDecoderAdapter` wraps an existing decoder object exposing either:

- `decode_batch(syndromes)`; or
- scalar `decode(syndrome)`.

The scalar fallback allocates an array of shape
`(batch_size, check_matrix.shape[1])`, using `uint8` by default to match the
historical CSS helper; callers can select another allocation dtype where an
older helper used one.  The adapter can preserve legacy batch/scalar input
casts independently.  A legacy ndarray return is wrapped in `DecodeResult`
without changing its values or dtype; an existing `DecodeResult` passes
through.

`LegacyDecoderGeneratorAdapter` wraps the existing callable convention.  It
calls `decoder_generator(check_matrix)` when no weights are provided and
`decoder_generator(check_matrix, weights=weights)` when weights are provided,
matching current Hex call sites.  `adapt_decoder_generator(...)` is a
convenience constructor.

## Compatibility boundary

Existing module callback APIs still return correction ndarrays by default.
The adapters unwrap `DecodeResult.correction` at those boundaries, so the
static correction propagation remains unchanged.  Confidence, convergence,
and metrics are retained only when a caller directly uses an adapter or
returns a structured module result; no Phase 1 code makes an accept/reject
decision.

## BP-LSD cluster-LLR adapter

`HexBPLSDDecoder` adapts `ldpc.bplsd_decoder.BpLsdDecoder` to Hex. Its
`decode_batch(syndromes)` input has shape `(shots, checks)` and its correction
output has shape `(shots, check_matrix.shape[1])`. It calls BP-LSD once per
shot because the installed LDPC API exposes per-shot statistics through the
decoder's mutable `statistics` attribute. `set_do_stats(True)` and
`always_run_lsd=True` are enabled so cluster statistics are available.

The adapter returns the BP-LSD recovery vector as `DecodeResult.correction`,
the cluster-LLR value as both `DecodeResult.confidence` and the named
`metrics["cluster_llr"]` array, with shape `(shots,)`. This cluster LLR is
risk-like: zero means no active cluster/high confidence, while larger values
indicate more unresolved cluster weight. `ClusterLLRPolicy` therefore extends
when the value is above its threshold.

`make_bplsd_decoder_generator(physical_error, alpha=2.0, **decoder_options)`
preserves the historical generator signature. When Hex supplies no `weights`
(the code-capacity call), it creates a uniform probability vector of shape
`(check_matrix.shape[1],)`. When weights are supplied, they are used as the
per-column error channel and therefore should be probabilities; the initial
example uses `matchable=False` so Hex supplies raw DEM priors.

The adapter is optional and does not change the legacy PyMatching, BP, or
BP-OSD generator interface. It is demonstrated in
`examples/bplsd_adaptive_knill.py`.

## Custom decoder integration procedure

A custom decoder is integrated at the existing generator boundary; it does
not need to inherit from a Hex class. The required procedure is:

1. Implement `decode_batch(syndromes)` on an adapter. The input is a binary
   array with shape `(shots, number_of_checks)`. Return a `DecodeResult` whose
   correction has shape `(shots, number_of_decoder_variables)`. Put the
   primary policy value in `confidence` with shape `(shots,)`, and retain
   additional arrays in `metrics`.
2. Wrap construction in a generator with the historical signature
   `generator(check_matrix, weights=None)`. `weights=None` is the
   code-capacity path; supplied weights are the decoder variables of the DEM
   path and must be interpreted according to the decoder's API.
3. Pass that generator as `offline_decoder_generator` to
   `knill_online_offline_adaptive(...)`. Keep the online decoder generator
   separate unless the custom decoder is also intended for Bell/final
   measurement decoding.
4. Choose the metric direction and threshold in an `AdaptivePolicy`. The
   simulator only passes the `DecodeResult`; it does not know whether larger
   or smaller confidence means “extend”.
5. If a CSS module has multiple inner decoder results, provide
   `confidence_aggregator(results) -> ndarray` to combine their scalar
   confidences into one value per shot.

For example, BP-LSD with the adapter in this package can be connected as:

```python
import numpy as np
import pymatching
from hex_qec.decoders import make_bplsd_decoder_generator
from hex_qec.modularisation import AdaptiveSERounds
from hex_qec.protocols import knill_online_offline_adaptive
from hex_qec.simulation import ClusterLLRPolicy

offline = make_bplsd_decoder_generator(
    physical_error=0.01,
    alpha=2.0,
    # Additional ldpc BpLsdDecoder options may be supplied here.
)

def worst_css_cluster_llr(results):
    values = [r.confidence for r in results if r.confidence is not None]
    return np.max(np.stack(values), axis=0) if values else None

result = knill_online_offline_adaptive(
    parity_check_tuple,
    AdaptiveSERounds(
        short_rounds=1,
        long_rounds=3,
        policy=ClusterLLRPolicy(threshold=0.01),
    ),
    online_decoder_generator=pymatching.Matching.from_check_matrix,
    offline_decoder_generator=offline,
    matchable_offline_decoding=False,
    physical_error=0.01,
    max_shots=256,
    max_errors_before_halting=10,
    pauli="z",
    num_teleportations=1,
    confidence_aggregator=worst_css_cluster_llr,
    detail_level="analysis",
)
```

`HexBPLSDDecoder` computes the cluster LLR from BP-LSD's per-shot
`statistics["individual_cluster_stats"]`. In the current adapter, zero is
the no-active-cluster case and is treated as highest confidence; larger values
are risk-like, so `ClusterLLRPolicy` extends when the value is above its
threshold. This convention belongs to the example policy, not to the generic
decoder protocol. For a different decoder, replace the adapter and policy
while retaining the same batch shape and generator boundary.

## Dependencies and limitations

The compatibility layer depends only on NumPy and the Python standard
library. The BP-LSD adapter additionally requires `ldpc`. It does not infer
confidence from a legacy decoder, and it does not adapt decoders that expose
neither `decode_batch` nor `decode`. DEM probabilities and code-capacity
probabilities represent different variable sets; the adapter does not derive
circuit-effective code-capacity priors.
