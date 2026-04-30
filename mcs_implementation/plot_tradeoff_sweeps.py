from __future__ import annotations

from pathlib import Path
import re

import pandas as pd
import matplotlib.pyplot as plt


RESULTS_DIR = Path("mcs_implementation/results")
SUMMARY_CSV = RESULTS_DIR / "policy_comparison_summary.csv"
PLOTS_DIR = RESULTS_DIR / "plots"


def load_summary() -> pd.DataFrame:
    if not SUMMARY_CSV.exists():
        raise FileNotFoundError(f"Missing summary CSV: {SUMMARY_CSV}")

    df = pd.read_csv(SUMMARY_CSV)

    required = {
        "policy",
        "policy_name",
        "total_carbon_grams",
        "total_day_ahead_cost",
        "total_real_time_cost",
        "completed",
    }
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns in summary CSV: {sorted(missing)}")

    return df


def classify_family(policy_name: str) -> str:
    if policy_name == "carbonscaler":
        return "Baseline"
    if policy_name == "carbonscaler_price_tiebreak":
        return "Option A"
    if policy_name == "carbonscaler_budget":
        return "Option B"
    if policy_name == "carbonscaler_weighted":
        return "Option C"
    return "Other"


def short_label(row: pd.Series) -> str:
    policy_name = str(row["policy_name"])

    if policy_name == "carbonscaler":
        return "Base"

    if policy_name == "carbonscaler_price_tiebreak":
        val = row.get("tie_threshold_ratio", "")
        return f"A-{val}"

    if policy_name == "carbonscaler_budget":
        budget = row.get("cost_budget_ratio", "")
        beta = row.get("cost_penalty_beta", "")
        gamma = row.get("urgency_gamma", "")
        return f"B-{budget}|b{beta}|g{gamma}"

    if policy_name == "carbonscaler_weighted":
        lam = row.get("lambda_carbon", "")
        return f"C-{lam}"

    return str(row["policy"])


def family_sort_key(row: pd.Series) -> float:
    policy_name = str(row["policy_name"])

    if policy_name == "carbonscaler":
        return 0.0

    if policy_name == "carbonscaler_price_tiebreak":
        try:
            return float(row.get("tie_threshold_ratio", 0))
        except Exception:
            return 0.0

    if policy_name == "carbonscaler_budget":
        # Sort by budget, then beta, then gamma
        try:
            budget = float(row.get("cost_budget_ratio", 0))
        except Exception:
            budget = 0.0
        try:
            beta = float(row.get("cost_penalty_beta", 0))
        except Exception:
            beta = 0.0
        try:
            gamma = float(row.get("urgency_gamma", 0))
        except Exception:
            gamma = 0.0
        return budget * 1000 + beta * 100 + gamma

    if policy_name == "carbonscaler_weighted":
        try:
            return float(row.get("lambda_carbon", 0))
        except Exception:
            return 0.0

    return 0.0


def add_family_and_labels(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["family"] = out["policy_name"].apply(classify_family)
    out["short_label"] = out.apply(short_label, axis=1)
    out["sort_key"] = out.apply(family_sort_key, axis=1)
    return out


def plot_tradeoff(
    df: pd.DataFrame,
    y_col: str,
    y_label: str,
    filename: str,
) -> None:
    PLOTS_DIR.mkdir(parents=True, exist_ok=True)

    family_colors = {
        "Baseline": "black",
        "Option A": "tab:blue",
        "Option B": "tab:green",
        "Option C": "tab:red",
        "Other": "gray",
    }

    plt.figure(figsize=(11, 8))

    # Plot trend lines per family
    for family, group in df.groupby("family"):
        group_sorted = group.sort_values("sort_key")

        color = family_colors.get(family, "gray")
        marker = "o"

        # Use x markers for incomplete schedules
        complete_group = group_sorted[group_sorted["completed"] == True]
        incomplete_group = group_sorted[group_sorted["completed"] != True]

        if len(group_sorted) > 1:
            plt.plot(
                group_sorted["total_carbon_grams"],
                group_sorted[y_col],
                color=color,
                linewidth=1.8,
                alpha=0.8,
                label=family,
            )
        else:
            # ensure family still shows in legend
            plt.plot(
                [],
                [],
                color=color,
                linewidth=1.8,
                label=family,
            )

        if not complete_group.empty:
            plt.scatter(
                complete_group["total_carbon_grams"],
                complete_group[y_col],
                color=color,
                marker="o",
                s=75,
                alpha=0.95,
            )

        if not incomplete_group.empty:
            plt.scatter(
                incomplete_group["total_carbon_grams"],
                incomplete_group[y_col],
                color=color,
                marker="x",
                s=85,
                alpha=0.95,
            )

        for _, row in group_sorted.iterrows():
            plt.annotate(
                row["short_label"],
                (row["total_carbon_grams"], row[y_col]),
                textcoords="offset points",
                xytext=(6, 6),
                fontsize=8,
            )

    plt.xlabel("Total Carbon Emissions (gCO2eq)")
    plt.ylabel(y_label)
    plt.title(f"Carbon vs {y_label} Across All Policy Sweeps")
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.savefig(PLOTS_DIR / filename, dpi=220)
    plt.close()


def plot_tradeoff_with_savings_axes(df: pd.DataFrame, filename: str) -> None:
    """
    Optional complementary plot:
    x-axis = carbon savings vs baseline
    y-axis = real-time cost savings vs baseline
    """
    if "carbon_savings_vs_base_pct" not in df.columns or "real_time_cost_savings_vs_base_pct" not in df.columns:
        return

    PLOTS_DIR.mkdir(parents=True, exist_ok=True)

    family_colors = {
        "Baseline": "black",
        "Option A": "tab:blue",
        "Option B": "tab:green",
        "Option C": "tab:red",
        "Other": "gray",
    }

    plt.figure(figsize=(11, 8))

    for family, group in df.groupby("family"):
        group_sorted = group.sort_values("sort_key")
        color = family_colors.get(family, "gray")

        if len(group_sorted) > 1:
            plt.plot(
                group_sorted["carbon_savings_vs_base_pct"],
                group_sorted["real_time_cost_savings_vs_base_pct"],
                color=color,
                linewidth=1.8,
                alpha=0.8,
                label=family,
            )
        else:
            plt.plot([], [], color=color, linewidth=1.8, label=family)

        complete_group = group_sorted[group_sorted["completed"] == True]
        incomplete_group = group_sorted[group_sorted["completed"] != True]

        if not complete_group.empty:
            plt.scatter(
                complete_group["carbon_savings_vs_base_pct"],
                complete_group["real_time_cost_savings_vs_base_pct"],
                color=color,
                marker="o",
                s=75,
                alpha=0.95,
            )

        if not incomplete_group.empty:
            plt.scatter(
                incomplete_group["carbon_savings_vs_base_pct"],
                incomplete_group["real_time_cost_savings_vs_base_pct"],
                color=color,
                marker="x",
                s=85,
                alpha=0.95,
            )

        for _, row in group_sorted.iterrows():
            plt.annotate(
                row["short_label"],
                (
                    row["carbon_savings_vs_base_pct"],
                    row["real_time_cost_savings_vs_base_pct"],
                ),
                textcoords="offset points",
                xytext=(6, 6),
                fontsize=8,
            )

    plt.axvline(0, color="gray", linewidth=1, alpha=0.5)
    plt.axhline(0, color="gray", linewidth=1, alpha=0.5)
    plt.xlabel("Carbon Savings vs Baseline (%)")
    plt.ylabel("Real-Time Cost Savings vs Baseline (%)")
    plt.title("Savings Tradeoff Across All Policy Sweeps")
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.savefig(PLOTS_DIR / filename, dpi=220)
    plt.close()


def main() -> None:
    df = load_summary()
    df = add_family_and_labels(df)

    plot_tradeoff(
        df=df,
        y_col="total_day_ahead_cost",
        y_label="Total Day-Ahead Cost",
        filename="all_policies_tradeoff_carbon_vs_day_ahead_cost.png",
    )

    plot_tradeoff(
        df=df,
        y_col="total_real_time_cost",
        y_label="Total Real-Time Cost",
        filename="all_policies_tradeoff_carbon_vs_real_time_cost.png",
    )

    plot_tradeoff_with_savings_axes(
        df=df,
        filename="all_policies_savings_tradeoff.png",
    )

    print("Wrote plots to:")
    print(PLOTS_DIR.resolve())


if __name__ == "__main__":
    main()