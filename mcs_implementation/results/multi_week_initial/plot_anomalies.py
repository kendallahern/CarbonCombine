#---------------------------------
# Anomaly 1 - Parameter Sensitivty 
#---------------------------------

import pandas as pd

df = pd.read_csv("mcs_implementation/results/multi_week_initial/combined_weekly_policy_summary.csv")

# Only completed runs (important)
df = df[df["completed"] == True].copy()

df["price_diff"] = df["total_real_time_cost"] - df["total_day_ahead_cost"]

# Parameters to analyze
params = [
    "tie_threshold_ratio",
    "cost_budget_ratio",
    "cost_penalty_beta",
    "urgency_gamma",
    "lambda_carbon"
]

results = []

for param in params:
    if param not in df.columns:
        continue

    grouped = df.dropna(subset=[param]).groupby(param)

    for val, group in grouped:
        if len(group) < 2:
            continue

        results.append({
            "parameter": param,
            "value": val,
            "price_diff_std": group["price_diff"].std(),
            "carbon_std": group["total_carbon_grams"].std(),
            "count": len(group)
        })

sens_df = pd.DataFrame(results)

print(sens_df.sort_values(["parameter", "value"]))

#---------------------------------
# Anomaly 2 - Unique Ration
#---------------------------------

summary = []

for param in params:
    if param not in df.columns:
        continue

    subset = df.dropna(subset=[param])

    total = len(subset)

    unique_outputs = subset[[
        "price_diff",
        "total_carbon_grams"
    ]].drop_duplicates().shape[0]

    summary.append({
        "parameter": param,
        "total_points": total,
        "unique_outputs": unique_outputs,
        "uniqueness_ratio": unique_outputs / total
    })

summary_df = pd.DataFrame(summary)
print(summary_df)


#---------------------------------
# Anomaly 3 - Dead Params
#---------------------------------
import matplotlib.pyplot as plt

param = "cost_budget_ratio"  # change this

subset = df.dropna(subset=[param])

plt.figure()

plt.scatter(
    subset[param],
    subset["price_diff"],
    alpha=0.4,
    label="Price Diff"
)

plt.scatter(
    subset[param],
    subset["total_carbon_grams"],
    alpha=0.4,
    label="Carbon"
)

plt.xlabel(param)
plt.title(f"Effect of {param} on Outcomes")
plt.legend()
plt.grid(True)

plt.show()

#---------------------------------
# Anomaly 4- Duplicates
#---------------------------------

duplicates = df.groupby([
    "price_diff",
    "total_carbon_grams"
]).size().reset_index(name="count")

duplicates = duplicates[duplicates["count"] > 1]

print(duplicates.sort_values("count", ascending=False))



"""
              parameter   value  price_diff_std  carbon_std  count
5     cost_budget_ratio  0.8500        9.726561   13.174672      2
6     cost_budget_ratio  0.9000      101.143693   97.611336     25
7     cost_budget_ratio  1.0000      113.744090   81.931838      7
8     cost_budget_ratio  1.1000      115.934253   83.827930      7
9     cost_budget_ratio  1.2000      115.934253   83.827930      7
10    cost_penalty_beta  0.0025      146.059508  131.107355      2
11    cost_penalty_beta  0.0050      146.059508  131.107355      2
12    cost_penalty_beta  0.0100      104.849264   88.357939     38
13    cost_penalty_beta  0.0200      112.364746  114.885016      3
14    cost_penalty_beta  0.0400      122.098779  100.939324      4
20        lambda_carbon  0.5000       73.298433   91.356323      7
21        lambda_carbon  0.6000       76.135829   87.003840      7
22        lambda_carbon  0.7000       80.939770   85.275998      7
23        lambda_carbon  0.8000      104.757798   83.751017      7
24        lambda_carbon  0.9000      113.952610   82.380277      7
0   tie_threshold_ratio  0.0100      130.134961   81.688486      7
1   tie_threshold_ratio  0.0300      129.369692   83.982246      7
2   tie_threshold_ratio  0.0500      127.474190   81.191637      7
3   tie_threshold_ratio  0.1000      127.260001   84.403233      7
4   tie_threshold_ratio  0.2000      121.648668   86.620030      7
15        urgency_gamma  0.1000      135.822014  133.646151      2
16        urgency_gamma  0.2500      135.822014  133.646151      2
17        urgency_gamma  0.5000      105.963679   86.893456     41
18        urgency_gamma  0.7500      135.822014  133.646151      2
19        urgency_gamma  1.0000      135.822014  133.646151      2
             parameter  total_points  unique_outputs  uniqueness_ratio
0  tie_threshold_ratio            35              21          0.600000
1    cost_budget_ratio            49              17          0.346939
2    cost_penalty_beta            49              17          0.346939
3        urgency_gamma            49              17          0.346939
4        lambda_carbon            35              32          0.914286
    price_diff  total_carbon_grams  count
64  175.760591            140.1708     13
19  -16.320744            329.1750     11
67  184.348835            119.0244      7
75  242.539974            139.8672      5
38   -0.208340            115.8234      4
63  175.076731            132.4158      4
2  -107.892229            131.1552      4
0  -110.972339            131.7888      3
44   19.317815            262.6536      3
24  -13.795958            325.3602      2
43   17.637054            259.5912      2
16  -19.865846            117.9420      2
50   34.494537            268.2174      2
59  155.275840            156.2022      2
60  169.369305            136.6068      2
14  -21.305218            121.5192      2
12  -23.708504            131.1552      2
3  -101.157380            134.1978      2
68  186.947013            118.8594      2
71  189.516025            121.5390      2
72  192.763378            139.9464      2
"""

"""
🧠 1. What your sensitivity table means
Columns:
price_diff_std → how much cost difference varies
carbon_std → how much carbon varies
count → number of data points used

👉 Think of this as:

“If I fix this parameter value, how much do outcomes still vary?”

🔴 A. cost_budget_ratio (VERY IMPORTANT)
Value	price std	carbon std	meaning
0.85	LOW (~10)	LOW (~13)	Almost no variability → very stable behavior
0.90	HUGE (~101)	HUGE (~98)	wildly different outcomes
1.00+	HUGE (~110+)	high (~80+)	still high variability
🔥 Interpretation
At 0.85 → system is locked / constrained
At 0.90 → system “opens up” → many behaviors possible
After 1.0 → plateau (no new structure)

👉 This confirms your earlier finding:

There is a phase transition around budget ≈ 0.9–1.0

🔴 B. cost_penalty_beta
Value	pattern
0.0025, 0.005	identical stats → no effect
0.01	large variance
0.02–0.04	still large variance
🔥 Interpretation
Small beta values → completely inactive
Only larger values matter

👉 This is a dead parameter region

🔴 C. lambda_carbon (BEST BEHAVED PARAMETER)
Value	trend
0.5 → 0.9	steadily increasing std
🔥 Interpretation
This parameter actually smoothly changes behavior
No flat regions

👉 This is your most meaningful tuning knob

🔴 D. tie_threshold_ratio

All values:

price std ≈ 120–130
carbon std ≈ 80–86
🔥 Interpretation
Almost identical across all values
Changing tie threshold barely matters

👉 This parameter is weak / ineffective

🔴 E. urgency_gamma
Value	pattern
0.1, 0.25, 0.75, 1.0	identical stats
0.5	different
🔥 Interpretation
Only gamma = 0.5 does anything
Everything else → identical behavior

👉 This is a discrete switch, not continuous control

🚀 2. Uniqueness Ratio Table (MOST IMPORTANT)

This is the strongest result in your entire analysis.

Parameter	Uniqueness Ratio	Meaning
tie_threshold_ratio	0.60	moderate redundancy
cost_budget_ratio	0.35	🔴 lots of redundancy
cost_penalty_beta	0.35	🔴 lots of redundancy
urgency_gamma	0.35	🔴 lots of redundancy
lambda_carbon	0.91	🟢 highly effective
🔥 Interpretation
🟢 Lambda (GOOD)
91% unique outputs → almost every value produces new behavior
👉 Excellent parameter
🔴 Budget / Beta / Gamma (BAD)
Only ~35% unique outputs
👉 ~65% of runs are redundant
🟡 Tie Threshold (MID)
60% unique
👉 Some effect, but limited
🎯 What this means (very important)

“Most of the parameter space is wasted.”

Only lambda_carbon is truly exploring meaningful behavior.

🔍 3. Duplicate Output Table

This shows exact same outcomes repeated many times

🔥 Biggest duplicates:
price_diff	carbon	count
175.76	140.17	13 times
-16.32	329.17	11 times
184.35	119.02	7 times
🔴 Interpretation
13 different configurations → SAME result
11 different configs → SAME result

👉 That is massive redundancy

🧠 What this tells you

Your system behaves like:

“Many parameter combinations collapse to the same decision”

This means:

decision space is discrete
not continuous optimization
📊 4. Your Plot (Budget vs Outcomes)

Looking at your image:

What you’re seeing:
Vertical bands → same budget value
Horizontal clusters → identical outputs
stacked points → redundancy
🔥 Key patterns
1. Budget < 0.9
tight clusters → constrained system
2. Budget = 0.9
explosion of spread → transition point
3. Budget ≥ 1.0
repeating clusters → saturation
🧠 FINAL TAKEAWAYS (THIS IS WHAT YOU SAY)
🥇 1. The system is NOT continuously sensitive

“Most parameters do not produce continuous variation; instead, the system exhibits discrete behavioral regimes.”

🥇 2. There is a clear phase transition

“A sharp transition occurs around cost_budget_ratio ≈ 0.9–1.0, where the system shifts from constrained to highly variable behavior.”

🥇 3. Most of the parameter space is redundant

“Only ~35% of configurations for several parameters produce unique outcomes, indicating large dead regions in the search space.”

🥇 4. Lambda is the only strong control parameter

“Lambda_carbon demonstrates high sensitivity (91% uniqueness), making it the most effective parameter for tuning.”

🥇 5. The system operates in discrete regimes

“Many parameter combinations collapse to identical outputs, suggesting the underlying scheduling decisions are discrete rather than continuous.”
"""