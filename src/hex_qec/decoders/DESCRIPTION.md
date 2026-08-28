# `decoders`

This package contains the Phase 1 decoder result type and compatibility
adapters.  It does not implement a decoder, confidence policy, or adaptive
execution path.

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
and are not interpreted by Phase 1.  `metrics` preserves decoder-specific
arrays without imposing a universal confidence definition.

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

## Dependencies and limitations

The package depends only on NumPy and the Python standard library.  It does
not require PyMatching, BP, BP-OSD, Stim, or a new decoder dependency.  It
does not infer confidence from a legacy decoder, and it does not adapt
decoders that expose neither `decode_batch` nor `decode`.
