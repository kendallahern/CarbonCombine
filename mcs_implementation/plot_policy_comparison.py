from __future__ import annotations

from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt


RESULTS_DIR = Path("mcs_implementation/results")
SUMMARY_CSV = RESULTS_DIR / "policy_comparison_summary.csv"
SCHEDULE_CSV = RESULTS_DIR / "policy_comparison_schedules.csv"
PLOTS_DIR = RESULTS_DIR / "plots"


def load_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    if not SUMMARY_CSV.exists():
        raise FileNotFoundError(f"Missing summary CSV: {SUMMARY_CSV}")
    if not SCHEDULE_CSV.exists():
        raise FileNotFoundError(f"Missing schedule CSV: {SCHEDULE_CSV}")

    summary_df = pd.read_csv(SUMMARY_CSV)
    schedule_df = pd.read_csv(SCHEDULE_CSV)

    return summary_df, schedule_df


def save_bar_plot(summary_df: pd.DataFrame) -> None:
    PLOTS_DIR.mkdir(parents=True, exist_ok=True)

    metrics = [
        ("total_carbon_grams", "Total Carbon (gCO2eq)", "policy_comparison_carbon.png"),
        ("total_day_ahead_cost", "Total Day-Ahead Cost", "policy_comparison_day_ahead_cost.png"),
        ("total_real_time_cost", "Total Real-Time Cost", "policy_comparison_real_time_cost.png"),
        ("total_energy_kwh", "Total Energy (kWh)", "policy_comparison_energy.png"),
    ]

    for column, ylabel, filename in metrics:
        plt.figure(figsize=(10, 6))
        plt.bar(summary_df["policy"], summary_df[column])
        plt.ylabel(ylabel)
        plt.xlabel("Policy")
        plt.title(ylabel)
        plt.xticks(rotation=20, ha="right")
        plt.tight_layout()
        plt.savefig(PLOTS_DIR / filename, dpi=200)
        plt.close()


def save_scale_timeline_plot(schedule_df: pd.DataFrame) -> None:
    PLOTS_DIR.mkdir(parents=True, exist_ok=True)

    plt.figure(figsize=(12, 6))

    for policy in schedule_df["policy"].unique():
        policy_df = schedule_df[schedule_df["policy"] == policy].sort_values("slot_index")
        plt.step(
            policy_df["slot_index"],
            policy_df["scale"],
            where="mid",
            label=policy,
        )

    plt.xlabel("Slot Index")
    plt.ylabel("Scale")
    plt.title("Scale Schedule by Policy")
    plt.legend()
    plt.tight_layout()
    plt.savefig(PLOTS_DIR / "policy_comparison_scale_timeline.png", dpi=200)
    plt.close()


def save_policy_overlay_plots(schedule_df: pd.DataFrame) -> None:
    PLOTS_DIR.mkdir(parents=True, exist_ok=True)

    for policy in schedule_df["policy"].unique():
        policy_df = schedule_df[schedule_df["policy"] == policy].sort_values("slot_index")

        fig, ax1 = plt.subplots(figsize=(12, 6))
        ax2 = ax1.twinx()

        ax1.step(
            policy_df["slot_index"],
            policy_df["scale"],
            where="mid",
            label="Scale",
        )
        ax2.plot(
            policy_df["slot_index"],
            policy_df["carbon_intensity"],
            label="Carbon Intensity",
        )
        ax2.plot(
            policy_df["slot_index"],
            policy_df["day_ahead_price"],
            label="Day-Ahead Price",
        )

        ax1.set_xlabel("Slot Index")
        ax1.set_ylabel("Scale")
        ax2.set_ylabel("Carbon Intensity / Day-Ahead Price")
        ax1.set_title(f"Policy Overlay: {policy}")

        lines1, labels1 = ax1.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper right")

        fig.tight_layout()
        fig.savefig(PLOTS_DIR / f"{policy}_overlay.png", dpi=200)
        plt.close(fig)


def save_completion_slot_plot(summary_df: pd.DataFrame) -> None:
    PLOTS_DIR.mkdir(parents=True, exist_ok=True)

    plt.figure(figsize=(10, 6))
    plt.bar(summary_df["policy"], summary_df["completion_slot"])
    plt.ylabel("Completion Slot")
    plt.xlabel("Policy")
    plt.title("Completion Slot by Policy")
    plt.xticks(rotation=20, ha="right")
    plt.tight_layout()
    plt.savefig(PLOTS_DIR / "policy_comparison_completion_slot.png", dpi=200)
    plt.close()

def save_tradeoff_plots(summary_df: pd.DataFrame) -> None:
    PLOTS_DIR.mkdir(parents=True, exist_ok=True)

    # Day-ahead tradeoff
    plt.figure(figsize=(8, 6))
    for _, row in summary_df.iterrows():
        x = row["total_carbon_grams"]
        y = row["total_day_ahead_cost"]
        label = row["policy"]

        plt.scatter(x, y, s=80)
        plt.annotate(
            label,
            (x, y),
            textcoords="offset points",
            xytext=(6, 6),
        )

    plt.xlabel("Total Carbon Emissions (gCO2eq)")
    plt.ylabel("Total Day-Ahead Cost")
    plt.title("Carbon vs Day-Ahead Cost Tradeoff")
    plt.tight_layout()
    plt.savefig(PLOTS_DIR / "tradeoff_carbon_vs_day_ahead_cost.png", dpi=200)
    plt.close()

    # Real-time tradeoff
    plt.figure(figsize=(8, 6))
    for _, row in summary_df.iterrows():
        x = row["total_carbon_grams"]
        y = row["total_real_time_cost"]
        label = row["policy"]

        plt.scatter(x, y, s=80)
        plt.annotate(
            label,
            (x, y),
            textcoords="offset points",
            xytext=(6, 6),
        )

    plt.xlabel("Total Carbon Emissions (gCO2eq)")
    plt.ylabel("Total Real-Time Cost")
    plt.title("Carbon vs Real-Time Cost Tradeoff")
    plt.tight_layout()
    plt.savefig(PLOTS_DIR / "tradeoff_carbon_vs_real_time_cost.png", dpi=200)
    plt.close()

def save_threshold_tradeoff_plot(summary_df: pd.DataFrame) -> None:
    PLOTS_DIR.mkdir(parents=True, exist_ok=True)

    threshold_df = summary_df.copy()
    threshold_df = threshold_df[threshold_df["tie_threshold_ratio"].notna()]
    threshold_df = threshold_df[threshold_df["tie_threshold_ratio"] != ""].copy()

    if threshold_df.empty:
        return

    threshold_df["tie_threshold_ratio"] = threshold_df["tie_threshold_ratio"].astype(float)
    threshold_df = threshold_df.sort_values("tie_threshold_ratio")

    fig, ax1 = plt.subplots(figsize=(9, 6))
    ax2 = ax1.twinx()

    ax1.plot(
        threshold_df["tie_threshold_ratio"],
        threshold_df["carbon_savings_vs_base_pct"],
        marker="o",
        label="Carbon Savings vs Base (%)",
    )

    ax2.plot(
        threshold_df["tie_threshold_ratio"],
        threshold_df["day_ahead_cost_savings_vs_base_pct"],
        marker="o",
        linestyle="--",
        label="Day-Ahead Cost Savings vs Base (%)",
    )
    ax2.plot(
        threshold_df["tie_threshold_ratio"],
        threshold_df["real_time_cost_savings_vs_base_pct"],
        marker="s",
        linestyle=":",
        label="Real-Time Cost Savings vs Base (%)",
    )

    ax1.set_xlabel("Tie Threshold Ratio")
    ax1.set_ylabel("Carbon Savings vs Base (%)")
    ax2.set_ylabel("Cost Savings vs Base (%)")
    ax1.set_title("Option A Threshold Sensitivity")

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="best")

    fig.tight_layout()
    fig.savefig(PLOTS_DIR / "option_a_threshold_tradeoff.png", dpi=200)
    plt.close(fig)

def main() -> None:
    summary_df, schedule_df = load_data()

    save_bar_plot(summary_df)
    save_scale_timeline_plot(schedule_df)
    save_policy_overlay_plots(schedule_df)
    save_completion_slot_plot(summary_df)
    save_tradeoff_plots(summary_df)
    save_threshold_tradeoff_plot(summary_df)

    print("Wrote plots to:")
    print(PLOTS_DIR.resolve())


if __name__ == "__main__":
    main()