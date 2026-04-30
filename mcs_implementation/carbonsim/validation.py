from __future__ import annotations

from .controller import ControllerRunResult
from .config import WorkloadConfig
from .profiler import work_completed_in_slot, WorkloadProfile


def assert_controller_result_valid(
    result: ControllerRunResult,
    workload: WorkloadConfig,
    atol: float = 1e-6,
) -> None:
    target = float(workload.total_work_units)
    completed_work = float(result.total_work)

    assert completed_work >= 0.0, f"completed work is negative: {completed_work}"
    assert result.active_slots >= 0, f"active_slots is negative: {result.active_slots}"
    assert result.max_scale_used >= 0, f"max_scale_used is negative: {result.max_scale_used}"

    if result.completed:
        assert completed_work + atol >= target, (
            f"completed=True but total_work={completed_work} < target={target}"
        )
        assert result.completion_slot is not None, (
            "completed=True but completion_slot is None"
        )
    else:
        assert completed_work < target - atol, (
            f"completed=False but total_work={completed_work} >= target={target}"
        )


def assert_schedule_and_result_consistent(
    result: ControllerRunResult,
    workload: WorkloadConfig,
    profile: WorkloadProfile,
    atol: float = 1e-6,
) -> None:
    schedule_work = 0.0
    for slot in result.schedule.slots:
        schedule_work += work_completed_in_slot(profile, slot.scale, workload.slot_minutes)

    assert schedule_work + atol >= result.total_work, (
        f"schedule work {schedule_work} is less than reported total_work {result.total_work}"
    )

    if result.completed:
        assert schedule_work + atol >= workload.total_work_units, (
            f"completed result but schedule_work={schedule_work} < target={workload.total_work_units}"
        )