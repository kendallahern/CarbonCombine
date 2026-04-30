from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt


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
        # alpha = row.get("price_exponent", "")
        return "price_only"
    if policy_name == "carbonscaler_price_tiebreak":
        val = row.get("tie_threshold_ratio", "")
        return f"A-{val}"
    if policy_name == "carbonscaler_budget":
        b = row.get("cost_budget_ratio", "")
        beta = row.get("cost_penalty_beta", "")
        gamma = row.get("urgency_gamma", "")
        return f"B-{b}|b{beta}|g{gamma}"
    if policy_name == "carbonscaler_weighted":
        lam = row.get("lambda_carbon", "")
        return f"C-{lam}"

    return str(row["policy"])


def pick_top5_for_week(df: pd.DataFrame) -> pd.DataFrame:
    completed = df[df["completed"] == True].copy()
    if completed.empty:
        return completed

    carbon = completed["total_carbon_grams"].astype(float)
    rt_cost = completed["total_real_time_cost"].astype(float)

    carbon_norm = (carbon - carbon.min()) / max(carbon.max() - carbon.min(), 1e-9)
    rt_norm = (rt_cost - rt_cost.min()) / max(rt_cost.max() - rt_cost.min(), 1e-9)

    completed["selection_score"] = 0.5 * carbon_norm + 0.5 * rt_norm
    return completed.sort_values("selection_score").head(5).copy()


def main() -> None:
    if not COMBINED_CSV.exists():
        raise FileNotFoundError(f"Missing combined summary CSV: {COMBINED_CSV}")

    df = pd.read_csv(COMBINED_CSV)
    df["family"] = df["policy_name"].apply(classify_family)
    df["short_label"] = df.apply(short_label, axis=1)

    family_colors = {
        "Baseline": "black",
        "Price Only": "tab:orange",
        "Option A": "tab:blue",
        "Option B": "tab:green",
        "Option C": "tab:red",
        "Other": "gray",
    }

    week_slugs = sorted(df["week_slug"].dropna().unique())
    n = len(week_slugs)
    ncols = 2
    nrows = int(np.ceil(n / ncols))

    fig, axes = plt.subplots(nrows=nrows, ncols=ncols, figsize=(14, 5 * nrows))
    axes = np.array(axes).reshape(-1)

    for ax, week_slug in zip(axes, week_slugs):
        week_df = df[df["week_slug"] == week_slug].copy()
        top5 = pick_top5_for_week(week_df)

        completed = week_df[week_df["completed"] == True].copy()

        ax.scatter(
            completed["total_carbon_grams"],
            completed["total_real_time_cost"],
            color="lightgray",
            s=45,
            alpha=0.6,
            label="Completed policies",
        )

        for _, row in top5.iterrows():
            color = family_colors.get(row["family"], "gray")
            ax.scatter(
                row["total_carbon_grams"],
                row["total_real_time_cost"],
                color=color,
                s=90,
                edgecolors="white",
                linewidths=0.8,
                zorder=3,
            )
            ax.annotate(
                row["short_label"],
                (row["total_carbon_grams"], row["total_real_time_cost"]),
                textcoords="offset points",
                xytext=(6, 5),
                fontsize=8,
            )

        ax.set_title(f"Top 5 Policies: {week_slug}")
        ax.set_xlabel("Total Carbon Emissions (gCO2eq)")
        ax.set_ylabel("Total Real-Time Cost")
        ax.grid(True, alpha=0.3)

    for ax in axes[len(week_slugs):]:
        ax.axis("off")

    plt.tight_layout()
    out = PLOTS_DIR / "top5_policies_by_week.png"
    plt.savefig(out, dpi=300, bbox_inches="tight")
    plt.close()

    top_rows = []
    for week_slug in week_slugs:
        week_df = df[df["week_slug"] == week_slug].copy()
        top5 = pick_top5_for_week(week_df)
        top_rows.append(top5)

    top5_df = pd.concat(top_rows, ignore_index=True)
    top5_out = MULTI_WEEK_DIR / "top5_policies_by_week.csv"
    top5_df.to_csv(top5_out, index=False)

    print("Wrote:")
    print(out)
    print(top5_out)


if __name__ == "__main__":
    main()