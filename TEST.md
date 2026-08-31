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
