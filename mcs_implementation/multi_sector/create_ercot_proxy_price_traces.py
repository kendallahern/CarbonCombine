from __future__ import annotations

import argparse
import csv
import math
import random
from pathlib import Path


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def read_price_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        required = {"timestamp", "day_ahead_price", "real_time_price"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{path} missing columns: {sorted(missing)}")
        return list(reader)


def write_price_csv(path: Path, rows: list[dict[str, object]]) -> None:
    ensure_dir(path.parent)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["timestamp", "day_ahead_price", "real_time_price"],
        )
        writer.writeheader()
        writer.writerows(rows)


def hour_from_timestamp(timestamp: str) -> int:
    # timestamp format: 2026-04-06T00:00:00Z
    return int(timestamp.split("T")[1].split(":")[0])


def ercot_proxy_transform(
    rows: list[dict[str, str]],
    seed: int,
    volatility: float = 1.0,
) -> list[dict[str, object]]:
    """
    Convert Ontario-style price traces into ERCOT-style proxy traces.

    This is NOT official ERCOT data. It preserves the same timestamps and schema,
    but reshapes the price behavior to look more ERCOT-like:
      - lower overnight prices
      - higher late afternoon / evening prices
      - more real-time volatility
      - occasional scarcity spikes
    """
    rng = random.Random(seed)
    out: list[dict[str, object]] = []

    for row in rows:
        ts = row["timestamp"]
        hour = hour_from_timestamp(ts)

        ont_da = float(row["day_ahead_price"])
        ont_rt = float(row["real_time_price"])

        # Daily shape: ERCOT often has stronger afternoon/evening stress.
        evening_peak = math.exp(-((hour - 18) ** 2) / 18.0)
        morning_peak = 0.45 * math.exp(-((hour - 7) ** 2) / 16.0)
        overnight_discount = -0.25 if 0 <= hour <= 5 else 0.0

        shape_multiplier = 0.85 + 0.55 * evening_peak + 0.20 * morning_peak + overnight_discount
        shape_multiplier = max(0.45, shape_multiplier)

        # Day-ahead proxy: smoother than real-time.
        da_noise = rng.normalvariate(0.0, 3.0 * volatility)
        ercot_da = ont_da * shape_multiplier + da_noise

        # Real-time proxy: more volatile and can diverge from DA.
        rt_spread = rng.normalvariate(0.0, 12.0 * volatility)
        ercot_rt = ercot_da + rt_spread

        # Occasional scarcity events, biased toward late afternoon/evening.
        spike_probability = 0.015
        if 15 <= hour <= 20:
            spike_probability = 0.055

        if rng.random() < spike_probability:
            spike = rng.uniform(75, 350) * volatility
            ercot_rt += spike

            # Sometimes DA partially anticipates scarcity, but less sharply.
            if rng.random() < 0.35:
                ercot_da += spike * rng.uniform(0.15, 0.45)

        # Occasional very low/near-zero real-time prices during low-load hours.
        if 0 <= hour <= 5 and rng.random() < 0.04:
            ercot_rt = rng.uniform(0, 5)

        # Keep values non-negative for this project.
        ercot_da = max(0.0, ercot_da)
        ercot_rt = max(0.0, ercot_rt)

        out.append(
            {
                "timestamp": ts,
                "day_ahead_price": round(ercot_da, 4),
                "real_time_price": round(ercot_rt, 4),
            }
        )

    return out


def output_name_from_ontario_name(name: str) -> str:
    # ontario_week01_2026-04-06_to_2026-04-12_price.csv
    return name.replace("ontario_", "ercot_texas_", 1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Create ERCOT/Texas-style proxy weekly price CSVs from existing "
            "Ontario weekly price CSVs. These are synthetic proxy traces, not "
            "official ERCOT data."
        )
    )
    parser.add_argument(
        "--input-dir",
        default="mcs_implementation/multi_sector/weekly_price_csvs/ontario",
        help="Directory containing Ontario weekly price CSVs",
    )
    parser.add_argument(
        "--output-dir",
        default="mcs_implementation/multi_sector/weekly_price_csvs/texas",
        help="Directory where ERCOT proxy CSVs will be written",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducible proxy traces",
    )
    parser.add_argument(
        "--volatility",
        type=float,
        default=1.0,
        help="Volatility multiplier. Try 0.75, 1.0, or 1.25",
    )

    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    ensure_dir(output_dir)

    if not input_dir.exists():
        raise FileNotFoundError(f"Input directory not found: {input_dir}")

    files = sorted(input_dir.glob("ontario_week*_price.csv"))
    if not files:
        raise FileNotFoundError(f"No Ontario weekly price CSVs found in {input_dir}")

    print(f"Input dir : {input_dir}")
    print(f"Output dir: {output_dir}")
    print(f"Files     : {len(files)}")
    print("Mode      : ERCOT/Texas synthetic proxy prices")

    for idx, path in enumerate(files):
        rows = read_price_csv(path)
        proxy_rows = ercot_proxy_transform(
            rows,
            seed=args.seed + idx,
            volatility=args.volatility,
        )

        out_path = output_dir / output_name_from_ontario_name(path.name)
        write_price_csv(out_path, proxy_rows)

        print(f"  ✓ {path.name} -> {out_path.name} ({len(proxy_rows)} rows)")

    readme = output_dir / "README_ercot_proxy_data.txt"
    readme.write_text(
        "These CSV files are ERCOT/Texas-style synthetic proxy electricity price traces.\n"
        "They were generated from Ontario weekly price CSVs by preserving timestamps\n"
        "and applying ERCOT-like daily shape, volatility, and scarcity-spike behavior.\n"
        "They are NOT official ERCOT market data and should be described as proxy/synthetic\n"
        "data in the report or final codebase.\n",
        encoding="utf-8",
    )

    print("\nWrote README:")
    print(readme)


if __name__ == "__main__":
    main()