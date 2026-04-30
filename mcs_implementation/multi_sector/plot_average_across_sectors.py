from __future__ import annotations

from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt


RESULTS_ROOT = Path("mcs_implementation/results")
MULTI_WEEK_DIR = RESULTS_ROOT / "multi_week"
PLOTS_DIR = MULTI_WEEK_DIR / "plots"
PLOTS_DIR.mkdir(parents=True, exist_ok=True)

AVG_CSV = MULTI_WEEK_DIR / "average_policy_summary_across_weeks.csv"


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
        return f"price_only"
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


def main() -> None:
    if not AVG_CSV.exists():
        raise FileNotFoundError(f"Missing average summary CSV: {AVG_CSV}")

    df = pd.read_csv(AVG_CSV)
    df["family"] = df["policy_name"].apply(classify_family)
    df["short_label"] = df.apply(short_label, axis=1)
    df["sort_key"] = df.apply(family_sort_key, axis=1)

    family_colors = {
        "Baseline": "black",
        "Price Only": "tab:orange",
        "Option A": "tab:blue",
        "Option B": "tab:green",
        "Option C": "tab:red",
        "Other": "gray",
    }

    plt.figure(figsize=(12, 9))

    for family, group in df.groupby("family"):
        group_sorted = group.sort_values("sort_key")
        color = family_colors.get(family, "gray")

        if len(group_sorted) > 1:
            plt.plot(
                group_sorted["avg_total_carbon_grams"],
                group_sorted["avg_total_real_time_cost"],
                color=color,
                linewidth=2,
                alpha=0.8,
                label=family,
            )
        else:
            plt.plot([], [], color=color, linewidth=2, label=family)

        plt.scatter(
            group_sorted["avg_total_carbon_grams"],
            group_sorted["avg_total_real_time_cost"],
            color=color,
            s=90,
            edgecolors="white",
            linewidths=0.8,
            zorder=3,
        )

        for _, row in group_sorted.iterrows():
            plt.annotate(
                row["short_label"],
                (row["avg_total_carbon_grams"], row["avg_total_real_time_cost"]),
                textcoords="offset points",
                xytext=(6, 5),
                fontsize=8,
            )

    plt.xlabel("Average Total Carbon Emissions Across Weeks (gCO2eq)")
    plt.ylabel("Average Total Real-Time Cost Across Weeks")
    plt.title("Average Carbon vs Real-Time Cost Across Ontario Weeks")
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout()

    out = PLOTS_DIR / "average_tradeoff_across_weeks.png"
    plt.savefig(out, dpi=300, bbox_inches="tight")
    plt.close()

    print("Wrote:")
    print(out)


if __name__ == "__main__":
    main()