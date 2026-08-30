# Test log

This log contains only commands actually run during the Phase 0 baseline
session.  All commands were run from the repository root on 2026-08-28.

## Environment and import checks

1. `python --version; pip show hex-qec stim pymatching stimbposd ldpc`

   Outcome: Python 3.12.7.  `stim` 1.15.0, PyMatching 2.3.1, and `ldpc`
   2.1.2 were present.  `hex-qec` and `stimbposd` were initially absent.

2. `PYTHONPATH=src python - <<'PY' ... import hex_qec ... PY`

   Outcome: failed before dependency setup with
   `ModuleNotFoundError: No module named 'stimbposd'` (the first import probe
   without `PYTHONPATH` also correctly reported that the source checkout was
   not installed as `hex_qec`).

3. `python -m pip install 'stimbposd>=0.1.0'`

   Outcome: installed `stimbposd==0.2.0`; all other requirements were already
   satisfied.  This changed the Python test environment only, not the repo.

4. `PYTHONPATH=src python - <<'PY' ... import hex_qec; import stim,
   pymatching, stimbposd, ldpc ... PY`

   Outcome: PASS.  Imports succeeded.  Versions were Stim 1.15.0, PyMatching
   2.3.1, stimbposd 0.2.0, and ldpc 2.1.2.

## Circuit and module probes

5. Matrix/block/circuit-generation probe for surface `d=3` and
   `color_triangular d=3`, including `get_parity_check_matrices`, block
   creation, and both `stabilizer_measurement_circuit` builders.

   Outcome: PASS.  Surface matrices were `(4,9), (4,9), (1,9), (1,9)`;
   color-triangular matrices were `(3,7), (3,7), (1,7), (1,7)`.  The surface
   three-round both-detector circuits were `(17 qubits, 24 measurements,
   20 detectors)` for both bases.

6. Direct CSS module probe using `np.zeros(..., dtype=np.uint8)` as the raw
   measurement input.

   Outcome: FAIL as a direct-call probe.  Stim 1.15.0 treated uint8 input as
   bit-packed and raised `ValueError: Expected 24 bits per shot`.

7. Corrected CSS module probe using boolean raw measurement arrays, after
   removing an assumed-but-not-created `correction_to_measurement_flips`
   attribute.

   Outcome: PASS.  Surface `d=3`, three-round Z preparation had module output
   shape `(2,80)`, X/Z detector counts `8/12`, DEM check shapes `(8,21)` and
   `(12,41)`, and local DEM measurement-map shapes `(21,24)` and `(41,24)`.
   X preparation had output shape `(2,78)`, detector counts `12/8`, DEM
   shapes `(12,35)` and `(8,25)`, and maps `(35,24)` and `(25,24)`.

8. A follow-up version of the same probe attempted to read
   `css_detector_module.correction_to_measurement_flips` before global map
   generation.

   Outcome: FAIL as an attribute-assumption probe with `AttributeError`.  The
   attribute is created by `generate_measurement_flip_map`, not by the CSS
   module constructor.

9. `python -m compileall -q src`

   Outcome: PASS (`compileall: PASS`).

## Fixed-round protocol smoke tests

All protocol probes used `PYTHONPATH=src`, surface `d=3`, PyMatching for both
decoders, `max_shots=256`, `max_errors_before_halting=1` (or 2 for the noisy
Knill probes), and `physical_error=0.0` unless stated otherwise.

10. `knill_online_offline(..., syndrome_measurement_rounds=3,
    num_teleportations=1, physical_error=0.0)`

    Outcome: PASS, `(256, 0)`, runtime 0.1024 s.

11. `knill_online_offline(..., syndrome_measurement_rounds=3,
    num_teleportations=2, physical_error=0.0)`

    Outcome: PASS, `(256, 0)`, runtime 0.1392 s.

12. `knill_online_offline(..., syndrome_measurement_rounds=3,
    num_teleportations=1, physical_error=0.001)`

    Outcome: PASS, `(256, 0)`, runtime 0.1465 s.

13. `knill_online_offline(..., syndrome_measurement_rounds=3,
    num_teleportations=2, physical_error=0.001)`

    Outcome: PASS, `(256, 1)`, runtime 0.2358 s.  The nonzero error count is a
    stochastic smoke-test result, not a reference LER.

14. `steane_online_offline(..., syndrome_measurement_rounds=3,
    num_teleportations=1, physical_error=0.0)`

    Outcome: PASS, `(256, 0)`, runtime 0.1249 s.

No adaptive simulator or core-code refactor was implemented or tested.

15. Final Phase 0 check: `python -m compileall -q src` and `git diff --check`.

    Outcome: PASS.  Python compilation completed successfully and the tracked
    diff contained no whitespace errors.  The new documentation files remained
    untracked, as shown by the final `git status` check.

## Phase 1 implementation checks

16. `PYTHONPATH=src pytest -q tests/test_phase1_decoder_adapters.py`

    Outcome: PASS, 6 tests passed with 8 dependency deprecation warnings in
    1.94 s on the first run.

17. `PYTHONPATH=src python - <<'PY' ... knill_online_offline(...)
    ... num_teleportations in (1, 2) ... PY`

    Outcome: PASS before the scalar-dtype compatibility adjustment: both
    cases returned `(256, 0)` for surface `d=3`, zero physical error, with
    runtimes 0.0742 s and 0.0796 s.

18. `PYTHONPATH=src python -m compileall -q src tests`

    Outcome: PASS before the scalar-dtype compatibility adjustment.

19. `PYTHONPATH=src pytest -q tests/test_phase1_decoder_adapters.py`

    Outcome: PASS after the compatibility adjustment, 6 tests passed with 8
    dependency deprecation warnings in 0.44 s.

20. Fixed-round Knill integration probe with surface `d=3`, zero physical
    error, PyMatching decoders, 256 maximum shots, and one/two teleportations.

    Outcome: PASS after the compatibility adjustment.  One teleportation
    returned `(256, 0)` in 0.0646 s; two teleportations returned `(256, 0)`
    in 0.0870 s.

21. Fixed-round Steane integration probe with the same surface `d=3` setup,
    zero physical error, and one teleportation.

    Outcome: PASS after the compatibility adjustment, `(256, 0)` in 0.0631 s.

22. `PYTHONPATH=src python -m compileall -q src tests`

    Outcome: PASS after the compatibility adjustment.

23. `PYTHONPATH=src pytest -q tests/test_phase1_decoder_adapters.py &&
    PYTHONPATH=src python -m compileall -q src tests`

    Outcome: PASS after structured-result constructor support was added: 8
    tests passed with 8 dependency deprecation warnings in 0.47 s, followed by
    successful compilation.

24. Final fixed-round regression probe with surface `d=3`, zero physical
    error, PyMatching decoders, 256 maximum shots, and Knill one/two
    teleportations plus Steane one teleportation.

    Outcome: PASS after structured callback validation was added.  Knill
    returned `(256, 0)` for one teleportation in 0.0625 s and `(256, 0)` for
    two in 0.0860 s; Steane returned `(256, 0)` in 0.0628 s.  `git diff --check`
    also passed.

25. Tiny BP/BP-OSD adapter probe using `ldpc==2.1.2` without its required
    `input_vector_type` constructor argument.

    Outcome: FAIL during third-party decoder construction with ldpc's
    `ValueError: Please specify the input vector type`.  The adapter was not
    reached; this records the installed ldpc API requirement.

26. Tiny BP/BP-OSD adapter probe repeated with
    `input_vector_type='syndrome'`.

    Outcome: PASS.  Both adapters returned correction arrays of shape `(2,2)`
    and dtype `uint8`; the BP and BP-OSD corrections were `[[0,0],[0,1]]`.

27. `PYTHONPATH=src pytest -q tests/test_phase1_decoder_adapters.py &&
    PYTHONPATH=src python -m compileall -q src tests`

    Outcome: PASS after adding static-engine structured-result coverage: 9
    tests passed with 8 dependency deprecation warnings in 0.44 s, followed
    by successful compilation.

## Phase 2 implementation checks

28. `PYTHONPATH=src pytest -q tests/test_phase2_results.py`

    Outcome: PASS, 6 tests passed with 8 dependency deprecation warnings in
    1.62 s.

29. `PYTHONPATH=src pytest -q tests/test_phase1_decoder_adapters.py
    tests/test_phase2_results.py`

    Outcome: PASS, 15 tests passed with 8 dependency deprecation warnings in
    0.48 s.

30. Initial protocol smoke command using `physical_error_rate=` instead of
    the repository parameter `physical_error`.

    Outcome: FAIL before simulation with `TypeError: knill_online_offline()
    got an unexpected keyword argument 'physical_error_rate'`. No repository
    code was changed by this invocation.

31. Corrected surface `d=3`, zero-noise PyMatching protocol smoke command
    using `physical_error=0.0`, 256 maximum shots, and one/two teleportations
    for both Knill and Steane.

    Outcome: PASS. Knill one/two teleportations and Steane one/two
    teleportations each returned `(256, 0)`.

32. `PYTHONPATH=src pytest -q tests`

    Outcome: PASS, 15 tests passed with 8 dependency deprecation warnings in
    1.53 s.

33. `PYTHONPATH=src python -m compileall -q src tests` and `git diff --check`

    Outcome: PASS. Python compilation and whitespace validation completed
    successfully.

62. Final `PYTHONPATH=src python -m compileall -q src tests examples && git
    diff --check` after the resumed documentation corrections.

    Outcome: PASS. Python compilation and whitespace validation completed
    successfully.

63. Direct confidence-switching smoke for d=3, BP-LSD offline decoding,
    `AdaptiveSERounds(1, 2, ClusterLLRPolicy(0.001))`, two teleportations,
    two shots, and `detail_level="analysis"`.

    Outcome: PASS. The run returned `(2, 0)`, four adaptive event records,
    `used_long.shape == (2, 4)`, and mixed long counts `[0, 1, 1, 0]` across
    the two teleportation indices and both ancilla bases.

64. `PYTHONPATH=src pytest -q tests/test_phase5_confidence_adaptive.py
    tests/test_phase4_adaptive_state_prep.py` after the adapter option and
    custom-integration documentation correction.

    Outcome: PASS, 14 tests passed with 8 dependency deprecation warnings in
    2.88 s.

65. Final `PYTHONPATH=src pytest -q && PYTHONPATH=src python -m compileall -q
    src tests examples && git diff --check`.

    Outcome: PASS. The full local suite passed 39 tests with 8 dependency
    deprecation warnings in 5.05 s; compilation and whitespace validation
    also passed.

## Phase 3 implementation checks

34. Initial Stim API introspection using `inspect.signature` on the built-in
    `stim.FlipSimulator` constructor.

    Outcome: FAIL for that introspection call with Python's
    `ValueError: no signature found for builtin`; the command was rerun using
    the built-in docstrings and method annotations.

35. Stim 1.15.0 API inspection of `FlipSimulator.do`, `copy`,
    `get_measurement_flips`, `get_detector_flips`, `clear`,
    `set_pauli_flip`, and `to_numpy`.

    Outcome: PASS. Confirmed `do()` mutates and returns `None`, measurement
    flips use `(measurements, batch_size)` axes, `copy(copy_rng=True)` copies
    the continuation RNG, and randomization is controlled by
    `disable_stabilizer_randomization`.

36. Direct deterministic Stim probe using `reference_sample()` XOR
    `get_measurement_flips().T`, plus intrinsic-randomness and copy-RNG checks.

    Outcome: PASS. Deterministic noisy records reconstructed exactly;
    disabled randomization produced only zero flips for `H; M`, enabled
    randomization produced both values, and copied simulators agreed.

37. First `PYTHONPATH=src pytest -q tests/test_phase3_stateful_backend.py`
    run.

    Outcome: FAIL for one test because its manually written expected XOR
    array was incorrect; 6 other tests passed. The fixture was corrected.

38. Corrected `PYTHONPATH=src pytest -q
    tests/test_phase3_stateful_backend.py`.

    Outcome: PASS, 7 tests passed with 8 dependency deprecation warnings in
    1.16 s.

39. Fixed-round surface d=3 Knill comparison at zero physical error for one
    and two teleportations, using static protocol execution followed by the
    stateful backend.

    Outcome: PASS. Both paths returned `(256, 0)` for both teleportation
    counts.

40. Fixed-round surface d=3 Knill comparison at physical error 0.001 with
    512 and then 4096 shots for one and two teleportations.

    Outcome: PASS as an independent Monte Carlo comparison. At 4096 shots,
    one teleportation produced static/stateful error counts `5/4`, and two
    produced `10/8`; rates were compared statistically rather than exactly.

41. Fixed-round surface d=5 Knill comparison at zero physical error, 256
    maximum shots, for one and two teleportations.

    Outcome: PASS. Both paths returned `(256, 0)`; circuit dimensions were
    `(315, 216)` for one and `(605, 432)` for two teleportations.

42. Updated `PYTHONPATH=src pytest -q tests/test_phase3_stateful_backend.py`
    after extending deterministic coverage to d=5.

    Outcome: PASS, 9 tests passed with 8 dependency deprecation warnings in
    1.79 s.

43. Final `PYTHONPATH=src pytest -q tests`.

    Outcome: PASS, 24 tests passed with 8 dependency deprecation warnings in
    3.90 s.

44. Final `PYTHONPATH=src python -m compileall -q src tests && git diff --check`.

    Outcome: PASS. Python compilation and whitespace validation completed
    successfully.

45. `PYTHONPATH=src pytest -q tests/test_phase3_stateful_backend.py` after
    adding stateful `SimulationResult` wrapper coverage.

    Outcome: PASS, 10 tests passed with 8 dependency deprecation warnings in
    1.77 s.

46. Final combined command:
    `PYTHONPATH=src pytest -q tests/test_phase3_stateful_backend.py &&
    PYTHONPATH=src pytest -q tests && PYTHONPATH=src python -m compileall -q
    src tests && git diff --check`.

    Outcome: PASS. The Phase 3 suite passed 10 tests, the full local suite
    passed 25 tests, compilation succeeded, and whitespace validation passed;
    each pytest invocation reported 8 dependency deprecation warnings.

47. `git diff --check && PYTHONPATH=src python -m compileall -q src tests`
    after the final documentation updates.

    Outcome: PASS. Python compilation and whitespace validation completed
    successfully.

48. `git diff --check && PYTHONPATH=src python -m compileall -q src tests &&
    git status --short` after the final status/documentation corrections.

    Outcome: PASS. Python compilation and whitespace validation completed;
    the expected Phase 1/2/3 source, test, and documentation files are the
    only listed working-tree changes.

## Phases 4 and diagnostic Phase 5 checks

49. Direct adaptive endpoint probe importing
    `StatefulAdaptiveStatePrepExecutor` from `hex_qec.simulation` before the
    lazy-export correction.

    Outcome: FAIL with an import cycle between
    `modularisation.adaptive_state_prep` and `simulation.adaptive`. The
    simulation package export was changed to lazy loading; no numerical code
    was changed by the correction.

50. Direct d=3 adaptive state-preparation probe with
    `AdaptiveSERounds(1, 3, policy)`, PyMatching, and batch size 4.

    Outcome: PASS after the lazy-export correction. The description exposed
    short/extra/long measurement counts `8/16/24`; AlwaysShort selected an
    8-measurement result and AlwaysLong selected a 24-measurement result.

51. `PYTHONPATH=src pytest -q tests/test_phase4_adaptive_state_prep.py`.

    Outcome: PASS, 7 tests passed with 8 dependency deprecation warnings in
    1.54 s. This covered forced policies, exact circuit decomposition, data
    reset protection, same-shot long continuation, complete long-history
    decoding, and ordinary fixed-round decoder endpoint equivalence for X/Z.

52. `PYTHONPATH=src pytest -q tests`.

    Outcome: PASS, 32 tests passed with 8 dependency deprecation warnings in
    3.58 s.

53. Final post-documentation command:
    `PYTHONPATH=src pytest -q tests/test_phase4_adaptive_state_prep.py &&
    PYTHONPATH=src pytest -q tests && PYTHONPATH=src python -m compileall -q
    src tests && git diff --check`.

    Outcome: PASS. The adaptive endpoint suite passed 7 tests, the full local
    suite passed 32 tests, compilation succeeded, and whitespace validation
    passed; each pytest invocation reported 8 dependency deprecation warnings.

54. `PYTHONPATH=src pytest -q tests/test_phase4_adaptive_state_prep.py` after
    adding explicit mixed-mask deferral and multiple-support coverage.

    Outcome: PASS, 9 tests passed with 8 dependency deprecation warnings in
    1.41 s.

55. Final `PYTHONPATH=src pytest -q tests && PYTHONPATH=src python -m
    compileall -q src tests && git diff --check`.

    Outcome: PASS. The full local suite passed 34 tests, compilation
    succeeded, and whitespace validation passed; pytest reported 8 dependency
    deprecation warnings.

56. `git diff --check && PYTHONPATH=src python -m compileall -q src tests &&
    git status --short` after final documentation updates.

    Outcome: PASS. Compilation and whitespace validation succeeded; the
    working tree contains only the expected Phase 4/diagnostic Phase 5 source,
    test, and documentation changes.

## Phase 5 confidence-switching checks

57. `PYTHONPATH=src pytest -q tests/test_phase4_adaptive_state_prep.py
    tests/test_phase5_confidence_adaptive.py` after resuming the interrupted
    implementation.

    Outcome: PASS, 14 tests passed with 8 dependency deprecation warnings in
    2.74 s. This covered the endpoint regressions, same-shot continuation,
    mixed policy masks, BP-LSD soft output, and adaptive Knill result fields.

58. `PYTHONPATH=src pytest -q`.

    Outcome: PASS, 39 tests passed with 8 dependency deprecation warnings in
    4.96 s.

59. The real confidence-threshold smoke test
    `test_real_cluster_llr_threshold_produces_mixed_short_long_batch`.

    Outcome: PASS as part of entry 57. With BP-LSD cluster LLR confidence and
    `ClusterLLRPolicy`, the d=3, short-round 1/long-round 3 batch contained
    both committed-short and continued-long shots.

60. The two-teleportation adaptive Knill smoke test
    `test_adaptive_knill_endpoints_support_two_teleportations`.

    Outcome: PASS as part of entry 57. AlwaysShort and AlwaysLong both
    returned `(2, 0)` for d=3 and recorded four events (two bases at each of
    two teleportation indices).

61. `PYTHONPATH=src python -m compileall -q src tests examples && git diff
    --check` after documentation and status updates.

    Outcome: PASS. Python compilation and whitespace validation completed
    successfully.
