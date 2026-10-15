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

## Proposed only

The [factory specification](../../../docs/README.md) calls for two reused
supports, exact preparation depths, signed stage/record metadata, and one
terminal ideal evaluation readout. No factory builder or ledger was added in
H0. Future compiled cases must reuse circuits/samplers across shots and keep
the actual consumed-block readout noisy.
