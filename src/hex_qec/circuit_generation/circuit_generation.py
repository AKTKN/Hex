import stim
import glob
from pathlib import Path
from scipy.io import mmread, mmwrite


############################################
# ######################################## #
# # Generate syndrome extraction circuit # #
# ######################################## #
############################################

####################
# Helper functions #
####################

def get_parity_check_matrices(code, distance):
    parity_check_directory = Path(__file__).parent / f"parity_check_matrices/{code}"
    x_pcm_filename     = glob.glob(f"{parity_check_directory}/{code}_*_{distance}_hx.mtx")[0]
    z_pcm_filename     = glob.glob(f"{parity_check_directory}/{code}_*_{distance}_hz.mtx")[0]
    x_logical_filename = glob.glob(f"{parity_check_directory}/{code}_*_{distance}_lx.mtx")[0]
    z_logical_filename = glob.glob(f"{parity_check_directory}/{code}_*_{distance}_lz.mtx")[0]
    x_pcm = mmread(x_pcm_filename)
    z_pcm = mmread(z_pcm_filename)
    x_logical = mmread(x_logical_filename)
    z_logical = mmread(z_logical_filename)

    parity_check_tuple = (x_pcm, z_pcm, x_logical, z_logical)
    return parity_check_tuple

def generate_blocks(number_of_blocks, block_template):
    size_of_block = len(block_template["data_qubits"] + block_template["x_ancillas"] + block_template["z_ancillas"])
    blocks = []
    for block_number in range(number_of_blocks):
        new_block = {}
        new_block["data_qubits"] = block_template["data_qubits"].copy()
        new_block["x_ancillas"] = block_template["x_ancillas"].copy()
        new_block["z_ancillas"] = block_template["z_ancillas"].copy()
        for qubit_type in ["data_qubits", "x_ancillas", "z_ancillas"]:
            for index, q in enumerate(new_block[qubit_type]):
                new_block[qubit_type][index] = q + (block_number * size_of_block)
        blocks.append(new_block)

    return blocks

# This currently is for CSS codes where there are seperate X and Z pcms
def sparse_binary_array_to_paulistrings(sparse_binary_array, pauli):
    n = sparse_binary_array.shape[1]
    paulistrings = []
    for row_index in range(sparse_binary_array.shape[0]):
        paulistring = stim.PauliString("I") * n
        for i in sparse_binary_array.getrow(row_index).indices:
            paulistring[i] = pauli
        paulistrings.append(paulistring)
    return paulistrings

def create_stabilizers_and_block_template(x_pcm, z_pcm, x_logical_binary, z_logical_binary):
    assert x_pcm.shape[1] == z_pcm.shape[1]
    n = x_pcm.shape[1]
    # There may be redundant stabilizers, Rank(x_pcm) != x_pcm.shape[0], but this is fine
    # x_stab_num = np.linalg.matrix_rank(x_pcm.toarray())
    # z_stab_num = np.linalg.matrix_rank(z_pcm.toarray())

    x_stab_num = x_pcm.shape[0]
    z_stab_num = z_pcm.shape[0]

    # Iterate through the rows of the parity check matrices
    x_stabilizers_redundant = sparse_binary_array_to_paulistrings(x_pcm, "X")
    logical_X = sparse_binary_array_to_paulistrings(x_logical_binary, "X")
    z_stabilizers_redundant = sparse_binary_array_to_paulistrings(z_pcm, "Z")
    logical_Z = sparse_binary_array_to_paulistrings(z_logical_binary, "Z")

    tab_Z = stim.Tableau.from_stabilizers(x_stabilizers_redundant + z_stabilizers_redundant + logical_Z, allow_redundant=True)

    # Template circuit for generating logical 0
    logical_0_prep_template = tab_Z.to_circuit()
    # Template circuit for generating logical +
    tab_X = stim.Tableau.from_stabilizers(x_stabilizers_redundant + z_stabilizers_redundant + logical_X, allow_redundant=True)
    logical_plus_prep_template = tab_X.to_circuit()

    # block template
    data_qubits = list(range(0, n))
    x_ancilla_qubits = list(range(n, n + x_stab_num))
    z_ancilla_qubits = list(range(n + x_stab_num, n + x_stab_num + z_stab_num))
    block_template = {"data_qubits": data_qubits, "x_ancillas": x_ancilla_qubits, "z_ancillas": z_ancilla_qubits}
    assert(len(block_template["x_ancillas"]) == x_stab_num)
    assert(len(block_template["z_ancillas"]) == z_stab_num)

    stabilizer_tuple = (x_stabilizers_redundant, z_stabilizers_redundant, logical_X, logical_Z)

    return block_template, stabilizer_tuple, logical_0_prep_template, logical_plus_prep_template

def qubit_initialisation(circuit, pauli, block, prob):
    state_prep_error = prob
    data_qubits = block["data_qubits"]
    # Prepare all physical qubits in the |0> state
    if pauli.lower() == "z":
        circuit.append("R", block["data_qubits"])
        circuit.append("X_ERROR", block["data_qubits"], state_prep_error)
    # Prepare all physical qubits in the |+> state
    elif pauli.lower() == "x":
        circuit.append("RX", block["data_qubits"])
        circuit.append("Z_ERROR", block["data_qubits"], state_prep_error)
            

def qubit_measurement(circuit, pauli, block, prob):
    measurement_error = prob
    data_qubits = block["data_qubits"]
    # Prepare all physical qubits in the |0> state
    if pauli.lower() == "z":
        circuit.append("X_ERROR", block["data_qubits"], measurement_error)
        circuit.append("M", block["data_qubits"])
    # Prepare all physical qubits in the |+> state
    elif pauli.lower() == "x":
        circuit.append("Z_ERROR", block["data_qubits"], measurement_error)
        circuit.append("MX", block["data_qubits"])

def measure_X_stabilizers(circuit, x_stabilizers, block, prob):
    two_qubit_error = prob
    ancilla_error = prob
    data_qubits = block["data_qubits"]
    x_ancilla_qubits = block["x_ancillas"]
    # Prepare the ancillas
    circuit.append("R", x_ancilla_qubits)  # |+> State prep
    circuit.append("H", x_ancilla_qubits)
    circuit.append("Z_ERROR", x_ancilla_qubits, ancilla_error)  # State preparation error
    # Iterate over stabilizers and measure them using the corresponding ancilla

    for ancilla_index, ancilla in enumerate(x_ancilla_qubits):
        stabilizer = x_stabilizers[ancilla_index]
        stabilizer_qubit_locations = []
        for q_ind, q_loc in enumerate(data_qubits):
            if stabilizer[q_ind] == 1:
                stabilizer_qubit_locations.append(q_loc)
                circuit.append("CX", [ancilla, q_loc])
                circuit.append("DEPOLARIZE2", [ancilla, q_loc], two_qubit_error)

    circuit.append("Z_ERROR", x_ancilla_qubits, ancilla_error)  # Measurement error
    circuit.append("H", x_ancilla_qubits)  # X measurement
    circuit.append("MR", x_ancilla_qubits)

def measure_Z_stabilizers(circuit, z_stabilizers, block, prob):
    two_qubit_error = prob
    ancilla_error = prob
    data_qubits = block["data_qubits"]
    z_ancilla_qubits = block["z_ancillas"]
    # Prepare the ancillas
    circuit.append("R", z_ancilla_qubits)  # |+> State prep
    circuit.append("H", z_ancilla_qubits)
    circuit.append("Z_ERROR", z_ancilla_qubits, ancilla_error)  # State preparation error
    # Iterate over stabilizers and measure them using the corresponding ancilla

    for ancilla_index, ancilla in enumerate(z_ancilla_qubits):
        stabilizer = z_stabilizers[ancilla_index]
        stabilizer_qubit_locations = []
        for q_ind, q_loc in enumerate(data_qubits):
            if stabilizer[q_ind] == 3:
                stabilizer_qubit_locations.append(q_loc)
                circuit.append("CZ", [ancilla, q_loc])
                circuit.append("DEPOLARIZE2", [ancilla, q_loc], two_qubit_error)

    circuit.append("Z_ERROR", z_ancilla_qubits, ancilla_error)  # Measurement error
    circuit.append("H", z_ancilla_qubits)  # Z measurement
    circuit.append("MR", z_ancilla_qubits)

def transversal_cnot(circuit, first_block, second_block, prob):
    first_block_data_qubits = first_block["data_qubits"]
    second_block_data_qubits = second_block["data_qubits"]
    # Make sure the number of physical qubits is the same for both logical qubits
    assert len(first_block_data_qubits) == len(second_block_data_qubits)
    # Apply transversal cnot gate
    for q_index in range(len(first_block_data_qubits)):
        circuit.append("CX", [first_block_data_qubits[q_index], second_block_data_qubits[q_index]])
    circuit.append("DEPOLARIZE2", [item for pair in zip(first_block_data_qubits, second_block_data_qubits) for item in pair], prob)

def ideal_preparation_circuit(circuit, block, template):
    data_qubits = block["data_qubits"]
    qubit_relabelling = {}
    for q_ind, q_loc in enumerate(data_qubits):
        qubit_relabelling[str(q_ind)] = str(q_loc)

    def replace_numbers(match):
        num = match.group()
        return qubit_relabelling.get(num, num)

    prep_circ_str = ""
    inside_bracket = False
    current_num = ""
    for char in str(template) + "\n":
        if char == "[":
            inside_bracket = True
            prep_circ_str += char
        elif char == "]":
            inside_bracket = False
            prep_circ_str += char
        else:
            # Only deal with integers outside of brackets
            if inside_bracket is False and char in ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9"]:
                # build new number
                current_num += char
            elif inside_bracket is False and len(current_num) > 0:
                # swap number and add to string
                prep_circ_str += qubit_relabelling[current_num]
                prep_circ_str += char
                current_num = ""
            else:
                prep_circ_str += char

    circuit.append_from_stim_program_text(prep_circ_str)

#####################
# Cicuit generation #
#####################

def stabilizer_measurement_circuit(
        parity_check_tuple,
        # stabilizer_tuple,
        # block_template,
        pauli,
        syndrome_repetitions,
        prob,
        disable_final_detectors=True,
        debug=False
):
    block_template, stabilizer_tuple, logical_0_prep_template, logical_plus_prep_template = create_stabilizers_and_block_template(*parity_check_tuple)
    x_stabilizers, z_stabilizers, x_logicals, z_logicals = stabilizer_tuple
    blocks = generate_blocks(1, block_template)
    block = blocks[0]
    circ = stim.Circuit()


    n = len(block["data_qubits"])
    num_z_stabilizers = len(block["z_ancillas"])
    num_x_stabilizers = len(block["x_ancillas"])
        

    # Apply a Hadamard to all gates if you want to prepare in the X-basis
    #circ.append("H", block["data_qubits"])

    # Noisey physical qubit state preparation
    qubit_initialisation(circ, pauli, block, prob)

    # First found of stabilizer measurement
    measure_X_stabilizers(circ, x_stabilizers, block, prob)
    measure_Z_stabilizers(circ, z_stabilizers, block, prob)

    # Initial detectors
    if pauli.lower() == "x":
        for stab_num in range(num_x_stabilizers):
            #print(-num_stabilizers + stab_num)
            circ.append("DETECTOR", [stim.target_rec(-(num_z_stabilizers + num_x_stabilizers) + stab_num)])
    elif pauli.lower() == "z":
        for stab_num in range(num_z_stabilizers):
            #print(-num_stabilizers + stab_num)
            circ.append("DETECTOR", [stim.target_rec(-num_z_stabilizers + stab_num)])

    for syndrome_repetition in range(2, syndrome_repetitions+1):
        measure_X_stabilizers(circ, x_stabilizers, block, prob)
        measure_Z_stabilizers(circ, z_stabilizers, block, prob)
        # Add detectors
        if pauli.lower() == "x":
            for stab_num in range(num_x_stabilizers):
                circ.append("DETECTOR", [stim.target_rec(-2*(num_z_stabilizers + num_x_stabilizers) + stab_num), stim.target_rec(-(num_z_stabilizers + num_x_stabilizers) + stab_num)])
        elif pauli.lower() == "z":
            for stab_num in range(num_z_stabilizers):
                circ.append("DETECTOR", [stim.target_rec(-(2*num_z_stabilizers + num_x_stabilizers) + stab_num), stim.target_rec(-num_z_stabilizers + stab_num)])


    # # Noisy physical qubit measurement
    # qubit_measurement(circ, pauli, block, prob)

    # if not disable_final_detectors:
    #     # Form detectors between directly measured qubits and the previous stabilizer measurements
    #     for stab_num in range(num_stabilizers):
    #         circ.append("DETECTOR", [stim.target_rec(-n - num_stabilizers + stab_num)] + [stim.target_rec(-n + i) for i in z_pcm.col[z_pcm.row == stab_num]])

    #     circ.append("OBSERVABLE_INCLUDE", [stim.target_rec(-n + i) for i in z_logical_binary.nonzero()[1]], 0)

    # debug and print(f"Number of detectors: {circ.num_detectors} = {circ.num_detectors / num_stabilizers} * {num_stabilizers}(number of stabilizers)")

    return circ

def stabilizer_measurement_circuit_both_detectors(
        parity_check_tuple,
        # stabilizer_tuple,
        # block_template,
        pauli,
        syndrome_repetitions,
        prob,
        disable_final_detectors=True,
        debug=False
):
    block_template, stabilizer_tuple, logical_0_prep_template, logical_plus_prep_template = create_stabilizers_and_block_template(*parity_check_tuple)
    x_stabilizers, z_stabilizers, x_logicals, z_logicals = stabilizer_tuple
    blocks = generate_blocks(1, block_template)
    block = blocks[0]
    circ = stim.Circuit()

    n = len(block["data_qubits"])
    num_z_stabilizers = len(block["z_ancillas"])
    num_x_stabilizers = len(block["x_ancillas"])

    # Noisey physical qubit state preparation
    qubit_initialisation(circ, pauli, block, prob)

    # First found of stabilizer measurement
    measure_X_stabilizers(circ, x_stabilizers, block, prob)
    measure_Z_stabilizers(circ, z_stabilizers, block, prob)

    # Initial detectors
    if pauli.lower() == "x":
        for stab_num in range(num_x_stabilizers):
            #print(-num_stabilizers + stab_num)
            circ.append("DETECTOR", [stim.target_rec(-(num_z_stabilizers + num_x_stabilizers) + stab_num)])
    elif pauli.lower() == "z":
        for stab_num in range(num_z_stabilizers):
            #print(-num_stabilizers + stab_num)
            circ.append("DETECTOR", [stim.target_rec(-num_z_stabilizers + stab_num)])

    for syndrome_repetition in range(2, syndrome_repetitions+1):
        measure_X_stabilizers(circ, x_stabilizers, block, prob)
        measure_Z_stabilizers(circ, z_stabilizers, block, prob)
        # Add detectors
        # if pauli.lower() == "x":
        for stab_num in range(num_x_stabilizers):
            circ.append("DETECTOR", [stim.target_rec(-2*(num_z_stabilizers + num_x_stabilizers) + stab_num), stim.target_rec(-(num_z_stabilizers + num_x_stabilizers) + stab_num)])
        # elif pauli.lower() == "z":
        for stab_num in range(num_z_stabilizers):
            circ.append("DETECTOR", [stim.target_rec(-(2*num_z_stabilizers + num_x_stabilizers) + stab_num), stim.target_rec(-num_z_stabilizers + stab_num)])

    return circ

def noiseless_unitary_state_prep(
        code: str,
        distance: int,
        pauli: str,
        eigenvalue: int,
) -> stim.Circuit:

    parity_check_tuple = get_parity_check_matrices(code, distance)
    block_template, stabilizer_tuple, logical_0_prep_template, logical_plus_prep_template = create_stabilizers_and_block_template(*parity_check_tuple)
    x_stabilizers, z_stabilizers, x_logicals, z_logicals = stabilizer_tuple
    blocks = generate_blocks(1, block_template)
    block = blocks[0]
    circuit = stim.Circuit()
    if pauli.lower() == "x":
        ideal_preparation_circuit(circuit, block, logical_plus_prep_template)
        if eigenvalue == 1:
            circuit.append("Z", block["data_qubits"])
    elif pauli.lower() == "z":
        ideal_preparation_circuit(circuit, block, logical_0_prep_template)
        if eigenvalue == 1:
            circuit.append("X", block["data_qubits"])

    return circuit
