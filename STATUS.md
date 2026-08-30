# Implementation status

Date: 2026-08-29
Branch: `hex-adaptive`  
Base commit: `cc26813` (`Implement two-level adaptive state-preparation framework with diagnostic policies`)

## Completed checkpoints

- Read `AGENTS.md`, `PLAN.md`, and `FUTURE.md` before inspection.
- Inspected repository state/history, package layout, exports, dependencies,
  circuit generation, modularisation, protocol builders, examples, and README
  call flow.
- Verified that the local commit matches the upstream snapshot recorded in
  `AGENTS.md`; no tracked core-code changes are present.
- Corrected `AGENTS.md` to describe the actual sparse Matrix Market inputs,
  package exports, and local baseline environment.
- Added package descriptions at:
  `src/hex_qec/circuit_generation/DESCRIPTION.md`,
  `src/hex_qec/modularisation/DESCRIPTION.md`, and
  `src/hex_qec/protocols/DESCRIPTION.md`.
- Added this status report, `TEST.md`, and the theory skeleton `THEORY.md`.
- Implemented Phase 1 decoder results, protocols, legacy decoder adapters, and
  module-output normalization under `src/hex_qec/decoders/` and
  `src/hex_qec/modularisation/results.py`.
- Implemented Phase 2 aggregate simulation results in the existing
  modularisation result module without changing the sampling backend or
  adaptive control flow.
- Implemented Phase 3 `StatefulFlipSimulatorBackend` under
  `src/hex_qec/simulation/stateful.py` for fixed-round module-by-module
  execution with `stim.FlipSimulator`.
- Implemented the Phase 4 two-level state-preparation descriptions and Phase 5
  executor under
  `src/hex_qec/modularisation/adaptive_state_prep.py` and
  `src/hex_qec/simulation/adaptive.py`.
- Added `AdaptivePolicy`, `AlwaysShortPolicy`, `AlwaysLongPolicy`, and the
  example `ClusterLLRPolicy`.
- Implemented confidence-driven mixed short/long execution. Low-confidence
  shots continue the same physical `FlipSimulator` state through the extra
  suffix; the long decoder receives the complete round-1..long history.
- Added `HexBPLSDDecoder` and `make_bplsd_decoder_generator(...)` as an
  adapter example exposing BP-LSD cluster LLR through `DecodeResult.confidence`.
- Added the separate `knill_online_offline_adaptive(...)` result-returning
  entry point, including `|0_L>` and `|+_L>` events at each teleportation.
- Integrated the adapters into existing decoder call sites while preserving
  historical input casts and scalar-fallback output dtypes.
- Added focused tests under `tests/test_phase1_decoder_adapters.py`.
- Added a structured-output constructor check for `measurement_module`.
- Verified the legacy adapter with tiny PyMatching, BP, and BP-OSD decoders;
  the installed ldpc version requires `input_vector_type='syndrome'`.
- Made no changes to core numerical, physical-noise, or correction behavior.

## Current implementation

The legacy repository remains fixed-round: its protocols build a complete
static Stim circuit, precompute correction-to-measurement maps, sample in
batches of 256, and return the historical two-count tuple.  Phase 1 provides
`DecodeResult`, decoder protocols/adapters, and `ModuleDecodeResult`
normalization.  Phase 2 adds `SimulationSummary`, `AdaptiveStatePrepStats`,
and `SimulationResult`.  Phase 3 adds the separate fixed-round
`StatefulFlipSimulatorBackend`.

The new `knill_online_offline_adaptive(...)` entry point uses the separate
stateful adaptive executor.  It performs short decoding, policy evaluation,
same-shot continuation for selected shots, full-history long decoding, and
event/result aggregation.  The legacy protocol entry points and static backend
are unchanged.  `ClusterLLRPolicy` is an example policy; the executor does
not assume BP-LSD or a particular confidence metric.

The stateful backend reconstructs physical records with
`Circuit.reference_sample() XOR get_measurement_flips().T`, while maintaining
decoder corrections in a separate software measurement-flip frame.  It
executes each module on one physical simulator state and does not apply
decoded corrections to that state.

The adaptive state-preparation executor runs `short_circuit` first. It calls
the policy with the short `DecodeResult`, continues only selected shots on
the same `FlipSimulator` instance with the exact `extra_circuit` suffix, and
decodes the complete long record. It verifies that the reconstructed long
record retains the short prefix. The short correction is committed only for
short shots; the long correction is committed only for long shots.

The source checkout is not installed as a `hex-qec` distribution in the test
environment, so smoke tests use `PYTHONPATH=src`.  `stimbposd` was missing at
the initial environment check; the declared dependency was installed as
`stimbposd==0.2.0` to execute the unmodified baseline.  Other observed
versions are Stim 1.15.0, PyMatching 2.3.1, ldpc 2.1.2, and Python 3.12.7.

## Baseline results

For surface code `d=3`, `physical_error=0.0`, `max_shots=256`, and
`max_errors_before_halting=1`:

- Knill, one teleportation: `(samples_performed, logical_errors) = (256, 0)`;
  runtime 0.1024 s.
- Knill, two teleportations: `(256, 0)`; runtime 0.1392 s.
- Steane, one teleportation: `(256, 0)`; runtime 0.1249 s.

For surface code `d=3`, `physical_error=0.001`, the same limits and PyMatching
decoders:

- Knill, one teleportation: `(256, 0)`; runtime 0.1465 s.
- Knill, two teleportations: `(256, 1)`; runtime 0.2358 s.

These are smoke-test observations, not statistically meaningful LER estimates.

## Verified dimensions

For surface `d=3`, the four loaded matrices have shapes
`(4, 9), (4, 9), (1, 9), (1, 9)` and load as integer SciPy COO matrices.
The three-round both-detector state-preparation circuit has 17 qubits, 24
measurements, and 20 detectors.  The Z-preparation CSS module has 8 X
detectors, 12 Z detectors, and matchable DEM check shapes `(8, 21)` and
`(12, 41)`; its local measurement maps have shapes `(21, 24)` and `(41, 24)`.

## Uncertainties and limitations

- The checked-in tests are focused adapter/result/backend tests; broader
  evidence is from the smoke commands recorded in `TEST.md`.
- `simulate` samples whole 256-shot batches and can exceed `max_shots`.
- Direct `css_detector_module.c_func` calls must use a normal boolean/int
  measurement array with Stim 1.15.0; `uint8` is interpreted as bit-packed by
  Stim's converter and was not accepted in the un-packed probe.
- `only_postselection_module._change_support` is incomplete and the class is
  not used by the bundled protocols.
- The existing package-level `__all__` lists fewer names than are imported by
  `__init__.py`.
- No larger-shot numerical fixed-round regression baseline beyond the Phase 3
  d=3 noisy comparison has been established yet.

## Phase 3 validation

The installed Stim 1.15.0 API was inspected directly.  `do()` mutates state
and returns `None`; `get_measurement_flips()` returns `(measurements, shots)`;
`copy(copy_rng=True)` preserves state and continuation randomness; and
stabilizer randomization must remain enabled for physical sampling.  The
deterministic reconstruction tests and fixed-round Knill comparisons pass for
surface distances 3 and 5 with one and two teleportations.  Independent
noisy d=3 Monte Carlo LER checks also pass within the documented finite-shot
uncertainty bound.

## Phase 3 design issue

`DecodeResult` can carry confidence, convergence, and metrics, but the current
module callback and static simulation APIs intentionally discard those fields
after extracting `correction`; `SimulationResult` reserves their future
locations but does not fabricate them for fixed-round circuits.  The protocol
functions also continue to return their legacy two-count tuple, while direct
`modularised_circuit` users can request the new wrapper.  A future protocol
level result path will need an explicit result-plumbing design if adaptive
event identity is to be exposed without changing existing protocol returns.
The stateful backend currently mirrors the static module-processing loop so it
can preserve the static path untouched; a future refactor may consolidate
that logic only after compatibility coverage remains stable.  The legacy
detector module still constructs its decoder during each callback, preserving
historical behavior but leaving a future performance question.

## Phases 4 and 5 validation

`AdaptiveSERounds` and `AdaptiveStatePrepModule` expose the short circuit,
exact extra suffix, and full long circuit/decoder.  Endpoint tests pass for
both X and Z state preparation; short/long decoder outputs match the ordinary
fixed-round builders exactly; and long execution preserves the short physical
prefix on the same `FlipSimulator` instance.  A real cluster-LLR threshold
test produces both short and long shots.  Adaptive Knill smoke tests cover
both bases, two teleportations, and confidence-result fields.

The reference implementation intentionally executes one shot at a time and
does not compact branch states.  Confidence calibration, circuit-derived
code-capacity priors, and optimized branch execution remain future work.

## Next recommended task

The next recommended step is diagnostic validation of confidence calibration
and then a separately scoped optimization of branch execution.  Do not change
the static backend or decoder mathematics.  Circuit-derived code-capacity
priors and confidence-threshold selection policy remain experimental and are
documented in `FUTURE.md`.
