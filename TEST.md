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

## Surface-code sweep preflight and notebook

62. `PYTHONPATH=src pytest -q tests/test_phase4_adaptive_state_prep.py
    tests/test_phase5_confidence_adaptive.py
    tests/test_phase1_decoder_adapters.py` after the BP-LSD membership,
    surface-code, and synchronized-pair changes.

    Outcome: PASS, 26 tests passed with 8 existing dependency deprecation
    warnings in 6.71 s.

63. Direct BP-LSD surface-code confidence probes for `(p, threshold)` values
    `(0.1, 0.01)`, `(0.01, 0.001)`, and `(0.001, 0.0001)` using eight d=3
    state-preparation shots.

    Outcome: PASS. The observed long/short counts were `1/7`, `4/4`, and
    `2/6`, respectively, demonstrating both branches for these smoke points.

64. `PYTHONPATH=src python` execution of notebook code cells 1 through 10
    from `notebooks/surface_code_knill_fixed_adaptive_sweeps.ipynb`.

    Outcome: PASS. The notebook's tiny validation cell completed all fixed
    p=0 checks, endpoint checks, real confidence switching, event-count,
    prefix, synchronization, and fallback-cause assertions. It printed the
    installed versions Stim 1.15.0, ldpc 2.1.2, and PyMatching 2.3.1. The
    generated smoke NPZ artifact was removed afterward; no production sweep
    was run.

65. `PYTHONPATH=src pytest -q tests/test_phase4_adaptive_state_prep.py
    tests/test_phase5_confidence_adaptive.py
    tests/test_phase1_decoder_adapters.py && python -m json.tool
    notebooks/surface_code_knill_fixed_adaptive_sweeps.ipynb` followed by
    compilation of every notebook code cell and `git diff --check`.

    Outcome: PASS, 26 tests passed with 8 warnings; notebook JSON parsing,
    all 9 code-cell compilations, and whitespace validation passed.

66. `PYTHONPATH=src pytest -q && PYTHONPATH=src python -m compileall -q src
    tests examples` followed by JSON parsing/compilation of all 13 notebook
    cells and `git diff --check`.

    Outcome: PASS, 42 tests passed with 8 existing dependency deprecation
    warnings in 8.53 s. Python compilation, notebook validation, and
    whitespace validation also passed. No production sweep was run.

67. `PYTHONPATH=src pytest -q tests/test_phase4_adaptive_state_prep.py
    tests/test_phase5_confidence_adaptive.py
    tests/test_phase1_decoder_adapters.py` after adding the fixed protocol
    surface-code smoke test and pair-risk analysis assertions.

    Outcome: PASS, 27 tests passed with 8 existing dependency deprecation
    warnings in 5.23 s.

68. `PYTHONPATH=src pytest -q && PYTHONPATH=src python -m compileall -q src
    tests examples && python -m json.tool
    notebooks/surface_code_knill_fixed_adaptive_sweeps.ipynb` followed by
    compilation of every notebook code cell and `git diff --check`.

    Outcome: PASS, 43 tests passed with 8 existing dependency deprecation
    warnings in 7.89 s. Python compilation, notebook JSON/code validation,
    and whitespace validation also passed. No production sweep was run.

69. `PYTHONPATH=src pytest -q tests/test_phase5_confidence_adaptive.py`
    after adding four independent BP-LSD growth-history syndrome cases.

    Outcome: PASS, 12 tests passed with 8 existing dependency deprecation
    warnings in 3.96 s.

70. `PYTHONPATH=src pytest -q && PYTHONPATH=src python -m compileall -q src
    tests examples && python -m json.tool
    notebooks/surface_code_knill_fixed_adaptive_sweeps.ipynb` followed by
    compilation of every notebook code cell and `git diff --check`.

    Outcome: PASS, 47 tests passed with 8 existing dependency deprecation
    warnings in 8.18 s. Python compilation, notebook JSON/code validation,
    and whitespace validation also passed. No production sweep was run.

71. Two fixed d=3, surface-code Knill calls at `physical_error=0.001`,
    `seed=123`, and identical decoder/configuration, asserting equal legacy
    tuples.

    Outcome: PASS. Both calls returned `(256, 0)`, confirming the optional
    static Stim seed is consumed consistently in this local environment.

72. `PYTHONPATH=src pytest -q && PYTHONPATH=src python -m compileall -q src
    tests examples && python -m json.tool
    notebooks/surface_code_knill_fixed_adaptive_sweeps.ipynb` followed by
    compilation of every notebook code cell and `git diff --check` after the
    optional static seed extension.

    Outcome: PASS, 47 tests passed with 8 existing dependency deprecation
    warnings in 8.20 s. Python compilation, notebook JSON/code validation,
    and whitespace validation also passed. No production sweep was run.

73. `PYTHONPATH=src pytest -q tests/test_phase4_adaptive_state_prep.py
    tests/test_phase5_confidence_adaptive.py` after changing the adaptive
    schedule invariant from `short_rounds <= long_rounds` to the strict
    `short_rounds < long_rounds` rule and adding an equality regression.

    Outcome: PASS, 22 tests passed with 8 existing dependency deprecation
    warnings in 3.09 s.

74. Notebook schedule preflight with the notebook code cells loaded and
    overridden to `DISTANCES=[3]`, `SHORT_ROUNDS=[1, 3]`.

    Outcome: PASS. The preflight rejected `(distance=3, short_rounds=3,
    long_rounds=3)` before any simulation point was run.

75. `PYTHONPATH=src pytest -q && PYTHONPATH=src python -m compileall -q src
    tests examples && python -m json.tool
    notebooks/surface_code_knill_fixed_adaptive_sweeps.ipynb` followed by
    compilation of all notebook code cells and `git diff --check`.

    Outcome: PASS, 47 tests passed with 8 existing dependency deprecation
    warnings in 3.70 s. Python compilation, notebook JSON/code validation,
    and whitespace validation also passed. The production sweep was not run.

76. `PYTHONPATH=src pytest -q tests/test_phase4_adaptive_state_prep.py
    tests/test_phase5_confidence_adaptive.py && PYTHONPATH=src python -m
    compileall -q src tests && git diff --check` after making the surface-code
    stabilizer diagnostic messages debug-only.

    Outcome: PASS, 23 tests passed with 8 existing dependency deprecation
    warnings in 5.67 s. Python compilation and whitespace validation also
    passed.

77. `PYTHONPATH=src pytest -q` after making the surface-code stabilizer
    diagnostic messages debug-only.

    Outcome: PASS, 48 tests passed with 8 existing dependency deprecation
    warnings in 5.38 s.

78. `PYTHONPATH=src pytest -q tests/test_phase4_adaptive_state_prep.py` after
    making the logical-measurement qubit-count diagnostic debug-only.

    Outcome: PASS, 12 tests passed with 8 existing dependency deprecation
    warnings in 1.46 s.

79. `PYTHONPATH=src pytest -q` after making the logical-measurement
    qubit-count diagnostic debug-only.

    Outcome: PASS, 49 tests passed with 8 existing dependency deprecation
    warnings in 4.93 s.

80. `PYTHONPATH=src python -m compileall -q src tests` followed by
    `git diff --check`.

    Outcome: PASS. Python compilation and whitespace validation passed.

## Confidence-workflow audit (adaptive state preparation)

81. `PYTHONPATH=src python -m compileall -q src tests examples` after adding
    `hex_qec.decoders.CSSInnerDecodeResults`,
    `hex_qec.decoders.aggregators` (`dem_only_max_confidence`,
    `all_components_max_confidence`), the `CSSInnerDecodeResults` return type
    in `css_detector_module.c_func_rich`, and the new
    `confidence_zero`/`confidence_plus`/`would_extend_zero`/
    `would_extend_plus` per-shot fields in
    `StatefulAdaptiveKnillExecutor.simulate_result`.

    Outcome: PASS. Python compilation completed with no output (success).

82. `PYTHONPATH=src pytest -q tests/test_phase5_confidence_adaptive.py` after
    adding `test_css_inner_decode_results_is_list_compatible`,
    `test_dem_only_default_excludes_code_capacity_confidence`,
    `test_bell_pair_patch_independence_and_or_synchronization` (parametrized
    over the four zero/plus extend combinations),
    `test_pair_or_logic_is_agnostic_to_confidence_direction` (parametrized
    over which basis has the "low" synthetic score under a dummy inverted-
    direction policy).

    Outcome: PASS, 20 tests passed (12 previous + 8 new) with 8 existing
    dependency deprecation warnings in 3.52 s.

83. `PYTHONPATH=src pytest -q` (full local suite) after the same changes.

    Outcome: PASS, 57 tests passed (49 previous + 8 new) with 8 existing
    dependency deprecation warnings in 4.58 s.

84. Direct exploratory probes of `dem_only_max_confidence` under the
    notebook's `BPLSD_OPTIONS` (`bp_method="minimum_sum"`, `max_iter=30`) at
    surface `d=3`: 20+ seeds at `short_rounds=1` and `short_rounds=2`,
    `physical_error` up to 0.3, threshold down to `1e-9`.

    Outcome: PASS as a diagnostic probe (no assertion failures; this
    characterized behavior, it did not test a requirement). DEM-only Cluster
    LLR confidence was identically zero in every case: BP alone (with these
    specific options) reliably converges on the small `d=3` DEM check
    matrix, so BP-LSD's LSD stage never forms an active cluster regardless
    of noise. The same formula without `BPLSD_OPTIONS`, and at
    `short_rounds=2` with `d=5` (the production sweep's configuration),
    both produced genuine nonzero DEM-only confidence in separate probes.
    Recorded as a smoke-scale/decoder-option artifact in `STATUS.md`, not a
    defect; the notebook's validation cell now asserts this contrast
    directly (`dem_only_max_confidence` gives zero switching,
    `all_components_max_confidence` still switches) instead of assuming
    DEM-only must switch at this tiny configuration.

85. `PYTHONPATH=src python3 -c "..."` execution of the actual notebook file
    `notebooks/surface_code_knill_fixed_adaptive_sweeps.ipynb`, extracting
    and `exec`-ing its code cells 0 through 7 (imports/metadata, helpers,
    decoder-factory/aggregator definitions, fixed-point/sweep functions,
    adaptive-point/sweep functions, plotting-helper definitions, the
    revised `validate_small_configuration()` cell, and the benchmark cell);
    cells 8-9 (the opt-in production sweep and its plot) were not run.

    Outcome: PASS. Printed "All small fixed/adaptive validation checks
    passed." (covering F1-F8, including the new F3/F4 DEM-only-vs-
    all-components contrast and F7's mocked code-capacity-exclusion check)
    and the benchmark cell's timing dict, with no exceptions.

86. `PYTHONPATH=src timeout 60 python3 examples/bplsd_adaptive_knill.py`
    after switching its wired `confidence_aggregator` from an inline
    `max_decoder_confidence` (all four results) to the shipped
    `dem_only_max_confidence`.

    Outcome: PASS. Printed a `SimulationSummary` and two
    `AdaptiveStatePrepStats` records; the `z`-basis patch showed 2 long
    shots out of 256 with nonzero DEM-only confidence
    (`confidence_summary={'mean': ..., 'max': 0.31855626170940876, ...}`),
    confirming the DEM-only default triggers real switching under this
    script's plain (non-`BPLSD_OPTIONS`) decoder settings.

87. `python -m json.tool notebooks/surface_code_knill_fixed_adaptive_sweeps.ipynb`
    followed by compiling every code cell and `PYTHONPATH=src python -m
    compileall -q src tests examples && git diff --check` after all
    documentation updates (`STATUS.md`, this file, `FUTURE.md`,
    `decoders/DESCRIPTION.md`, `modularisation/DESCRIPTION.md`,
    `protocols/DESCRIPTION.md`).

    Outcome: PASS. Notebook JSON parsing and all 10 code-cell compilations
    passed; Python compilation and whitespace validation also passed.

## Reproducibility validation infrastructure

88. `PYTHONPATH=src python -m pytest -q
    tests/test_validation_infrastructure.py`

    Outcome: PASS, 8 fast validation-infrastructure tests.  These cover
    parameter-derived seeds, Wilson intervals, Fisher tables, pooled counts,
    Holm adjustment, underpowered status, checkpoint deduplication, fixed
    distance-round configuration, and synthetic plotting.

89. `PYTHONPATH=src python -m compileall -q validation tests` followed by
    `git diff --check`.

    Outcome: PASS.

90. `PYTHONPATH=src python -m validation.fixed_workflow_repro --smoke
    --overwrite --output-dir /tmp/hex-validation-smoke-fixed`.

    Outcome: PASS. The d=3, p=0, 256-shot smoke run created
    `fixed_workflow_raw.csv`, `fixed_workflow_comparison.csv`, and invocation
    metadata. It recorded 256 shots for both `legacy_static` and
    `stateful_fixed`; both had zero logical errors.

91. `PYTHONPATH=src python -m validation.adaptive_forced_long_repro --smoke
    --overwrite --output-dir /tmp/hex-validation-smoke-adaptive`.

    Outcome: PASS. The d=3, p=0, 256-shot smoke run created the adaptive raw
    and comparison CSVs and metadata. The adaptive row recorded
    `short_rounds=1`, `extra_rounds=2`, `total_long_rounds=3`, two patch
    events, `pair_fallback_rate=1.0`, and `mean_effective_rounds=3.0`; both
    workflows had zero logical errors.

92. Reran both smoke runners without `--overwrite` and checked raw CSV line
    counts, then ran
    `PYTHONPATH=src python -m validation.plot_knill_repro --validation fixed`
    and the corresponding adaptive command.

    Outcome: PASS. Each raw file remained at three lines (header plus two
    workflow rows), and both suites produced nonempty PNG and PDF figures
    without rerunning simulation from the plotting module.

93. `PYTHONPATH=src python -m pytest -q`.

    Outcome: PASS, 64 tests with the existing eight dependency deprecation
    warnings.  The requested production d=5/7 validation matrix was not run.

94. `PYTHONPATH=src python -m pytest -q
    tests/test_validation_infrastructure.py`,
    `PYTHONPATH=src python -m pytest -q`, and
    `PYTHONPATH=src python -m compileall -q src tests validation` followed by
    `git diff --check` after the final validation test addition.

    Outcome: PASS. The focused validation suite passed 8 tests; the full local
    suite passed 65 tests with the existing eight dependency deprecation
    warnings; compilation and whitespace validation also passed.

95. `bash validation/run_knill_repro.sh --smoke --overwrite
    --output-dir /tmp/hex-validation-smoke-script`, after `bash -n
    validation/run_knill_repro.sh`.

    Outcome: PASS. The combined launcher ran both validations and created
    three-line fixed and adaptive raw CSV files.

96. `bash -n validation/run_knill_repro.sh` and
    `bash validation/run_knill_repro.sh --smoke --overwrite
    --output-dir /tmp/hex-validation-script-params` after embedding the
    production parameter set in the launcher.

    Outcome: PASS. The embedded production arguments were accepted, the
    explicit smoke override ran both validations, and both raw CSV files had
    three lines. The production matrix itself was not run.

97. `bash validation/run_knill_repro.sh --smoke --verbose --overwrite
    --output-dir /tmp/hex-validation-verbose`.

    Outcome: PASS. Both runners emitted real-time flushed progress. The
    adaptive smoke output reported `pair_fallback_rate=1.000` and
    `mean_rounds=3.000`; both checkpoints were written successfully.

98. `PYTHONPATH=src python -m pytest -q
     tests/test_knill_repro_analysis.py tests/test_validation_infrastructure.py`.

    Outcome: PASS, 14 focused post-processing and validation-infrastructure
    tests with the existing eight dependency deprecation warnings.  This
    covered Newcombe interval sign/edge cases, equivalence decisions, JSON
    sanitization, incomplete data, mixed-signature rejection, and regression
    against the existing Fisher/Holm helper.

99. `PYTHONPATH=src python -m validation.analyze_knill_repro --suite fixed
     --config-signature 3146193f6c2bd7b1 --equivalence-margin 0.001
     --alpha 0.05` and the corresponding adaptive-forced-long command without
     an explicit signature.

    Outcome: PASS. Both commands consumed existing raw CSVs only and wrote
    valid JSON and Markdown reports under `validation/results/`. An attempt
    to analyze the fixed CSV without a signature correctly rejected its two
    available signatures instead of pooling them.

100. `PYTHONPATH=src python -m pytest -q`.

    Outcome: PASS, 85 tests with the existing eight dependency deprecation
    warnings. No simulation runner was invoked for this post-processing task.

101. `bash -n validation/run_knill_repro.sh` followed by
     `bash validation/run_knill_repro.sh --smoke --overwrite
     --output-dir /tmp/hex-validation-with-plot`.

     Outcome: PASS. Both smoke validations completed first, then the launcher
     created nonempty fixed and adaptive PNG/PDF figures under the selected
     output directory.

102. `bash -n validation/run_knill_repro.sh` followed by
     `bash validation/run_knill_repro.sh --smoke --overwrite
     --output-dir /tmp/hex-integrated-validation` after separating sampling
     and analysis arguments.

     Outcome: PASS. The launcher ran both samplers, generated fixed and
     adaptive JSON/Markdown reports with margin `0.001`, and then created both
     fixed and adaptive PNG/PDF figures. No production simulation matrix was
     run.

## Adaptive wall-time profiling

98. `PYTHONPATH=src pytest -q tests/test_phase4_adaptive_state_prep.py
    tests/test_phase5_confidence_adaptive.py` after adding opt-in timing
    hooks.

    Outcome: PASS, 32 tests with the existing eight dependency deprecation
    warnings.

99. `PYTHONPATH=src pytest -q tests/test_walltime_profiling.py`.

    Outcome: PASS, 4 tests with the existing eight dependency deprecation
    warnings. This covered nested/repeated timing sections, disabled timing,
    raw/summary/Markdown report creation, correction-map/reference-sample
    instrumentation, and seeded profiling-result preservation.

100. `PYTHONPATH=src pytest -q && PYTHONPATH=src python -m compileall -q
     src tests profiling && git diff --check`.

     Outcome: PASS, 69 tests with the existing eight dependency deprecation
     warnings; compilation and whitespace validation also passed.

101. `PYTHONPATH=src python -m profiling.adaptive_walltime_profile
     --distance 3 --physical-error 0.003 --short-rounds 1 --long-rounds 3
     --num-shots 2 --warmup-shots 1 --seed 1234 --policy always-long
     --output-dir /tmp/hex-adaptive-profile-smoke` and the same command after
     the recorder scope correction.

     Outcome: PASS. The d=3 AlwaysLong profiling runner completed 2 measured
     shots and wrote raw, summary, Markdown, and PNG outputs.

102. `python -m profiling.adaptive_walltime_profile --distance 5
     --physical-error 0.003 --short-rounds 1 --long-rounds 5 --num-shots 5
     --warmup-shots 1 --seed 1234 --policy always-long --pauli z
     --output-dir profiling/results`.

     Outcome: PASS. The requested profile completed with 5 measured shots,
     0/5 logical errors, mean measured end-to-end time 0.181446721 s/shot,
     35 corrected-measurement/reference-sample calls, 5 cache hits, 30 cache
     misses, and 0.618240641 s total map generation. It created
     `profiling/results/adaptive_walltime_raw.csv`,
     `adaptive_walltime_summary.csv`, `adaptive_walltime_report.md`, and
     `adaptive_walltime_breakdown.png`.

103. `python -m profiling.adaptive_walltime_profile --distance 3
     --physical-error 0.003 --short-rounds 1 --long-rounds 3 --num-shots 2
     --warmup-shots 1 --seed 1234 --policy cluster-llr --confidence-threshold
     0.01 --output-dir /tmp/hex-adaptive-profile-cluster`.

     Outcome: PASS. The optional Cluster-LLR profile completed 2 measured
     shots and recorded short selection for both synchronized pairs.

## Shared correction-map cache optimization

104. `PYTHONPATH=src pytest -q tests/test_walltime_profiling.py
     tests/test_shared_correction_map_cache.py` after moving correction-map
     ownership to the executor.

    Outcome: PASS, 8 tests with the existing eight dependency deprecation
    warnings. This covered same-object reuse by separate shot runners,
    eager short/long path preparation, zero measured-shot fallback misses,
    and a two-teleportation smoke run.

105. `PYTHONPATH=src pytest -q tests/test_phase4_adaptive_state_prep.py
     tests/test_phase5_confidence_adaptive.py tests/test_phase3_stateful_backend.py
     tests/test_shared_correction_map_cache.py tests/test_walltime_profiling.py`.

    Outcome: PASS, 49 tests with the existing eight dependency deprecation
    warnings.

106. `PYTHONPATH=src pytest -q && PYTHONPATH=src python -m compileall -q
     src tests profiling && git diff --check`.

    Outcome: PASS, 73 tests with the existing eight dependency deprecation
    warnings; compilation and whitespace validation also passed.

107. `python -m profiling.adaptive_walltime_profile --distance 5
     --physical-error 0.003 --short-rounds 1 --long-rounds 5 --num-shots 5
     --warmup-shots 1 --seed 1234 --policy always-long --pauli z
     --output-dir profiling/results` after all tests passed.

    Outcome: PASS. The optimized profile completed 5 measured shots with
    0/5 logical errors and mean measured E2E time 0.059968956 s/shot. It
    recorded 35 measured-shot map lookups, zero fallback misses/generation,
    0.158809057 s offline generation across 9 unique path sets, and wrote
    the distinct shared-cache raw/summary/report/PNG outputs plus
    `adaptive_walltime_cache_comparison.md`. The preserved pre-cache profile
    remains unchanged.

## Detector-stripped adaptive suffix precomputation

108. `PYTHONPATH=src pytest -q tests/test_shared_correction_map_cache.py`.

    Outcome: PASS, 7 focused suffix/cache tests with the existing eight
    dependency deprecation warnings. This covered exact z/x stripped-suffix
    equivalence, no remaining detector annotations, setup-only stripping
    across three shots, AlwaysShort non-execution, shared-map reuse, distinct
    correction-map paths, and a two-teleportation smoke run.

109. `PYTHONPATH=src pytest -q tests/test_phase4_adaptive_state_prep.py
     tests/test_phase5_confidence_adaptive.py tests/test_phase3_stateful_backend.py
     tests/test_shared_correction_map_cache.py tests/test_walltime_profiling.py`.

    Outcome: PASS, 53 tests with the existing eight dependency deprecation
    warnings.

110. `PYTHONPATH=src pytest -q && PYTHONPATH=src python -m compileall -q
     src tests profiling && git diff --check`.

    Outcome: PASS, 76 tests with the existing eight dependency deprecation
    warnings; compilation and whitespace validation also passed.

111. `python -m profiling.adaptive_walltime_profile --distance 5
     --physical-error 0.003 --short-rounds 1 --long-rounds 5 --num-shots 5
     --warmup-shots 1 --seed 1234 --policy always-long --pauli z
     --output-dir profiling/results` after all tests passed.

    Outcome: PASS. The suffix-precomputed profile completed 5 measured shots
    with 0/5 logical errors and mean measured E2E time 0.009330932 s/shot.
    Setup suffix preparation was 0.049755752 s; measured-shot suffix
    preparation was zero. It wrote the distinct
    `adaptive_walltime_shared_map_suffix_*` artifacts and
    `adaptive_walltime_optimization_comparison.md`, preserving earlier
    profile outputs.

## Lazy reference-sample cache optimization

112. `PYTHONPATH=src pytest -q tests/test_shared_correction_map_cache.py
     tests/test_walltime_profiling.py` after adding the executor-lifetime
     lazy reference-sample cache.

    Outcome: PASS, 13 tests with the existing eight dependency deprecation
    warnings. This covered physical-path key identity, shared cache ownership
    across three shot runners, lazy miss/hit behavior, existing correction-map
    caching, suffix reuse, and profiling semantics.

113. `PYTHONPATH=src pytest -q tests`.

    Outcome: PASS, 78 tests with the existing eight dependency deprecation
    warnings.

114. `PYTHONPATH=src python -m profiling.adaptive_walltime_profile
     --distance 3 --physical-error 0.003 --short-rounds 1 --long-rounds 3
     --num-shots 3 --warmup-shots 1 --seed 1234 --policy always-long`
     using a temporary output directory.

    Outcome: PASS. The profile completed 3 measured shots with 0 logical
    errors. It observed 6 reference-sample cache misses during warm-up and 21
    measured cache hits; measured E2E time was 0.009555058 s/shot.

115. `PYTHONPATH=src python -m profiling.adaptive_walltime_profile
     --distance 5 --physical-error 0.003 --short-rounds 1 --long-rounds 5
     --num-shots 5 --warmup-shots 1 --seed 1234 --policy always-long
     --pauli z` using a temporary output directory.

    Outcome: PASS. The profile completed 5 measured shots with 0 logical
    errors. It observed 6 reference-sample cache misses during warm-up and 35
    measured cache hits; measured E2E time was 0.011149359 s/shot.

116. Repeated the d=5 profile from item 115 with
    `--output-dir profiling/results --output-prefix
    adaptive_walltime_reference_cache` so the cache-specific artifacts are
    available in the repository results directory.

    Outcome: PASS. The profile completed 5 measured shots with 0 logical
    errors and wrote the raw CSV, summary CSV, Markdown report, and PNG
    breakdown. This repeat measured 0.010170195 s/shot, with 6 warm-up
    reference-sample misses and 35 measured cache hits.

## Independent forced-long consistency diagnostic

117. `PYTHONPATH=src pytest -q tests/test_forced_long_consistency_diagnostic.py`

    Outcome: PASS, 11 tests with the existing eight dependency deprecation
    warnings. This covers physical instruction comparison, exact d=3 fixed /
    adaptive-long state preparation for both bases, short-plus-extra physical
    equality, production permutation order and bijection, correction-vector
    round trips, shared-record decoder endpoints, reference-cache equality,
    classification, JSON safety, pairwise statistics, and checkpoint resume.

118. `PYTHONPATH=src pytest -q`

    Outcome: PASS, 96 tests with the existing eight dependency deprecation
    warnings.

119. `PYTHONPATH=src python -m diagnostics.forced_long_consistency --smoke
     --overwrite`

    Outcome: PASS. The smoke run used d=3, p=0, one teleportation, 256 shots,
    and AlwaysLong forced-long execution. All structural checks passed; the
    intentionally underpowered no-margin result was classified as
    `statistically_inconclusive`. Independent smoke reports were written
    under `diagnostics/results/forced_long_consistency/`.

## Diagnostic noisy-criterion repair

120. `PYTHONPATH=src pytest -q tests/test_forced_long_consistency_diagnostic.py`

    Outcome: PASS, 14 tests with the existing eight dependency deprecation
    warnings. Added regression coverage for nonzero logical errors with
    passing final detector validation, detector-validation failure, nested
    Markdown rendering, and point-level structural status.

121. `PYTHONPATH=src pytest -q`

    Outcome: PASS, 99 tests with the existing eight dependency deprecation
    warnings.

122. `PYTHONPATH=src python -m diagnostics.forced_long_consistency --smoke
     --output-dir /tmp/hex-forced-long-p0-fix --overwrite`

    Outcome: PASS. Structural checks passed and the result was
    `statistically_inconclusive` for the intentionally underpowered,
    no-margin p=0 smoke.

123. `PYTHONPATH=src python -m diagnostics.forced_long_consistency
     --distances 3 --physical-errors 0.005 --shots 256 --batch-size 256
     --output-dir /tmp/hex-forced-long-noisy-fix --overwrite`

    Outcome: PASS. Structural checks passed at nonzero noise even though the
    B/C structural probes observed 5 and 6 logical errors. The report
    contained 3 base workflow rows and 3 pairwise comparison rows; the result
    was `statistically_inconclusive` without an equivalence margin.

## Auxiliary-system H0 documentation baseline

Date: 2026-10-15 (Asia/Tokyo). Hex branch `auxiliary-system`, audited Python
revision `5de58f2f80791054411ad3c0885a4fe3671ed56a`. Commands below ran from
`/home/quantum_teresheys/workspace/knilll_bench/external/Hex` with
`/home/quantum_teresheys/anaconda3/bin/python` (3.12.7).

1. `PYTHONPATH=src python -m pytest -q tests/test_phase1_decoder_adapters.py tests/test_phase2_results.py`

   PASS: **15 passed**, eight existing dependency deprecation warnings,
   **1.86 s**. Covers batch/scalar casts, generator/result compatibility,
   module normalization, and aggregate/detail-level results. Existing static
   fixtures sample a full 256-shot deterministic batch; they were not changed.

2. `PYTHONPATH=src python -m pytest -q tests/test_validation_infrastructure.py tests/test_knill_repro_analysis.py`

   PASS: **14 passed**, eight existing dependency deprecation warnings,
   **2.70 s**. Synthetic counts/checkpoint/plot/report fixtures only; no
   validation Monte Carlo CLI was launched or experiment results committed.

3. `PYTHONPATH=src python -m pytest --collect-only -q tests`

   PASS: **99 tests collected**, eight warnings, **0.88 s**. This inventory
   does not mean all 99 tests were executed. H0 executed the 29 tests above.

4. Source import/matrix/circuit probe with `PYTHONPATH=src python` importing
   `hex_qec`, public adapter/result/protocol/backend APIs,
   `get_parity_check_matrices('surface', 3)`, and
   `stabilizer_measurement_circuit_both_detectors(matrices, basis, 3, 0.001, surface_code=True)`
   for bases `z` and `x`.

   PASS: Hex import resolved to this worktree. Matrix shapes were
   `(4,9), (4,9), (1,9), (1,9)`; both circuits had 17 qubits, 24 measurements,
   and 20 detectors. No sampling or new scientific validation was performed.

5. `cmp /home/quantum_teresheys/workspace/knilll_bench/implementation/auxiliary_factory_theory.md docs/auxiliary_factory_theory.md`
   and `sha256sum docs/auxiliary_factory_theory.md`.

   PASS: exact byte copy; SHA-256
   `ca7a2748f60e05c2944cddd318c1096eedb269293280826661180b49056337b4`.
   Its proposed/untested status is in `docs/README.md` and `STATUS.md`.

6. Documentation integrity probe (`python` using `pathlib`, regular expressions,
   and `git show HEAD:<file>`) and `git diff --check`.

   PASS: all eight Python module directories have `DOCS.md`; local Markdown
   link destinations exist; previous `AGENTS.md`, `STATUS.md`, and `TEST.md`
   contents are preserved as exact byte prefixes; the theory copy is exact;
   tracked changes contain Markdown only; no whitespace errors were reported.

No Python/test algorithms or fault boundaries changed. H1, the full pytest
suite, opt-in profiling/Monte Carlo runners, factory physics, logical gap,
and projected-prior validation were not run or implemented in H0.

## Auxiliary-system H1 single-stage factory

Date: 2026-10-15 (Asia/Tokyo); branch `auxiliary-system`, base `bceeabb4`.
Same Python 3.12.7/source-path environment as H0. All commands ran from Hex.

1. `PYTHONPATH=src python -m pytest -q tests/test_factory_circuit.py`

   PASS: **35 passed**, eight existing dependency deprecation warnings,
   **1.38 s**, before the additional input/repair contract cases.

2. Targeted regression command:

   ```bash
   PYTHONPATH=src python -m pytest -q \
     tests/test_factory_circuit.py \
     tests/test_phase1_decoder_adapters.py \
     tests/test_phase2_results.py \
     tests/test_phase4_adaptive_state_prep.py \
     tests/test_phase3_stateful_backend.py \
     tests/test_phase5_confidence_adaptive.py::test_fixed_knill_surface_code_keyword_is_backward_compatible \
     -k 'not ler_is_statistically_compatible'
   ```

   PASS after physical-noise/repair guards: **72 passed**, two deselected,
   eight warnings, **2.62 s**. PASS after the final generic support/shape/noise
   validation: **75 passed**, two deselected, eight warnings, **2.71 s**.
   Final run after adding B-SE readout and correlated CNOT pair faults:
   **77 passed**, two deselected, eight warnings, **2.68 s**. The final run
   includes all **41 H1 tests** plus 36 existing regressions.
   The two excluded tests run inherited statistical LER comparisons; no large
   Monte Carlo or production validation runner was launched.

   The new tests cover seeded d=3/5 zero-noise cases (<=128 shots), both random
   raw logical branches, correct/wrong X byproducts, signed flows and strict
   DEM, reversed-CNOT detection, independent depths, complete two-block
   supports, preparation/pure-error sign repair, noisy operational boundaries,
   an ideal terminal-only oracle, eight deterministic fault cases,
   and a terminal logical fault. Prep end-frame maps are compared exactly with
   legacy correction-to-measurement propagation in both bases. Corrections
   match legacy CSS arrays; split/whole batches agree and Matching construction
   is forbidden during `resolve`. Unresolved decoder signs are rejected.

3. Fresh-process import checks:

   ```bash
   PYTHONPATH=src python -c 'from hex_qec.circuit_generation.factory_surface import RotatedSurfaceCodeAdapter; from hex_qec.protocols import FactoryCircuitBuilder; print("fresh adapter-first import: PASS")'
   PYTHONPATH=src python -c 'from hex_qec.modularisation.factory import PreparationPlan; from hex_qec.protocols import FactoryCircuitBuilder; print("fresh contracts-first import: PASS")'
   ```

   PASS: both import orders succeeded. `git diff --check` also passed after
   source edits. No existing physical builder/decoder implementation changed.

4. `python -m compileall -q src tests` and the documentation integrity probe.

   PASS: compilation succeeded; changed local Markdown links/anchors resolve;
   original `AGENTS.md`, `STATUS.md`, and `TEST.md` remain exact byte prefixes;
   the supplied scientific specification remains byte-identical. No generated
   experiment files were staged.

No H2 sampler/runner, multi-stage recycling, public terminal label, gap,
projected priors, full pytest suite, paper reproduction, or performance sweep
was implemented/run in H1. Test-only online/oracle recovery helpers do not
constitute production result APIs.

## Auxiliary-system H2 batched factory

Date: 2026-10-16 (Asia/Tokyo); branch `auxiliary-system`, base `aaba3593`.
Same Python 3.12.7/source-path environment as H0/H1; commands ran from Hex.

1. Small structural/sampling probes: d=3, T=1/2/3, r_0=1, r_plus=2.
   Built strict signed-flow/DEM-validated circuits with 34 qubits and
   42/67/92 measurements. Zero-noise compiled batches of 64 shots at seed 1729
   had zero logical errors and corrected syndromes, with expected stage shapes.

2. `PYTHONPATH=src python -m pytest -q tests/test_factory_batch.py`

   Initial result: **9 failed, 21 passed**, eight warnings, **12.14 s**.
   Eight exact frame/byproduct reference comparisons failed at repeated RX
   resets: the legacy deterministic propagator retained an invisible X frame
   component; labels agreed and frame differences had zero syndrome/logical
   action. The reference now canonicalizes map propagation with reference-only
   R-before-RX sentinels. Additional unmodified replay tests verify physical
   equivalence and labels. No sampling circuit was changed for this fix.
   One hash-test failure used unsupported Stim item assignment; corrected to
   circuit concatenation. Follow-up: **32 passed**, eight warnings,
   **13.88 s**.

3. `PYTHONPATH=src python -m pytest -q tests/test_factory_batch.py tests/test_factory_circuit.py`

   PASS after surface-readout separation and causal guards: **73 passed**,
   eight existing dependency deprecation warnings, **16.22 s** (before two
   additional causal-contract/recovery-failure tests).

4. Final targeted regression command:

   ```bash
   PYTHONPATH=src python -m pytest -q \
     tests/test_factory_batch.py \
     tests/test_factory_circuit.py \
     tests/test_phase1_decoder_adapters.py \
     tests/test_phase2_results.py \
     tests/test_phase4_adaptive_state_prep.py \
     tests/test_phase3_stateful_backend.py \
     tests/test_phase5_confidence_adaptive.py::test_fixed_knill_surface_code_keyword_is_backward_compatible \
     -k 'not ler_is_statistically_compatible'
   ```

   PASS: **111 passed**, **2 deselected**, **8 warnings**, **10.14 s**.
   Includes all 34 H2, 41 H1 and 36 relevant legacy regressions. The two
   inherited statistical-LER cases were deliberately excluded; no production
   Monte Carlo or full suite was run. New physical batches contain <=64 shots.
   Tests cover oracle/future perturbations, both Pauli reference maps, role
   swaps/resets, per-role per-stage single faults and logical faults, one
   last-survivor oracle, deterministic decoding, seed/chunk repeatability,
   uint64/bool shapes and guards, no input mutation, unsupported conventions,
   residual recovery, exact cache identity and setup-only constructors.

5. H1 compatibility probe: loaded the H1 builder with
   `git show HEAD:src/hex_qec/protocols/logical_zero_factory.py` into a separate
   Python module and compared new T=1 output. PASS: identical circuit text,
   ledger, stage descriptors and signed flows for `(d,p,r_0,r_plus)` equal to
   `(3,0,1,2)`, `(3,0.002,2,2)`, and `(5,0.002,1,1)`. Metadata intentionally
   versions the frame/terminal conventions and generalizes CNOT role names.

6. `python -m compileall -q src tests`, `git diff --check`, and fresh imports:

   ```bash
   PYTHONPATH=src python -c 'from hex_qec.simulation.factory import CompiledFactory; from hex_qec.protocols import FactoryCircuitBuilder; print("factory-first import: PASS")'
   PYTHONPATH=src python -c 'from hex_qec.decoders.factory_surface import SurfaceFactoryReadout; from hex_qec.protocols import FactoryCircuitBuilder; from hex_qec.simulation import CompiledFactory; print("readout-first import: PASS")'
   ```

   PASS: compilation, whitespace and both import orders. Documentation
   integrity checks confirm changed local links/anchors, DOCS coverage of all
   package directories, preserved historical AGENTS/STATUS/TEST prefixes,
   byte-identical scientific specification, and no experiment outputs.

No H3 gap, projected priors, threshold selection, full suite, paper
reproduction, or timing benchmark was implemented/run in H2.

## Auxiliary-system H3 surface logical gap

Date: 2026-10-16 (Asia/Tokyo); branch `auxiliary-system`, base `076a8345`.
Python/native versions remain the H0/H2 environment. NetworkX 3.3 was already
installed through PyMatching; its direct TOML requirement needs no install.

1. Read the required `_forced_gap.py`, `_constraints.py`, `_decoder_adapter.py`
   and `FUTURE.md` under the separate `decoder-confidence` checkout. Verified
   the installed PyMatching 2.3.1 `from_check_matrix`, `decode_batch` with
   `return_weights=True`, and `ensure_num_fault_ids` API/docstrings, plus
   official API/version-pinned weight conversion sources. Small d=3/5 probes
   confirmed connected planar lifts and finite nonuniform sector costs.

2. `PYTHONPATH=src python -m pytest -q tests/test_surface_gap.py`

   Initial result: **2 failed, 34 passed**, **10 warnings**, **5.97 s**.
   Two nonuniform-weight cases failed the native-cost comparison guard;
   a diagnostic found <=`2.15e-7` differences from native weight rounding.
   The implementation still recomputes costs in original weights, now checks
   native costs with an n-edge rounding allowance and rejects unsupported
   dynamic range. The posterior comparison helper also emitted two warnings:
   unsigned negation overflowed, giving NaN. Fixed to float64 sum and added a
   finite-value assertion. The exhaustive cost/class oracle is unchanged.

3. `PYTHONPATH=src python -m pytest -q tests/test_surface_gap.py tests/test_factory_batch.py`

   PASS: **71 passed**, eight existing dependency warnings, **20.03 s**.

4. Final targeted command after adding the bad-native-weight guard test:

   ```bash
   PYTHONPATH=src python -m pytest -q \
     tests/test_surface_gap.py \
     tests/test_factory_batch.py \
     tests/test_factory_circuit.py \
     tests/test_phase1_decoder_adapters.py \
     tests/test_phase2_results.py \
     tests/test_phase4_adaptive_state_prep.py \
     tests/test_phase3_stateful_backend.py \
     tests/test_phase5_confidence_adaptive.py::test_fixed_knill_surface_code_keyword_is_backward_compatible \
     -k 'not ler_is_statistically_compatible'
   ```

   PASS: **148 passed**, **2 deselected**, **8 warnings**, **24.50 s**.
   Includes 37 H3, 34 H2, 41 H1 and 36 legacy tests. The two inherited
   statistical-LER cases remain excluded. Final isolated fast subset using
   command 2: **37 passed**, eight warnings, **6.04 s**.

   Final review added a native normalization-overflow guard and its tiny-weight
   test case. Reran the full command: **148 passed**, two deselected, eight
   warnings, **25.89 s**. No existing frame or score expectation changed.

   Exactness tests enumerate all d=3 `2^9` errors as a classical oracle and
   query 16 unique syndromes, four weight vectors and two logical-row gauges.
   They check both costs, gap, class, correction constraints, nonzero
   potentials, boundary parity, exact ties, parallel merging/width, invalid
   graph/observable/weight/native paths, posterior distinction, cache identity,
   two native batch calls and scalar/batch equality. Physical factory tests
   use <=32 seeded shots, stage-wise exhaustive scores, future/oracle
   perturbations, raw logical parity independence, and p=0 d=3 T=1/2/3,
   d=5 T=2 finite gap d. H2 constructor gates now expect 15 matchings/one
   sampler, with no construction during sampling/decoding.

5. H2 compatibility probe: loaded
   `git show HEAD:src/hex_qec/simulation/factory.py` into a separate module
   and decoded the same saved 32-shot records with old/new stage loops.
   PASS: all `FactoryOperationalBatch` fields and terminal labels equal for
   `(T,p)=(1,0),(2,0.02),(3,0.02)`, d=3, both depths 2, seed 721. Only the new
   score fields differ. No physical builder/noise/correction path was changed.

6. `python -m compileall -q src tests`, `git diff --check`, TOML parsing and
   fresh gap-first/factory-first imports passed. Documentation integrity
   checks verify changed local links/anchors, package DOCS coverage, unchanged
   AGENTS/STATUS/TEST historical prefixes and byte-identical scientific spec.
   Parent bench status remains its pre-existing user edits, with no generated
   experiment files in the Hex diff.

No H4 prior model, threshold selection, full suite, large Monte Carlo, speed
benchmark, general fault-tolerance proof or paper reproduction was run.

## Auxiliary-system H4 projected factory priors

Date: 2026-10-16 (Asia/Tokyo); branch `auxiliary-system`, base `9e5fce5c`.
No environment/dependency changes. All commands ran from the Hex worktree.

1. Setup probes inspected full factory noise/stage ledgers and installed
   Stim 1.15.0 deterministic flip/paired-copy APIs, with official versioned
   error-analyzer/gate references. d=3, depths `(2,2)`, p=0.001, T=2 produced
   1,666 / 2,571 controlled mechanisms at stage 0/1. The final canonical-reset
   model has nine active complete signatures plus one no-op event per stage,
   raw-vs-resolved mismatches 375/280, and valid H3 lifts. Independent raw
   signed detector marginals agreed with Stim's prefix DEM to <=3.7e-15.

2. `PYTHONPATH=src python -m pytest -q tests/test_codecapacity_dem.py`

   Initial result: **2 failed, 29 passed**, eight warnings, **14.26 s**.
   The plus-SE paired-state test found a genuine context-dependent logical
   response: Z30 at instruction 257, mechanism 1518, has reference `(D0,L0)`
   but 13/16 physical prep contexts have a different logical response at
   seed 341. Raw flip maps are identical and syndrome D0 agrees, so the
   fixed-reference projection cannot be called an exact conditional/marginal
   model. The test now explicitly characterizes the mismatch, retaining exact
   propagation/syndrome checks and seven other full-signature comparisons.
   It does not assert that the scientific mismatch was eliminated.

   The p=0 failure attempted to decode impossible q=0 faults against empty
   prep DEM graphs. Zero-probability instructions are now counted without
   inferring their nonexistent responses; no positive mechanism is dropped.
   Follow-up after that fix and stage-2 coverage: **32 passed**, eight
   warnings, **14.74 s**.

3. Targeted regression command:

   ```bash
   PYTHONPATH=src python -m pytest -q \
     tests/test_codecapacity_dem.py \
     tests/test_surface_gap.py \
     tests/test_factory_batch.py \
     tests/test_factory_circuit.py \
     tests/test_phase1_decoder_adapters.py \
     tests/test_phase2_results.py \
     tests/test_phase4_adaptive_state_prep.py \
     tests/test_phase3_stateful_backend.py \
     tests/test_phase5_confidence_adaptive.py::test_fixed_knill_surface_code_keyword_is_backward_compatible \
     -k 'not ler_is_statistically_compatible'
   ```

   PASS after actual prep-weight/validation/underflow guards: **182 passed**,
   two inherited statistical-LER tests deselected, eight existing dependency
   warnings, **41.73 s**. After bounded setup chunks and partition coverage,
   command 2 passed **35 tests**, eight warnings, **18.37 s**. Final command 3
   with unsupported active-model inspection: **184 passed**, **2 deselected**,
   **8 warnings**, **40.77 s** (36 H4 + 148 previous targeted tests).

   Physical tests use 16 paired shots for reset/SE/CNOT/readout cases and 32
   saved shots for weighted/Hamming comparison. Controlled model lanes and
   classical 2^9 event enumeration are not physical Monte Carlo shots.
   Tests cover full mechanism/provenance retention, complete-signature XOR
   merging, independent depolarizing factorization, natural log weights,
   unsupported noise/graphs/logical-only/degenerate probabilities, zero noise,
   causal prefix/oracle/future isolation, third-stage reuse, exact cache hashes,
   changed native prep weights, bounded chunk identity and post-setup reuse.

4. Additional model-accuracy probe/test: all nine individual initial-A reset
   X faults have zero effective response at the reference, but **18/36**
   two-fault combinations produce logical-only responses after prep decoding.
   The test requires a nonzero counterexample; it does not declare independent
   superposition exact. This is a measured O(p^2) limit in addition to the
   single-fault preparation-context limit above.

5. H3 compatibility probe loaded
   `git show HEAD:src/hex_qec/simulation/factory.py` into a separate module.
   PASS: identical seeded raw samples and every factory result field for
   d=3, depths `(2,2)`, `(T,p)=(1,0),(2,0.002),(3,0.02)`, seed 751, 32 shots.
   Public default Knill signatures/paths and all physical builders are unchanged.

6. Final export-preservation assertions use:

   ```bash
   PYTHONPATH=src python -m pytest -q \
     tests/test_codecapacity_dem.py::test_all_mechanisms_preserved_and_only_final_online_checks \
     tests/test_codecapacity_dem.py::test_graph_hyperedge_and_logical_only_rejection_without_matching
   ```

   PASS: **6 passed**, eight warnings, **6.80 s**. Cases retain no-op error instructions and logical-only error
   targets explicitly (not merely the declared L0), without unsupported
   matching construction. This adds no new model/physical behavior.

7. `python -m compileall -q src tests`, `git diff --check`, fresh prior-first
   and factory-first imports passed. Documentation integrity verifies changed
   local Markdown links/anchors, module DOCS coverage, unchanged historical
   AGENTS/STATUS/TEST prefixes and byte-identical supplied scientific spec.
   Parent bench status is unchanged; no experiment outputs are generated.

No H5 option, full pytest suite, large Monte Carlo, performance sweep, exact
conditional/marginal-model claim, LER-improvement claim or paper reproduction.


## Auxiliary-system H5 public options and whole-implementation audit

Date: 2026-10-16. Same Python 3.12.7 / NumPy 1.26.4 / SciPy 1.13.1 /
Stim 1.15.0 / PyMatching 2.3.1 / stimbposd 0.2.0 / local LDPC 2.1.2 /
pytest 7.4.4 environment as H4. No dependencies were installed/upgraded.

Initial refactor check:

```bash
PYTHONPATH=src python -m pytest -q tests/test_codecapacity_dem.py tests/test_factory_batch.py
```

Result: **1 failed, 69 passed, 8 warnings, 33.65 s**. The cached H4 builder
re-enumerated faults before checking the result cache; inspect now validates
its index and returns a cached result before any context/enumeration work.
That regression is fixed and passes in the subsequent whole selection.

Initial public-option check:

```bash
PYTHONPATH=src python -m pytest -q tests/test_codecapacity_public.py
```

Result: **2 failed, 12 passed, 8 warnings, 32.56 s**. Both supported full-Knill
models passed the lift; two test assertions incorrectly guessed 905 mechanisms.
The actual full prefix has 1,058 retained mechanisms. Corrected the expected
counts; did not change/drop model faults to fit the assertion.

Whole fast repository selection:

```bash
PYTHONPATH=src python -m pytest -q tests -k 'not ler_is_statistically_compatible'
```

Result: **260 passed, 2 deselected, 8 warnings, 94.24 s**. It covers all
H1/H2/H3/H4/H5 tests, decoder/result adapters, fixed and stateful Knill,
adaptive preparation/confidence/pair logic, shared correction caches,
forced-long diagnostics, validation/statistical-analysis infrastructure and
profiling tests. The two intentionally excluded inherited tests run 2,048
physical shots per workflow to compare statistical LERs. This is a complete
fast selection, not a claim that the unrestricted suite or paper figure ran.
Existing inherited 256-shot static fixtures remain; new physical tests use
<=64 shots (mostly 16/32), and controlled fault lanes/classical enumeration
are not Monte Carlo shots. All warnings are existing pkg_resources/namespace
deprecations from the local LDPC dependency environment.

After adding stronger context-vs-manual replay, final-noise independence,
direct Bell True-context API and unsupported prep-backend assertions, reran:

```bash
PYTHONPATH=src python -m pytest -q tests/test_codecapacity_public.py
```

Result: **15 passed, 8 warnings, 37.11 s**. No production algorithm changed
since the whole selection except explanatory docstrings. Coverage includes:

- False implicit/explicit API compatibility and fixed-seed circuit/raw/
  complete-correction/per-shot-label regression against an isolated H4 archive;
- d=3 full Knill True, one SE round/T=1, both bases and both sectors,
  noisy final readout, `(shots,2)` logical Z/X feed-forward and exhaustive
  both-sector min-sum classes;
- explicit rejection before sampling of d=3 full-Knill X-sector invisible
  logical terms at two/three SE rounds, plus zero-noise finite-weight requests;
- full-prefix interpretation equal to manual prep-correction replay, strict
  width/sector/code checks, unchanged models after final-noise removal,
  complete-context standalone gadget use and unsupported prep backend guards;
- six paired physical fault cases at prep reset/SE, correlated Bell coupling
  and both X/Z destructive readouts; raw controlled propagation matches exactly;
- d=3 depths (2,2) factory True T=1/2, finite log-weight gaps, frame equations,
  identical saved physical records, scalar/batch equality, actual earlier
  projected policy identities and future/oracle causal isolation;
- factory counters (eight setup matchings when reusing the prepared bundle,
  one compiled sampler for T=2) and forbidden native constructions during
  repeated callbacks/sample/decode; complete input/flag/context boundaries.

Golden False data were produced by extracting `git archive 7df0b96 src` into
a temporary directory outside the repo and running only that package in a
fresh process. At d=3, p=.015, seed 1021 and 64 shots, (r,T,basis)=(1,1,X)
has 11 error labels and (2,2,Z) has 9. Checked-in tests pin circuit/raw/label/
correction SHA256 hashes; native hashes are scoped to Stim 1.15.0/PyMatching
2.3.1. The archive and physical outputs are not committed. Default factory
regressions remain covered by H1-H4 tests and their saved-record checks.

The whole assessment is software/model validity within tested domains. H4's
13/16 physical-context logical mismatch and 18/36 nonlinear two-fault pairs
are retained regression cases, not corrected away. No exact marginal,
conditional/posterior, validated gain, threshold, speedup, large Monte Carlo
or FT claim follows. See [the H5 audit guide](docs/logical_zero_factory_h5.md).


Final whole-audit extension: a setup probe also accepted full Knill d=3,
p=.001, one SE round, T=2/Z. Added a sixteenth H5 test that compares both
stages/sectors to independent manual replay of actual prep and preceding
projected Bell feed-forward on 16 saved physical shots, with zero detector
residuals. The final rerun of
`PYTHONPATH=src python -m pytest -q tests -k 'not ler_is_statistically_compatible'`
passed **261 tests, 2 deselected, 8 warnings, 86.27 s**. This extends tested
full-Knill coverage to T=2/Z without weakening the two/three-SE X-sector
rejection. A test-order review also moved prepared-bundle construction before
count instrumentation so the factory reuse counter can run independently.


Final integrity checks: `PYTHONPATH=src python -m compileall -q src` and
`git diff --check` pass. Fresh decoder-first and protocol-first interpreter
imports pass. All six Python package directories have DOCS.md; all 107 local
links/anchors in changed Markdown resolve. Root AGENTS/STATUS/TEST retain their
exact H4 byte prefixes, and the scientific specification remains byte-identical
to the parent copy (SHA256
`ca7a2748f60e05c2944cddd318c1096eedb269293280826661180b49056337b4`).
All 25 changed files are source/tests/Markdown; parent pre-existing `.gitignore`
and untracked AGENTS/STATUS remain untouched. No experiment outputs are staged.
The independently invoked factory construction-counter test also passes:
`PYTHONPATH=src python -m pytest -q tests/test_codecapacity_public.py::test_factory_true_reuses_graphs_sampler_and_maps`
(**1 passed, 8 warnings, 4.73 s**).
