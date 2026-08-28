# Theory notes

This file is a research/theory skeleton for the current Hex baseline.  It
records the mathematical conventions that the implementation currently uses;
adaptive scheduling and its performance claims are intentionally left for a
later validated phase.

## CSS code convention

For `n` data qubits, the baseline represents a CSS code by binary parity-check
matrices

```text
H_X ∈ GF(2)^(m_X × n)
H_Z ∈ GF(2)^(m_Z × n)
```

and logical-operator rows `L_X` and `L_Z` with `n` columns.  A binary error or
measurement-error vector `e` has one coordinate per physical qubit.  The
corresponding check syndrome is evaluated as

```text
s_X = H_X e mod 2,
s_Z = H_Z e mod 2.
```

Rows are checks/operators and columns are physical qubits.  The code data
must satisfy the usual CSS commutation condition

```text
H_X H_Z^T = 0 mod 2,
```

although the current loader and circuit builders do not explicitly verify it.

## Stabilizer measurement and temporal detectors

Each stabilizer-extraction round measures X and Z check operators using
ancillas.  For repeated rounds, the detector construction compares a check
result in one round with the corresponding result in the preceding round.
Ignoring boundary and preparation-specific details, a temporal detector is a
parity such as

```text
d_{r,j} = s_{r,j} + s_{r-1,j} mod 2.
```

The first round has a preparation-dependent deterministic detector family;
subsequent rounds contain both X and Z families in the current both-detector
circuit.  The detector error model describes how physical circuit faults map
to these detector outcomes.

## Decoder and repair-frame interpretation

The modular engine decodes detector outcomes to a correction-variable vector
and then uses a precomputed GF(2) propagation map to update later measurement
records.  If `c` is a row vector of decoder correction variables and `M` is
the correction-to-measurement map, the software update is conceptually

```text
m_corrected = m + c M mod 2.
```

The map convention used by the implementation is:

```text
M.shape = (number_of_correction_variables, number_of_measurement_entries)
M[j, k] = 1 iff correction variable j flips measurement entry k.
```

Detector corrections are first used to repair the local measurement history;
the final X/Z stabilizer signs are then code-capacity decoded to obtain repair
corrections.  Logical measurement values are computed from the corrected
physical measurement vector and the logical-operator rows.

## Noise model represented by the current builders

The circuit builders use a simplified circuit-level Pauli model.  The single
`prob` value is supplied to data initialization/readout errors, ancilla
preparation/readout errors, two-qubit depolarizing instructions after
interactions, and transversal gates.  This is an implementation convention,
not a claim that all hardware error mechanisms have the same probability.

For a decoder error model with prior `p`, the matchable path derives a weight
using the code's current expression

```text
w = log(1 + p) - log(p),
```

after converting hyperedges to edges.  The non-matchable path retains the DEM
check matrix and uses the DEM priors directly as weights.

## Knill and Steane interpretation

Knill error correction prepares encoded `|0_L>` and `|+_L>` ancillas, creates
an encoded Bell pair with a transversal CNOT, and teleports the data through
a Bell measurement.  The final logical measurement tests whether the
selected logical basis value agrees with the expected value.

Steane error correction uses encoded ancillas and transversal CNOTs to extract
syndromes for data correction.  Both protocols can repeat their correction
step for multiple teleportation/QEC indices in the current builders.

The baseline logical error rate is the Monte Carlo quantity

```text
LER = number of shots with one or more wrong logical values / sampled shots.
```

Postselected counts, when a module supplies postselection flags, are tracked
separately by the static engine.

## Scope of this skeleton

The current implementation samples a complete static circuit before module
decoding.  It therefore does not yet represent a short-round confidence
decision, continuation of one physical shot, or a long decode over a
short-plus-extra history.  Those semantics require a separate stateful
sampling design and should be added only after the fixed-round baseline is
validated.

Future additions should cite the specific QEC and Knill literature, define
the confidence metric mathematically, and distinguish physical state from
software correction state.
