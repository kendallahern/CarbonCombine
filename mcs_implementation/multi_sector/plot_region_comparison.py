from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt


ONTARIO_PATH = Path(
    "mcs_implementation/multi_sector/weekly_price_csvs/ontario/average_policy_summary_across_weeks.csv"
)

TEXAS_PATH = Path(
    "mcs_implementation/multi_sector/weekly_price_csvs/ercot_texas/average_policy_summary_across_weeks.csv"
)

OUTPUT_DIR = Path(
    "mcs_implementation/multi_sector/weekly_price_csvs/region_comparison_plots"
)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def load_df(path: Path, region: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["region"] = region

    required = {
        "policy",
        "policy_name",
        "total_carbon_grams",
        "total_day_ahead_cost",
        "total_real_time_cost",
    }
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"{path} is missing columns: {sorted(missing)}")

    df["cost_gap"] = df["total_real_time_cost"] - df["total_day_ahead_cost"]

    return df


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


def main() -> None:
    ontario = load_df(ONTARIO_PATH, "Ontario")
    texas = load_df(TEXAS_PATH, "Texas")

    combined = pd.concat([ontario, texas], ignore_index=True)
    combined["family"] = combined["policy_name"].apply(classify_family)

    # Match exact policy + parameter combination across regions
    matching_policies = sorted(
        set(ontario["policy"]).intersection(set(texas["policy"]))
    )

    if not matching_policies:
        raise ValueError("No matching policy names found between Ontario and Texas CSVs.")

    print(f"Matched policies: {len(matching_policies)}")

    family_colors = {
        "Baseline": "black",
        "Price Only": "tab:orange",
        "Option A": "tab:blue",
        "Option B": "tab:green",
        "Option C": "tab:red",
        "Other": "gray",
    }

    fig, ax = plt.subplots(figsize=(14, 9))

    for policy in matching_policies:
        ont_row = ontario[ontario["policy"] == policy].iloc[0]
        tex_row = texas[texas["policy"] == policy].iloc[0]

        family = classify_family(str(ont_row["policy_name"]))
        color = family_colors.get(family, "gray")

        # line connecting same policy across regions
        ax.plot(
            [ont_row["total_carbon_grams"], tex_row["total_carbon_grams"]],
            [ont_row["cost_gap"], tex_row["cost_gap"]],
            color=color,
            linestyle="--",
            alpha=0.45,
            linewidth=1.2,
        )

        # Ontario point
        ax.scatter(
            ont_row["total_carbon_grams"],
            ont_row["cost_gap"],
            color=color,
            marker="o",
            s=70,
            edgecolors="white",
            linewidths=0.8,
            zorder=3,
        )

        # Texas point
        ax.scatter(
            tex_row["total_carbon_grams"],
            tex_row["cost_gap"],
            color=color,
            marker="^",
            s=80,
            edgecolors="white",
            linewidths=0.8,
            zorder=3,
        )

    # legend by family
    for family, color in family_colors.items():
        if family in combined["family"].unique():
            ax.scatter([], [], color=color, label=family)

    # marker legend
    ax.scatter([], [], color="gray", marker="o", label="Ontario")
    ax.scatter([], [], color="gray", marker="^", label="Texas")

    ax.axhline(0, color="gray", linestyle="--", linewidth=1, alpha=0.6)

    ax.set_xlabel("Average Carbon Emissions (gCO2eq)")
    ax.set_ylabel("Average Cost Gap: Real-Time Cost - Day-Ahead Cost")
    ax.set_title("Policy Generalization: Ontario vs ERCOT/Texas")

    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=9, loc="best")
    plt.tight_layout()

    out_path = OUTPUT_DIR / "ontario_vs_texas_all_policies_cost_gap_vs_carbon.png"
    plt.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close()

    print(f"Saved: {out_path}")


if __name__ == "__main__":
    main()