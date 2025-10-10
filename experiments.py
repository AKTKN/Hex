import numpy as np
import stim
from pprint import pprint
import re


def apply_classical_functions(classical_functions, circuit_string_with_cfunc, num_samples=1):
    circuit_string = ""
    circuit_string_pauli_annotations = ""
    functions_that_need_running = []
    number_of_measurements = 0
    number_of_cfuncs = 0
    for line in circuit_string_with_cfunc.split("\n"):
        line_split = line.split("|")
        # Assuming one measurement per line
        if line_split[0][0] == "M":
            number_of_measurements += 1
        if len(line_split) > 1:
            #print("|".join(line_split))
            functions_that_need_running.append({
                "name": line_split[0].split()[1],
                "measurements": [number_of_measurements + int(meas_loc) for meas_loc in line_split[1].split()],
                "pauli locations": line_split[2].split()
            })
            circuit_string_pauli_annotations += f"PAULI[{number_of_cfuncs}] {" ".join(line_split[2].split())}\n"
            number_of_cfuncs += 1
        else:
            circuit_string += " ".join(line_split) + "\n"
            circuit_string_pauli_annotations += " ".join(line_split) + "\n"

    # Remove noise channels from the pauli annotated circuit
    circuit_string_pauli_annotations = re.sub("\n.*\(.*\).*\n", "\n", circuit_string_pauli_annotations)

    sim = stim.FlipSimulator(
        batch_size = 1,
        disable_stabilizer_randomization = True
    )
    # Iterate over the classical function location and identify what measurements they could flip
    flip_matrices = []
    split_circ_at_pauli_loc = re.split("PAULI.*\n",circuit_string_pauli_annotations)
    for cfunc_index, cfunc in enumerate(functions_that_need_running):
        flip_matrix_list = []
        for pauli in ["X", "Z"]:
            for pauli_loc in cfunc['pauli locations']:
                split_circ_at_pauli_loc.insert(cfunc_index+1, f"{pauli}_ERROR(1.0) {pauli_loc}\n")
                sim.do(stim.Circuit("".join(split_circ_at_pauli_loc)))
                split_circ_at_pauli_loc.pop(cfunc_index+1)
                flips = sim.get_measurement_flips()
                flip_matrix_list.append(flips)
                sim.clear()
        flip_matrix = np.hstack(flip_matrix_list)
        flip_matrices.append(flip_matrix.astype(int))

    # Sample the circuit
    sampler = stim.Circuit(circuit_string).compile_sampler()
    measurements = sampler.sample(num_samples)
    #print(measurements)

    # Run classical functions
    for cfunc_index, cfunc in enumerate(functions_that_need_running):
        #print(measurements[:, cfunc['measurements']])
        applied_paulis = np.apply_along_axis(classical_functions[cfunc['name']], 1, measurements[:, cfunc['measurements']])
        #print(applied_paulis)
        # print(measurements.astype(int))
        # print(applied_paulis @ flip_matrices[cfunc_index].T)
        measurements = (measurements + (applied_paulis @ flip_matrices[cfunc_index].T)) % 2
    #print(measurements)
    #print(np.sum(measurements[:, -1]))
    return measurements

if __name__ == "__main__":
    experiment_num = 3

    if experiment_num == 1:
        circuit = stim.Circuit("""
        I 0 1 2 3 4
        H 5
        CX 5 0
        X_ERROR(1.0) 5
        CX 5 1
        CX 5 2
        CX 5 3
        MRX 5


        CX 5 0
        CX 5 1
        CX 5 2
        CX 5 3
        MRX 5 CZ 5 0
        CZ 5 1
        CZ 5 2
        CZ 5 3
        MRX 5
        """)
        sampler = circuit.compile_sampler()
        print(sampler.sample(1))
        print(circuit.diagram())

        sim = stim.FlipSimulator(
            batch_size = 5,
            disable_stabilizer_randomization = True
        )
        sim.do(circuit)
        measurement_flips = sim.get_measurement_flips()
        print(measurement_flips)
    elif experiment_num == 2:
        bell_circuit_string_with_cfunc = """I 0 1 2 3 4 5 6
H 1
CX 1 2
CX 0 1
MX 0
MZ 1 # First bell measurement
cfunc bell_tell | -2 -1 | 2
H 3
CX 3 4
CX 2 3
MX 2
MZ 3 # Second bell measurement
cfunc bell_tell | -2 -1 | 4
H 5
CX 5 6
CX 4 5
MX 4
MZ 5 # Second bell measurement
cfunc bell_tell | -2 -1 | 6
M 6"""
        def bell_tell(measurements):
            # Pauli to apply in binary symplectic representation
            return np.array([measurements[1], measurements[0]])

        # Parse circuit string for classical function
        classical_functions = {"bell_tell": bell_tell}
        # I can probably do this parsing with regex
        bell_circuit_string = ""
        bell_circuit_string_pauli_annotations = ""
        functions_that_need_running = []
        number_of_measurements = 0
        number_of_cfuncs = 0
        for line in bell_circuit_string_with_cfunc.split("\n"):
            line_split = line.split("|")
            # Assuming one measurement per line
            if line_split[0][0] == "M":
                number_of_measurements += 1
            if len(line_split) > 1:
                #print("|".join(line_split))
                functions_that_need_running.append({
                    "name": line_split[0].split()[1],
                    "measurements": [number_of_measurements + int(meas_loc) for meas_loc in line_split[1].split()],
                    "pauli locations": line_split[2].split()
                })
                bell_circuit_string_pauli_annotations += f"PAULI({number_of_cfuncs}) {" ".join(line_split[2].split())}\n"
                number_of_cfuncs += 1
            else:
                bell_circuit_string += " ".join(line_split) + "\n"
                bell_circuit_string_pauli_annotations += " ".join(line_split) + "\n"

        sim = stim.FlipSimulator(
            batch_size = 1,
            disable_stabilizer_randomization = True
        )
        # Iterate over the classical function location and identify what measurements they could flip
        flip_matrices = []
        split_circ_at_pauli_loc = re.split("PAULI.*\n",bell_circuit_string_pauli_annotations)
        for cfunc_index, cfunc in enumerate(functions_that_need_running):
            flip_matrix_list = []
            for pauli in ["X", "Z"]:
                for pauli_loc in cfunc['pauli locations']:
                    split_circ_at_pauli_loc.insert(cfunc_index+1, f"{pauli}_ERROR(1.0) {pauli_loc}\n")
                    sim.do(stim.Circuit("".join(split_circ_at_pauli_loc)))
                    split_circ_at_pauli_loc.pop(cfunc_index+1)
                    flips = sim.get_measurement_flips()
                    flip_matrix_list.append(flips)
                    sim.clear()
            flip_matrix = np.hstack(flip_matrix_list)
            flip_matrices.append(flip_matrix.astype(int))

        # Sample the circuit
        sampler = stim.Circuit(bell_circuit_string).compile_sampler()
        measurements = sampler.sample(1000000)
        #print(measurements)

        # Run classical functions
        for cfunc_index, cfunc in enumerate(functions_that_need_running):
            #print(measurements[:, cfunc['measurements']])
            applied_paulis = np.apply_along_axis(classical_functions[cfunc['name']], 1, measurements[:, cfunc['measurements']])
            #print(applied_paulis)
            # print(measurements.astype(int))
            # print(applied_paulis @ flip_matrices[cfunc_index].T)
            measurements = (measurements + (applied_paulis @ flip_matrices[cfunc_index].T)) % 2
        #print(measurements)
        print(np.sum(measurements[:, -1]))
            

    elif experiment_num == 3:
        repetition_code_circuit_string_with_cfunc = """I 0 1 2 3 4
H 0 1 2
H 3
CZ 3 0
CZ 3 1
MX 3
H 4
CZ 4 1
CZ 4 2
MX 4
R 3
R 4
cfunc rep_dec | -2 -1 | 0 1 2
H 3
CZ 3 0
CZ 3 1
MX 3
H 4
CZ 4 1
CZ 4 2
MX 4
R 3
R 4
cfunc rep_dec | -2 -1 | 0 1 2
X_ERROR(0.2) 0 1
H 3
CZ 3 0
CZ 3 1
MX 3
H 4
CZ 4 1
CZ 4 2
MX 4
R 3
R 4
cfunc rep_dec | -2 -1 | 0 1 2
H 3
CZ 3 0
CZ 3 1
MX 3
H 4
CZ 4 1
CZ 4 2
MX 4
R 3
R 4
cfunc rep_dec | -2 -1 | 0 1 2
M 0        
M 1        
M 2"""

        def repetition_decoder(measurements):
            # Pauli to apply in binary symplectic representation
            if measurements[0] == 0 and measurements[1] == 0:
                return np.array([0, 0, 0, 0, 0, 0])
            if measurements[0] == 1 and measurements[1] == 0:
                return np.array([1, 0, 0, 0, 0, 0])
            elif measurements[0] == 0 and measurements[1] == 1:
                return np.array([0, 0, 1, 0, 0, 0])
            elif measurements[0] == 1 and measurements[1] == 1:
                return np.array([0, 1, 0, 0, 0, 0])

        classical_functions = {"rep_dec": repetition_decoder}

        measurements = apply_classical_functions(classical_functions, repetition_code_circuit_string_with_cfunc, num_samples=25)
        print(measurements)
