from __future__ import annotations

from dataclasses import dataclass, asdict

from .config import PowerModelConfig, WorkloadConfig
from .profiler import WorkloadProfile
from .scheduler import (
    ExecutionSchedule,
    summarize_schedule,
    total_carbon_for_schedule_grams,
    total_energy_for_schedule_kwh,
    total_work_for_schedule,
)

from .price_service import PriceService
from .scheduler import ExecutionSchedule
from .power_sim import estimate_slot_energy_kwh

@dataclass(frozen=True)
class PolicyResult:
    cluster_name: str
    workload_name: str
    policy_name: str
    total_work: float
    total_energy_kwh: float
    total_carbon_grams: float
    active_slots: int
    max_scale_used: int
    completion_slot: int | None


def completion_slot(schedule: ExecutionSchedule) -> int | None:
    """
    Returns the index of the last active slot, or None if the schedule never runs.
    """
    active = [slot.slot_index for slot in schedule.slots if slot.scale > 0]
    if not active:
        return None
    return max(active)


def build_policy_result(
    cluster_name: str,
    workload: WorkloadConfig,
    profile: WorkloadProfile,
    power_model: PowerModelConfig,
    policy_name: str,
    schedule: ExecutionSchedule,
) -> PolicyResult:
    summary = summarize_schedule(
        name=policy_name,
        schedule=schedule,
        profile=profile,
        workload=workload,
        power_model=power_model,
    )

    return PolicyResult(
        cluster_name=cluster_name,
        workload_name=workload.name,
        policy_name=policy_name,
        total_work=float(summary["total_work"]),
        total_energy_kwh=float(summary["total_energy_kwh"]),
        total_carbon_grams=float(summary["total_carbon_grams"]),
        active_slots=int(summary["active_slots"]),
        max_scale_used=int(summary["max_scale_used"]),
        completion_slot=completion_slot(schedule),
    )


def carbon_savings_percent(
    baseline_carbon_grams: float,
    candidate_carbon_grams: float,
) -> float:
    if baseline_carbon_grams <= 0:
        raise ValueError("baseline_carbon_grams must be > 0")

    return 100.0 * (baseline_carbon_grams - candidate_carbon_grams) / baseline_carbon_grams


def energy_overhead_percent(
    baseline_energy_kwh: float,
    candidate_energy_kwh: float,
) -> float:
    if baseline_energy_kwh <= 0:
        raise ValueError("baseline_energy_kwh must be > 0")

    return 100.0 * (candidate_energy_kwh - baseline_energy_kwh) / baseline_energy_kwh


def result_to_dict(result: PolicyResult) -> dict[str, object]:
    return asdict(result)


def compare_to_baseline(
    baseline: PolicyResult,
    candidate: PolicyResult,
) -> dict[str, object]:
    return {
        "cluster_name": candidate.cluster_name,
        "workload_name": candidate.workload_name,
        "policy_name": candidate.policy_name,
        "baseline_policy": baseline.policy_name,
        "candidate_total_carbon_grams": candidate.total_carbon_grams,
        "baseline_total_carbon_grams": baseline.total_carbon_grams,
        "carbon_savings_percent": carbon_savings_percent(
            baseline.total_carbon_grams,
            candidate.total_carbon_grams,
        ),
        "candidate_total_energy_kwh": candidate.total_energy_kwh,
        "baseline_total_energy_kwh": baseline.total_energy_kwh,
        "energy_overhead_percent": energy_overhead_percent(
            baseline.total_energy_kwh,
            candidate.total_energy_kwh,
        ),
        "candidate_completion_slot": candidate.completion_slot,
        "baseline_completion_slot": baseline.completion_slot,
    }


def compare_policy_results(
    baseline: PolicyResult,
    candidates: list[PolicyResult],
) -> list[dict[str, object]]:
    return [compare_to_baseline(baseline, candidate) for candidate in candidates]

def total_day_ahead_cost_for_schedule(
    schedule: ExecutionSchedule,
    workload: WorkloadConfig,
    power_model: PowerModelConfig,
    day_ahead_prices: list[float],
) -> float:
    """
    Compute the planned electricity cost of a schedule using day-ahead prices.

    Assumes:
    - energy is computed per slot in kWh
    - prices are in cost units per kWh
    """
    if len(day_ahead_prices) != len(schedule.slots):
        raise ValueError("day_ahead_prices must have the same length as schedule.slots")

    total = 0.0
    for slot in schedule.slots:
        energy_kwh = estimate_slot_energy_kwh(
            workload=workload,
            scale=slot.scale,
            power_model=power_model,
            slot_minutes=workload.slot_minutes,
        )
        total += energy_kwh * day_ahead_prices[slot.slot_index]

    return total


def total_real_time_cost_for_schedule(
    schedule: ExecutionSchedule,
    workload: WorkloadConfig,
    power_model: PowerModelConfig,
    real_time_prices: list[float],
) -> float:
    """
    Compute the realized electricity cost of a schedule using real-time prices.

    Assumes:
    - energy is computed per slot in kWh
    - prices are in cost units per kWh
    """
    if len(real_time_prices) != len(schedule.slots):
        raise ValueError("real_time_prices must have the same length as schedule.slots")

    total = 0.0
    for slot in schedule.slots:
        energy_kwh = estimate_slot_energy_kwh(
            workload=workload,
            scale=slot.scale,
            power_model=power_model,
            slot_minutes=workload.slot_minutes,
        )
        total += energy_kwh * real_time_prices[slot.slot_index]

    return total


def summarize_schedule_with_prices(
    name: str,
    schedule: ExecutionSchedule,
    profile: WorkloadProfile,
    workload: WorkloadConfig,
    power_model: PowerModelConfig,
    day_ahead_prices: list[float],
    real_time_prices: list[float],
) -> dict[str, float | str]:
    """
    Extended schedule summary including electricity price-based cost metrics.
    """
    base = summarize_schedule(
        name=name,
        schedule=schedule,
        profile=profile,
        workload=workload,
        power_model=power_model,
    )

    base["total_day_ahead_cost"] = total_day_ahead_cost_for_schedule(
        schedule=schedule,
        workload=workload,
        power_model=power_model,
        day_ahead_prices=day_ahead_prices,
    )
    base["total_real_time_cost"] = total_real_time_cost_for_schedule(
        schedule=schedule,
        workload=workload,
        power_model=power_model,
        real_time_prices=real_time_prices,
    )

    return base


def cost_savings_percent(
    baseline_cost: float,
    candidate_cost: float,
) -> float:
    if baseline_cost <= 0:
        raise ValueError("baseline_cost must be > 0")

    return 100.0 * (baseline_cost - candidate_cost) / baseline_cost