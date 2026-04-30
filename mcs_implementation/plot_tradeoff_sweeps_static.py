from __future__ import annotations

from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt


RESULTS_DIR = Path("mcs_implementation/results")
SUMMARY_CSV = RESULTS_DIR / "policy_comparison_summary.csv"
PLOTS_DIR = RESULTS_DIR / "plots_static"


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
        "carbon_savings_vs_base_pct",
        "real_time_cost_savings_vs_base_pct",
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


def add_metadata(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["family"] = out["policy_name"].apply(classify_family)
    out["short_label"] = out.apply(short_label, axis=1)
    out["sort_key"] = out.apply(family_sort_key, axis=1)
    out["completed_bool"] = out["completed"].astype(str).str.lower().map(
        {"true": True, "false": False}
    ).fillna(out["completed"])
    return out


def compute_pareto(df: pd.DataFrame, x_col: str, y_col: str) -> pd.DataFrame:
    points = df[[x_col, y_col, "policy"]].sort_values([x_col, y_col]).reset_index(drop=True)

    pareto_indices = []
    best_y = float("inf")
    for idx, row in points.iterrows():
        if row[y_col] < best_y:
            pareto_indices.append(idx)
            best_y = row[y_col]

    return points.iloc[pareto_indices]


def save_tradeoff_plot(
    df: pd.DataFrame,
    y_col: str,
    y_label: str,
    title: str,
    filename: str,
    with_frontier: bool = False,
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

    for family, group in df.groupby("family"):
        group_sorted = group.sort_values("sort_key")
        color = family_colors.get(family, "gray")

        # trend line
        if len(group_sorted) > 1:
            plt.plot(
                group_sorted["total_carbon_grams"],
                group_sorted[y_col],
                color=color,
                linewidth=2,
                alpha=0.75,
                label=family,
            )
        else:
            plt.plot([], [], color=color, linewidth=2, label=family)

        complete_group = group_sorted[group_sorted["completed_bool"] == True]
        incomplete_group = group_sorted[group_sorted["completed_bool"] != True]

        if not complete_group.empty:
            plt.scatter(
                complete_group["total_carbon_grams"],
                complete_group[y_col],
                color=color,
                s=90,
                marker="o",
                edgecolors="white",
                linewidths=0.8,
                zorder=3,
            )

        if not incomplete_group.empty:
            plt.scatter(
                incomplete_group["total_carbon_grams"],
                incomplete_group[y_col],
                color=color,
                s=100,
                marker="x",
                linewidths=2,
                zorder=3,
            )

        for _, row in group_sorted.iterrows():
            plt.annotate(
                row["short_label"],
                (row["total_carbon_grams"], row[y_col]),
                textcoords="offset points",
                xytext=(6, 5),
                fontsize=8,
            )

    if with_frontier:
        frontier = compute_pareto(df, "total_carbon_grams", y_col)
        plt.plot(
            frontier["total_carbon_grams"],
            frontier[y_col],
            linestyle="--",
            linewidth=2.5,
            color="purple",
            marker="D",
            markersize=5,
            label="Pareto-like frontier",
            zorder=2,
        )

    plt.xlabel("Total Carbon Emissions (gCO2eq)")
    plt.ylabel(y_label)
    plt.title(title)
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.savefig(PLOTS_DIR / filename, dpi=300, bbox_inches="tight")
    plt.close()


def save_savings_tradeoff(df: pd.DataFrame, filename: str) -> None:
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
                linewidth=2,
                alpha=0.75,
                label=family,
            )
        else:
            plt.plot([], [], color=color, linewidth=2, label=family)

        complete_group = group_sorted[group_sorted["completed_bool"] == True]
        incomplete_group = group_sorted[group_sorted["completed_bool"] != True]

        if not complete_group.empty:
            plt.scatter(
                complete_group["carbon_savings_vs_base_pct"],
                complete_group["real_time_cost_savings_vs_base_pct"],
                color=color,
                s=90,
                marker="o",
                edgecolors="white",
                linewidths=0.8,
                zorder=3,
            )

        if not incomplete_group.empty:
            plt.scatter(
                incomplete_group["carbon_savings_vs_base_pct"],
                incomplete_group["real_time_cost_savings_vs_base_pct"],
                color=color,
                s=100,
                marker="x",
                linewidths=2,
                zorder=3,
            )

        for _, row in group_sorted.iterrows():
            plt.annotate(
                row["short_label"],
                (
                    row["carbon_savings_vs_base_pct"],
                    row["real_time_cost_savings_vs_base_pct"],
                ),
                textcoords="offset points",
                xytext=(6, 5),
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
    plt.savefig(PLOTS_DIR / filename, dpi=300, bbox_inches="tight")
    plt.close()


def main() -> None:
    df = load_summary()
    df = add_metadata(df)

    save_tradeoff_plot(
        df=df,
        y_col="total_day_ahead_cost",
        y_label="Total Day-Ahead Cost",
        title="Carbon vs Day-Ahead Cost Across All Policy Sweeps",
        filename="tradeoff_carbon_vs_day_ahead_cost_static.png",
        with_frontier=False,
    )

    save_tradeoff_plot(
        df=df,
        y_col="total_real_time_cost",
        y_label="Total Real-Time Cost",
        title="Carbon vs Real-Time Cost Across All Policy Sweeps",
        filename="tradeoff_carbon_vs_real_time_cost_static.png",
        with_frontier=True,
    )

    save_savings_tradeoff(
        df=df,
        filename="savings_tradeoff_static.png",
    )

    print("Wrote static plots to:")
    print(PLOTS_DIR.resolve())


if __name__ == "__main__":
    main()