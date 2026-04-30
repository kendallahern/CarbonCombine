from __future__ import annotations

from carbonsim.carbon_service import build_carbon_service
from carbonsim.config import load_simulation_config
from carbonsim.metrics import (
    build_policy_result,
    compare_policy_results,
)
from carbonsim.profiler import build_workload_profile
from carbonsim.scheduler import (
    build_carbon_agnostic_schedule,
    build_carbonscaler_schedule,
    build_static_scale_schedule,
    build_suspend_resume_schedule,
)


def format_float(value: float) -> str:
    return f"{value:.2f}"


def print_policy_result(result) -> None:
    print(
        f"  {result.policy_name:<18}"
        f" carbon={format_float(result.total_carbon_grams):>10} g"
        f"  energy={format_float(result.total_energy_kwh):>8} kWh"
        f"  active_slots={result.active_slots:>3}"
        f"  completion_slot={str(result.completion_slot):>3}"
        f"  max_scale={result.max_scale_used:>2}"
    )


def print_comparison_rows(rows: list[dict[str, object]]) -> None:
    for row in rows:
        print(
            f"    vs {row['baseline_policy']:<16}"
            f" policy={row['policy_name']:<18}"
            f" savings={format_float(float(row['carbon_savings_percent'])):>8}%"
            f"  energy_overhead={format_float(float(row['energy_overhead_percent'])):>8}%"
        )


def main() -> None:
    cfg = load_simulation_config("mcs_implementation/config")
    workload = cfg.workloads["nbody100k"]
    profile = build_workload_profile(workload)
    carbon_service = build_carbon_service(cfg.clusters)

    print("=" * 80)
    print(f"Simulation workload: {workload.display_name} ({workload.name})")
    print(f"Slot length: {workload.slot_minutes} minutes")
    print(f"Total work units: {workload.total_work_units}")
    print(f"Deadline hours: {workload.deadline_hours}")
    print("=" * 80)

    for cluster in cfg.clusters:
        power_model = cfg.power_models[cluster.name]
        horizon_slots = int(workload.deadline_hours * 60 / workload.slot_minutes)
        forecast = carbon_service.forecast_values(cluster.name, horizon_slots)

        ag = build_carbon_agnostic_schedule(forecast, profile, workload)
        ss = build_static_scale_schedule(forecast, profile, workload, static_scale=3)
        sr = build_suspend_resume_schedule(forecast, profile, workload)
        cs = build_carbonscaler_schedule(forecast, profile, workload, power_model)

        ag_result = build_policy_result(
            cluster_name=cluster.name,
            workload=workload,
            profile=profile,
            power_model=power_model,
            policy_name="carbon_agnostic",
            schedule=ag,
        )
        ss_result = build_policy_result(
            cluster_name=cluster.name,
            workload=workload,
            profile=profile,
            power_model=power_model,
            policy_name="static_scale_3",
            schedule=ss,
        )
        sr_result = build_policy_result(
            cluster_name=cluster.name,
            workload=workload,
            profile=profile,
            power_model=power_model,
            policy_name="suspend_resume",
            schedule=sr,
        )
        cs_result = build_policy_result(
            cluster_name=cluster.name,
            workload=workload,
            profile=profile,
            power_model=power_model,
            policy_name="carbonscaler",
            schedule=cs,
        )

        comparisons = compare_policy_results(ag_result, [ss_result, sr_result, cs_result])

        print()
        print(f"[{cluster.name}] {cluster.display_name}")
        print("-" * 80)
        print_policy_result(ag_result)
        print_policy_result(ss_result)
        print_policy_result(sr_result)
        print_policy_result(cs_result)
        print("  comparisons:")
        print_comparison_rows(comparisons)

    print()
    print("=" * 80)
    print("Done.")
    print("=" * 80)


if __name__ == "__main__":
    main()