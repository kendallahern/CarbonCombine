from __future__ import annotations

from dataclasses import dataclass

from .config import PowerModelConfig, WorkloadConfig
from .power_sim import estimate_slot_energy_kwh
from .profiler import (
    WorkloadProfile,
    marginal_throughput_at_scale,
    throughput_at_scale,
    work_completed_in_slot,
)


@dataclass(frozen=True)
class ScheduleSlot:
    slot_index: int
    scale: int
    carbon_intensity: float


@dataclass
class ExecutionSchedule:
    slots: list[ScheduleSlot]

    def scales(self) -> list[int]:
        return [slot.scale for slot in self.slots]

    def carbon_intensities(self) -> list[float]:
        return [slot.carbon_intensity for slot in self.slots]

    def __len__(self) -> int:
        return len(self.slots)


@dataclass(frozen=True)
class CandidateAssignment:
    slot_index: int
    scale: int
    score: float
    day_ahead_price: float= 0.0

@dataclass(frozen=True)
class PriceTiebreakStats:
    total_iterations: int
    tie_break_used_count: int

def _validate_forecast(forecast: list[float]) -> None:
    if not forecast:
        raise ValueError("Forecast must not be empty")

    for value in forecast:
        if value < 0:
            raise ValueError(f"Carbon intensity must be >= 0, got {value}")


def _empty_schedule(forecast: list[float]) -> ExecutionSchedule:
    return ExecutionSchedule(
        slots=[
            ScheduleSlot(slot_index=i, scale=0, carbon_intensity=forecast[i])
            for i in range(len(forecast))
        ]
    )


def total_work_for_schedule(
    schedule: ExecutionSchedule,
    profile: WorkloadProfile,
    slot_minutes: int,
) -> float:
    total = 0.0
    for slot in schedule.slots:
        total += work_completed_in_slot(profile, slot.scale, slot_minutes)
    return total


def total_energy_for_schedule_kwh(
    schedule: ExecutionSchedule,
    workload: WorkloadConfig,
    power_model: PowerModelConfig,
) -> float:
    total = 0.0
    for slot in schedule.slots:
        total += estimate_slot_energy_kwh(
            workload=workload,
            scale=slot.scale,
            power_model=power_model,
            slot_minutes=workload.slot_minutes,
        )
    return total


def total_carbon_for_schedule_grams(
    schedule: ExecutionSchedule,
    workload: WorkloadConfig,
    power_model: PowerModelConfig,
) -> float:
    total = 0.0
    for slot in schedule.slots:
        energy_kwh = estimate_slot_energy_kwh(
            workload=workload,
            scale=slot.scale,
            power_model=power_model,
            slot_minutes=workload.slot_minutes,
        )
        total += energy_kwh * slot.carbon_intensity
    return total


def build_carbon_agnostic_schedule(
    forecast: list[float],
    profile: WorkloadProfile,
    workload: WorkloadConfig,
) -> ExecutionSchedule:
    """
    Carbon-agnostic:
    run immediately at the minimum replica count until the job finishes.
    """
    _validate_forecast(forecast)

    schedule = _empty_schedule(forecast)
    remaining_work = workload.total_work_units

    for i in range(len(schedule.slots)):
        if remaining_work <= 0:
            break

        scale = workload.min_replicas
        schedule.slots[i] = ScheduleSlot(
            slot_index=i,
            scale=scale,
            carbon_intensity=forecast[i],
        )
        remaining_work -= work_completed_in_slot(profile, scale, workload.slot_minutes)

    return schedule


def build_static_scale_schedule(
    forecast: list[float],
    profile: WorkloadProfile,
    workload: WorkloadConfig,
    static_scale: int,
) -> ExecutionSchedule:
    """
    Static-scale:
    run immediately at one fixed scale until the job finishes.
    """
    _validate_forecast(forecast)

    if not (workload.min_replicas <= static_scale <= workload.max_replicas):
        raise ValueError(
            f"static_scale must be in [{workload.min_replicas}, {workload.max_replicas}]"
        )

    schedule = _empty_schedule(forecast)
    remaining_work = workload.total_work_units

    for i in range(len(schedule.slots)):
        if remaining_work <= 0:
            break

        schedule.slots[i] = ScheduleSlot(
            slot_index=i,
            scale=static_scale,
            carbon_intensity=forecast[i],
        )
        remaining_work -= work_completed_in_slot(profile, static_scale, workload.slot_minutes)

    return schedule


def build_suspend_resume_schedule(
    forecast: list[float],
    profile: WorkloadProfile,
    workload: WorkloadConfig,
) -> ExecutionSchedule:
    """
    Deadline-aware suspend-resume:
    choose the lowest-carbon slots and run at min_replicas.
    """
    _validate_forecast(forecast)

    schedule = _empty_schedule(forecast)
    slot_work = work_completed_in_slot(
        profile,
        workload.min_replicas,
        workload.slot_minutes,
    )

    if slot_work <= 0:
        raise ValueError("Min-replica slot work must be > 0")

    ranked_slots = sorted(range(len(forecast)), key=lambda i: forecast[i])

    remaining_work = workload.total_work_units
    for slot_index in ranked_slots:
        if remaining_work <= 0:
            break

        schedule.slots[slot_index] = ScheduleSlot(
            slot_index=slot_index,
            scale=workload.min_replicas,
            carbon_intensity=forecast[slot_index],
        )
        remaining_work -= slot_work

    return schedule


def _candidate_score(
    slot_index: int,
    scale: int,
    forecast: list[float],
    profile: WorkloadProfile,
    workload: WorkloadConfig,
    power_model: PowerModelConfig,
) -> float:
    """
    CarbonScaler score:
    marginal throughput / (marginal energy * carbon intensity)

    This is the simulation equivalent of:
        marginal work per unit carbon
    """
    carbon_intensity = forecast[slot_index]
    if carbon_intensity <= 0:
        carbon_intensity = 1e-9

    incremental_work = marginal_throughput_at_scale(profile, scale) * (
        workload.slot_minutes / 60.0
    )

    scale_energy_kwh = estimate_slot_energy_kwh(
        workload=workload,
        scale=scale,
        power_model=power_model,
        slot_minutes=workload.slot_minutes,
    )

    if scale == workload.min_replicas:
        prev_energy_kwh = 0.0
    else:
        prev_energy_kwh = estimate_slot_energy_kwh(
            workload=workload,
            scale=scale - 1,
            power_model=power_model,
            slot_minutes=workload.slot_minutes,
        )

    marginal_energy_kwh = scale_energy_kwh - prev_energy_kwh
    if marginal_energy_kwh <= 0:
        raise ValueError(
            f"Non-positive marginal energy at scale {scale} for workload '{workload.name}'"
        )

    marginal_carbon = marginal_energy_kwh * carbon_intensity
    return incremental_work / marginal_carbon


def build_carbonscaler_schedule(
    forecast: list[float],
    profile: WorkloadProfile,
    workload: WorkloadConfig,
    power_model: PowerModelConfig,
) -> ExecutionSchedule:
    """
    Greedy CarbonScaler-style scheduler.

    It allocates incremental scale to the slot/scale combinations with the
    highest marginal work per unit carbon until enough work is scheduled.
    """
    _validate_forecast(forecast)

    schedule = _empty_schedule(forecast)
    assignments: list[CandidateAssignment] = []

    for slot_index in range(len(forecast)):
        for scale in range(workload.min_replicas, workload.max_replicas + 1):
            score = _candidate_score(
                slot_index=slot_index,
                scale=scale,
                forecast=forecast,
                profile=profile,
                workload=workload,
                power_model=power_model,
            )
            assignments.append(
                CandidateAssignment(
                    slot_index=slot_index,
                    scale=scale,
                    score=score,
                )
            )

    assignments.sort(key=lambda x: x.score, reverse=True)

    remaining_work = workload.total_work_units

    while remaining_work > 0:
        picked_index = None

        for idx, candidate in enumerate(assignments):
            current_scale = schedule.slots[candidate.slot_index].scale

            if current_scale == 0 and candidate.scale == workload.min_replicas:
                picked_index = idx
                break

            if current_scale > 0 and candidate.scale == current_scale + 1:
                picked_index = idx
                break

        if picked_index is None:
            raise RuntimeError("No feasible candidate assignment found for CarbonScaler")

        candidate = assignments.pop(picked_index)

        schedule.slots[candidate.slot_index] = ScheduleSlot(
            slot_index=candidate.slot_index,
            scale=candidate.scale,
            carbon_intensity=forecast[candidate.slot_index],
        )

        remaining_work = workload.total_work_units - total_work_for_schedule(
            schedule=schedule,
            profile=profile,
            slot_minutes=workload.slot_minutes,
        )

    return schedule

def build_price_only_schedule(
    day_ahead_prices: list[float],
    profile: WorkloadProfile,
    workload: WorkloadConfig,
    power_model: PowerModelConfig,
    forecast: list[float] | None = None,
) -> ExecutionSchedule:
    """
    Price-only scheduler.

    score =
        work / (energy * normalized_price)

    Higher score is better.

    forecast is optional and only used to populate ScheduleSlot.carbon_intensity
    for downstream simulation.
    """
    horizon_slots = len(day_ahead_prices)

    if forecast is None:
        forecast = [0.0] * horizon_slots

    if len(forecast) != horizon_slots:
        raise ValueError("forecast must have same length as day_ahead_prices")

    schedule = ExecutionSchedule(
        slots=[
            ScheduleSlot(
                slot_index=i,
                scale=0,
                carbon_intensity=forecast[i],
            )
            for i in range(horizon_slots)
        ]
    )

    price_values = [float(x) for x in day_ahead_prices if float(x) > 0]
    if not price_values:
        raise ValueError("day_ahead_prices must contain positive values")

    price_values_sorted = sorted(price_values)
    price_median = price_values_sorted[len(price_values_sorted) // 2]

    candidates = []

    for slot_index in range(horizon_slots):
        day_ahead_price = day_ahead_prices[slot_index]
        normalized_price = day_ahead_price / price_median

        for scale in range(workload.min_replicas, workload.max_replicas + 1):
            work = work_completed_in_slot(profile, scale, workload.slot_minutes)
            if work <= 0:
                continue

            energy = estimate_slot_energy_kwh(
                workload=workload,
                scale=scale,
                power_model=power_model,
                slot_minutes=workload.slot_minutes,
            )
            if energy <= 0:
                continue

            denominator = energy * normalized_price
            if denominator <= 0:
                continue

            score = work / denominator

            candidates.append(
                {
                    "slot_index": slot_index,
                    "scale": scale,
                    "score": score,
                }
            )

    candidates.sort(key=lambda x: x["score"], reverse=True)

    remaining_work = workload.total_work_units
    current_scales = [0] * horizon_slots

    while remaining_work > 0:
        feasible = []

        for c in candidates:
            slot = c["slot_index"]
            scale = c["scale"]

            if current_scales[slot] == 0 and scale == workload.min_replicas:
                feasible.append(c)
            elif current_scales[slot] > 0 and scale == current_scales[slot] + 1:
                feasible.append(c)

        if not feasible:
            break

        chosen = feasible[0]
        remove_index = next(i for i, candidate in enumerate(candidates) if candidate is chosen)
        candidates.pop(remove_index)

        slot = chosen["slot_index"]
        scale = chosen["scale"]

        schedule.slots[slot] = ScheduleSlot(
            slot_index=slot,
            scale=scale,
            carbon_intensity=forecast[slot],
        )
        current_scales[slot] = scale

        incremental_work = (
            work_completed_in_slot(profile, scale, workload.slot_minutes)
            - work_completed_in_slot(profile, scale - 1, workload.slot_minutes)
        )
        remaining_work = max(0.0, remaining_work - incremental_work)

    return schedule

def build_carbonscaler_price_tiebreak_schedule(
    forecast: list[float],
    day_ahead_prices: list[float],
    profile: WorkloadProfile,
    workload: WorkloadConfig,
    power_model: PowerModelConfig,
    tie_threshold_ratio: float = 0.05,
) -> ExecutionSchedule:
    """
    CarbonScaler with day-ahead price tie-breaking.

    Primary objective:
        maximize marginal work per unit carbon

    Secondary rule:
        when two candidate carbon scores are very close, prefer the lower
        day-ahead electricity price.
    """
    _validate_forecast(forecast)

    if len(day_ahead_prices) != len(forecast):
        raise ValueError("day_ahead_prices must have the same length as forecast")

    schedule = _empty_schedule(forecast)
    assignments: list[CandidateAssignment] = []

    for slot_index in range(len(forecast)):
        for scale in range(workload.min_replicas, workload.max_replicas + 1):
            score = _candidate_score(
                slot_index=slot_index,
                scale=scale,
                forecast=forecast,
                profile=profile,
                workload=workload,
                power_model=power_model,
            )
            assignments.append(
                CandidateAssignment(
                    slot_index=slot_index,
                    scale=scale,
                    score=score,
                    day_ahead_price=day_ahead_prices[slot_index],
                )
            )

    def sort_key(candidate: CandidateAssignment) -> tuple[float, float]:
        return (candidate.score, -candidate.day_ahead_price)

    assignments.sort(key=sort_key, reverse=True)

    remaining_work = workload.total_work_units

    while remaining_work > 0:
        feasible: list[CandidateAssignment] = []

        for candidate in assignments:
            current_scale = schedule.slots[candidate.slot_index].scale

            if current_scale == 0 and candidate.scale == workload.min_replicas:
                feasible.append(candidate)
            elif current_scale > 0 and candidate.scale == current_scale + 1:
                feasible.append(candidate)

        if not feasible:
            raise RuntimeError(
                "No feasible candidate assignment found for CarbonScaler price tie-break"
            )

        best = feasible[0]

        close_candidates = []
        for candidate in feasible:
            if best.score <= 0:
                relative_gap = 0.0 if candidate.score == best.score else float("inf")
            else:
                relative_gap = abs(best.score - candidate.score) / best.score

            if relative_gap <= tie_threshold_ratio:
                close_candidates.append(candidate)

        chosen = min(close_candidates, key=lambda c: c.day_ahead_price)

        remove_index = next(i for i, c in enumerate(assignments) if c == chosen)
        chosen = assignments.pop(remove_index)

        schedule.slots[chosen.slot_index] = ScheduleSlot(
            slot_index=chosen.slot_index,
            scale=chosen.scale,
            carbon_intensity=forecast[chosen.slot_index],
        )

        remaining_work = workload.total_work_units - total_work_for_schedule(
            schedule=schedule,
            profile=profile,
            slot_minutes=workload.slot_minutes,
        )

    return schedule

def build_carbonscaler_price_tiebreak_schedule_with_stats(
    forecast: list[float],
    day_ahead_prices: list[float],
    profile: WorkloadProfile,
    workload: WorkloadConfig,
    power_model: PowerModelConfig,
    tie_threshold_ratio: float = 0.05,
) -> tuple[ExecutionSchedule, PriceTiebreakStats]:
    """
    Same as build_carbonscaler_price_tiebreak_schedule, but also returns
    how often the day-ahead price tie-break was used.
    """
    _validate_forecast(forecast)

    if len(day_ahead_prices) != len(forecast):
        raise ValueError("day_ahead_prices must have the same length as forecast")

    schedule = _empty_schedule(forecast)
    assignments: list[CandidateAssignment] = []

    for slot_index in range(len(forecast)):
        for scale in range(workload.min_replicas, workload.max_replicas + 1):
            score = _candidate_score(
                slot_index=slot_index,
                scale=scale,
                forecast=forecast,
                profile=profile,
                workload=workload,
                power_model=power_model,
            )
            assignments.append(
                CandidateAssignment(
                    slot_index=slot_index,
                    scale=scale,
                    score=score,
                    day_ahead_price=day_ahead_prices[slot_index],
                )
            )

    assignments.sort(key=lambda c: c.score, reverse=True)

    remaining_work = workload.total_work_units
    total_iterations = 0
    tie_break_used_count = 0

    while remaining_work > 0:
        total_iterations += 1

        feasible: list[CandidateAssignment] = []

        for candidate in assignments:
            current_scale = schedule.slots[candidate.slot_index].scale

            if current_scale == 0 and candidate.scale == workload.min_replicas:
                feasible.append(candidate)
            elif current_scale > 0 and candidate.scale == current_scale + 1:
                feasible.append(candidate)

        if not feasible:
            raise RuntimeError(
                "No feasible candidate assignment found for CarbonScaler price tie-break"
            )

        best = feasible[0]

        close_candidates = []
        for candidate in feasible:
            if best.score <= 0:
                relative_gap = 0.0 if candidate.score == best.score else float("inf")
            else:
                relative_gap = abs(best.score - candidate.score) / best.score

            if relative_gap <= tie_threshold_ratio:
                close_candidates.append(candidate)

        if len(close_candidates) > 1:
            tie_break_used_count += 1

        chosen = min(close_candidates, key=lambda c: c.day_ahead_price)

        remove_index = next(i for i, c in enumerate(assignments) if c == chosen)
        chosen = assignments.pop(remove_index)

        schedule.slots[chosen.slot_index] = ScheduleSlot(
            slot_index=chosen.slot_index,
            scale=chosen.scale,
            carbon_intensity=forecast[chosen.slot_index],
        )

        remaining_work = workload.total_work_units - total_work_for_schedule(
            schedule=schedule,
            profile=profile,
            slot_minutes=workload.slot_minutes,
        )

    stats = PriceTiebreakStats(
        total_iterations=total_iterations,
        tie_break_used_count=tie_break_used_count,
    )
    return schedule, stats

def build_carbonscaler_budget_schedule(
    forecast: list[float],
    day_ahead_prices: list[float],
    profile: WorkloadProfile,
    workload: WorkloadConfig,
    power_model: PowerModelConfig,
    cost_budget: float,
    cost_penalty_beta: float = 0.01,
    urgency_gamma: float = 0.5,
) -> ExecutionSchedule:
    """
    CarbonScaler-style scheduling with:
    - hard day-ahead cost budget
    - soft cost penalty
    - completion urgency

    score =
        (carbon_efficiency * urgency_multiplier)
        / (1 + beta * slot_cost)

    where:
        carbon_efficiency = work / carbon
        urgency_multiplier = 1 + gamma * (work / required_work_per_slot)
    """
    horizon_slots = len(forecast)

    if len(day_ahead_prices) != horizon_slots:
        raise ValueError("day_ahead_prices must have same length as forecast")

    schedule = ExecutionSchedule(
        slots=[
            ScheduleSlot(
                slot_index=i,
                scale=0,
                carbon_intensity=forecast[i],
            )
            for i in range(horizon_slots)
        ]
    )

    remaining_work = workload.total_work_units
    used_cost = 0.0
    current_scales = [0] * horizon_slots

    while remaining_work > 0:
        remaining_slots = sum(1 for s in current_scales if s < workload.max_replicas)
        if remaining_slots <= 0:
            break

        required_work_per_slot = remaining_work / max(remaining_slots, 1)

        candidates = []

        for slot_index in range(horizon_slots):
            current_scale = current_scales[slot_index]

            # Next feasible scale for this slot:
            # 0 -> min_replicas, 1 -> 2, etc.
            if current_scale == 0:
                next_scale = workload.min_replicas
            else:
                next_scale = current_scale + 1

            if next_scale > workload.max_replicas:
                continue

            carbon_intensity = forecast[slot_index]
            day_ahead_price = day_ahead_prices[slot_index]

            incremental_work = (
                work_completed_in_slot(profile, next_scale, workload.slot_minutes)
                - work_completed_in_slot(profile, current_scale, workload.slot_minutes)
            )

            if incremental_work <= 0:
                continue

            incremental_energy = (
                estimate_slot_energy_kwh(
                    workload=workload,
                    scale=next_scale,
                    power_model=power_model,
                    slot_minutes=workload.slot_minutes,
                )
                - estimate_slot_energy_kwh(
                    workload=workload,
                    scale=current_scale,
                    power_model=power_model,
                    slot_minutes=workload.slot_minutes,
                )
            )

            if incremental_energy <= 0:
                continue

            incremental_cost = incremental_energy * day_ahead_price
            incremental_carbon = incremental_energy * carbon_intensity

            if incremental_carbon <= 0:
                continue

            carbon_efficiency = incremental_work / incremental_carbon
            urgency_multiplier = 1.0 + urgency_gamma * (
                incremental_work / max(required_work_per_slot, 1e-9)
            )

            score = (
                carbon_efficiency * urgency_multiplier
            ) / (1.0 + cost_penalty_beta * incremental_cost)

            candidates.append(
                {
                    "slot_index": slot_index,
                    "scale": next_scale,
                    "incremental_work": incremental_work,
                    "incremental_energy": incremental_energy,
                    "incremental_cost": incremental_cost,
                    "incremental_carbon": incremental_carbon,
                    "score": score,
                }
            )

        if not candidates:
            break

        candidates.sort(key=lambda x: x["score"], reverse=True)

        chosen = None
        for c in candidates:
            if used_cost + c["incremental_cost"] <= cost_budget:
                chosen = c
                break

        if chosen is None:
            break

        slot = chosen["slot_index"]
        scale = chosen["scale"]

        schedule.slots[slot] = ScheduleSlot(
            slot_index=slot,
            scale=scale,
            carbon_intensity=forecast[slot],
        )
        current_scales[slot] = scale
        used_cost += chosen["incremental_cost"]
        remaining_work = max(0.0, remaining_work - chosen["incremental_work"])

    return schedule

# def build_carbonscaler_budget_schedule(
#     forecast: list[float],
#     day_ahead_prices: list[float],
#     profile: WorkloadProfile,
#     workload: WorkloadConfig,
#     power_model: PowerModelConfig,
#     cost_budget: float,
#     cost_penalty_beta: float = 0.01,
# ) -> ExecutionSchedule:
#     """
#     CarbonScaler-style scheduling with a hard day-ahead cost budget and
#     a soft cost penalty in the candidate score.

#     score = (work / carbon) / (1 + beta * slot_cost)

#     Higher score is better.
#     """
#     horizon_slots = len(forecast)

#     if len(day_ahead_prices) != horizon_slots:
#         raise ValueError("day_ahead_prices must have same length as forecast")

#     schedule = ExecutionSchedule(
#         slots=[
#             ScheduleSlot(
#                 slot_index=i,
#                 scale=0,
#                 carbon_intensity=forecast[i],
#             )
#             for i in range(horizon_slots)
#         ]
#     )

#     remaining_work = workload.total_work_units
#     used_cost = 0.0

#     candidates = []

#     for slot_index in range(horizon_slots):
#         carbon_intensity = forecast[slot_index]
#         day_ahead_price = day_ahead_prices[slot_index]

#         for scale in range(workload.min_replicas, workload.max_replicas + 1):
#             work = work_completed_in_slot(profile, scale, workload.slot_minutes)
#             if work <= 0:
#                 continue

#             energy = estimate_slot_energy_kwh(
#                 workload=workload,
#                 scale=scale,
#                 power_model=power_model,
#                 slot_minutes=workload.slot_minutes,
#             )

#             slot_cost = energy * day_ahead_price
#             slot_carbon = energy * carbon_intensity

#             if slot_carbon <= 0:
#                 continue

#             carbon_efficiency = work / slot_carbon
#             score = carbon_efficiency / (1.0 + cost_penalty_beta * slot_cost)

#             candidates.append(
#                 {
#                     "slot_index": slot_index,
#                     "scale": scale,
#                     "work": work,
#                     "energy": energy,
#                     "cost": slot_cost,
#                     "carbon": slot_carbon,
#                     "score": score,
#                 }
#             )

#     candidates.sort(key=lambda x: x["score"], reverse=True)

#     # Track current slot scale so we can build the schedule incrementally
#     current_scales = [0] * horizon_slots

#     while remaining_work > 0:
#         feasible = []

#         for c in candidates:
#             slot = c["slot_index"]
#             scale = c["scale"]

#             # Feasible only if this candidate is the first assignment for the slot
#             # or the next incremental scale-up for that slot.
#             if current_scales[slot] == 0 and scale == workload.min_replicas:
#                 feasible.append(c)
#             elif current_scales[slot] > 0 and scale == current_scales[slot] + 1:
#                 feasible.append(c)

#         if not feasible:
#             break

#         chosen = None
#         for c in feasible:
#             if used_cost + c["cost"] <= cost_budget:
#                 chosen = c
#                 break

#         if chosen is None:
#             break

#         slot = chosen["slot_index"]
#         scale = chosen["scale"]

#         schedule.slots[slot] = ScheduleSlot(
#             slot_index=slot,
#             scale=scale,
#             carbon_intensity=forecast[slot],
#         )
#         current_scales[slot] = scale
#         used_cost += chosen["cost"]
#         remaining_work = max(0.0, remaining_work - chosen["work"])

#         # Remove the chosen candidate so it isn't reused
#         remove_index = next(i for i, candidate in enumerate(candidates) if candidate is chosen)
#         candidates.pop(remove_index)

#     return schedule

def build_carbonscaler_weighted_schedule(
    forecast: list[float],
    day_ahead_prices: list[float],
    profile: WorkloadProfile,
    workload: WorkloadConfig,
    power_model: PowerModelConfig,
    lambda_carbon: float = 0.8,
) -> ExecutionSchedule:
    """
    Option C: weighted carbon + price scheduler.

    score =
        work / (energy * blended_signal)

    blended_signal =
        lambda * normalized_carbon + (1 - lambda) * normalized_price

    Higher score is better.
    """
    if not 0.0 <= lambda_carbon <= 1.0:
        raise ValueError("lambda_carbon must be between 0.0 and 1.0")

    horizon_slots = len(forecast)
    if len(day_ahead_prices) != horizon_slots:
        raise ValueError("day_ahead_prices must have same length as forecast")

    schedule = ExecutionSchedule(
        slots=[
            ScheduleSlot(
                slot_index=i,
                scale=0,
                carbon_intensity=forecast[i],
            )
            for i in range(horizon_slots)
        ]
    )

    # Normalize by medians to keep units comparable
    carbon_values = [float(x) for x in forecast if float(x) > 0]
    price_values = [float(x) for x in day_ahead_prices if float(x) > 0]

    if not carbon_values or not price_values:
        raise ValueError("forecast and day_ahead_prices must contain positive values")

    carbon_values_sorted = sorted(carbon_values)
    price_values_sorted = sorted(price_values)

    carbon_median = carbon_values_sorted[len(carbon_values_sorted) // 2]
    price_median = price_values_sorted[len(price_values_sorted) // 2]

    candidates = []

    for slot_index in range(horizon_slots):
        carbon_intensity = forecast[slot_index]
        day_ahead_price = day_ahead_prices[slot_index]

        normalized_carbon = carbon_intensity / carbon_median
        normalized_price = day_ahead_price / price_median

        blended_signal = (
            lambda_carbon * normalized_carbon
            + (1.0 - lambda_carbon) * normalized_price
        )

        for scale in range(workload.min_replicas, workload.max_replicas + 1):
            work = work_completed_in_slot(profile, scale, workload.slot_minutes)
            if work <= 0:
                continue

            energy = estimate_slot_energy_kwh(
                workload=workload,
                scale=scale,
                power_model=power_model,
                slot_minutes=workload.slot_minutes,
            )
            if energy <= 0:
                continue

            denominator = energy * blended_signal
            if denominator <= 0:
                continue

            score = work / denominator

            candidates.append(
                {
                    "slot_index": slot_index,
                    "scale": scale,
                    "score": score,
                }
            )

    candidates.sort(key=lambda x: x["score"], reverse=True)

    remaining_work = workload.total_work_units
    current_scales = [0] * horizon_slots

    while remaining_work > 0:
        feasible = []

        for c in candidates:
            slot = c["slot_index"]
            scale = c["scale"]

            if current_scales[slot] == 0 and scale == workload.min_replicas:
                feasible.append(c)
            elif current_scales[slot] > 0 and scale == current_scales[slot] + 1:
                feasible.append(c)

        if not feasible:
            break

        chosen = feasible[0]
        remove_index = next(i for i, candidate in enumerate(candidates) if candidate is chosen)
        candidates.pop(remove_index)

        slot = chosen["slot_index"]
        scale = chosen["scale"]

        schedule.slots[slot] = ScheduleSlot(
            slot_index=slot,
            scale=scale,
            carbon_intensity=forecast[slot],
        )
        current_scales[slot] = scale

        incremental_work = (
            work_completed_in_slot(profile, scale, workload.slot_minutes)
            - work_completed_in_slot(profile, scale - 1, workload.slot_minutes)
        )
        remaining_work = max(0.0, remaining_work - incremental_work)

    return schedule

def summarize_schedule(
    name: str,
    schedule: ExecutionSchedule,
    profile: WorkloadProfile,
    workload: WorkloadConfig,
    power_model: PowerModelConfig,
) -> dict[str, float | str]:
    return {
        "policy": name,
        "total_work": total_work_for_schedule(schedule, profile, workload.slot_minutes),
        "total_energy_kwh": total_energy_for_schedule_kwh(schedule, workload, power_model),
        "total_carbon_grams": total_carbon_for_schedule_grams(schedule, workload, power_model),
        "active_slots": float(sum(1 for slot in schedule.slots if slot.scale > 0)),
        "max_scale_used": float(max((slot.scale for slot in schedule.slots), default=0)),
    }