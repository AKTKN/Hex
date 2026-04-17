# Hex

`hex_qec` is a Python tool for building fault-tolerant quantum error-correction protocols from reusable circuit modules.

The main idea is:

1. define a small set of module types that represent the common circuit patterns that appear in fault-tolerant protocols
2. assemble those modules into a protocol as a sequence
3. let the framework propagate inferred corrections through the rest of the circuit during simulation

The current main example in the repository is Knill error correction, implemented in [`src/hex_qec/protocols/knill_online_offline.py`](src/hex_qec/protocols/knill_online_offline.py).

## Installation

Install from the repository root:

```bash
pip install .
```

For development:

```bash
pip install -e .
```

I built this package to make is easier to run numerical experiments: [`https://github.com/ewanmurphy/Experiments`](https://github.com/ewanmurphy/Experiments). If you want to install the additional dependencies that allow you to use this tool run:

```bash
pip install -e ".[experiment]"
```

## Running the Knill error correction example with the experiments tool

Move in the examples directory
```bash
cd examples
```

This will run the Knill error correction experiment, sequentially performing each simulation of 1 core:
```bash
experiment local-run knill_offline_online
```

To run the simulation using 10 cores:
```bash
experiment local-run knill_offline_online --parallel 10
```

To change the parameters modify the file: [`examples/experiments/knill_offline_online/config.yaml`](examples/experiments/knill_offline_online/config.yaml)

## What This Library Is For

This library is not just a circuit generator. Its purpose is to help you write protocols in a modular way.

Instead of building one large Stim circuit and manually handling every decoding step, you build a protocol from modules. Each module carries:

- Stim circuit
- A classical function for processing the circuits measurement data.
- Rules for turning those output of that function into Pauli corrections, logical values, or postselection flags

At simulation time, the framework composes the circuits from all the modules into one large circuit. Then samples this circuit, and applies each module's correction logic in sequence.

That is what allows protocols to be written as clean module sequences.

## Package Layout

```text
src/hex_qec/
├── circuit_generation/
├── modularisation/
└── protocols/
```

- `circuit_generation` contains code-family data and low-level Stim circuit builders.
- `modularisation` contains the base module classes, helper generators, and the protocol simulation engine.
- `protocols` contains example protocols built using this tool

The tool currently expects CSS-style code data:

- `x_pcm`
- `z_pcm`
- `x_logical`
- `z_logical`

These are passed around as a `parity_check_tuple`.

The repository includes pre-generated matrices for:

- `Rotated Surace Code`
- `Smaller family of Lifted Product Codes from` [1].
- `Larger family of Lifted Product Codes from` [1].

Load them with:

```python
from hex_qec.circuit_generation import get_parity_check_matrices

parity_check_tuple = get_parity_check_matrices("surface", 3)
```

You can also provide your own tuple of matrices if you want to build protocols for another CSS code.

## Core Module Types

The modules are defined in [`src/hex_qec/modularisation/modularised_circuit.py`](src/hex_qec/modularisation/modularised_circuit.py).

### `no_measurement_module`

Use this for circuit fragments with no measurements and no detectors.

Typical use:

- ideal logical state preparation
- transversal gates
- any pure circuit block that only changes the quantum state

### `measurement_module`

Use this when the module produces measurements and you already know how to decode those measurements directly.

You provide:

- Stim circuit
- A python function `c_func(measurements)` that is applied to batches of measurement data sampled from this module's stim circuit.
- The `correction_array`, a python dictionary that maps the output bits of c_func to specific Paulis that need inserting into the circuit.

`c_func` must return one correction bit per entry in `correction_array`.

Each entry of `correction_array` is:

```python
(pauli_string, instruction_offset)
```

meaning:

- if the corresponding output bit of c_func is `1`
- insert `pauli_string` after `instruction_offset`
- then the effect of that correction will be propagated to later measurements

This module is a good fit for:

- Bell measurements
- correction steps driven by raw measurement outcomes
- custom decode-and-correct gadgets
- When you're not planning to use a detector error model

### `detector_module`

Use this when the natural interface to the module is its detector error model.

You provide a decoder generator that will decode detector flips. The class extracts the detector error model from the circuit and builds the correction array automatically from representative faults.

This is useful when you want a module to decode from detector events rather than raw measurement bits.

This module is a good fit for:

- Repeated syndrome measurement

### `css_detector_module`

This is a specialised detector-based module.

It splits a module's detectors into X-type and Z-type detector sets, decodes them separately, then also decodes the final stabilizer measurements to return the combined physical correction data needed by the module.

In the current codebase, this is the main abstraction used for noisy encoded state preparation.

### `logical_measurement_module`

Use this for the final protocol checks.

Instead of returning corrections, its `c_func` returns logical measurement values. During simulation, those values are compared against `c_func_expected_output`, and mismatches count as logical errors.

### `only_postselection_module`

Use this when a module only flags shots for rejection.

The postselection value is accumulated during simulation. A shot with postselection flag `1` is excluded from the postselected logical error statistics.


This module is a good fit for:

- Circuits that use flag qubits

## How Simulation Works

The execution flow is controlled by `modularised_circuit`:

```python
from hex_qec.modularisation import modularised_circuit
```

The typical workflow is:

1. build a list of modules 
2. construct `modularised_circuit(module_list)`
3. call `generate_correction_to_measurement_flip_map()`
4. call `simulate(...)`

Example:

```python
protocol = modularised_circuit(module_list)
protocol.generate_correction_to_measurement_flip_map()
samples_performed, logical_errors = protocol.simulate(
    max_shots=10_000,
    max_errors_before_halting=500,
)
```

### Why we need `generate_correction_to_measurement_flip_map()`

This step is necessary because we are sampling the entire circuit at once.

For each correction a module might apply, the framework pre-computes which later measurements and detectors would flip if that correction were inserted into the circuit. Then, during simulation, decoded corrections are converted into measurement updates without having to propagate them through the circuit again.

That is how one module can affect all later modules while still being defined locally.

### What `simulate(...)` does

`simulate(...)` samples the concatenated Stim circuit in batches and then walks through the module list from left to right.

For each module it:

- extracts that module's measurements or detectors
- runs the module decoder
- computes the correction bits
- applies the corresponding precomputed measurement updates
- optionally accumulates postselection flags

When it reaches a `logical_measurement_module`, it compares the decoded logical values against the expected ones and counts logical failures.

If `results_path` is supplied, cumulative statistics are written to JSON during the run.

## Support Remapping

Most module constructors take a support list such as `new_support`.

You usually define a module once on a template support like:

```text
0, 1, 2, ..., n-1
```

and then remap it onto the actual qubits used by a protocol instance. This helps make the modules more reusable.

For example:

- a single encoded state-preparation module can be generated once
- copied
- then placed onto multiple different ancilla blocks

The helper `generate_blocks(...)` is used throughout the codebase to allocate repeated code blocks with consistent qubit numbering.

## Helper Functions For Building Protocols

The file [`src/hex_qec/modularisation/module_generation.py`](src/hex_qec/modularisation/module_generation.py) contains reusable builders for common protocol components.

The most useful ones are:

- `generate_logical_measurement_module(...)`
- `generate_state_prep_modules(...)`
- `generate_state_prep_module_no_noise(...)`
- `generate_transversal_cnot_module(...)`
- `generate_bell_measurement_and_correction_module(...)`

These are not the whole framework. They are examples of how to package common gadgets using the base module types.

## How Knill Error Correction Is Implemented

Knill error correction is implemented as a sequence of modules in [`src/hex_qec/protocols/knill_online_offline.py`](src/hex_qec/protocols/knill_online_offline.py).

### Step 1: Allocate blocks

The protocol starts by building a block template from the parity-check data and then generating:

```python
blocks = generate_blocks(2 * num_teleportations + 1, block_template)
```

Conceptually:

- `blocks[0]` is the current data block
- for each teleportation step:
  - one block is the first Bell ancilla block
  - one block is the second Bell ancilla block

### Step 2: Prepare the initial data block ideally

The input logical state is prepared with a noiseless unitary circuit:

- `|0_L>` if `pauli == "z"`
- `|+_L>` if `pauli == "x"`

This is wrapped in a `no_measurement_module`, because there are no measurements or detectors involved.

### Step 3: Prepare noisy ancilla blocks offline

For each teleportation step, the protocol prepares:

- a noisy encoded `|0_L>` block
- a noisy encoded `|+_L>` block

This is done with `generate_state_prep_modules(...)`, which returns `css_detector_module` instances placed on the requested supports.

This is the offline part of the protocol:

- the ancilla blocks are prepared using repeated stabilizer measurements
- the module decodes its own detectors and final stabilizer outcomes
- the _offline decoder_ is used here

### Step 4: Create the encoded Bell pair

After the two ancilla blocks are prepared, the protocol applies a transversal CNOT from the `|+_L>` block to the `|0_L>` block:

```python
generate_transversal_cnot_module(...)
```

This is a `no_measurement_module`.

### Step 5: Teleport the data through a Bell measurement

The core Knill step is:

```python
generate_bell_measurement_and_correction_module(...)
```

This module:

- performs a transversal CNOT between the current data block and the first Bell block
- measures the data block in X
- measures the first Bell block in Z
- decodes those measurement outcomes using the _online decoder_
- infers the logical X/Z teleportation corrections
- applies those logical corrections to the second Bell block

This is implemented as a `measurement_module`.

### Step 6: Repeat teleportation if requested

If `num_teleportations > 1`, the output block from one teleportation becomes the input data block for the next teleportation step.

### Step 7: Perform the final logical measurement

At the end, the protocol builds a `logical_measurement_module` on the final data block:

- X-basis if `pauli == "x"`
- Z-basis if `pauli == "z"`

This produces the logical values used to count failures.

### High-level structure of the Knill module list

In protocol order, the structure is:

```text
-> ideal data preparation
-> offline |0_L> preparation
-> offline |+_L> preparation
-> transversal CNOT to make Bell pair
-> Bell measurement and correction
-> repeat previous four steps if teleporting again
-> final logical measurement
```

## Writing Your Own Protocol

The easiest way to write your own protocol is to follow the as similar pattern to `knill_online_offline(...)`.

### Design recipe

1. Decide what the reusable gadgets in your protocol are.
2. For each gadget, decide which base module type it should be.
3. Give each gadget a clean local circuit and a decoder interface.
4. Remap each gadget onto the right support in the global protocol.
5. Append the modules in execution order.
6. Precompute correction-to-measurement maps.
7. Simulate.

### Choosing a base module

Use:

- `no_measurement_module` for pure circuit actions
- `measurement_module` when you decode from raw measurement outcomes
- `detector_module` when you decode from detector events
- `css_detector_module` when you want the both an X and Z DEM seperately
- `logical_measurement_module` for final success/failure checks
- `only_postselection_module` when you want to post-select but don't have any decoding

This is intentionally simple, but it shows the core shape of a protocol in this framework.

### Returning postselection flags

For `measurement_module`, `detector_module`, and `css_detector_module`, the simulation loop also accepts:

```python
(corrections, postselection_mask)
```

from the decoder function.

This lets a module both propose corrections and mark shots for rejection.

## Practical Notes

- The code is currently built around CSS codes with separate X and Z parity-check matrices.
- The module support you pass in should match the number of qubits in the module circuit.
- The helper generators in `module_generation.py` are examples of how to package gadgets, not fixed protocol definitions you must use.
- If you want to understand the framework, start with:
  - `src/hex_qec/modularisation/modularised_circuit.py`
  - `src/hex_qec/modularisation/module_generation.py`
  - `src/hex_qec/protocols/knill_online_offline.py`

## Attribution
If you use this software in your research please cite as follows:
```
@software{murphy_hex_2026,
  author       = {Ewan Murphy},
  title        = {Hex: modular simulation toolkit for quantum error correction},
  year         = {2026},
  url          = {https://github.com/ewanmurphy/Hex},
}
```

## References
[1] https://quantum-journal.org/papers/q-2022-07-20-767/
