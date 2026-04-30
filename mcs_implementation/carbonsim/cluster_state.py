from __future__ import annotations

from dataclasses import dataclass, field

from .config import ClusterConfig, PowerModelConfig, WorkloadConfig
from .power_sim import estimate_slot_carbon_grams, estimate_slot_energy_kwh
from .profiler import WorkloadProfile, work_completed_in_slot


@dataclass
class SlotExecutionRecord:
    slot_index: int
    scale: int
    carbon_intensity: float
    work_completed: float
    energy_kwh: float
    carbon_grams: float


@dataclass
class SimulationState:
    cluster: ClusterConfig
    power_model: PowerModelConfig
    workload: WorkloadConfig
    profile: WorkloadProfile

    current_slot: int = 0
    completed_work_units: float = 0.0
    total_energy_kwh: float = 0.0
    total_carbon_grams: float = 0.0
    history: list[SlotExecutionRecord] = field(default_factory=list)

    @property
    def remaining_work_units(self) -> float:
        remaining = self.workload.total_work_units - self.completed_work_units
        return max(0.0, remaining)

    @property
    def is_complete(self) -> bool:
        return self.remaining_work_units <= 1e-9

    def run_slot(self, scale: int, carbon_intensity: float) -> SlotExecutionRecord:
        """
        Simulate running exactly one slot on this cluster.
        """
        if scale < 0:
            raise ValueError("scale must be >= 0")
        if carbon_intensity < 0:
            raise ValueError("carbon_intensity must be >= 0")

        if self.is_complete:
            record = SlotExecutionRecord(
                slot_index=self.current_slot,
                scale=0,
                carbon_intensity=carbon_intensity,
                work_completed=0.0,
                energy_kwh=0.0,
                carbon_grams=0.0,
            )
            self.history.append(record)
            self.current_slot += 1
            return record

        if scale == 0:
            record = SlotExecutionRecord(
                slot_index=self.current_slot,
                scale=0,
                carbon_intensity=carbon_intensity,
                work_completed=0.0,
                energy_kwh=0.0,
                carbon_grams=0.0,
            )
            self.history.append(record)
            self.current_slot += 1
            return record

        slot_work = work_completed_in_slot(
            profile=self.profile,
            scale=scale,
            slot_minutes=self.workload.slot_minutes,
        )

        actual_work = min(slot_work, self.remaining_work_units)

        full_slot_energy = estimate_slot_energy_kwh(
            workload=self.workload,
            scale=scale,
            power_model=self.power_model,
            slot_minutes=self.workload.slot_minutes,
        )
        full_slot_carbon = estimate_slot_carbon_grams(
            workload=self.workload,
            scale=scale,
            power_model=self.power_model,
            carbon_intensity_g_per_kwh=carbon_intensity,
            slot_minutes=self.workload.slot_minutes,
        )

        utilization_fraction = actual_work / slot_work if slot_work > 0 else 0.0
        actual_energy = full_slot_energy * utilization_fraction
        actual_carbon = full_slot_carbon * utilization_fraction

        self.completed_work_units += actual_work
        self.total_energy_kwh += actual_energy
        self.total_carbon_grams += actual_carbon

        record = SlotExecutionRecord(
            slot_index=self.current_slot,
            scale=scale,
            carbon_intensity=carbon_intensity,
            work_completed=actual_work,
            energy_kwh=actual_energy,
            carbon_grams=actual_carbon,
        )
        self.history.append(record)
        self.current_slot += 1
        return record