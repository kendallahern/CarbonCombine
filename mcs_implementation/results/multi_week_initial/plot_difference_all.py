import pandas as pd
import matplotlib.pyplot as plt

def make_label(row):
    if "tie" in row["policy"]:
        return f"tie={row['tie_threshold_ratio']}"
    elif "budget" in row["policy"]:
        return f"b={row['cost_budget_ratio']}, β={row['cost_penalty_beta']}"
    elif "lambda" in row["policy"]:
        return f"λ={row['lambda_carbon']}"
    else:
        return row["policy_name"]

# Load your data
df = pd.read_csv("mcs_implementation/results/multi_week_initial/combined_weekly_policy_summary.csv")

# Create price difference
df["price_diff"] = df["total_real_time_cost"] - df["total_day_ahead_cost"]
df = df[df["completed"] == True]

# Map shapes to options
shape_map = {
    "price_only": "o",
    "carbonscaler_price_tiebreak": "s",  # Option A
    "carbonscaler_budget": "^",          # Option B
    "carbonscaler_weighted": "D"         # Option C
}

# Get unique weeks and assign colors automatically
weeks = df["week_slug"].unique()

# Plot
plt.figure()

for week in weeks:
    week_df = df[df["week_slug"] == week]
    
    for policy_name, marker in shape_map.items():
        subset = week_df[week_df["policy_name"] == policy_name]
        
        plt.scatter(
            subset["price_diff"],
            subset["total_carbon_grams"],
            label=f"{week} | {policy_name}",
            marker=marker
        )

        # Add labels
        for _, row in subset.iterrows():
            label = row["policy"]
            plt.annotate(
                label,
                (row["price_diff"], row["total_carbon_grams"]),
                fontsize=7,
                alpha=0.7
            )

plt.xlabel("Real-Time Cost - Day-Ahead Cost")
plt.ylabel("Total Carbon Emissions (grams)")
plt.title("Price Difference vs Carbon Emissions")

plt.legend(fontsize=6)
plt.grid(True)

plt.show()