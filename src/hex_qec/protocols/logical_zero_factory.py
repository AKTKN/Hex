"""H1: a static two-block, single-stage logical-zero factory circuit.

This builder contains no sampling, online decoding, confidence, or retry loop.
The sole ideal output readout is an explicitly separate evaluation region.
"""

from dataclasses import dataclass
import hashlib
import math
from numbers import Real
from types import MappingProxyType
from typing import Mapping

import stim

from hex_qec.modularisation.factory import (
    BlockSupport, CircuitRegion, CodeSpec, FactoryCodeAdapter, IndexRange,
    MeasurementLedger, MeasurementRecord, PreparationFramePlan, PreparationPlan,
    RecordParity, SignedCheckFlow, TeleportationStage,
)
from hex_qec.modularisation.module_generation import generate_transversal_cnot_module
from hex_qec.circuit_generation.circuit_generation import qubit_measurement


@dataclass(frozen=True)
class FactoryCircuitBundle:
    circuit: stim.Circuit
    code: CodeSpec
    preparation: PreparationPlan
    blocks: tuple[BlockSupport, BlockSupport]
    ledger: MeasurementLedger
    stages: tuple[TeleportationStage, ...]
    preparation_frames: tuple[PreparationFramePlan, ...]
    detector_flows: tuple[SignedCheckFlow, ...]
    oracle: CircuitRegion
    metadata: Mapping[str, object]

    @property
    def oracle_record_indices(self) -> tuple[int, ...]:
        return self.ledger.oracle_indices

    @property
    def operational_circuit(self) -> stim.Circuit:
        """Only physically accessible measurements/detectors; excludes the oracle."""
        return self.circuit[:self.oracle.instructions.start]

    def validate(self) -> None:
        """Check signed flows on their own prefixes and strict operational DEM.

        Stim ignores stochastic noise when checking signed flows. Strict DEM
        extraction checks deterministic detector structure, not fault tolerance.
        No oracle bit, detector, or observable enters the operational model.
        """
        oracle_start = self.oracle.measurements.start
        if len(self.blocks) != 2 or len(self.stages) != 1:
            raise ValueError("H1 requires exactly two blocks and one stage")
        if tuple(record.index for record in self.ledger.records) != tuple(range(self.circuit.num_measurements)):
            raise ValueError("measurement ledger must cover the complete record in order")
        if self.oracle_record_indices != tuple(range(oracle_start, self.circuit.num_measurements)):
            raise ValueError("oracle must be the sole terminal evaluation region")
        suffix = self.circuit[self.oracle.instructions.start:]
        survivor = next(block for block in self.blocks if block.name == self.stages[0].surviving_block)
        if (len(suffix) != 1 or suffix[0].name != "M" or suffix[0].gate_args_copy()
                or tuple(target.value for target in suffix[0].targets_copy()) != survivor.data_qubits):
            raise ValueError("oracle must be a noiseless terminal Z readout of the survivor")
        if self.operational_circuit.num_measurements != oracle_start or self.circuit.num_observables:
            raise ValueError("oracle and operational record boundaries disagree")
        if any(record >= oracle_start for flow in self.detector_flows for record in flow.parity.records):
            raise ValueError("operational detector refers to the evaluation oracle")
        flows = list(self.detector_flows)
        for stage in self.stages:
            flows.extend(stage.input_checks + stage.output_checks)
            if any(record >= stage.measurement.measurements.stop for record in stage.raw_logical_outcome.records):
                raise ValueError("logical byproduct refers to a future measurement")
        by_prefix: dict[int, list[stim.Flow]] = {}
        for flow in flows:
            prefix_measurements = self.circuit[:flow.instruction_stop].num_measurements
            if any(record >= prefix_measurements for record in flow.parity.records):
                raise ValueError("signed flow refers to a future measurement")
            by_prefix.setdefault(flow.instruction_stop, []).append(flow.as_stim_flow(self.circuit.num_qubits))
        for stop, group in by_prefix.items():
            if not self.circuit[:stop].has_all_flows(group, unsigned=False):
                raise ValueError(f"invalid signed CSS check flow at instruction {stop}")
        self.operational_circuit.detector_error_model(
            allow_gauge_detectors=False, approximate_disjoint_errors=False,
        )


class FactoryCircuitBuilder:
    """Construct exactly T_tel=1 using an explicit CSS code-family adapter."""

    def __init__(self, adapter: FactoryCodeAdapter, preparation: PreparationPlan,
                 physical_error: float = 0.001):
        if (isinstance(physical_error, bool) or not isinstance(physical_error, Real)
                or not math.isfinite(physical_error) or not 0 <= physical_error <= 0.5):
            raise ValueError("physical_error must be finite and in [0, 0.5]")
        self.adapter, self.preparation = adapter, preparation
        self.physical_error = float(physical_error)

    def build(self) -> FactoryCircuitBundle:
        code, plan, p = self.adapter.code, self.preparation, self.physical_error
        blocks = self.adapter.blocks()
        a, b = blocks
        if a.name == b.name or set(a.qubits) & set(b.qubits):
            raise ValueError("factory blocks must have disjoint supports")
        if not code.x_checks or not code.z_checks:
            raise ValueError("factory adapter must supply both CSS check families")
        for block in blocks:
            if (len(block.data_qubits), len(block.x_ancillas), len(block.z_ancillas)) != (
                    code.num_data_qubits, len(code.x_checks), len(code.z_checks)):
                raise ValueError("adapter block dimensions disagree with CodeSpec")
        circuit = stim.Circuit()
        records: list[MeasurementRecord] = []
        detectors: list[SignedCheckFlow] = []
        regions: list[CircuitRegion] = []
        modules = []
        last_checks: dict[tuple[str, str], tuple[int, ...]] = {}

        for block, basis, rounds in ((a, "Z", plan.r_0), (b, "X", plan.r_plus)):
            module = self.adapter.prepare(block, basis, rounds, p)
            modules.append(module)
            start_instruction, start_record = len(circuit), circuit.num_measurements
            detector_metadata = [(basis, check) for check in range(len(code.x_checks if basis == "X" else code.z_checks))]
            for _ in range(1, rounds):
                detector_metadata.extend(("X", check) for check in range(len(code.x_checks)))
                detector_metadata.extend(("Z", check) for check in range(len(code.z_checks)))
            local_record, local_detector = 0, 0
            width = len(code.x_checks) + len(code.z_checks)
            for instruction in module.circuit:
                circuit.append(instruction)
                if instruction.name == "MR":
                    for target in instruction.targets_copy():
                        check_basis = "X" if target.value in block.x_ancillas else "Z"
                        records.append(MeasurementRecord(
                            start_record + local_record, target.value, "Z", block.name,
                            f"prepare_{block.name}", 0, local_record // width + 1, check_basis,
                        ))
                        local_record += 1
                elif instruction.name == "DETECTOR":
                    check_basis, check = detector_metadata[local_detector]
                    parity = RecordParity(tuple(circuit.num_measurements + target.value
                                                for target in instruction.targets_copy()))
                    detectors.append(SignedCheckFlow(block.name, check_basis, check, (), parity,
                                                     len(circuit), len(detectors)))
                    local_detector += 1
            if local_record != rounds * width or local_detector != len(detector_metadata):
                raise ValueError("adapter preparation record layout differs from X/Z SE rounds")
            region = CircuitRegion(f"prepare_{block.name}", IndexRange(start_instruction, len(circuit)),
                                   IndexRange(start_record, circuit.num_measurements))
            regions.append(region)
            last = circuit.num_measurements - width
            last_checks[block.name, "X"] = tuple(range(last, last + len(code.x_checks)))
            last_checks[block.name, "Z"] = tuple(range(last + len(code.x_checks), circuit.num_measurements))

        def check_flows(stop: int, propagated: bool) -> tuple[SignedCheckFlow, ...]:
            output = []
            for block in blocks:
                for basis, checks in (("X", code.x_checks), ("Z", code.z_checks)):
                    for index, support in enumerate(checks):
                        parity = RecordParity((last_checks[block.name, basis][index],))
                        if propagated and (block == a and basis == "Z" or block == b and basis == "X"):
                            other = b if block == a else a
                            parity ^= RecordParity((last_checks[other.name, basis][index],))
                        output.append(SignedCheckFlow(block.name, basis, index,
                                      tuple(block.data_qubits[q] for q in support), parity, stop))
            return tuple(output)

        inputs = check_flows(len(circuit), False)
        gate_start = len(circuit)
        circuit += generate_transversal_cnot_module(p, list(b.data_qubits), list(a.data_qubits)).circuit
        coupling = CircuitRegion("cnot_B_to_A", IndexRange(gate_start, len(circuit)),
                                 IndexRange(circuit.num_measurements, circuit.num_measurements))
        outputs = check_flows(len(circuit), True)

        start_instruction, start_record = len(circuit), circuit.num_measurements
        qubit_measurement(circuit, "z", {"data_qubits": list(a.data_qubits)}, p)
        for position, qubit in enumerate(a.data_qubits):
            records.append(MeasurementRecord(start_record + position, qubit, "Z", a.name, "teleport_z", 0))
        terminal = []
        for index, support in enumerate(code.z_checks):
            sign = next(flow.parity for flow in outputs if flow.block == a.name and flow.basis == "Z" and flow.check_index == index)
            parity = RecordParity(tuple(start_record + q for q in support)) ^ sign
            circuit.append("DETECTOR", [stim.target_rec(record - circuit.num_measurements) for record in parity.records])
            flow = SignedCheckFlow(a.name, "Z", index, (), parity, len(circuit), len(detectors))
            detectors.append(flow)
            terminal.append(flow)
        measurement = CircuitRegion("teleport_z", IndexRange(start_instruction, len(circuit)),
                                    IndexRange(start_record, circuit.num_measurements))
        stage = TeleportationStage(0, a.name, b.name, tuple(regions), coupling, measurement,
                                   inputs, outputs, tuple(terminal),
                                   RecordParity(tuple(start_record + q for q in code.logical_z)))

        oracle_start_instruction, oracle_start_record = len(circuit), circuit.num_measurements
        circuit.append("M", list(b.data_qubits))
        for position, qubit in enumerate(b.data_qubits):
            records.append(MeasurementRecord(oracle_start_record + position, qubit, "Z", b.name, "oracle_z", 0,
                                              evaluation_only=True))
        oracle = CircuitRegion("oracle_z", IndexRange(oracle_start_instruction, len(circuit)),
                               IndexRange(oracle_start_record, circuit.num_measurements))
        frames = tuple(PreparationFramePlan(module, block, region)
                       for module, block, region in zip(modules, blocks, regions))
        metadata = MappingProxyType({
            "protocol": "logical_zero_factory", "T_tel": 1, "noise": "hex_uniform",
            "physical_error": p, "r_0": plan.r_0, "r_plus": plan.r_plus,
            "cnot_direction": "B_plus_to_A_zero", "live_blocks": 2,
            "frame_convention": "software_pauli_xz_at_preparation_boundary",
            "oracle": "terminal_ideal_Z_evaluation_only",
            "terminal_label_convention": "future_codecapacity_recovery_then_logical_Z",
            "preparation_prior": "hex_legacy_matchable",
            "circuit_sha256": hashlib.sha256(str(circuit).encode()).hexdigest(),
        })
        bundle = FactoryCircuitBundle(circuit, code, plan, blocks, MeasurementLedger(tuple(records)),
                                       (stage,), frames, tuple(detectors), oracle, metadata)
        bundle.validate()
        return bundle
