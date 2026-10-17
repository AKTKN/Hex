# Circuit generation: current API and boundaries

Detailed background: [DESCRIPTION.md](DESCRIPTION.md). The implementation is
procedural in `circuit_generation.py`; matrix data directories contain no
Python modules.

## Implemented today

- `get_parity_check_matrices(code, distance)` loads Matrix Market sparse
  `(H_X, H_Z, L_X, L_Z)` from the bundled code families. Checks have shape
  `(m_x/m_z, n)` and logical rows `(k, n)`.
- `create_stabilizers_and_block_template(*matrices)` returns a support
  dictionary, stabilizer/logical Pauli strings, and two ideal tableau encoder
  templates. `generate_blocks(count, template)` offsets complete supports of
  size `n + m_x + m_z`; keys are `data_qubits`, `x_ancillas`, `z_ancillas`.
- `qubit_initialisation`, `qubit_measurement`, stabilizer-measurement helpers,
  `transversal_cnot`, and `ideal_preparation_circuit` append Stim fragments.
  `noiseless_unitary_state_prep(matrices, pauli, eigenvalue)` returns an ideal
  encoded-state circuit.
- `stabilizer_measurement_circuit(...)` includes noisy final data readout even
  when `disable_final_detectors=True`; that flag suppresses terminal detectors
  and the observable. Its repeated detectors compare only the selected basis.
  `stabilizer_measurement_circuit_both_detectors(...)` omits final readout and
  compares both check families after the first round.

Each SE round records X checks then Z checks, so `r >= 1` rounds have
`r*(m_x+m_z)` ancilla measurements. Initial detectors use only the prepared
basis: `m_init = m_x` for plus, `m_z` for zero. The both-detector builder has
`m_init + (r-1)*(m_x+m_z)` detectors; the single-basis builder has `r*m_init`
before any optional terminal closure. Unknown opposite-basis initial signs
are not deterministic detector bits. This clarifies the repeated-detector
count in the older description.

Noise uses the same `prob` for data reset/readout flips, ancilla preparation
and readout flips, and `DEPOLARIZE2` after interactions. There is no explicit
idle or one-qubit depolarizing noise. Surface ordering is opt-in:
`surface_code=True`; weight-four X supports use sorted support order, and
Z supports swap the middle two interactions. The low-level transversal helper
groups its noise after the CNOTs; the modular gadget interleaves gate/noise
pairs. Preserve the chosen builder's order when reusing it.

Builders return unsampled circuits and do not cache samplers or validate full
CSS rank/commutation. Missing code data use unchecked glob lookup; argument
validation is limited. The SE builder always emits its first round even for
invalid nonpositive repetition values. H0 fixes none of these issues.

Existing coverage is in `test_phase4_adaptive_state_prep.py` and backend tests;
H0 executed only the adapter/result and validation subsets listed in
[TEST.md](../../../TEST.md#auxiliary-system-h0-documentation-baseline).

## H1 adapter

`factory_surface.RotatedSurfaceCodeAdapter(distance)` is the sole implemented
factory family adapter. Its `code` is a geometry-independent `CodeSpec`,
`matrices` the four sparse CSS matrices, `blocks()` two complete
`BlockSupport`s, and `prepare(block,basis,rounds,p)` an existing surface-ordered
`css_detector_module`. It validates bundled odd d>=3, n=d*d, binary CSS
commutation/logical anticommutation, and single logical rows. Generic factory
contracts do not assume d*d. No existing low-level builder changed.

H1 tests d=3/5 exact independent SE depths, support count, hook-builder reuse,
reset/readout/CNOT noise, and strict signed flows. The factory's actual
consumed-block readout stays noisy; only its evaluation suffix is ideal.
See [the H1 guide](../../../docs/logical_zero_factory_h1.md). Multi-stage
support recycling and compiled sampling remain later work.

## HEX-N1 configurable noise objects

`factory_noise.py` exports frozen `CircuitNoiseModel`, `FactoryNoiseModel`,
`IdleWindow`, `PlusPreparationIdle` and `idle_depolarizing_probability`.
Multipliers/durations are finite nonnegative reals; resolved channels are in
[0,1], with explicit fractional-power domain checks and no clipping. This
stage adds no channel to existing circuits. See the
[noise guide](../../../docs/factory_noise_model.md) for equations, opt-in
semantics, timing boundaries and planned factory-only integration.
