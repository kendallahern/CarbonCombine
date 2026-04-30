from __future__ import annotations

from dataclasses import dataclass

from .config import PowerModelConfig, WorkloadConfig


@dataclass(frozen=True)
class PowerEstimate:
    scale: int
    utilization: float
    per_node_watts: float
    network_overhead_watts_total: float
    it_power_watts: float
    facility_power_watts: float


def clamp_utilization(utilization: float) -> float:
    return max(0.0, min(1.0, utilization))


def estimate_per_node_power(
    utilization: float,
    idle_watts_per_node: float,
    full_watts_per_node: float,
) -> float:
    """
    Linear power model:
        power = idle + util * (full - idle)
    """
    util = clamp_utilization(utilization)
    return idle_watts_per_node + util * (full_watts_per_node - idle_watts_per_node)


def estimate_job_power(
    scale: int,
    utilization: float,
    power_model: PowerModelConfig,
) -> PowerEstimate:
    if scale <= 0:
        return PowerEstimate(
            scale=0,
            utilization=0.0,
            per_node_watts=0.0,
            network_overhead_watts_total=0.0,
            it_power_watts=0.0,
            facility_power_watts=0.0,
        )

    util = clamp_utilization(utilization)

    per_node_watts = estimate_per_node_power(
        utilization=util,
        idle_watts_per_node=power_model.idle_watts_per_node,
        full_watts_per_node=power_model.full_watts_per_node,
    )

    network_overhead_total = scale * power_model.network_overhead_watts_per_node
    it_power_watts = (scale * per_node_watts) + network_overhead_total
    facility_power_watts = it_power_watts * power_model.pue

    return PowerEstimate(
        scale=scale,
        utilization=util,
        per_node_watts=per_node_watts,
        network_overhead_watts_total=network_overhead_total,
        it_power_watts=it_power_watts,
        facility_power_watts=facility_power_watts,
    )


def estimate_workload_power_at_scale(
    workload: WorkloadConfig,
    scale: int,
    power_model: PowerModelConfig,
) -> PowerEstimate:
    if scale == 0:
        return estimate_job_power(scale=0, utilization=0.0, power_model=power_model)

    if scale not in workload.utilization_by_scale:
        raise ValueError(
            f"Missing utilization profile for workload '{workload.name}' at scale {scale}"
        )

    utilization = workload.utilization_by_scale[scale]
    return estimate_job_power(
        scale=scale,
        utilization=utilization,
        power_model=power_model,
    )


def watts_to_kwh(power_watts: float, hours: float) -> float:
    if hours < 0:
        raise ValueError("hours must be >= 0")
    return (power_watts * hours) / 1000.0


def estimate_slot_energy_kwh(
    workload: WorkloadConfig,
    scale: int,
    power_model: PowerModelConfig,
    slot_minutes: int | None = None,
) -> float:
    if scale == 0:
        return 0.0

    effective_slot_minutes = slot_minutes if slot_minutes is not None else workload.slot_minutes
    if effective_slot_minutes <= 0:
        raise ValueError("slot_minutes must be > 0")

    power = estimate_workload_power_at_scale(
        workload=workload,
        scale=scale,
        power_model=power_model,
    )
    slot_hours = effective_slot_minutes / 60.0
    return watts_to_kwh(power.facility_power_watts, slot_hours)


def estimate_slot_carbon_grams(
    workload: WorkloadConfig,
    scale: int,
    power_model: PowerModelConfig,
    carbon_intensity_g_per_kwh: float,
    slot_minutes: int | None = None,
) -> float:
    if carbon_intensity_g_per_kwh < 0:
        raise ValueError("carbon_intensity_g_per_kwh must be >= 0")

    energy_kwh = estimate_slot_energy_kwh(
        workload=workload,
        scale=scale,
        power_model=power_model,
        slot_minutes=slot_minutes,
    )
    return energy_kwh * carbon_intensity_g_per_kwh