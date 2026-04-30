from __future__ import annotations

from pathlib import Path

import pandas as pd


RESULTS_ROOT = Path("mcs_implementation/results/sectors")
OUTPUT_DIR = Path("mcs_implementation/multi_sector/weekly_price_csvs/ercot_texas")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def discover_ercot_week_dirs() -> list[Path]:
    return sorted(
        [
            p for p in RESULTS_ROOT.iterdir()
            if p.is_dir() and p.name.startswith("texas_week")
        ]
    )


def load_week_summary(week_dir: Path) -> pd.DataFrame:
    path = week_dir / "policy_comparison_summary.csv"
    if not path.exists():
        raise FileNotFoundError(f"Missing summary CSV: {path}")

    df = pd.read_csv(path)
    df["week_slug"] = week_dir.name
    return df


def normalize_completed(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["completed"] = (
        out["completed"]
        .astype(str)
        .str.lower()
        .map({"true": True, "false": False})
    )
    return out


def build_combined_summary() -> pd.DataFrame:
    week_dirs = discover_ercot_week_dirs()

    if not week_dirs:
        raise FileNotFoundError(
            f"No ERCOT/Texas week directories found in {RESULTS_ROOT}. "
            "Expected folders named like texas_week01_..."
        )

    frames = [load_week_summary(week_dir) for week_dir in week_dirs]
    combined = pd.concat(frames, ignore_index=True)
    combined = normalize_completed(combined)
    return combined


def build_average_summary(combined: pd.DataFrame) -> pd.DataFrame:
    numeric_cols = [
        "total_work",
        "total_energy_kwh",
        "total_carbon_grams",
        "total_day_ahead_cost",
        "total_real_time_cost",
        "active_slots",
        "max_scale_used",
        "carbon_savings_vs_base_pct",
        "day_ahead_cost_savings_vs_base_pct",
        "real_time_cost_savings_vs_base_pct",
    ]

    group_cols = [
        "policy",
        "policy_name",
        "tie_threshold_ratio",
        "cost_budget_ratio",
        "cost_penalty_beta",
        "urgency_gamma",
        "lambda_carbon",
        "sweep_group",
    ]

    # Keep only columns that exist, so this works even if price_exponent is absent.
    group_cols = [c for c in group_cols if c in combined.columns]
    numeric_cols = [c for c in numeric_cols if c in combined.columns]

    avg = (
        combined.groupby(group_cols, dropna=False, as_index=False)
        .agg(
            week_count=("week_slug", "nunique"),
            completed=("completed", "mean"),
            avg_completion_slot=("completion_slot", "mean"),
            **{
                f"avg_{col}": (col, "mean")
                for col in numeric_cols
            },
        )
    )

    # Rename selected avg columns to match your plotting/header convention.
    rename_map = {
        "avg_total_carbon_grams": "total_carbon_grams",
        "avg_total_day_ahead_cost": "total_day_ahead_cost",
        "avg_total_real_time_cost": "total_real_time_cost",
        "avg_carbon_savings_vs_base_pct": "carbon_savings_vs_base_pct",
        "avg_real_time_cost_savings_vs_base_pct": "real_time_cost_savings_vs_base_pct",
    }
    avg = avg.rename(columns=rename_map)

    # Optional: also rename these so plots can read non-avg names.
    avg = avg.rename(
        columns={
            "avg_total_work": "total_work",
            "avg_total_energy_kwh": "total_energy_kwh",
            "avg_active_slots": "active_slots",
            "avg_max_scale_used": "max_scale_used",
            "avg_day_ahead_cost_savings_vs_base_pct": "day_ahead_cost_savings_vs_base_pct",
        }
    )

    return avg


def main() -> None:
    combined = build_combined_summary()

    combined_out = OUTPUT_DIR / "combined_weekly_policy_summary.csv"
    combined.to_csv(combined_out, index=False)

    avg = build_average_summary(combined)
    avg_out = OUTPUT_DIR / "average_policy_summary_across_weeks.csv"
    avg.to_csv(avg_out, index=False)

    print("Wrote:")
    print(combined_out)
    print(avg_out)


if __name__ == "__main__":
    main()