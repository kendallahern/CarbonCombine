from __future__ import annotations

from dataclasses import dataclass

from .config import WorkloadConfig


@dataclass(frozen=True)
class ScaleProfilePoint:
    scale: int
    throughput: float
    utilization: float


@dataclass(frozen=True)
class MarginalCapacityPoint:
    scale: int
    throughput: float
    marginal_throughput: float
    utilization: float


@dataclass(frozen=True)
class WorkloadProfile:
    workload_name: str
    min_replicas: int
    max_replicas: int
    scale_points: dict[int, ScaleProfilePoint]
    marginal_points: dict[int, MarginalCapacityPoint]


def build_workload_profile(workload: WorkloadConfig) -> WorkloadProfile:
    scale_points: dict[int, ScaleProfilePoint] = {}
    marginal_points: dict[int, MarginalCapacityPoint] = {}

    prev_throughput = 0.0

    for scale in range(workload.min_replicas, workload.max_replicas + 1):
        if scale not in workload.throughput_by_scale:
            raise ValueError(
                f"Missing throughput profile for workload '{workload.name}' at scale {scale}"
            )

        if scale not in workload.utilization_by_scale:
            raise ValueError(
                f"Missing utilization profile for workload '{workload.name}' at scale {scale}"
            )

        throughput = float(workload.throughput_by_scale[scale])
        utilization = float(workload.utilization_by_scale[scale])

        if throughput <= 0:
            raise ValueError(
                f"Throughput must be > 0 for workload '{workload.name}' at scale {scale}"
            )

        if not (0.0 <= utilization <= 1.0):
            raise ValueError(
                f"Utilization must be in [0, 1] for workload '{workload.name}' at scale {scale}"
            )

        marginal_throughput = throughput - prev_throughput
        if marginal_throughput <= 0:
            raise ValueError(
                f"Marginal throughput must be > 0 for workload '{workload.name}' at scale {scale}. "
                f"Got throughput {throughput} after previous throughput {prev_throughput}."
            )

        scale_points[scale] = ScaleProfilePoint(
            scale=scale,
            throughput=throughput,
            utilization=utilization,
        )

        marginal_points[scale] = MarginalCapacityPoint(
            scale=scale,
            throughput=throughput,
            marginal_throughput=marginal_throughput,
            utilization=utilization,
        )

        prev_throughput = throughput

    return WorkloadProfile(
        workload_name=workload.name,
        min_replicas=workload.min_replicas,
        max_replicas=workload.max_replicas,
        scale_points=scale_points,
        marginal_points=marginal_points,
    )


def throughput_at_scale(profile: WorkloadProfile, scale: int) -> float:
    if scale == 0:
        return 0.0

    if scale not in profile.scale_points:
        raise ValueError(
            f"Scale {scale} not found in workload profile '{profile.workload_name}'"
        )

    return profile.scale_points[scale].throughput


def marginal_throughput_at_scale(profile: WorkloadProfile, scale: int) -> float:
    if scale not in profile.marginal_points:
        raise ValueError(
            f"Scale {scale} not found in marginal profile '{profile.workload_name}'"
        )

    return profile.marginal_points[scale].marginal_throughput


def utilization_at_scale(profile: WorkloadProfile, scale: int) -> float:
    if scale == 0:
        return 0.0

    if scale not in profile.scale_points:
        raise ValueError(
            f"Scale {scale} not found in workload profile '{profile.workload_name}'"
        )

    return profile.scale_points[scale].utilization


def work_completed_in_slot(profile: WorkloadProfile, scale: int, slot_minutes: int) -> float:
    """
    Returns the amount of work completed in one slot.

    Assumption:
    - throughput values are in work-units per hour
    - slot_minutes converts that hourly rate into per-slot work
    """
    if scale == 0:
        return 0.0

    if slot_minutes <= 0:
        raise ValueError("slot_minutes must be > 0")

    throughput = throughput_at_scale(profile, scale)
    slot_hours = slot_minutes / 60.0
    return throughput * slot_hours


def minimum_slots_to_finish(
    profile: WorkloadProfile,
    total_work_units: float,
    scale: int,
    slot_minutes: int,
) -> int:
    if total_work_units <= 0:
        return 0

    work_per_slot = work_completed_in_slot(profile, scale, slot_minutes)
    if work_per_slot <= 0:
        raise ValueError("work_per_slot must be > 0")

    remaining = total_work_units
    slots = 0
    while remaining > 0:
        remaining -= work_per_slot
        slots += 1

    return slots