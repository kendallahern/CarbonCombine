from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .carbon_service import CarbonService
from .cluster_state import SimulationState
from .config import ClusterConfig, PowerModelConfig, WorkloadConfig
from .power_sim import estimate_slot_energy_kwh
from .price_service import PriceService
from .profiler import WorkloadProfile, work_completed_in_slot
from .scheduler import (
    ExecutionSchedule,
    ScheduleSlot,
    build_carbon_agnostic_schedule,
    build_carbonscaler_price_tiebreak_schedule,
    build_carbonscaler_schedule,
    build_static_scale_schedule,
    build_suspend_resume_schedule,
    build_carbonscaler_budget_schedule,
    build_carbonscaler_weighted_schedule,
    build_price_only_schedule,
)
from .job_renderer import SlotJobRenderRequest, render_slot_job_script
from .slurm_adapter import (
    MockSlurmAdapter,
    DockerComposeSlurmAdapter,
    SlurmJobRequest,
)



@dataclass(frozen=True)
class ControllerRunResult:
    cluster_name: str
    policy_name: str
    horizon_slots: int
    completed: bool
    completion_slot: int | None
    total_work: float
    total_energy_kwh: float
    total_carbon_grams: float
    max_scale_used: int
    active_slots: int
    schedule: ExecutionSchedule
    state: SimulationState


class SimulationController:
    def __init__(
        self,
        carbon_service: CarbonService,
        cluster: ClusterConfig,
        power_model: PowerModelConfig,
        workload: WorkloadConfig,
        profile: WorkloadProfile,
        price_service: PriceService | None = None,
    ) -> None:
        self.carbon_service = carbon_service
        self.cluster = cluster
        self.power_model = power_model
        self.workload = workload
        self.profile = profile
        self.price_service = price_service

    def _build_schedule(
        self,
        policy_name: str,
        horizon_slots: int,
        static_scale: int = 3,
        tie_threshold_ratio: float = 0.05,
        cost_budget: float | None = None,
        cost_penalty_beta: float = 0.01,
        urgency_gamma: float = 0.5,
        lambda_carbon: float = 0.8,
    ) -> ExecutionSchedule:
        forecast = self.carbon_service.forecast_values(self.cluster.name, horizon_slots)

        if policy_name == "carbon_agnostic":
            return build_carbon_agnostic_schedule(forecast, self.profile, self.workload)

        if policy_name == "static_scale":
            return build_static_scale_schedule(
                forecast,
                self.profile,
                self.workload,
                static_scale=static_scale,
            )

        if policy_name == "suspend_resume":
            return build_suspend_resume_schedule(forecast, self.profile, self.workload)

        if policy_name == "carbonscaler":
            return build_carbonscaler_schedule(
                forecast,
                self.profile,
                self.workload,
                self.power_model,
            )
        
        if policy_name == "price_only":
            if self.price_service is None:
                raise ValueError("price_service is required for price_only")

            day_ahead_prices = self.price_service.day_ahead_forecast_values(
                self.cluster.name,
                horizon_slots,
            )

            return build_price_only_schedule(
                day_ahead_prices=day_ahead_prices,
                profile=self.profile,
                workload=self.workload,
                power_model=self.power_model,
                forecast=forecast,
            )

        if policy_name == "carbonscaler_price_tiebreak":
            if self.price_service is None:
                raise ValueError("price_service is required for carbonscaler_price_tiebreak")

            day_ahead_prices = self.price_service.day_ahead_forecast_values(
                self.cluster.name,
                horizon_slots,
            )

            return build_carbonscaler_price_tiebreak_schedule(
                forecast=forecast,
                day_ahead_prices=day_ahead_prices,
                profile=self.profile,
                workload=self.workload,
                power_model=self.power_model,
                tie_threshold_ratio=tie_threshold_ratio,
            )

        if policy_name == "carbonscaler_budget":
            if self.price_service is None:
                raise ValueError("price_service is required for carbonscaler_budget")
            if cost_budget is None:
                raise ValueError("cost_budget is required for carbonscaler_budget")

            day_ahead_prices = self.price_service.day_ahead_forecast_values(
                self.cluster.name,
                horizon_slots,
            )

            return build_carbonscaler_budget_schedule(
                forecast=forecast,
                day_ahead_prices=day_ahead_prices,
                profile=self.profile,
                workload=self.workload,
                power_model=self.power_model,
                cost_budget=cost_budget,
                cost_penalty_beta=cost_penalty_beta,
                urgency_gamma=urgency_gamma,
            )
        
        if policy_name == "carbonscaler_weighted":
            if self.price_service is None:
                raise ValueError("price_service is required for carbonscaler_weighted")

            day_ahead_prices = self.price_service.day_ahead_forecast_values(
                self.cluster.name,
                horizon_slots,
            )

            return build_carbonscaler_weighted_schedule(
                forecast=forecast,
                day_ahead_prices=day_ahead_prices,
                profile=self.profile,
                workload=self.workload,
                power_model=self.power_model,
                lambda_carbon=lambda_carbon,
            )

        raise ValueError(f"Unknown policy_name: {policy_name}")

    def _build_budget_schedule(
        self,
        forecast: list[float],
        day_ahead_prices: list[float],
        horizon_slots: int,
        cost_budget: float,
    ) -> ExecutionSchedule:
        if len(forecast) != horizon_slots:
            raise ValueError("forecast length must match horizon_slots")
        if len(day_ahead_prices) != horizon_slots:
            raise ValueError("day_ahead_prices length must match horizon_slots")

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

        remaining_work = self.workload.total_work_units
        current_planned_cost = 0.0

        for slot_index in range(horizon_slots):
            if remaining_work <= 0:
                break

            chosen_scale = self._choose_scale_with_budget(
                slot_index=slot_index,
                remaining_work=remaining_work,
                current_cost=current_planned_cost,
                cost_budget=cost_budget,
                carbon_intensity=forecast[slot_index],
                day_ahead_price=day_ahead_prices[slot_index],
            )

            schedule.slots[slot_index] = ScheduleSlot(
                slot_index=slot_index,
                scale=chosen_scale,
                carbon_intensity=forecast[slot_index],
            )

            if chosen_scale > 0:
                slot_work = work_completed_in_slot(
                    self.profile,
                    chosen_scale,
                    self.workload.slot_minutes,
                )
                remaining_work = max(0.0, remaining_work - slot_work)

                slot_energy = estimate_slot_energy_kwh(
                    workload=self.workload,
                    scale=chosen_scale,
                    power_model=self.power_model,
                    slot_minutes=self.workload.slot_minutes,
                )
                current_planned_cost += slot_energy * day_ahead_prices[slot_index]

        return schedule

    def _choose_scale_with_budget(
        self,
        slot_index: int,
        remaining_work: float,
        current_cost: float,
        cost_budget: float,
        carbon_intensity: float,
        day_ahead_price: float,
    ) -> int:
        best_scale = 0
        best_score = float("-inf")

        for scale in range(self.workload.min_replicas, self.workload.max_replicas + 1):
            slot_work = work_completed_in_slot(
                self.profile,
                scale,
                self.workload.slot_minutes,
            )
            if slot_work <= 0:
                continue

            actual_work = min(slot_work, remaining_work)

            slot_energy = estimate_slot_energy_kwh(
                workload=self.workload,
                scale=scale,
                power_model=self.power_model,
                slot_minutes=self.workload.slot_minutes,
            )
            slot_cost = slot_energy * day_ahead_price

            if current_cost + slot_cost > cost_budget:
                continue

            # Carbon efficiency: more work and lower carbon are better.
            # Equivalent to maximizing work per unit carbon.
            slot_carbon = slot_energy * carbon_intensity
            if slot_carbon <= 0:
                continue

            score = actual_work / slot_carbon

            if score > best_score:
                best_score = score
                best_scale = scale

        return best_scale

    def run(
        self,
        policy_name: str,
        horizon_slots: int,
        static_scale: int = 3,
        tie_threshold_ratio: float = 0.05,
        cost_budget: float | None = None,
        cost_penalty_beta: float = 0.01,
        urgency_gamma: float = 0.5,
        lambda_carbon: float = 0.8,
    ) -> ControllerRunResult:
        schedule = self._build_schedule(
            policy_name=policy_name,
            horizon_slots=horizon_slots,
            static_scale=static_scale,
            tie_threshold_ratio=tie_threshold_ratio,
            cost_budget=cost_budget,
            cost_penalty_beta=cost_penalty_beta,
            urgency_gamma=urgency_gamma,
            lambda_carbon=lambda_carbon,
        )

        state = SimulationState(
            cluster=self.cluster,
            power_model=self.power_model,
            workload=self.workload,
            profile=self.profile,
        )

        max_scale_used = 0
        active_slots = 0
        completion_slot: int | None = None

        for slot in schedule.slots:
            record = state.run_slot(
                scale=slot.scale,
                carbon_intensity=slot.carbon_intensity,
            )

            if record.scale > 0:
                active_slots += 1
                max_scale_used = max(max_scale_used, record.scale)

            if state.is_complete and completion_slot is None:
                completion_slot = record.slot_index

        return ControllerRunResult(
            cluster_name=self.cluster.name,
            policy_name=policy_name,
            horizon_slots=horizon_slots,
            completed=state.is_complete,
            completion_slot=completion_slot,
            total_work=state.completed_work_units,
            total_energy_kwh=state.total_energy_kwh,
            total_carbon_grams=state.total_carbon_grams,
            max_scale_used=max_scale_used,
            active_slots=active_slots,
            schedule=schedule,
            state=state,
        )

    def run_with_mock_slurm(
        self,
        policy_name: str,
        horizon_slots: int,
        static_scale: int = 3,
        run_dir: str = "mcs_implementation/generated_runs",
        tie_threshold_ratio: float = 0.05,
        cost_budget: float | None = None,
        cost_penalty_beta: float = 0.01,
        urgency_gamma: float = 0.5,
        lambda_carbon: float = 0.8,
    ) -> ControllerRunResult:
        schedule = self._build_schedule(
            policy_name=policy_name,
            horizon_slots=horizon_slots,
            static_scale=static_scale,
            tie_threshold_ratio=tie_threshold_ratio,
            cost_budget=cost_budget,
            cost_penalty_beta=cost_penalty_beta,
            urgency_gamma=urgency_gamma,
            lambda_carbon=lambda_carbon,
        )

        state = SimulationState(
            cluster=self.cluster,
            power_model=self.power_model,
            workload=self.workload,
            profile=self.profile,
        )

        adapter = MockSlurmAdapter()
        run_root = Path(run_dir) / self.cluster.name / policy_name
        run_root.mkdir(parents=True, exist_ok=True)

        max_scale_used = 0
        active_slots = 0
        completion_slot: int | None = None

        for slot in schedule.slots:
            if slot.scale > 0:
                active_slots += 1
                max_scale_used = max(max_scale_used, slot.scale)

                job_name = f"{self.workload.name}-{policy_name}-slot-{slot.slot_index}"
                script_path = run_root / "scripts" / f"{job_name}.sbatch"
                output_path = run_root / "logs" / f"{job_name}.out"
                error_path = run_root / "logs" / f"{job_name}.err"
                checkpoint_path = run_root / "checkpoints" / f"{self.workload.name}.ckpt"

                work_per_slot = work_completed_in_slot(
                    self.profile,
                    slot.scale,
                    self.workload.slot_minutes,
                )
                remaining_work = state.remaining_work_units

                rendered_script = render_slot_job_script(
                    SlotJobRenderRequest(
                        cluster_name=self.cluster.name,
                        job_name=job_name,
                        nodes=slot.scale,
                        slot_minutes=self.workload.slot_minutes,
                        checkpoint_path=str(checkpoint_path),
                        output_path=str(output_path),
                        error_path=str(error_path),
                        rendered_script_path=str(script_path),
                        slot_index=slot.slot_index,
                        scale=slot.scale,
                        work_per_slot=work_per_slot,
                        remaining_work=remaining_work,
                    )
                )

                handle = adapter.submit_slot_job(
                    SlurmJobRequest(
                        cluster_name=self.cluster.name,
                        job_name=job_name,
                        nodes=slot.scale,
                        slot_minutes=self.workload.slot_minutes,
                        script_path=rendered_script,
                        output_path=str(output_path),
                        error_path=str(error_path),
                        checkpoint_path=str(checkpoint_path),
                    )
                )
                adapter.wait_for_job(handle)

            record = state.run_slot(
                scale=slot.scale,
                carbon_intensity=slot.carbon_intensity,
            )

            if state.is_complete and completion_slot is None:
                completion_slot = record.slot_index

        return ControllerRunResult(
            cluster_name=self.cluster.name,
            policy_name=policy_name,
            horizon_slots=horizon_slots,
            completed=state.is_complete,
            completion_slot=completion_slot,
            total_work=state.completed_work_units,
            total_energy_kwh=state.total_energy_kwh,
            total_carbon_grams=state.total_carbon_grams,
            max_scale_used=max_scale_used,
            active_slots=active_slots,
            schedule=schedule,
            state=state,
        )

    def run_with_docker_slurm(
        self,
        policy_name: str,
        horizon_slots: int,
        compose_project_dir: str,
        service_name: str = "slurmctld",
        static_scale: int = 3,
        run_dir: str = "mcs_implementation/generated_runs",
        chdir: str = "/tmp",
        tie_threshold_ratio: float = 0.05,
        cost_budget: float | None = None,
        cost_penalty_beta: float = 0.01,
        urgency_gamma: float = 0.5,
        lambda_carbon: float = 0.8,
    ) -> ControllerRunResult:
        schedule = self._build_schedule(
            policy_name=policy_name,
            horizon_slots=horizon_slots,
            static_scale=static_scale,
            tie_threshold_ratio=tie_threshold_ratio,
            cost_budget=cost_budget,
            cost_penalty_beta=cost_penalty_beta,
            urgency_gamma=urgency_gamma,
            lambda_carbon=lambda_carbon,
        )

        state = SimulationState(
            cluster=self.cluster,
            power_model=self.power_model,
            workload=self.workload,
            profile=self.profile,
        )

        adapter = DockerComposeSlurmAdapter(
            compose_project_dir=compose_project_dir,
            service_name=service_name,
            worker_service_names=["cpu-worker"],
        )

        run_root = Path(run_dir) / self.cluster.name / policy_name
        run_root.mkdir(parents=True, exist_ok=True)

        worker_host_path = "mcs_implementation/workers/nbody_slot_runner.py"
        worker_remote_path = "/tmp/mcs_workers/nbody_slot_runner.py"
        adapter.copy_file_to_service(worker_host_path, worker_remote_path)

        max_scale_used = 0
        active_slots = 0
        completion_slot: int | None = None

        for slot in schedule.slots:
            if slot.scale > 0:
                active_slots += 1
                max_scale_used = max(max_scale_used, slot.scale)

                job_name = f"{self.workload.name}-{policy_name}-slot-{slot.slot_index}"
                script_path = run_root / "scripts" / f"{job_name}.sbatch"
                output_path = run_root / "logs" / f"{job_name}.out"
                error_path = run_root / "logs" / f"{job_name}.err"
                checkpoint_path = Path("/tmp/mcs_checkpoints") / f"{self.workload.name}.ckpt"

                work_per_slot = work_completed_in_slot(
                    self.profile,
                    slot.scale,
                    self.workload.slot_minutes,
                )
                remaining_work = state.remaining_work_units

                rendered_script = render_slot_job_script(
                    SlotJobRenderRequest(
                        cluster_name=self.cluster.name,
                        job_name=job_name,
                        nodes=slot.scale,
                        slot_minutes=self.workload.slot_minutes,
                        checkpoint_path=str(checkpoint_path),
                        output_path=str(output_path),
                        error_path=str(error_path),
                        rendered_script_path=str(script_path),
                        slot_index=slot.slot_index,
                        scale=slot.scale,
                        work_per_slot=work_per_slot,
                        remaining_work=remaining_work,
                    )
                )

                handle = adapter.submit_slot_job(
                    SlurmJobRequest(
                        cluster_name=self.cluster.name,
                        job_name=job_name,
                        nodes=slot.scale,
                        slot_minutes=self.workload.slot_minutes,
                        script_path=rendered_script,
                        output_path=str(output_path),
                        error_path=str(error_path),
                        checkpoint_path=str(checkpoint_path),
                        partition=self.cluster.partition,
                        chdir=chdir,
                    )
                )
                adapter.wait_for_job(handle)

            record = state.run_slot(
                scale=slot.scale,
                carbon_intensity=slot.carbon_intensity,
            )

            if state.is_complete and completion_slot is None:
                completion_slot = record.slot_index

        return ControllerRunResult(
            cluster_name=self.cluster.name,
            policy_name=policy_name,
            horizon_slots=horizon_slots,
            completed=state.is_complete,
            completion_slot=completion_slot,
            total_work=state.completed_work_units,
            total_energy_kwh=state.total_energy_kwh,
            total_carbon_grams=state.total_carbon_grams,
            max_scale_used=max_scale_used,
            active_slots=active_slots,
            schedule=schedule,
            state=state,
        )