from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt


ONTARIO_PATH = Path(
    "mcs_implementation/multi_sector/weekly_price_csvs/ontario/combined_weekly_policy_summary.csv"
)

TEXAS_PATH = Path(
    "mcs_implementation/multi_sector/weekly_price_csvs/ercot_texas/combined_weekly_policy_summary.csv"
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
        "week_slug",
        "total_carbon_grams",
        "total_day_ahead_cost",
        "total_real_time_cost",
        "completed",
    }
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"{path} is missing columns: {sorted(missing)}")

    df["completed_bool"] = (
        df["completed"].astype(str).str.lower().map({"true": True, "false": False})
    )

    df = df[df["completed_bool"] == True].copy()

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


def plot_all_weekly_points(ontario: pd.DataFrame, texas: pd.DataFrame) -> None:
    combined = pd.concat([ontario, texas], ignore_index=True)
    combined["family"] = combined["policy_name"].apply(classify_family)

    family_colors = {
        "Baseline": "black",
        "Price Only": "tab:orange",
        "Option A": "tab:blue",
        "Option B": "tab:green",
        "Option C": "tab:red",
        "Other": "gray",
    }

    fig, ax = plt.subplots(figsize=(14, 9))

    for family, group in combined.groupby("family"):
        color = family_colors.get(family, "gray")

        ont = group[group["region"] == "Ontario"]
        tex = group[group["region"] == "Texas"]

        if not ont.empty:
            ax.scatter(
                ont["total_carbon_grams"],
                ont["cost_gap"],
                color=color,
                marker="o",
                s=45,
                alpha=0.45,
                label=f"{family} - Ontario",
            )

        if not tex.empty:
            ax.scatter(
                tex["total_carbon_grams"],
                tex["cost_gap"],
                color=color,
                marker="^",
                s=50,
                alpha=0.45,
                label=f"{family} - Texas",
            )

    ax.axhline(0, color="gray", linestyle="--", linewidth=1, alpha=0.6)

    ax.set_xlabel("Weekly Carbon Emissions (gCO2eq)")
    ax.set_ylabel("Weekly Cost Gap: Real-Time Cost - Day-Ahead Cost")
    ax.set_title("Weekly Policy Generalization: Ontario vs ERCOT/Texas")

    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8, loc="best")
    plt.tight_layout()

    out = OUTPUT_DIR / "weekly_ontario_vs_texas_all_points_cost_gap_vs_carbon.png"
    plt.savefig(out, dpi=300, bbox_inches="tight")
    plt.close()

    print(f"Saved: {out}")


# def plot_week_matched_policy_lines(ontario: pd.DataFrame, texas: pd.DataFrame) -> None:
#     """
#     Connects Ontario and Texas for the same policy and same week label.

#     This assumes week_slug contains weekXX somewhere in the name.
#     """
#     def extract_week_label(week_slug: str) -> str:
#         for part in str(week_slug).split("_"):
#             if part.startswith("week"):
#                 return part
#         return str(week_slug)

#     ont = ontario.copy()
#     tex = texas.copy()

#     ont["week_label"] = ont["week_slug"].apply(extract_week_label)
#     tex["week_label"] = tex["week_slug"].apply(extract_week_label)

#     ont["match_key"] = ont["policy"].astype(str) + "_" + ont["week_label"].astype(str)
#     tex["match_key"] = tex["policy"].astype(str) + "_" + tex["week_label"].astype(str)

#     matching_keys = sorted(set(ont["match_key"]) & set(tex["match_key"]))

#     fig, ax = plt.subplots(figsize=(14, 9))

#     family_colors = {
#         "Baseline": "black",
#         "Price Only": "tab:orange",
#         "Option A": "tab:blue",
#         "Option B": "tab:green",
#         "Option C": "tab:red",
#         "Other": "gray",
#     }

#     for key in matching_keys:
#         ont_row = ont[ont["match_key"] == key].iloc[0]
#         tex_row = tex[tex["match_key"] == key].iloc[0]

#         family = classify_family(str(ont_row["policy_name"]))
#         color = family_colors.get(family, "gray")

#         ax.plot(
#             [ont_row["total_carbon_grams"], tex_row["total_carbon_grams"]],
#             [ont_row["cost_gap"], tex_row["cost_gap"]],
#             color=color,
#             linestyle="--",
#             alpha=0.18,
#             linewidth=0.9,
#         )

#         ax.scatter(
#             ont_row["total_carbon_grams"],
#             ont_row["cost_gap"],
#             color=color,
#             marker="o",
#             s=35,
#             alpha=0.65,
#             edgecolors="white",
#             linewidths=0.5,
#         )

#         ax.scatter(
#             tex_row["total_carbon_grams"],
#             tex_row["cost_gap"],
#             color=color,
#             marker="^",
#             s=40,
#             alpha=0.65,
#             edgecolors="white",
#             linewidths=0.5,
#         )

#     for family, color in family_colors.items():
#         ax.scatter([], [], color=color, label=family)

#     ax.scatter([], [], color="gray", marker="o", label="Ontario")
#     ax.scatter([], [], color="gray", marker="^", label="Texas")

#     ax.axhline(0, color="gray", linestyle="--", linewidth=1, alpha=0.6)

#     ax.set_xlabel("Weekly Carbon Emissions (gCO2eq)")
#     ax.set_ylabel("Weekly Cost Gap: Real-Time Cost - Day-Ahead Cost")
#     ax.set_title("Matched Weekly Policy Shifts: Ontario vs ERCOT/Texas")

#     ax.grid(True, alpha=0.3)
#     ax.legend(fontsize=8, loc="best")
#     plt.tight_layout()

#     out = OUTPUT_DIR / "weekly_ontario_vs_texas_matched_policy_lines.png"
#     plt.savefig(out, dpi=300, bbox_inches="tight")
#     plt.close()

#     print(f"Saved: {out}")

def plot_each_week_individually(ontario: pd.DataFrame, texas: pd.DataFrame) -> None:
    """
    Creates one Ontario-vs-Texas comparison plot per week.
    Each plot includes all matching policies for that week.
    """

    def extract_week_label(week_slug: str) -> str:
        for part in str(week_slug).split("_"):
            if part.startswith("week"):
                return part
        return str(week_slug)

    ont = ontario.copy()
    tex = texas.copy()

    ont["week_label"] = ont["week_slug"].apply(extract_week_label)
    tex["week_label"] = tex["week_slug"].apply(extract_week_label)

    family_colors = {
        "Baseline": "black",
        "Price Only": "tab:orange",
        "Option A": "tab:blue",
        "Option B": "tab:green",
        "Option C": "tab:red",
        "Other": "gray",
    }

    matched_weeks = sorted(set(ont["week_label"]) & set(tex["week_label"]))

    for week_label in matched_weeks:
        ont_week = ont[ont["week_label"] == week_label].copy()
        tex_week = tex[tex["week_label"] == week_label].copy()

        matching_policies = sorted(set(ont_week["policy"]) & set(tex_week["policy"]))

        if not matching_policies:
            continue

        fig, ax = plt.subplots(figsize=(12, 8))

        for policy in matching_policies:
            ont_row = ont_week[ont_week["policy"] == policy].iloc[0]
            tex_row = tex_week[tex_week["policy"] == policy].iloc[0]

            family = classify_family(str(ont_row["policy_name"]))
            color = family_colors.get(family, "gray")

            ax.plot(
                [ont_row["total_carbon_grams"], tex_row["total_carbon_grams"]],
                [ont_row["cost_gap"], tex_row["cost_gap"]],
                color=color,
                linestyle="--",
                alpha=0.45,
                linewidth=1.2,
            )

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

        for family, color in family_colors.items():
            ax.scatter([], [], color=color, label=family)

        ax.scatter([], [], color="gray", marker="o", label="Ontario")
        ax.scatter([], [], color="gray", marker="^", label="Texas")

        ax.axhline(0, color="gray", linestyle="--", linewidth=1, alpha=0.6)

        ax.set_xlabel("Weekly Carbon Emissions (gCO2eq)")
        ax.set_ylabel("Weekly Cost Gap: Real-Time Cost - Day-Ahead Cost")
        ax.set_title(f"Ontario vs ERCOT/Texas Policy Shift — {week_label}")

        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=8, loc="best")
        plt.tight_layout()

        out = OUTPUT_DIR / f"ontario_vs_texas_{week_label}_policy_shift.png"
        plt.savefig(out, dpi=300, bbox_inches="tight")
        plt.close()

        print(f"Saved: {out}")


def main() -> None:
    ontario = load_df(ONTARIO_PATH, "Ontario")
    texas = load_df(TEXAS_PATH, "Texas")

    print(f"Ontario completed weekly rows: {len(ontario)}")
    print(f"Texas completed weekly rows: {len(texas)}")

    # plot_all_weekly_points(ontario, texas)
    # plot_week_matched_policy_lines(ontario, texas)
    plot_each_week_individually(ontario, texas)

if __name__ == "__main__":
    main()