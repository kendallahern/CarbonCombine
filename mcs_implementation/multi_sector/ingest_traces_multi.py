from __future__ import annotations

import argparse
import csv
import json
import os
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

import sys
from pathlib import Path

# Make mcs_implementation/ visible so sibling packages (carbonsim, etc.) resolve
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from  carbonsim.carbon_service import build_carbon_service
from  carbonsim.config import load_simulation_config
from  carbonsim.controller import SimulationController
from  carbonsim.metrics import (
    carbon_savings_percent,
    cost_savings_percent,
    summarize_schedule_with_prices,
)
from  carbonsim.price_service import build_price_service
from  carbonsim.profiler import build_workload_profile
from  carbonsim.scheduler import (
    build_carbonscaler_price_tiebreak_schedule_with_stats,
)
from  carbonsim.validation import (
    assert_controller_result_valid,
    assert_schedule_and_result_consistent,
)


# ---------------------------------------------------------------------------
# Region configuration
# ---------------------------------------------------------------------------
REGION_CONFIG: dict[str, dict[str, Any]] = {
    "ontario": {"zone": "CA-ON", "cluster": 1},
    "california": {"zone": "US-CAL-CISO", "cluster": 2},
    "netherlands": {"zone": "NL", "cluster": 3},
    "texas": {"zone": "US-TEX-ERCO", "cluster": 4},
    "arizona": {"zone": "US-SW-AZPS", "cluster": 5},
}

ALL_REGIONS = list(REGION_CONFIG.keys())

# Historical week requested by user: Apr 13–19, 2026 (inclusive)
DEFAULT_START_DATE = "2026-04-13"
DEFAULT_END_DATE = "2026-04-19"

TRACES_DIR = "mcs_implementation/traces"
RESULTS_ROOT = "mcs_implementation/results/sectors"
DEFAULT_WORKLOAD_NAME = "nbody100k"


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CarbonRecord:
    timestamp: str
    carbon_intensity: float


@dataclass(frozen=True)
class PriceRecord:
    timestamp: str
    day_ahead_price: float
    real_time_price: float


# ---------------------------------------------------------------------------
# File helpers
# ---------------------------------------------------------------------------

def ensure_parent_dir(path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)


def parse_date_utc(date_str: str) -> datetime:
    return datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc)


def iso_z(dt_obj: datetime) -> str:
    return dt_obj.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def week_start_dt(start_date: str) -> datetime:
    return parse_date_utc(start_date)


def week_end_exclusive_dt(end_date: str) -> datetime:
    # end date inclusive -> next day at 00:00Z exclusive
    return parse_date_utc(end_date) + timedelta(days=1)


def expected_horizon_hours(start_date: str, end_date: str) -> int:
    start = week_start_dt(start_date)
    end_exclusive = week_end_exclusive_dt(end_date)
    return int((end_exclusive - start).total_seconds() // 3600)


def carbon_csv_path(region: str, base_dir: str = TRACES_DIR) -> Path:
    cfg = REGION_CONFIG[region]
    return Path(base_dir) / f"cluster{cfg['cluster']}_{region}_real_carbon.csv"


def price_csv_path(region: str, base_dir: str = TRACES_DIR) -> Path:
    cfg = REGION_CONFIG[region]
    return Path(base_dir) / f"cluster{cfg['cluster']}_{region}_real_price.csv"


def sector_results_dir(region: str, base_dir: str = RESULTS_ROOT) -> Path:
    return Path(base_dir) / region


def write_carbon_csv(path: str | Path, rows: list[CarbonRecord]) -> None:
    ensure_parent_dir(path)
    with Path(path).open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["timestamp", "carbon_intensity"])
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "timestamp": row.timestamp,
                    "carbon_intensity": row.carbon_intensity,
                }
            )


def write_price_csv(path: str | Path, rows: list[PriceRecord]) -> None:
    ensure_parent_dir(path)
    with Path(path).open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["timestamp", "day_ahead_price", "real_time_price"],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "timestamp": row.timestamp,
                    "day_ahead_price": row.day_ahead_price,
                    "real_time_price": row.real_time_price,
                }
            )


def write_price_traces_yaml(path: str | Path, cluster_name: str, price_csv: str | Path) -> None:
    """
    YAML file compatible with build_price_service.
    Expected shape:

    price_traces:
      cluster1: "path/to/file.csv"
    """
    ensure_parent_dir(path)
    yaml_text = (
        "price_traces:\n"
        f'  {cluster_name}: "{price_csv}"\n'
    )
    Path(path).write_text(yaml_text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Carbon ingestion (historical)
# ---------------------------------------------------------------------------

def fetch_electricitymaps_carbon_past_range(
    zone: str,
    start_date: str,
    end_date: str,
    api_key: str,
) -> list[CarbonRecord]:
    """
    Fetch historical carbon intensity for a date range using Electricity Maps
    past-range endpoint.

    The requested window here is Apr 13–19, 2026 inclusive.
    """
    url = "https://api.electricitymap.org/v4/carbon-intensity/past-range"
    headers = {"auth-token": api_key}
    params = {
        "zone": zone,
        "start": iso_z(week_start_dt(start_date)),
        "end": iso_z(week_end_exclusive_dt(end_date)),
        "temporalGranularity": "hourly",
    }

    response = requests.get(url, headers=headers, params=params, timeout=30)
    response.raise_for_status()
    payload = response.json()

    rows: list[CarbonRecord] = []

    candidate_series = None
    if isinstance(payload, dict):
        for key in ("data", "history", "past", "results"):
            if isinstance(payload.get(key), list):
                candidate_series = payload[key]
                break
    elif isinstance(payload, list):
        candidate_series = payload

    if not isinstance(candidate_series, list):
        raise ValueError(
            f"Unexpected Electricity Maps historical carbon payload for zone {zone!r}: "
            f"{json.dumps(payload)[:700]}"
        )

    for item in candidate_series:
        timestamp = (
            item.get("datetime")
            or item.get("timestamp")
            or item.get("start")
            or item.get("time")
        )
        value = (
            item.get("carbonIntensity")
            or item.get("carbon_intensity")
            or item.get("value")
        )
        if timestamp is None or value is None:
            continue

        rows.append(CarbonRecord(timestamp=str(timestamp), carbon_intensity=float(value)))

    if not rows:
        raise ValueError(f"No usable historical carbon rows returned for zone {zone!r}")

    rows.sort(key=lambda r: r.timestamp)
    return rows


# ---------------------------------------------------------------------------
# Price ingestion (local normalized weekly CSVs)
# ---------------------------------------------------------------------------

def copy_price_csv_from_local(source_csv: str | Path) -> list[PriceRecord]:
    path = Path(source_csv)
    if not path.exists():
        raise FileNotFoundError(f"Price source file not found: {path}")

    rows: list[PriceRecord] = []

    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        required = {"timestamp", "day_ahead_price", "real_time_price"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Missing required columns in {path}: {sorted(missing)}")

        for row in reader:
            rows.append(
                PriceRecord(
                    timestamp=str(row["timestamp"]).strip(),
                    day_ahead_price=float(row["day_ahead_price"]),
                    real_time_price=float(row["real_time_price"]),
                )
            )

    if not rows:
        raise ValueError(f"No rows found in {path}")

    return rows


def filter_rows_to_week(
    rows: list[PriceRecord],
    start_date: str,
    end_date: str,
) -> list[PriceRecord]:
    start = week_start_dt(start_date)
    end_exclusive = week_end_exclusive_dt(end_date)

    out: list[PriceRecord] = []
    for row in rows:
        ts = datetime.fromisoformat(row.timestamp.replace("Z", "+00:00"))
        if start <= ts < end_exclusive:
            out.append(row)

    out.sort(key=lambda r: r.timestamp)
    return out


# ---------------------------------------------------------------------------
# Policy sweep construction
# ---------------------------------------------------------------------------

def build_policy_sweep() -> list[dict[str, Any]]:
    option_a_thresholds = [0.01, 0.03, 0.05, 0.10, 0.20]
    price_only_alphas = [0.50, 0.75, 1.00, 1.25, 1.50]
    option_b_budget_sweep = [0.80, 0.85, 0.90, 1.00, 1.10, 1.20]
    option_b_beta_sweep = [0.0025, 0.005, 0.01, 0.02, 0.04]
    option_b_gamma_sweep = [0.10, 0.25, 0.50, 0.75, 1.00]
    option_c_lambdas = [0.50, 0.60, 0.70, 0.80, 0.90]

    policies: list[dict[str, Any]] = []

    policies.append(
        {
            "policy_name": "carbonscaler",
            "label": "carbonscaler_base",
        }
    )

    # for alpha in price_only_alphas:
    #     policies.append(
    #         {
    #             "policy_name": "price_only",
    #             "label": f"price_only_alpha{alpha:.2f}",
    #             "price_exponent": alpha,
    #         }
    #     )


    policies.append(
        {
            "policy_name": "price_only",
            "label": "price_only"
        }
    )

    for threshold in option_a_thresholds:
        policies.append(
            {
                "policy_name": "carbonscaler_price_tiebreak",
                "label": f"optionA_tie_{threshold:.2f}",
                "tie_threshold_ratio": threshold,
            }
        )

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

    for lam in option_c_lambdas:
        policies.append(
            {
                "policy_name": "carbonscaler_weighted",
                "label": f"optionC_lambda{lam:.2f}",
                "lambda_carbon": lam,
            }
        )

    return policies


# ---------------------------------------------------------------------------
# Per-region orchestration
# ---------------------------------------------------------------------------

def ingest_region_traces(
    region: str,
    start_date: str,
    end_date: str,
    api_key: str,
    price_source_csv: str | Path,
    traces_dir: str = TRACES_DIR,
) -> tuple[Path, Path]:
    cfg = REGION_CONFIG[region]
    zone = cfg["zone"]

    c_path = carbon_csv_path(region, traces_dir)
    p_path = price_csv_path(region, traces_dir)

    carbon_rows = fetch_electricitymaps_carbon_past_range(
        zone=zone,
        start_date=start_date,
        end_date=end_date,
        api_key=api_key,
    )
    write_carbon_csv(c_path, carbon_rows)

    price_rows = copy_price_csv_from_local(price_source_csv)
    price_rows = filter_rows_to_week(price_rows, start_date=start_date, end_date=end_date)
    if not price_rows:
        raise ValueError(f"[{region}] No weekly price rows after filtering {price_source_csv}")

    write_price_csv(p_path, price_rows)

    expected_rows = expected_horizon_hours(start_date, end_date)
    if len(price_rows) != expected_rows:
        print(
            f"  ! Warning [{region}] weekly price rows = {len(price_rows)}, expected ~{expected_rows}"
        )
    if len(carbon_rows) != expected_rows:
        print(
            f"  ! Warning [{region}] weekly carbon rows = {len(carbon_rows)}, expected ~{expected_rows}"
        )

    return c_path, p_path


def run_policy_sweep_for_region(
    region: str,
    carbon_path: Path,
    price_path: Path,
    results_dir: str,
    workload_name: str,
    start_date: str,
    end_date: str,
) -> None:
    cfg = load_simulation_config("mcs_implementation/config")
    region_cfg = REGION_CONFIG[region]
    cluster_name = f"cluster{region_cfg['cluster']}"

    cluster_template = next(c for c in cfg.clusters if c.name == cluster_name)
    sector_cluster = replace(cluster_template, trace_file=str(carbon_path))

    power_model = cfg.power_models[sector_cluster.name]
    workload = cfg.workloads[workload_name]
    profile = build_workload_profile(workload)

    carbon_service = build_carbon_service([sector_cluster])

    # sector_out_dir = sector_results_dir(region, results_dir)
    sector_out_dir= Path(results_dir)
    sector_out_dir.mkdir(parents=True, exist_ok=True)

    sector_price_yaml = sector_out_dir / "price_traces.yaml"
    write_price_traces_yaml(sector_price_yaml, sector_cluster.name, price_path)
    price_service = build_price_service(str(sector_price_yaml))

    controller = SimulationController(
        carbon_service=carbon_service,
        cluster=sector_cluster,
        power_model=power_model,
        workload=workload,
        profile=profile,
        price_service=price_service,
    )

    horizon_slots = expected_horizon_hours(start_date, end_date)

    forecast = carbon_service.forecast_values(sector_cluster.name, horizon_slots)
    day_ahead_prices = price_service.day_ahead_forecast_values(sector_cluster.name, horizon_slots)
    real_time_prices = price_service.real_time_forecast_values(sector_cluster.name, horizon_slots)

    baseline_result_for_budget = controller.run(
        policy_name="carbonscaler",
        horizon_slots=horizon_slots,
    )
    assert_controller_result_valid(baseline_result_for_budget, workload)
    assert_schedule_and_result_consistent(baseline_result_for_budget, workload, profile)

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

    policies = build_policy_sweep()
    summary_rows: list[dict[str, object]] = []
    schedule_rows: list[dict[str, object]] = []
    baseline_summary: dict[str, object] | None = None

    for policy in policies:
        policy_name = str(policy["policy_name"])
        label = str(policy["label"])

        tie_threshold_ratio = policy.get("tie_threshold_ratio")
        cost_budget_ratio = policy.get("cost_budget_ratio")
        cost_penalty_beta = policy.get("cost_penalty_beta")
        urgency_gamma = policy.get("urgency_gamma")
        lambda_carbon = policy.get("lambda_carbon")
        # price_exponent = policy.get("price_exponent")

        kwargs: dict[str, Any] = {}
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
        # if price_exponent is not None:
        #     kwargs["price_exponent"] = float(price_exponent)

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
            "cluster_name": sector_cluster.name,
            "cluster_display_name": sector_cluster.display_name,
            "sector_slug": region,
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
            # "price_exponent": price_exponent if price_exponent is not None else "",
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
                    "policy_name": policy_name,
                    "sector_slug": region,
                    "slot_index": slot.slot_index,
                    "scale": slot.scale,
                    "carbon_intensity": slot.carbon_intensity,
                    "day_ahead_price": day_ahead_prices[slot.slot_index],
                    "real_time_price": real_time_prices[slot.slot_index],
                }
            )

    summary_csv = sector_out_dir / "policy_comparison_summary.csv"
    schedules_csv = sector_out_dir / "policy_comparison_schedules.csv"

    with summary_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(summary_rows[0].keys()))
        writer.writeheader()
        writer.writerows(summary_rows)

    with schedules_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(schedule_rows[0].keys()))
        writer.writeheader()
        writer.writerows(schedule_rows)

    print(f"  ✓ Wrote summaries for {region}:")
    print(f"    - {summary_csv}")
    print(f"    - {schedules_csv}")


# def parse_ontario_week_filename(path: Path) -> tuple[str, str, str]:
#     """
#     Parse filenames like:
#       ontario_week05_2026-03-09_to_2026-03-15_price.csv

#     Returns:
#       (week_label, start_date, end_date)
#     """
#     stem = path.stem  # e.g. ontario_week05_2026-03-09_to_2026-03-15_price
#     parts = stem.split("_")

#     if len(parts) < 6:
#         raise ValueError(f"Unexpected weekly filename format: {path.name}")

#     # Expected:
#     # parts[0] = ontario
#     # parts[1] = week05
#     # parts[2] = 2026-03-09
#     # parts[3] = to
#     # parts[4] = 2026-03-15
#     # parts[5] = price
#     if parts[0] != "ontario" or not parts[1].startswith("week") or parts[3] != "to":
#         raise ValueError(f"Unexpected weekly filename format: {path.name}")

#     week_label = parts[1]
#     start_date = parts[2]
#     end_date = parts[4]
#     return week_label, start_date, end_date

def parse_week_price_filename(path: Path) -> tuple[str, str, str, str]:
    """
    Parse filenames like:

      ontario_week05_2026-03-09_to_2026-03-15_price.csv
      ercot_texas_week05_2026-03-09_to_2026-03-15_price.csv

    Returns:
      (region, week_label, start_date, end_date)
    """
    stem = path.stem

    if stem.startswith("ontario_week"):
        parts = stem.split("_")
        if len(parts) < 6:
            raise ValueError(f"Unexpected weekly filename format: {path.name}")

        region = "ontario"
        week_label = parts[1]
        start_date = parts[2]
        end_date = parts[4]

        if parts[0] != "ontario" or not week_label.startswith("week") or parts[3] != "to":
            raise ValueError(f"Unexpected weekly filename format: {path.name}")

        return region, week_label, start_date, end_date

    if stem.startswith("ercot_texas_week"):
        parts = stem.split("_")
        if len(parts) < 7:
            raise ValueError(f"Unexpected weekly filename format: {path.name}")

        region = "texas"
        week_label = parts[2]
        start_date = parts[3]
        end_date = parts[5]

        if (
            parts[0] != "ercot"
            or parts[1] != "texas"
            or not week_label.startswith("week")
            or parts[4] != "to"
        ):
            raise ValueError(f"Unexpected weekly filename format: {path.name}")

        return region, week_label, start_date, end_date

    raise ValueError(f"Unsupported weekly price filename: {path.name}")

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
# def main() -> None:
#     parser = argparse.ArgumentParser(
#         description=(
#             "For each Ontario weekly price CSV, fetch the matching weekly carbon trace, "
#             "run the full policy sweep, and write a per-week "
#             "policy_comparison_summary.csv and policy_comparison_schedules.csv."
#         )
#     )

#     parser.add_argument(
#         "--traces-dir",
#         default=TRACES_DIR,
#         help=f"Trace output directory (default: {TRACES_DIR})",
#     )
#     parser.add_argument(
#         "--results-dir",
#         default=RESULTS_ROOT,
#         help=f"Per-week results directory (default: {RESULTS_ROOT})",
#     )
#     parser.add_argument(
#         "--workload-name",
#         default=DEFAULT_WORKLOAD_NAME,
#         help=f"Workload to evaluate (default: {DEFAULT_WORKLOAD_NAME})",
#     )
#     parser.add_argument(
#         "--price-source-dir",
#         required=True,
#         help=(
#             "Directory containing Ontario weekly price CSVs named like "
#             "ontario_week05_2026-03-09_to_2026-03-15_price.csv"
#         ),
#     )

#     args = parser.parse_args()

#     api_key = os.environ.get("ELECTRICITYMAPS_API_KEY")
#     if not api_key:
#         raise SystemExit(
#             "Error: set ELECTRICITYMAPS_API_KEY in your environment before running."
#         )

#     price_source_dir = Path(args.price_source_dir)
#     if not price_source_dir.exists():
#         raise SystemExit(f"Error: price source directory not found: {price_source_dir}")

#     weekly_price_files = sorted(price_source_dir.glob("ontario_week*_price.csv"))
#     if not weekly_price_files:
#         raise SystemExit(
#             f"Error: no Ontario weekly price CSVs found in {price_source_dir}"
#         )

#     print(f"Processing {len(weekly_price_files)} Ontario weekly price files from:")
#     print(f"  {price_source_dir}")

#     errors: list[str] = []

#     for weekly_price_file in weekly_price_files:
#         try:
#             week_label, start_date, end_date = parse_ontario_week_filename(weekly_price_file)
#             week_slug = f"ontario_{week_label}_{start_date}_to_{end_date}"

#             print(f"\n[{week_slug}]")
#             print(f"  Price file : {weekly_price_file.name}")
#             print(f"  Date range : {start_date} to {end_date}")

#             # Put traces in week-specific filenames so they do not overwrite each other
#             week_trace_dir = Path(args.traces_dir) / "ontario_weeks" / week_slug
#             week_trace_dir.mkdir(parents=True, exist_ok=True)

#             carbon_path, price_path = ingest_region_traces(
#                 region="ontario",
#                 start_date=start_date,
#                 end_date=end_date,
#                 api_key=api_key,
#                 price_source_csv=weekly_price_file,
#                 traces_dir=str(week_trace_dir),
#             )

#             # Put policy results in a per-week output folder
#             week_results_dir = Path(args.results_dir) / week_slug
#             week_results_dir.mkdir(parents=True, exist_ok=True)

#             run_policy_sweep_for_region(
#                 region="ontario",
#                 carbon_path=carbon_path,
#                 price_path=price_path,
#                 results_dir=str(week_results_dir),
#                 workload_name=args.workload_name,
#                 start_date=start_date,
#                 end_date=end_date,
#             )

#         except Exception as exc:  # noqa: BLE001
#             errors.append(f"[{weekly_price_file.name}] {exc}")

#     if errors:
#         print("\nErrors encountered:")
#         for err in errors:
#             print(f"  ✗ {err}")
#         raise SystemExit(1)

#     print("\nAll Ontario weekly traces ingested and swept successfully.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "For each weekly price CSV, fetch the matching weekly carbon trace, "
            "run the full policy sweep, and write per-week "
            "policy_comparison_summary.csv and policy_comparison_schedules.csv."
        )
    )

    parser.add_argument(
        "--traces-dir",
        default=TRACES_DIR,
        help=f"Trace output directory (default: {TRACES_DIR})",
    )
    parser.add_argument(
        "--results-dir",
        default=RESULTS_ROOT,
        help=f"Per-week results directory (default: {RESULTS_ROOT})",
    )
    parser.add_argument(
        "--workload-name",
        default=DEFAULT_WORKLOAD_NAME,
        help=f"Workload to evaluate (default: {DEFAULT_WORKLOAD_NAME})",
    )
    parser.add_argument(
        "--price-source-dir",
        required=True,
        help=(
            "Directory containing weekly price CSVs named like "
            "ontario_week05_2026-03-09_to_2026-03-15_price.csv or "
            "ercot_texas_week05_2026-03-09_to_2026-03-15_price.csv"
        ),
    )
    parser.add_argument(
        "--region",
        choices=["ontario", "texas", "auto"],
        default="auto",
        help=(
            "Which region files to process. Use 'auto' to infer from filenames. "
            "Default: auto."
        ),
    )

    args = parser.parse_args()

    api_key = os.environ.get("ELECTRICITYMAPS_API_KEY")
    if not api_key:
        raise SystemExit(
            "Error: set ELECTRICITYMAPS_API_KEY in your environment before running."
        )

    price_source_dir = Path(args.price_source_dir)
    if not price_source_dir.exists():
        raise SystemExit(f"Error: price source directory not found: {price_source_dir}")

    if args.region == "ontario":
        patterns = ["ontario_week*_price.csv"]
    elif args.region == "texas":
        patterns = ["ercot_texas_week*_price.csv"]
    else:
        patterns = ["ontario_week*_price.csv", "ercot_texas_week*_price.csv"]

    weekly_price_files: list[Path] = []
    for pattern in patterns:
        weekly_price_files.extend(sorted(price_source_dir.glob(pattern)))

    weekly_price_files = sorted(set(weekly_price_files))

    if not weekly_price_files:
        raise SystemExit(
            f"Error: no matching weekly price CSVs found in {price_source_dir}"
        )

    print(f"Processing {len(weekly_price_files)} weekly price files from:")
    print(f"  {price_source_dir}")
    print(f"Region mode: {args.region}")

    errors: list[str] = []

    for weekly_price_file in weekly_price_files:
        try:
            region, week_label, start_date, end_date = parse_week_price_filename(
                weekly_price_file
            )

            if args.region != "auto" and region != args.region:
                continue

            week_slug = f"{region}_{week_label}_{start_date}_to_{end_date}"

            print(f"\n[{week_slug}]")
            print(f"  Region     : {region}")
            print(f"  Price file : {weekly_price_file.name}")
            print(f"  Date range : {start_date} to {end_date}")

            week_trace_dir = Path(args.traces_dir) / f"{region}_weeks" / week_slug
            week_trace_dir.mkdir(parents=True, exist_ok=True)

            carbon_path, price_path = ingest_region_traces(
                region=region,
                start_date=start_date,
                end_date=end_date,
                api_key=api_key,
                price_source_csv=weekly_price_file,
                traces_dir=str(week_trace_dir),
            )

            week_results_dir = Path(args.results_dir) / week_slug
            week_results_dir.mkdir(parents=True, exist_ok=True)

            run_policy_sweep_for_region(
                region=region,
                carbon_path=carbon_path,
                price_path=price_path,
                results_dir=str(week_results_dir),
                workload_name=args.workload_name,
                start_date=start_date,
                end_date=end_date,
            )

        except Exception as exc:  # noqa: BLE001
            errors.append(f"[{weekly_price_file.name}] {exc}")

    if errors:
        print("\nErrors encountered:")
        for err in errors:
            print(f"  ✗ {err}")
        raise SystemExit(1)

    print("\nAll weekly traces ingested and swept successfully.")

if __name__ == "__main__":
    main()