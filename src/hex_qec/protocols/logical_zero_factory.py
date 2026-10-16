"""A static logical-zero factory reusing two blocks over fixed stages.

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
    FACTORY_FRAME_CONVENTION, _positive_integer,
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
        if len(self.blocks) != 2 or not self.stages:
            raise ValueError("factory requires exactly two blocks and at least one stage")
        if tuple(stage.index for stage in self.stages) != tuple(range(len(self.stages))):
            raise ValueError("factory stages must be chronological and contiguous")
        if self.metadata["T_tel"] != len(self.stages):
            raise ValueError("stage count disagrees with factory metadata")
        plans = {plan.region.measurements.start: plan for plan in self.preparation_frames}
        previous_stop = 0
        previous_measurement = 0
        for index, stage in enumerate(self.stages):
            target, control = self.blocks[index % 2], self.blocks[(index + 1) % 2]
            if (stage.consumed_block, stage.surviving_block) != (target.name, control.name):
                raise ValueError("stage roles must alternate between the two supports")
            if len(stage.preparations) != (2 if index == 0 else 1):
                raise ValueError("stage must contain only its initial/refresh preparations")
            for region in stage.preparations:
                plan = plans.get(region.measurements.start)
                if plan is None or plan.region != region:
                    raise ValueError("stage preparation has no matching local frame plan")
                if (region.instructions.start < previous_stop
                        or region.measurements.start < previous_measurement
                        or region.instructions.stop > stage.coupling.instructions.start
                        or region.measurements.stop > stage.measurement.measurements.start):
                    raise ValueError("preparation violates the causal stage boundary")
            if (stage.coupling.instructions.stop > stage.measurement.instructions.start
                    or stage.measurement.instructions.stop > self.oracle.instructions.start):
                raise ValueError("measurement violates the causal stage boundary")
            if any(not stage.measurement.measurements.start <= record < stage.measurement.measurements.stop
                   for record in stage.raw_logical_outcome.records):
                raise ValueError("logical byproduct must use only its own readout records")
            previous_stop = stage.measurement.instructions.stop
            previous_measurement = stage.measurement.measurements.stop
        if tuple(record.index for record in self.ledger.records) != tuple(range(self.circuit.num_measurements)):
            raise ValueError("measurement ledger must cover the complete record in order")
        if self.oracle_record_indices != tuple(range(oracle_start, self.circuit.num_measurements)):
            raise ValueError("oracle must be the sole terminal evaluation region")
        suffix = self.circuit[self.oracle.instructions.start:]
        survivor = next(block for block in self.blocks if block.name == self.stages[-1].surviving_block)
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
    """Unroll T_tel >= 1 stages without allocating additional supports.

    The default T_tel=1 preserves the H1 physical circuit and record layout.
    """

    def __init__(self, adapter: FactoryCodeAdapter, preparation: PreparationPlan,
                 physical_error: float = 0.001, *, T_tel: int = 1):
        if (isinstance(physical_error, bool) or not isinstance(physical_error, Real)
                or not math.isfinite(physical_error) or not 0 <= physical_error <= 0.5):
            raise ValueError("physical_error must be finite and in [0, 0.5]")
        self.adapter, self.preparation = adapter, preparation
        self.physical_error = float(physical_error)
        _positive_integer(T_tel, "T_tel")
        self.T_tel = int(T_tel)

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
        frames: list[PreparationFramePlan] = []
        templates: dict[tuple[str, str, int], PreparationFramePlan] = {}
        signs: dict[tuple[str, str, int], RecordParity] = {}

        def prepare(block: BlockSupport, basis: str, rounds: int, stage_index: int) -> CircuitRegion:
            key = (block.name, basis, rounds)
            template = templates.get(key)
            module = (template.module if template is not None
                      else self.adapter.prepare(block, basis, rounds, p))
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
                            f"prepare_{block.name}", stage_index, local_record // width + 1, check_basis,
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
            name = f"prepare_{block.name}" if stage_index == 0 else f"prepare_{block.name}_t{stage_index:03d}"
            region = CircuitRegion(name, IndexRange(start_instruction, len(circuit)),
                                   IndexRange(start_record, circuit.num_measurements))
            last = circuit.num_measurements - width
            for basis, indices in (("X", range(last, last + len(code.x_checks))),
                                   ("Z", range(last + len(code.x_checks), circuit.num_measurements))):
                for index, record in enumerate(indices):
                    signs[block.name, basis, index] = RecordParity((record,))
            if template is None:
                template = PreparationFramePlan(module, block, region)
                templates[key] = template
                frames.append(template)
            else:
                frames.append(template.bind(region))
            return region

        def check_flows(stop: int) -> tuple[SignedCheckFlow, ...]:
            output = []
            for block in blocks:
                for basis, checks in (("X", code.x_checks), ("Z", code.z_checks)):
                    for index, support in enumerate(checks):
                        parity = signs[block.name, basis, index]
                        output.append(SignedCheckFlow(block.name, basis, index,
                                      tuple(block.data_qubits[q] for q in support), parity, stop))
            return tuple(output)

        zero_region = prepare(a, "Z", plan.r_0, 0)
        stages = []
        memory, fresh = a, b
        for stage_index in range(self.T_tel):
            plus_region = prepare(fresh, "X", plan.r_plus, stage_index)
            regions = (zero_region, plus_region) if stage_index == 0 else (plus_region,)
            inputs = check_flows(len(circuit))
            gate_start = len(circuit)
            circuit += generate_transversal_cnot_module(p, list(fresh.data_qubits), list(memory.data_qubits)).circuit
            coupling = CircuitRegion(f"cnot_{fresh.name}_to_{memory.name}", IndexRange(gate_start, len(circuit)),
                                     IndexRange(circuit.num_measurements, circuit.num_measurements))
            for index in range(len(code.x_checks)):
                signs[fresh.name, "X", index] ^= signs[memory.name, "X", index]
            for index in range(len(code.z_checks)):
                signs[memory.name, "Z", index] ^= signs[fresh.name, "Z", index]
            outputs = check_flows(len(circuit))

            start_instruction, start_record = len(circuit), circuit.num_measurements
            qubit_measurement(circuit, "z", {"data_qubits": list(memory.data_qubits)}, p)
            for position, qubit in enumerate(memory.data_qubits):
                records.append(MeasurementRecord(start_record + position, qubit, "Z", memory.name,
                                                  "teleport_z", stage_index))
            terminal = []
            for index, support in enumerate(code.z_checks):
                parity = RecordParity(tuple(start_record + q for q in support)) ^ signs[memory.name, "Z", index]
                circuit.append("DETECTOR", [stim.target_rec(record - circuit.num_measurements) for record in parity.records])
                flow = SignedCheckFlow(memory.name, "Z", index, (), parity, len(circuit), len(detectors))
                detectors.append(flow)
                terminal.append(flow)
            measurement = CircuitRegion("teleport_z", IndexRange(start_instruction, len(circuit)),
                                        IndexRange(start_record, circuit.num_measurements))
            stages.append(TeleportationStage(stage_index, memory.name, fresh.name, regions, coupling, measurement,
                          inputs, outputs, tuple(terminal),
                          RecordParity(tuple(start_record + q for q in code.logical_z))))
            memory, fresh = fresh, memory

        oracle_start_instruction, oracle_start_record = len(circuit), circuit.num_measurements
        circuit.append("M", list(memory.data_qubits))
        for position, qubit in enumerate(memory.data_qubits):
            records.append(MeasurementRecord(oracle_start_record + position, qubit, "Z", memory.name, "oracle_z", self.T_tel - 1,
                                              evaluation_only=True))
        oracle = CircuitRegion("oracle_z", IndexRange(oracle_start_instruction, len(circuit)),
                               IndexRange(oracle_start_record, circuit.num_measurements))
        metadata = MappingProxyType({
            "protocol": "logical_zero_factory", "T_tel": self.T_tel, "noise": "hex_uniform",
            "physical_error": p, "r_0": plan.r_0, "r_plus": plan.r_plus,
            "cnot_direction": "fresh_plus_to_memory", "live_blocks": 2,
            "frame_convention": FACTORY_FRAME_CONVENTION,
            "oracle": "terminal_ideal_Z_evaluation_only",
            "terminal_label_convention": "codecapacity_recovery_then_logical_Z",
            "preparation_prior": "hex_legacy_matchable",
            "circuit_sha256": hashlib.sha256(str(circuit).encode()).hexdigest(),
        })
        bundle = FactoryCircuitBundle(circuit, code, plan, blocks, MeasurementLedger(tuple(records)),
                                       tuple(stages), tuple(frames), tuple(detectors), oracle, metadata)
        bundle.validate()
        return bundle
