from mcs_implementation.carbonsim.config import load_simulation_config
from mcs_implementation.carbonsim.carbon_service import build_carbon_service
from mcs_implementation.carbonsim.price_service import build_price_service
from mcs_implementation.carbonsim.profiler import build_workload_profile
from mcs_implementation.carbonsim.controller import SimulationController
from mcs_implementation.carbonsim.metrics import summarize_schedule_with_prices
from mcs_implementation.carbonsim.validation import (
    assert_controller_result_valid,
    assert_schedule_and_result_consistent,
)

cfg = load_simulation_config("mcs_implementation/config")
cluster = next(c for c in cfg.clusters if c.name == "cluster1")
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
day_ahead_prices = price_service.day_ahead_forecast_values(cluster.name, horizon_slots)
real_time_prices = price_service.real_time_forecast_values(cluster.name, horizon_slots)

result = controller.run(
    policy_name="price_only",
    horizon_slots=horizon_slots,
)

assert_controller_result_valid(result, workload)
assert_schedule_and_result_consistent(result, workload, profile)

summary = summarize_schedule_with_prices(
    "price_only",
    result.schedule,
    profile,
    workload,
    power_model,
    day_ahead_prices,
    real_time_prices,
)

print("completed:", result.completed)
print("completion_slot:", result.completion_slot)
print("total_carbon_grams:", summary["total_carbon_grams"])
print("total_day_ahead_cost:", summary["total_day_ahead_cost"])
print("total_real_time_cost:", summary["total_real_time_cost"])
print("max_scale_used:", result.max_scale_used)
print("scales:", result.schedule.scales())