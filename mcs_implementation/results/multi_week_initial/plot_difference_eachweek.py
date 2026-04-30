import pandas as pd
import matplotlib.pyplot as plt
import math
from matplotlib.lines import Line2D
from datetime import datetime

# Load data
df = pd.read_csv("mcs_implementation/results/multi_week_initial/combined_weekly_policy_summary.csv")


df = df[df["completed"] == True].copy()
df["price_diff"] = df["total_real_time_cost"] - df["total_day_ahead_cost"]

# Keep the policy groups you want
included_policies = [
    "carbonscaler",                  # CarbonScaler base
    "price_only",                    # Price only
    "carbonscaler_price_tiebreak",   # Option A
    "carbonscaler_budget",           # Option B
    "carbonscaler_weighted"          # Option C
]
df = df[df["policy_name"].isin(included_policies)].copy()

# -----------------------------
# Marker/legend settings
# -----------------------------
shape_map = {
    "carbonscaler": "X",
    "price_only": "o",
    "carbonscaler_price_tiebreak": "s",
    "carbonscaler_budget": "^",
    "carbonscaler_weighted": "D"
}

color_map = {
    "carbonscaler": "black",
    "price_only": "tab:orange",
    "carbonscaler_price_tiebreak": "tab:blue",
    "carbonscaler_budget": "tab:green",
    "carbonscaler_weighted": "tab:red"
}

legend_name_map = {
    "carbonscaler": "CarbonScaler Base",
    "price_only": "Price Only",
    "carbonscaler_price_tiebreak": "Option A: Tie-break",
    "carbonscaler_budget": "Option B: Budget",
    "carbonscaler_weighted": "Option C: Weighted"
}

# -----------------------------
# Helpers
# -----------------------------
ordinal_words = {
    1: "One", 2: "Two", 3: "Three", 4: "Four",
    5: "Five", 6: "Six", 7: "Seven", 8: "Eight",
    9: "Nine", 10: "Ten"
}

def parse_week_title(week_slug, week_index):
    """
    Example:
    ontario_week04_2026-03-02_to_2026-03-08
    -> Week Four (Mar 2–Mar 8, 2026)
    """
    parts = week_slug.split("_")
    start_str = parts[-3]
    end_str = parts[-1]

    start_dt = datetime.strptime(start_str, "%Y-%m-%d")
    end_dt = datetime.strptime(end_str, "%Y-%m-%d")

    week_word = ordinal_words.get(week_index, str(week_index))

    if start_dt.year == end_dt.year:
        if start_dt.month == end_dt.month:
            date_part = f"{start_dt.strftime('%b')} {start_dt.day}–{end_dt.day}, {start_dt.year}"
        else:
            date_part = f"{start_dt.strftime('%b')} {start_dt.day}–{end_dt.strftime('%b')} {end_dt.day}, {start_dt.year}"
    else:
        date_part = f"{start_dt.strftime('%b')} {start_dt.day}, {start_dt.year}–{end_dt.strftime('%b')} {end_dt.day}, {end_dt.year}"

    return f"Week {week_word} ({date_part})"

def build_label(row):
    """
    Descriptive label for subplot legend.
    """
    pname = row["policy_name"]

    if pname == "carbonscaler":
        return (
            "CarbonScaler Base\n"
            f"RT-DA: {row['price_diff']:.2f} $\n"
            f"Carbon: {row['total_carbon_grams']:.2f} g"
        )

    if pname == "price_only":
        return (
            "Price Only\n"
            f"RT-DA: {row['price_diff']:.2f} $\n"
            f"Carbon: {row['total_carbon_grams']:.2f} g"
        )

    if pname == "carbonscaler_price_tiebreak":
        return (
            f"Option A (tie={row['tie_threshold_ratio']:.2f})\n"
            f"RT-DA: {row['price_diff']:.2f} $\n"
            f"Carbon: {row['total_carbon_grams']:.2f} g"
        )

    if pname == "carbonscaler_budget":
        return (
            f"Option B (budget={row['cost_budget_ratio']:.2f}, "
            f"beta={row['cost_penalty_beta']:.4f}, "
            f"gamma={row['urgency_gamma']:.2f})\n"
            f"RT-DA: {row['price_diff']:.2f} $\n"
            f"Carbon: {row['total_carbon_grams']:.2f} g"
        )

    if pname == "carbonscaler_weighted":
        return (
            f"Option C (lambda={row['lambda_carbon']:.2f})\n"
            f"RT-DA: {row['price_diff']:.2f} $\n"
            f"Carbon: {row['total_carbon_grams']:.2f} g"
        )

    return (
        f"{pname}\n"
        f"RT-DA: {row['price_diff']:.2f} $\n"
        f"Carbon: {row['total_carbon_grams']:.2f} g"
    )

# -----------------------------
# Find top 3 closest to x = 0 for each week
# -----------------------------
df["abs_price_diff"] = df["price_diff"].abs()
df["highlight"] = False
df["highlight_rank"] = None

for week in sorted(df["week_slug"].unique()):
    week_subset = df[df["week_slug"] == week].nsmallest(3, "abs_price_diff")
    for rank, idx in enumerate(week_subset.index, start=1):
        df.loc[idx, "highlight"] = True
        df.loc[idx, "highlight_rank"] = rank

# -----------------------------
# Layout
# -----------------------------
weeks = sorted(df["week_slug"].unique())
n_weeks = len(weeks)

cols = 2
rows = math.ceil(n_weeks / cols)

x_min, x_max = df["price_diff"].min(), df["price_diff"].max()
y_min, y_max = df["total_carbon_grams"].min(), df["total_carbon_grams"].max()

x_pad = 0.05 * (x_max - x_min) if x_max > x_min else 1
y_pad = 0.05 * (y_max - y_min) if y_max > y_min else 1

fig, axes = plt.subplots(rows, cols, figsize=(15, 5 * rows))
axes = axes.flatten() if n_weeks > 1 else [axes]

# -----------------------------
# Plot each week
# -----------------------------
for i, week in enumerate(weeks):
    ax = axes[i]
    week_df = df[df["week_slug"] == week].copy()

    # plot all points, semi-transparent
    for policy_name in included_policies:
        subset = week_df[week_df["policy_name"] == policy_name]
        if subset.empty:
            continue

        ax.scatter(
            subset["price_diff"],
            subset["total_carbon_grams"],
            marker=shape_map[policy_name],
            s=85,
            color=color_map[policy_name],
            alpha=0.45,              # makes points see-through
            edgecolors="none",
            label=legend_name_map[policy_name]
        )

    # highlight top 3 with bold outlines + rank number
    top3 = week_df[week_df["highlight"] == True].copy()

    legend_handles = []
    legend_labels = []

    for _, row in top3.iterrows():
        policy_name = row["policy_name"]
        rank = int(row["highlight_rank"])

        # outlined highlight point
        ax.scatter(
            row["price_diff"],
            row["total_carbon_grams"],
            marker=shape_map[policy_name],
            s=140,
            color=color_map[policy_name],
            alpha=0.95,
            edgecolors="black",
            linewidths=1.2,
            zorder=5
        )

        # small rank number near point
        ax.annotate(
            str(rank),
            (row["price_diff"], row["total_carbon_grams"]),
            textcoords="offset points",
            xytext=(8, 6),
            fontsize=9,
            fontweight="bold",
            bbox=dict(boxstyle="circle,pad=0.2", fc="white", ec="gray", alpha=0.9)
        )

        # matching legend entry
        handle = Line2D(
            [0], [0],
            marker=shape_map[policy_name],
            color="w",
            markerfacecolor=color_map[policy_name],
            markeredgecolor="black",
            markersize=9,
            linewidth=0
        )
        legend_handles.append(handle)
        legend_labels.append(f"{rank}. {build_label(row)}")

    # subplot title
    nice_title = parse_week_title(week, i + 1)
    ax.set_title(nice_title, fontsize=11)

    ax.set_xlabel("Real-Time Cost - Day-Ahead Cost ($)")
    ax.set_ylabel("Total Carbon Emissions (g)")
    ax.axvline(0, linestyle="--", alpha=0.45, color="tab:blue")
    ax.grid(True, alpha=0.25)

    ax.set_xlim(x_min - x_pad, x_max + x_pad)
    ax.set_ylim(y_min - y_pad, y_max + y_pad)

    # per-subplot legend for top 3 only
    if legend_handles:
        ax.legend(
            legend_handles,
            legend_labels,
            title="Top 3 closest to zero",
            loc="upper right",
            fontsize=8,
            title_fontsize=9,
            framealpha=0.92
        )

# Remove unused subplot axes
for j in range(i + 1, len(axes)):
    fig.delaxes(axes[j])

# -----------------------------
# Main/global legend for policy types
# -----------------------------
global_handles = [
    Line2D([0], [0],
           marker=shape_map[p],
           color="w",
           markerfacecolor=color_map[p],
           markeredgecolor="none",
           markersize=8,
           linewidth=0,
           alpha=0.8)
    for p in included_policies
]

global_labels = [legend_name_map[p] for p in included_policies]

fig.legend(
    global_handles,
    global_labels,
    title="Policy Type",
    loc="upper center",
    ncol=3,
    bbox_to_anchor=(0.5, 1.02)
)

fig.suptitle("Price Difference vs Carbon Emissions by Week", fontsize=15)
plt.tight_layout(rect=[0, 0, 1, 0.96])

# Save high-quality image
plt.savefig("all_weeks_comparison_top3_labeled.png", dpi=300, bbox_inches="tight")

plt.show()