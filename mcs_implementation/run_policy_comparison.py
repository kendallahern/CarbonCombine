from __future__ import annotations

import csv
from pathlib import Path

from  carbonsim.config import load_simulation_config
from  carbonsim.carbon_service import build_carbon_service
from  carbonsim.price_service import build_price_service
from  carbonsim.profiler import build_workload_profile
from  carbonsim.controller import SimulationController
from  carbonsim.metrics import (
    summarize_schedule_with_prices,
    cost_savings_percent,
    carbon_savings_percent,
)
from  carbonsim.scheduler import (
    build_carbonscaler_price_tiebreak_schedule_with_stats,
)
from carbonsim.validation import (
    assert_controller_result_valid,
    assert_schedule_and_result_consistent,
)

option_a_thresholds = [0.01, 0.03, 0.05, 0.10, 0.20]

# option_b_configs = [
#     {"cost_budget_ratio": 0.85, "cost_penalty_beta": 0.01, "urgency_gamma": 0.25},
#     {"cost_budget_ratio": 0.90, "cost_penalty_beta": 0.01, "urgency_gamma": 0.50},
#     {"cost_budget_ratio": 1.00, "cost_penalty_beta": 0.01, "urgency_gamma": 0.50},
#     {"cost_budget_ratio": 1.10, "cost_penalty_beta": 0.01, "urgency_gamma": 0.50},
#     {"cost_budget_ratio": 1.20, "cost_penalty_beta": 0.02, "urgency_gamma": 0.75},
# ]

option_b_budget_sweep = [0.80, 0.85, 0.90, 1.00, 1.10, 1.20]
option_b_beta_sweep = [0.0025, 0.005, 0.01, 0.02, 0.04]
option_b_gamma_sweep = [0.10, 0.25, 0.50, 0.75, 1.00]

option_c_lambdas = [0.50, 0.60, 0.70, 0.80, 0.90]

price_only_alphas = [0.50, 0.75, 1.00, 1.25, 1.50]

def fmt(value: float) -> str:
    return f"{value:.4f}"


def ensure_parent_dir(path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)


def main() -> None:
    cfg = load_simulation_config("mcs_implementation/config")

    # cluster = cfg.clusters[1]  # California
    cluster = next(c for c in cfg.clusters if c.name == "cluster1")  # Ontario
    workload = cfg.workloads["nbody100k"]
    profile = build_workload_profile(workload)
    power_model = cfg.power_models[cluster.name]
    carbon_service = build_carbon_service(cfg.clusters)
    price_service = build_price_service("mcs_implementation/config/price_traces.yaml")

    controller = SimulationController(
        carbon_service=carbon_service,
        cluster=cluster,
        power_model=power_model,
        workload=workload,
        profile=profile,
        price_service=price_service,
    )

    horizon_slots = int(workload.deadline_hours * 60 / workload.slot_minutes)

    forecast = carbon_service.forecast_values(cluster.name, horizon_slots)
    day_ahead_prices = price_service.day_ahead_forecast_values(cluster.name, horizon_slots)
    real_time_prices = price_service.real_time_forecast_values(cluster.name, horizon_slots)

    # policies = [
    #     # Baseline
    #     {
    #         "policy_name": "carbonscaler",
    #         "label": "carbonscaler_base",
    #     },

    #     {
    #         "policy_name": "price_only",
    #         "label": "price_only",
    #     }
    # ]
            
    # for threshold in [0.01, 0.03, 0.05, 0.10, 0.20]:
    #     policies.append(
    #         {
    #             "policy_name": "carbonscaler_price_tiebreak",
    #             "label": f"optionA_tie_{threshold:.2f}",
    #             "tie_threshold_ratio": threshold,
    #         }
    #     )

    # for cfg in [
    #     {"cost_budget_ratio": 0.85, "cost_penalty_beta": 0.01, "urgency_gamma": 0.25},
    #     {"cost_budget_ratio": 0.90, "cost_penalty_beta": 0.01, "urgency_gamma": 0.50},
    #     {"cost_budget_ratio": 1.00, "cost_penalty_beta": 0.01, "urgency_gamma": 0.50},
    #     {"cost_budget_ratio": 1.10, "cost_penalty_beta": 0.01, "urgency_gamma": 0.50},
    #     {"cost_budget_ratio": 1.20, "cost_penalty_beta": 0.02, "urgency_gamma": 0.75},
    # ]:
    #     policies.append(
    #         {
    #             "policy_name": "carbonscaler_budget",
    #             "label": (
    #                 f"optionB_budget{cfg['cost_budget_ratio']:.2f}"
    #                 f"_beta{cfg['cost_penalty_beta']:.2f}"
    #                 f"_gamma{cfg['urgency_gamma']:.2f}"
    #             ),
    #             **cfg,
    #         }
    #     )
    

    # for lam in [0.50, 0.60, 0.70, 0.80, 0.90]:
    #     policies.append(
    #         {
    #             "policy_name": "carbonscaler_weighted",
    #             "label": f"optionC_lambda{lam:.2f}",
    #             "lambda_carbon": lam,
    #         }
    #     )


    policies = []

    # Baseline
    policies.append(
        {
            "policy_name": "carbonscaler",
            "label": "carbonscaler_base",
        }
    )

    # Price-only family
    policies.append(
        {
            "policy_name": "price_only",
            "label": f"price_only_"
        }
    )

    # Option A family
    for threshold in option_a_thresholds:
        policies.append(
            {
                "policy_name": "carbonscaler_price_tiebreak",
                "label": f"optionA_tie_{threshold:.2f}",
                "tie_threshold_ratio": threshold,
            }
        )

    # Option B — sweep 1: budget ratio, fixed beta/gamma
    for budget_ratio in option_b_budget_sweep:
        policies.append(
            {
                "policy_name": "carbonscaler_budget",
                "label": f"optionB_budget{budget_ratio:.2f}_beta0.01_gamma0.50",
                "sweep_group": "optionB_budget_sweep",
                "cost_budget_ratio": budget_ratio,
                "cost_penalty_beta": 0.01,
                "urgency_gamma": 0.50,
            }
        )

    # Option B — sweep 2: beta, fixed budget/gamma
    for beta in option_b_beta_sweep:
        policies.append(
            {
                "policy_name": "carbonscaler_budget",
                "label": f"optionB_budget0.90_beta{beta:.4f}_gamma0.50",
                "sweep_group": "optionB_beta_sweep",
                "cost_budget_ratio": 0.90,
                "cost_penalty_beta": beta,
                "urgency_gamma": 0.50,
            }
        )

    # Option B — sweep 3: gamma, fixed budget/beta
    for gamma in option_b_gamma_sweep:
        policies.append(
            {
                "policy_name": "carbonscaler_budget",
                "label": f"optionB_budget0.90_beta0.01_gamma{gamma:.2f}",
                "sweep_group": "optionB_gamma_sweep",
                "cost_budget_ratio": 0.90,
                "cost_penalty_beta": 0.01,
                "urgency_gamma": gamma,
            }
        )

    # Option C family
    for lam in option_c_lambdas:
        policies.append(
            {
                "policy_name": "carbonscaler_weighted",
                "label": f"optionC_lambda{lam:.2f}",
                "lambda_carbon": lam,
            }
        )


    summary_rows: list[dict[str, object]] = []
    schedule_rows: list[dict[str, object]] = []

    baseline_summary: dict[str, object] | None = None

    forecast = carbon_service.forecast_values(cluster.name, horizon_slots)
    day_ahead_prices = price_service.day_ahead_forecast_values(cluster.name, horizon_slots)
    real_time_prices = price_service.real_time_forecast_values(cluster.name, horizon_slots)


    baseline_result_for_budget = controller.run(
        policy_name="carbonscaler",
        horizon_slots=horizon_slots,
    )
    baseline_summary_for_budget = summarize_schedule_with_prices(
        name="carbonscaler_base",
        schedule=baseline_result_for_budget.schedule,
        profile=profile,
        workload=workload,
        power_model=power_model,
        day_ahead_prices=day_ahead_prices,
        real_time_prices=real_time_prices,
    )
    baseline_day_ahead_cost = float(baseline_summary_for_budget["total_day_ahead_cost"])

    for policy in policies:
        policy_name = str(policy["policy_name"])
        label = str(policy["label"])
        tie_threshold_ratio = policy.get("tie_threshold_ratio")
        cost_budget_ratio = policy.get("cost_budget_ratio")
        cost_penalty_beta = policy.get("cost_penalty_beta")
        urgency_gamma = policy.get("urgency_gamma")
        lambda_carbon = policy.get("lambda_carbon")

        kwargs = {}
        tie_break_used_count = 0

        if tie_threshold_ratio is not None:
            kwargs["tie_threshold_ratio"] = float(tie_threshold_ratio)

        if cost_budget_ratio is not None:
            kwargs["cost_budget"] = baseline_day_ahead_cost * float(cost_budget_ratio)

        if cost_penalty_beta is not None:
            kwargs["cost_penalty_beta"] = float(cost_penalty_beta)

        if urgency_gamma is not None:
            kwargs["urgency_gamma"] = float(urgency_gamma)

        if lambda_carbon is not None:
            kwargs["lambda_carbon"] = float(lambda_carbon)

        result = controller.run(
            policy_name=policy_name,
            horizon_slots=horizon_slots,
            **kwargs,
        )

        assert_controller_result_valid(result, workload)
        assert_schedule_and_result_consistent(result, workload, profile)

        if policy_name == "carbonscaler_price_tiebreak":
            _, stats = build_carbonscaler_price_tiebreak_schedule_with_stats(
                forecast=forecast,
                day_ahead_prices=day_ahead_prices,
                profile=profile,
                workload=workload,
                power_model=power_model,
                tie_threshold_ratio=float(tie_threshold_ratio),
            )
            tie_break_used_count = stats.tie_break_used_count

        summary = summarize_schedule_with_prices(
            name=label,
            schedule=result.schedule,
            profile=profile,
            workload=workload,
            power_model=power_model,
            day_ahead_prices=day_ahead_prices,
            real_time_prices=real_time_prices,
        )

        row = {
            "policy": label,
            "policy_name": policy_name,
            "cluster_name": cluster.name,
            "cluster_display_name": cluster.display_name,
            "workload_name": workload.name,
            "completed": result.completed,
            "completion_slot": result.completion_slot,
            "total_work": float(summary["total_work"]),
            "total_energy_kwh": float(summary["total_energy_kwh"]),
            "total_carbon_grams": float(summary["total_carbon_grams"]),
            "total_day_ahead_cost": float(summary["total_day_ahead_cost"]),
            "total_real_time_cost": float(summary["total_real_time_cost"]),
            "active_slots": int(summary["active_slots"]),
            "max_scale_used": int(summary["max_scale_used"]),
            "tie_threshold_ratio": tie_threshold_ratio if tie_threshold_ratio is not None else "",
            "tie_break_used_count": tie_break_used_count,
            "cost_budget_ratio": cost_budget_ratio if cost_budget_ratio is not None else "",
            "cost_penalty_beta": cost_penalty_beta if cost_penalty_beta is not None else "",
            "urgency_gamma": urgency_gamma if urgency_gamma is not None else "",
            "lambda_carbon": lambda_carbon if lambda_carbon is not None else "",
            "sweep_group": policy.get("sweep_group", ""),
        }

        if baseline_summary is None:
            baseline_summary = row.copy()
            row["carbon_savings_vs_base_pct"] = 0.0
            row["day_ahead_cost_savings_vs_base_pct"] = 0.0
            row["real_time_cost_savings_vs_base_pct"] = 0.0
        else:
            row["carbon_savings_vs_base_pct"] = carbon_savings_percent(
                float(baseline_summary["total_carbon_grams"]),
                float(row["total_carbon_grams"]),
            )
            row["day_ahead_cost_savings_vs_base_pct"] = cost_savings_percent(
                float(baseline_summary["total_day_ahead_cost"]),
                float(row["total_day_ahead_cost"]),
            )
            row["real_time_cost_savings_vs_base_pct"] = cost_savings_percent(
                float(baseline_summary["total_real_time_cost"]),
                float(row["total_real_time_cost"]),
            )

        summary_rows.append(row)

        for slot in result.schedule.slots:
            schedule_rows.append(
                {
                    "policy": label,
                    "slot_index": slot.slot_index,
                    "scale": slot.scale,
                    "carbon_intensity": slot.carbon_intensity,
                    "day_ahead_price": day_ahead_prices[slot.slot_index],
                    "real_time_price": real_time_prices[slot.slot_index],
                }
            )

    print("=" * 120)
    print(f"Cluster: {cluster.display_name} ({cluster.name})")
    print(f"Workload: {workload.display_name} ({workload.name})")
    print("=" * 120)
    print(
        f"{'policy':<34}"
        f"{'carbon_g':>12}"
        f"{'da_cost':>12}"
        f"{'rt_cost':>12}"
        f"{'energy':>12}"
        f"{'active':>8}"
        f"{'complete':>10}"
        f"{'done':>8}"
        f"{'max_scale':>10}"
        # f"{'tie_used':>10}"
        # f"{'budget':>10}"
        # f"{'beta':>8}"
        # f"{'gamma':>8}"
    )

    for row in summary_rows:
         print(
            f"{str(row['policy']):<34}"
            f"{fmt(float(row['total_carbon_grams'])):>12}"
            f"{fmt(float(row['total_day_ahead_cost'])):>12}"
            f"{fmt(float(row['total_real_time_cost'])):>12}"
            f"{fmt(float(row['total_energy_kwh'])):>12}"
            f"{int(row['active_slots']):>8}"
            f"{str(row['completion_slot']):>10}"
            f"{str(row['completed']):>8}"
            f"{int(row['max_scale_used']):>10}"
            # f"{int(row['tie_break_used_count']):>10}"
            # f"{str(row['cost_budget_ratio']):>10}"
            # f"{str(row['cost_penalty_beta']):>8}"
            # f"{str(row['urgency_gamma']):>8}"
        )

    print("\nSavings vs baseline:")
    for row in summary_rows[1:]:
        print("-" * 120)
        print("policy:", row["policy"])
        print("carbon_savings_vs_base_pct:", fmt(float(row["carbon_savings_vs_base_pct"])))
        print(
            "day_ahead_cost_savings_vs_base_pct:",
            fmt(float(row["day_ahead_cost_savings_vs_base_pct"])),
        )
        print(
            "real_time_cost_savings_vs_base_pct:",
            fmt(float(row["real_time_cost_savings_vs_base_pct"])),
        )

    output_dir = Path("mcs_implementation/results")
    output_dir.mkdir(parents=True, exist_ok=True)

    summary_csv = output_dir / "policy_comparison_summary.csv"
    schedule_csv = output_dir / "policy_comparison_schedules.csv"

    with summary_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(summary_rows[0].keys()))
        writer.writeheader()
        writer.writerows(summary_rows)

    with schedule_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(schedule_rows[0].keys()))
        writer.writeheader()
        writer.writerows(schedule_rows)

    print("\nWrote:")
    print(summary_csv)
    print(schedule_csv)


if __name__ == "__main__":
    main()