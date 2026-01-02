#!/usr/bin/env python3
import stim

if __name__ == "__main__":
    flip_sim = stim.FlipSimulator(batch_size=1, disable_stabilizer_randomization=True)
    circuit = stim.Circuit("""
    RX 0

    R 1
    CX 1 0
    MX 1
    R 1

    Z_ERROR(1) 0
    
    R 1
    CX 1 0
    MRX 1

    R 1
    CX 1 0
    MRX 1

    R 1
    CX 1 0
    MRX 1

    R 1
    CX 1 0
    MRX 1

    MX 0
    """)
    print(circuit.diagram())

    flip_sim.do(circuit)
    print(flip_sim.get_measurement_flips().T)
    flip_sim.clear()
