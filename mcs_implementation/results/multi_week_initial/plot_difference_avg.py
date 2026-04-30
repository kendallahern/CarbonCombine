import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

# -----------------------------
# Load data
# -----------------------------
df = pd.read_csv("mcs_implementation/results/multi_week_initial/average_policy_summary_across_weeks.csv")

# Average price differential
df["price_diff"] = df["total_real_time_cost"] - df["total_day_ahead_cost"]
df["abs_price_diff"] = df["price_diff"].abs()

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
# Descriptive labels for top 3
# -----------------------------
def build_label(row):
    pname = row["policy_name"]

    if pname == "carbonscaler":
        return (
            "CarbonScaler Base\n"
            f"Avg RT-DA: {row['price_diff']:.2f} $\n"
            f"Avg Carbon: {row['total_carbon_grams']:.2f} g\n"
            # f"Weeks: {int(row['week_count'])}"
        )

    if pname == "price_only":
        return (
            "Price Only\n"
            f"Avg RT-DA: {row['price_diff']:.2f} $\n"
            f"Avg Carbon: {row['total_carbon_grams']:.2f} g\n"
            # f"Weeks: {int(row['week_count'])}"
        )

    if pname == "carbonscaler_price_tiebreak":
        return (
            f"Option A (tie={row['tie_threshold_ratio']:.2f})\n"
            f"Avg RT-DA: {row['price_diff']:.2f} $\n"
            f"Avg Carbon: {row['total_carbon_grams']:.2f} g\n"
            # f"Weeks: {int(row['week_count'])}"
        )

    if pname == "carbonscaler_budget":
        return (
            f"Option B (budget={row['cost_budget_ratio']:.2f}, "
            f"beta={row['cost_penalty_beta']:.4f}, "
            f"gamma={row['urgency_gamma']:.2f})\n"
            f"Avg RT-DA: {row['price_diff']:.2f} $\n"
            f"Avg Carbon: {row['total_carbon_grams']:.2f} g\n"
            f"Completion: {row['completion_rate']:.2%}"
        )

    if pname == "carbonscaler_weighted":
        return (
            f"Option C (lambda={row['lambda_carbon']:.2f})\n"
            f"Avg RT-DA: {row['price_diff']:.2f} $\n"
            f"Avg Carbon: {row['total_carbon_grams']:.2f} g\n"
            # f"Weeks: {int(row['week_count'])}"
        )

    return (
        f"{pname}\n"
        f"Avg RT-DA: {row['price_diff']:.2f} $\n"
        f"Avg Carbon: {row['total_carbon_grams']:.2f} g"
    )

# -----------------------------
# Top 3 closest to zero line
# -----------------------------
top3 = df.nsmallest(3, "abs_price_diff").copy()
top3 = top3.reset_index(drop=True)
top3["rank"] = top3.index + 1

# -----------------------------
# Plot
# -----------------------------
fig, ax = plt.subplots(figsize=(11, 8))

# Plot all points first
for policy_name in included_policies:
    subset = df[df["policy_name"] == policy_name]
    if subset.empty:
        continue

    alpha_val = 0.7 if policy_name == "carbonscaler" else 0.45

    ax.scatter(
        subset["price_diff"],
        subset["total_carbon_grams"],
        marker=shape_map[policy_name],
        s=95,
        color=color_map[policy_name],
        alpha=alpha_val,
        edgecolors="none",
        label=legend_name_map[policy_name]
    )

# Highlight top 3
legend_handles = []
legend_labels = []

for _, row in top3.iterrows():
    policy_name = row["policy_name"]
    rank = int(row["rank"])

    ax.scatter(
        row["price_diff"],
        row["total_carbon_grams"],
        marker=shape_map[policy_name],
        s=170,
        color=color_map[policy_name],
        alpha=0.95,
        edgecolors="black",
        linewidths=1.3,
        zorder=5
    )

    ax.annotate(
        str(rank),
        (row["price_diff"], row["total_carbon_grams"]),
        textcoords="offset points",
        xytext=(8, 6),
        fontsize=10,
        fontweight="bold",
        bbox=dict(boxstyle="circle,pad=0.2", fc="white", ec="gray", alpha=0.95)
    )

    handle = Line2D(
        [0], [0],
        marker=shape_map[policy_name],
        color="w",
        markerfacecolor=color_map[policy_name],
        markeredgecolor="black",
        markersize=10,
        linewidth=0
    )
    legend_handles.append(handle)
    legend_labels.append(f"{rank}. {build_label(row)}")

# Zero line
ax.axvline(0, linestyle="--", alpha=0.45, color="tab:blue")

# Axis labels and title
ax.set_xlabel("Average Real-Time Cost - Day-Ahead Cost ($)")
ax.set_ylabel("Average Carbon Emissions (g)")
ax.set_title("Average Price Difference vs Average Carbon Emissions Across Weeks")

# Grid
ax.grid(True, alpha=0.25)

# Padding
x_min, x_max = df["price_diff"].min(), df["price_diff"].max()
y_min, y_max = df["total_carbon_grams"].min(), df["total_carbon_grams"].max()

x_pad = 0.08 * (x_max - x_min) if x_max > x_min else 1
y_pad = 0.08 * (y_max - y_min) if y_max > y_min else 1

ax.set_xlim(x_min - x_pad, x_max + x_pad)
ax.set_ylim(y_min - y_pad, y_max + y_pad)

# Global policy legend
policy_handles = [
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
policy_labels = [legend_name_map[p] for p in included_policies]

legend1 = ax.legend(
    policy_handles,
    policy_labels,
    title="Policy Type",
    loc="upper right",
    framealpha=0.95
)
ax.add_artist(legend1)

# Top-3 descriptive legend
ax.legend(
    legend_handles,
    legend_labels,
    title="Top 3 closest to zero (average RT-DA)",
    loc="upper center",
    fontsize=9,
    title_fontsize=10,
    framealpha=0.95
)

plt.tight_layout()
plt.savefig("average_across_weeks_top3.png", dpi=300, bbox_inches="tight")
plt.show()