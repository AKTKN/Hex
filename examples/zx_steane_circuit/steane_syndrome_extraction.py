import stim
import pymatching
import numpy as np
from numpy import ndarray
from hex_qec.circuit_generation import get_parity_check_matrices, stabilizer_measurement_circuit
from hex_qec.modularisation import logical_measurement_module, detector_module, measurement_module, modularised_circuit
from hex_qec.modularisation import generate_logical_measurement_module
from plotting_lib import threshold_plot_from_function 
from typing import List, Dict, Tuple, Callable, Any
from pprint import pprint


import stim
import glob
from pathlib import Path
from scipy.io import mmread, mmwrite
from scipy.sparse import csc_matrix, csr_matrix

def generate_steane_pcms():
    x_pcm = np.array([
        []
    ])
    
def steane_state_preparation():
    steane_flag_state_preparation_gen = lambda prob : stim.Circuit(f"""
    H 0 4 6
    #R 1 2 3 5 7
    CX 0 1 4 5 6 3 6 5 4 2 0 3 4 1 3 2
    DEPOLARIZE2({prob}) 0 1 4 5 6 3 6 5 4 2 0 3 4 1 3 2
    CX 1 7 3 7 5 7
    DEPOLARIZE2({prob}) 1 7 3 7 5 7
    M 0 1 2 3 4 5 6
    M 7
    DETECTOR rec[-8] rec[-7] rec[-6] rec[-5]
    DETECTOR rec[-7] rec[-6] rec[-4] rec[-3]
    DETECTOR rec[-6] rec[-5] rec[-3] rec[-2]
    DETECTOR rec[-1]
    OBSERVABLE_INCLUDE(0) rec[-4] rec[-3] rec[-2]
    """)
    steane_flag_state_preparation = steane_flag_state_preparation_gen(0.01)
    dem = steane_flag_state_preparation.detector_error_model()
    measurement_sampler = steane_flag_state_preparation.compile_sampler()
    m2d_converter = steane_flag_state_preparation.compile_m2d_converter()
    num_shots = 10
    measurement_samples = measurement_sampler.sample(shots=num_shots)
    detector_flips, observable_flips = m2d_converter.convert(measurements=measurement_samples, separate_observables=True)

    x_pcm, z_pcm, x_logical, z_logical = get_parity_check_matrices("color_triangular", distance=3)

    print(dem)
    print(detector_flips)
    print(observable_flips)

    # syndromes = (samples[:, 0:7] @ z_pcm.T) % 2
    # logical_value = (samples[:, 0:7] @ z_logical.T) % 2
    # pprint(samples)
    # pprint(syndromes)
    # pprint(logical_value)

if __name__ == "__main__":
    #generate_steane_pcms()
    steane_state_preparation()
