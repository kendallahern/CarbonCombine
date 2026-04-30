from __future__ import annotations

from pathlib import Path
import math

import matplotlib.pyplot as plt
import pandas as pd


RESULTS_ROOT = Path("mcs_implementation/results")
MULTI_WEEK_DIR = RESULTS_ROOT / "multi_week"
PLOTS_DIR = MULTI_WEEK_DIR / "plots"
PLOTS_DIR.mkdir(parents=True, exist_ok=True)

COMBINED_CSV = MULTI_WEEK_DIR / "combined_weekly_policy_summary.csv"


def classify_family(policy_name: str) -> str:
    if policy_name == "carbonscaler":
        return "Baseline"
    if policy_name == "price_only":
        return "Price Only"
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
    if policy_name == "price_only":
        # return f"P-{row.get('price_exponent', '')}"
        return "price_only"
    if policy_name == "carbonscaler_price_tiebreak":
        return f"A-{row.get('tie_threshold_ratio', '')}"
    if policy_name == "carbonscaler_budget":
        return (
            f"B-{row.get('cost_budget_ratio', '')}"
            f"|b{row.get('cost_penalty_beta', '')}"
            f"|g{row.get('urgency_gamma', '')}"
        )
    if policy_name == "carbonscaler_weighted":
        return f"C-{row.get('lambda_carbon', '')}"
    return str(row["policy"])


def family_sort_key(row: pd.Series) -> float:
    policy_name = str(row["policy_name"])

    if policy_name == "carbonscaler":
        return 0.0

    if policy_name == "price_only":
        # try:
        #     return float(row.get("price_exponent", 0))
        # except Exception:
        #     return 0.0
        return 0.0

    if policy_name == "carbonscaler_price_tiebreak":
        try:
            return float(row.get("tie_threshold_ratio", 0))
        except Exception:
            return 0.0

    if policy_name == "carbonscaler_budget":
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


def load_combined() -> pd.DataFrame:
    if not COMBINED_CSV.exists():
        raise FileNotFoundError(f"Missing combined weekly CSV: {COMBINED_CSV}")

    df = pd.read_csv(COMBINED_CSV)
    df["family"] = df["policy_name"].apply(classify_family)
    df["short_label"] = df.apply(short_label, axis=1)
    df["sort_key"] = df.apply(family_sort_key, axis=1)
    df["completed"] = (
        df["completed"].astype(str).str.lower().map({"true": True, "false": False})
    )
    return df


def summarize_policy_variability(df: pd.DataFrame) -> pd.DataFrame:
    numeric_cols = [
        "total_carbon_grams",
        "total_day_ahead_cost",
        "total_real_time_cost",
        "carbon_savings_vs_base_pct",
        "day_ahead_cost_savings_vs_base_pct",
        "real_time_cost_savings_vs_base_pct",
        "completion_slot",
    ]

    agg_map: dict[str, tuple[str, str]] = {
        "family": ("family", "first"),
        "short_label": ("short_label", "first"),
        "sort_key": ("sort_key", "first"),
        "week_count": ("week_slug", "nunique"),
        "completion_rate": ("completed", "mean"),
    }

    for col in numeric_cols:
        agg_map[f"avg_{col}"] = (col, "mean")
        agg_map[f"std_{col}"] = (col, "std")

    summary = (
        df.groupby(
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
        .agg(**agg_map)
    )

    summary = summary.sort_values(["family", "sort_key", "policy"])
    return summary


def plot_errorbar_tradeoff(
    summary: pd.DataFrame,
    x_avg: str,
    x_std: str,
    y_avg: str,
    y_std: str,
    xlabel: str,
    ylabel: str,
    title: str,
    filename: str,
) -> None:
    family_colors = {
        "Baseline": "black",
        "Price Only": "tab:orange",
        "Option A": "tab:blue",
        "Option B": "tab:green",
        "Option C": "tab:red",
        "Other": "gray",
    }

    plt.figure(figsize=(12, 9))

    for family, group in summary.groupby("family"):
        group_sorted = group.sort_values("sort_key")
        color = family_colors.get(family, "gray")

        # trend line through means
        if len(group_sorted) > 1:
            plt.plot(
                group_sorted[x_avg],
                group_sorted[y_avg],
                color=color,
                linewidth=2,
                alpha=0.8,
                label=family,
            )
        else:
            plt.plot([], [], color=color, linewidth=2, label=family)

        plt.errorbar(
            group_sorted[x_avg],
            group_sorted[y_avg],
            xerr=group_sorted[x_std].fillna(0.0),
            yerr=group_sorted[y_std].fillna(0.0),
            fmt="o",
            color=color,
            ecolor=color,
            elinewidth=1.2,
            capsize=3,
            markersize=7,
            alpha=0.95,
        )

        for _, row in group_sorted.iterrows():
            plt.annotate(
                row["short_label"],
                (row[x_avg], row[y_avg]),
                textcoords="offset points",
                xytext=(6, 5),
                fontsize=8,
            )

    plt.xlabel(xlabel)
    plt.ylabel(ylabel)
    plt.title(title)
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.savefig(PLOTS_DIR / filename, dpi=300, bbox_inches="tight")
    plt.close()


def plot_variability_bars(
    summary: pd.DataFrame,
    value_col: str,
    ylabel: str,
    title: str,
    filename: str,
) -> None:
    # rank by average performance, lowest is best for cost/carbon std
    top = summary.sort_values(value_col).head(15).copy()

    plt.figure(figsize=(13, 7))
    plt.bar(range(len(top)), top[value_col].fillna(0.0))
    plt.xticks(range(len(top)), top["short_label"], rotation=45, ha="right")
    plt.ylabel(ylabel)
    plt.title(title)
    plt.grid(True, axis="y", alpha=0.3)
    plt.tight_layout()
    plt.savefig(PLOTS_DIR / filename, dpi=300, bbox_inches="tight")
    plt.close()


def plot_completion_stability(summary: pd.DataFrame) -> None:
    ranked = summary.sort_values(["completion_rate", "avg_completion_slot"], ascending=[False, True]).copy()

    plt.figure(figsize=(13, 7))
    plt.bar(range(len(ranked)), ranked["completion_rate"].fillna(0.0))
    plt.xticks(range(len(ranked)), ranked["short_label"], rotation=45, ha="right")
    plt.ylabel("Completion Rate Across Weeks")
    plt.title("Policy Completion Stability Across Weeks")
    plt.ylim(0, 1.05)
    plt.grid(True, axis="y", alpha=0.3)
    plt.tight_layout()
    plt.savefig(PLOTS_DIR / "completion_rate_across_weeks.png", dpi=300, bbox_inches="tight")
    plt.close()


def main() -> None:
    df = load_combined()
    summary = summarize_policy_variability(df)

    summary_out = MULTI_WEEK_DIR / "policy_variability_summary_across_weeks.csv"
    summary.to_csv(summary_out, index=False)

    plot_errorbar_tradeoff(
        summary=summary,
        x_avg="avg_total_carbon_grams",
        x_std="std_total_carbon_grams",
        y_avg="avg_total_real_time_cost",
        y_std="std_total_real_time_cost",
        xlabel="Average Carbon Across Weeks (gCO2eq)",
        ylabel="Average Real-Time Cost Across Weeks",
        title="Average Carbon vs Real-Time Cost with Week-to-Week Variability",
        filename="variability_tradeoff_carbon_vs_rt_cost.png",
    )

    plot_errorbar_tradeoff(
        summary=summary,
        x_avg="avg_carbon_savings_vs_base_pct",
        x_std="std_carbon_savings_vs_base_pct",
        y_avg="avg_real_time_cost_savings_vs_base_pct",
        y_std="std_real_time_cost_savings_vs_base_pct",
        xlabel="Average Carbon Savings vs Baseline (%)",
        ylabel="Average Real-Time Cost Savings vs Baseline (%)",
        title="Average Savings Tradeoff with Week-to-Week Variability",
        filename="variability_savings_tradeoff.png",
    )

    plot_variability_bars(
        summary=summary,
        value_col="std_total_real_time_cost",
        ylabel="Std Dev of Real-Time Cost Across Weeks",
        title="Real-Time Cost Variability Across Weeks",
        filename="variability_rt_cost_std_bar.png",
    )

    plot_variability_bars(
        summary=summary,
        value_col="std_total_carbon_grams",
        ylabel="Std Dev of Carbon Across Weeks",
        title="Carbon Variability Across Weeks",
        filename="variability_carbon_std_bar.png",
    )

    plot_completion_stability(summary)

    print("Wrote:")
    print(summary_out)
    print(PLOTS_DIR)


if __name__ == "__main__":
    main()