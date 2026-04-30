from __future__ import annotations

from pathlib import Path
import pandas as pd


RESULTS_ROOT = Path("mcs_implementation/results")
WEEKLY_RESULTS_DIR = RESULTS_ROOT / "sectors"
MULTI_WEEK_DIR = RESULTS_ROOT / "multi_week"
MULTI_WEEK_DIR.mkdir(parents=True, exist_ok=True)


def discover_week_dirs() -> list[Path]:
    return sorted(
        [
            p for p in WEEKLY_RESULTS_DIR.iterdir()
            if p.is_dir() and p.name.startswith("ontario_week")
        ]
    )


def load_week_summary(week_dir: Path) -> pd.DataFrame:
    summary_path = week_dir / "policy_comparison_summary.csv"
    if not summary_path.exists():
        raise FileNotFoundError(f"Missing summary CSV: {summary_path}")

    df = pd.read_csv(summary_path)
    df["week_slug"] = week_dir.name
    return df


def build_combined_summary() -> pd.DataFrame:
    week_dirs = discover_week_dirs()
    if not week_dirs:
        raise FileNotFoundError(f"No Ontario week directories found in {WEEKLY_RESULTS_DIR}")

    frames = [load_week_summary(week_dir) for week_dir in week_dirs]
    combined = pd.concat(frames, ignore_index=True)

    combined["completed"] = (
        combined["completed"].astype(str).str.lower().map({"true": True, "false": False})
    )

    return combined


def build_policy_average_summary(combined: pd.DataFrame) -> pd.DataFrame:
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

    agg = (
        combined.groupby(
            [
                "policy",
                "policy_name",
                "tie_threshold_ratio",
                "cost_budget_ratio",
                "cost_penalty_beta",
                "urgency_gamma",
                "lambda_carbon",
                # "price_exponent",
                "sweep_group",
            ],
            dropna=False,
            as_index=False,
        )
        .agg(
            week_count=("week_slug", "nunique"),
            completion_rate=("completed", "mean"),
            avg_completion_slot=("completion_slot", "mean"),
            **{f"avg_{col}": (col, "mean") for col in numeric_cols},
        )
    )

    return agg


def main() -> None:
    combined = build_combined_summary()
    combined_out = MULTI_WEEK_DIR / "combined_weekly_policy_summary.csv"
    combined.to_csv(combined_out, index=False)

    avg_df = build_policy_average_summary(combined)
    avg_out = MULTI_WEEK_DIR / "average_policy_summary_across_weeks.csv"
    avg_df.to_csv(avg_out, index=False)

    print("Wrote:")
    print(combined_out)
    print(avg_out)


if __name__ == "__main__":
    main()