from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go

"""
RUN with
python mcs_implementation/multi_sector/plot_interactice.py
open mcs_implementation/multi_sector/plots_interactive/interactive_tradeoff_carbon_vs_day_ahead_cost.html
"""


RESULTS_DIR = Path("mcs_implementation/multi_sector")
SUMMARY_CSV = RESULTS_DIR / "weekly_price_csvs/average_policy_summary_across_weeks.csv"
PLOTS_DIR = RESULTS_DIR / "plots_interactive"


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
        "completion_rate",
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
        val = row.get("tie_threshold_ratio", "")
        return f"A-{val}"

    if policy_name == "carbonscaler_budget":
        budget = row.get("cost_budget_ratio", "")
        beta = row.get("cost_penalty_beta", "")
        gamma = row.get("urgency_gamma", "")
        return f"B-{budget}|b{beta}|g{gamma}"

    if policy_name == "carbonscaler_weighted":
        lam = row.get("lambda_carbon", "")
        return f"C-{lam}"

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
    # out["completed_bool"] = out["completed"].astype(str).str.lower().map(
    #     {"true": True, "false": False}
    # ).fillna(out["completed"])
    out["completed_numeric"] = pd.to_numeric(out["completion_rate"], errors="coerce")
    return out


def build_hover_text(row: pd.Series) -> str:
    return (
        f"<b>{row['policy']}</b><br>"
        f"Family: {row['family']}<br>"
        # f"Completed: {row['completed']}<br>"
        # f"Completion slot: {row['completion_slot']}<br>"
        f"Completion Rate: {row['completion_rate']}<br>"
        f"Carbon: {row['total_carbon_grams']:.3f} g<br>"
        f"Day-ahead cost: {row['total_day_ahead_cost']:.3f}<br>"
        f"Real-time cost: {row['total_real_time_cost']:.3f}<br>"
        f"Energy: {row['total_energy_kwh']:.3f} kWh<br>"
        f"Active slots: {row['active_slots']}<br>"
        f"Max scale: {row['max_scale_used']}<br>"
        f"Tie threshold: {row.get('tie_threshold_ratio', '')}<br>"
        f"Budget ratio: {row.get('cost_budget_ratio', '')}<br>"
        f"Beta: {row.get('cost_penalty_beta', '')}<br>"
        f"Gamma: {row.get('urgency_gamma', '')}<br>"
        f"Lambda carbon: {row.get('lambda_carbon', '')}<br>"
        f"Carbon savings vs base: {row.get('carbon_savings_vs_base_pct', 0):.3f}%<br>"
        f"RT cost savings vs base: {row.get('real_time_cost_savings_vs_base_pct', 0):.3f}%"
    )


def add_family_traces(
    fig: go.Figure,
    df: pd.DataFrame,
    x_col: str,
    y_col: str,
    title: str,
) -> go.Figure:
    family_colors = {
        "Baseline": "#111111",
        "Option A": "#1f77b4",
        "Option B": "#2ca02c",
        "Option C": "#d62728",
        "Other": "#7f7f7f",
    }

    for family, group in df.groupby("family"):

        # keep only rows with completed > 0.5
        group = group[group["completed_numeric"] > 0.5]

        if group.empty:
            continue

        group_sorted = group.sort_values("sort_key")
        color = family_colors.get(family, "#7f7f7f")

        # line trace
        fig.add_trace(
            go.Scatter(
                x=group_sorted[x_col],
                y=group_sorted[y_col],
                mode="lines",
                name=f"{family} trend",
                legendgroup=family,
                line=dict(color=color, width=2),
                opacity=0.7,
                hoverinfo="skip",
                showlegend=True,
            )
        )

        # circle markers
        fig.add_trace(
            go.Scatter(
                x=group_sorted[x_col],
                y=group_sorted[y_col],
                mode="markers+text",
                name=f"{family} points",
                legendgroup=family,
                marker=dict(
                    color=color,
                    size=12,
                    symbol="circle",
                    line=dict(width=1.5, color="white"),
                ),
                text=group_sorted["short_label"],
                textposition="top center",
                hovertext=group_sorted.apply(build_hover_text, axis=1),
                hoverinfo="text",
                showlegend=False,
            )
        )

        # line trace
        fig.add_trace(
            go.Scatter(
                x=group_sorted[x_col],
                y=group_sorted[y_col],
                mode="lines",
                name=f"{family} trend",
                legendgroup=family,
                line=dict(color=color, width=2),
                opacity=0.7,
                hoverinfo="skip",
                showlegend=True,
            )
        )

        # completed points
        # completed_group = group_sorted[group_sorted["completed_bool"] == True]
        # if not completed_group.empty:
        #     fig.add_trace(
        #         go.Scatter(
        #             x=completed_group[x_col],
        #             y=completed_group[y_col],
        #             mode="markers+text",
        #             name=f"{family} complete",
        #             legendgroup=family,
        #             marker=dict(
        #                 color=color,
        #                 size=11,
        #                 symbol="circle",
        #                 line=dict(width=1, color="white"),
        #             ),
        #             text=completed_group["short_label"],
        #             textposition="top center",
        #             hovertext=completed_group.apply(build_hover_text, axis=1),
        #             hoverinfo="text",
        #             showlegend=False,
        #         )
        #     )

        # incomplete points
        # incomplete_group = group_sorted[group_sorted["completed_bool"] != True]
        # if not incomplete_group.empty:
        #     fig.add_trace(
        #         go.Scatter(
        #             x=incomplete_group[x_col],
        #             y=incomplete_group[y_col],
        #             mode="markers+text",
        #             name=f"{family} incomplete",
        #             legendgroup=family,
        #             marker=dict(
        #                 color=color,
        #                 size=12,
        #                 symbol="x",
        #                 line=dict(width=2, color=color),
        #             ),
        #             text=incomplete_group["short_label"],
        #             textposition="bottom center",
        #             hovertext=incomplete_group.apply(build_hover_text, axis=1),
        #             hoverinfo="text",
        #             showlegend=False,
        #         )
        #     )


    fig.update_layout(
        title=title,
        template="plotly_white",
        width=1100,
        height=800,
        legend_title="Policy family",
        hovermode="closest",
        margin=dict(l=70, r=40, t=80, b=70),
    )
    return fig


def save_tradeoff_plot(
    df: pd.DataFrame,
    x_col: str,
    y_col: str,
    x_title: str,
    y_title: str,
    title: str,
    filename: str,
) -> None:
    fig = go.Figure()
    fig = add_family_traces(fig, df, x_col=x_col, y_col=y_col, title=title)
    fig.update_xaxes(title_text=x_title, showgrid=True)
    fig.update_yaxes(title_text=y_title, showgrid=True)
    fig.write_html(PLOTS_DIR / filename, include_plotlyjs="cdn")


def highlight_pareto_front(
    fig: go.Figure,
    df: pd.DataFrame,
    x_col: str,
    y_col: str,
) -> go.Figure:
    # Lower is better on both axes
    points = df[[x_col, y_col, "policy"]].sort_values([x_col, y_col]).reset_index(drop=True)

    pareto_indices = []
    best_y = float("inf")
    for idx, row in points.iterrows():
        if row[y_col] < best_y:
            pareto_indices.append(idx)
            best_y = row[y_col]

    pareto = points.iloc[pareto_indices]

    fig.add_trace(
        go.Scatter(
            x=pareto[x_col],
            y=pareto[y_col],
            mode="lines+markers",
            name="Pareto-like frontier",
            line=dict(color="#9467bd", width=3, dash="dot"),
            marker=dict(size=16, symbol="diamond", 
                        color='rgba(128,0,128,0)',
                        line=dict(width=2,color='#9467bd')
                        ),
            hovertext=pareto["policy"],
            hoverinfo="text",
        )
    )
    return fig


def save_rt_tradeoff_with_frontier(df: pd.DataFrame, filename: str) -> None:
    fig = go.Figure()
    fig = add_family_traces(
        fig,
        df,
        x_col="total_carbon_grams",
        y_col="total_real_time_cost",
        title="Carbon vs Real-Time Cost Across All Policy Sweeps",
    )
    fig = highlight_pareto_front(
        fig,
        df,
        x_col="total_carbon_grams",
        y_col="total_real_time_cost",
    )
    fig.update_xaxes(title_text="Total Carbon Emissions (gCO2eq)", showgrid=True)
    fig.update_yaxes(title_text="Total Real-Time Cost", showgrid=True)
    fig.write_html(PLOTS_DIR / filename, include_plotlyjs="cdn")


def save_savings_tradeoff(df: pd.DataFrame, filename: str) -> None:
    fig = go.Figure()
    fig = add_family_traces(
        fig,
        df,
        x_col="carbon_savings_vs_base_pct",
        y_col="real_time_cost_savings_vs_base_pct",
        title="Savings Tradeoff Across All Policy Sweeps",
    )
    fig.update_xaxes(
        title_text="Carbon Savings vs Baseline (%)",
        showgrid=True,
        zeroline=True,
        zerolinewidth=1,
    )
    fig.update_yaxes(
        title_text="Real-Time Cost Savings vs Baseline (%)",
        showgrid=True,
        zeroline=True,
        zerolinewidth=1,
    )
    fig.write_html(PLOTS_DIR / filename, include_plotlyjs="cdn")


def main() -> None:
    PLOTS_DIR.mkdir(parents=True, exist_ok=True)

    df = load_summary()
    df = add_metadata(df)

    save_tradeoff_plot(
        df=df,
        x_col="total_carbon_grams",
        y_col="total_day_ahead_cost",
        x_title="Total Carbon Emissions (gCO2eq)",
        y_title="Total Day-Ahead Cost",
        title="Carbon vs Day-Ahead Cost Across All Policy Sweeps",
        filename="interactive_tradeoff_carbon_vs_day_ahead_cost.html",
    )

    save_rt_tradeoff_with_frontier(
        df=df,
        filename="interactive_tradeoff_carbon_vs_real_time_cost.html",
    )

    save_savings_tradeoff(
        df=df,
        filename="interactive_savings_tradeoff.html",
    )

    print("Wrote interactive plots to:")
    print(PLOTS_DIR.resolve())


if __name__ == "__main__":
    main()