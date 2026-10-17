# Configurable factory physical noise

HEX-N1 introduces frozen validated configuration objects in
`hex_qec.circuit_generation.factory_noise` (also exported from
`hex_qec.circuit_generation`). HEX-N2 integrates them into the logical-zero
factory only. Full Knill, Fig. 4(d), Steane and adaptive protocols keep their
existing noise interfaces and physics.

`CircuitNoiseModel(one_qubit=1, two_qubit=1, idle=1, measurement=1, reset=1)`
contains reusable nonnegative finite multipliers relative to physical rate p.
`FactoryNoiseModel` extends it with `post_cnot_control=IdleWindow(duration=0,
rate_multiplier=1)` and `during_plus_preparation=PlusPreparationIdle(enabled=False,
se_round_duration=1, rate_multiplier=1)`. Dictionaries and duration expressions
such as `"d"` are rejected. Configuration objects are immutable and hashable;
`as_dict()` returns an independent JSON-compatible copy, and
`configuration_sha256` hashes canonical parameters, independently of p.

## Channels and idle mathematics

Custom one-qubit gates use `DEPOLARIZE1(p*one_qubit)`; two-qubit gates use
`DEPOLARIZE2(p*two_qubit)`. Measurements use the complementary Pauli flip
before the measurement, and resets use the complementary Pauli after reset:
X for Z-basis operations, Z for X-basis operations. Multipliers do not denote
probabilities themselves: each resolved channel probability must be in [0,1].
Parameters are never clipped. Preparation decoding must be built from the
same noisy preparation circuit, before any decoder/repair map is compiled.

`idle_depolarizing_probability(p, idle, duration, rate_multiplier=1)` computes

\[
q=p\,m_{idle}\,m_{window},\qquad
p_{eff}(\tau)=\frac34[1-(1-4q/3)^\tau].
\]

All inputs are finite nonnegative real numbers (booleans are rejected), with
p and q in [0,1]. Fractional duration requires q<=3/4 so the power is real.
Integer durations also support q>3/4. Zero duration has zero effective noise;
even then the base probability is validated. Stable `log1p`/`expm1`
evaluation retains tiny positive exposures. No arbitrary per-instruction idle
channel is implied. One aggregated channel composes the identical independent
depolarizing channels on a stored qubit over the specified idle interval.

The model intentionally distinguishes `noise_model=None` (legacy
`hex_uniform`, including its absence of one-qubit depolarizing channels) from
an all-one custom object. Neither window is enabled by default in the custom
object. No `additional_wait` option, threshold-dependent circuit or dynamic
retry is provided.

## Placement contract for factory integration

After the complete transversal CNOT, the surviving fresh-plus control's data
qubits receive the post-CNOT idle channel, before destructive Z target
readout. Neither target nor ancillas receives that special channel. It must
be within the identified coupling region so a downstream local DEM can
include it.

For stages j>=1, the old survivor stores logical zero while the consumed
support resets and prepares plus for r_plus rounds. Its idle duration is
`r_plus*se_round_duration`. An aggregated channel at the end of preparation
is equivalent because the stored block does not interact with the preparing
block in that interval. Initial zero/plus preparations are assumed parallel;
there is no initial storage wait. These two windows are disjoint, with no
generic idle layer counting either interval twice.

Physical simulation includes both windows. A downstream module-local prior
starting just before CNOT includes post-CNOT control idle, and may exclude
inter-stage storage idle along with preparation/earlier residuals. Such a
prior is approximate and is not the posterior conditioned on offline repair.
Hex H5 itself retains its full-prefix fixed-reference projected prior; it
does not silently switch to a module-local model. Structural DEM/graph checks
and complete detector/logical signatures must remain strict in either case.

The sole ideal terminal evaluation oracle is outside every operational
model; no oracle information is a decoder input or confidence score.
