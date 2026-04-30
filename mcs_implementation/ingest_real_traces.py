from __future__ import annotations

import argparse
import csv
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests


@dataclass(frozen=True)
class CarbonRecord:
    timestamp: str
    carbon_intensity: float


@dataclass(frozen=True)
class PriceRecord:
    timestamp: str
    day_ahead_price: float
    real_time_price: float


def ensure_parent_dir(path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)


def write_carbon_csv(path: str | Path, rows: list[CarbonRecord]) -> None:
    ensure_parent_dir(path)
    with Path(path).open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["timestamp", "carbon_intensity"])
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "timestamp": row.timestamp,
                    "carbon_intensity": row.carbon_intensity,
                }
            )


def write_price_csv(path: str | Path, rows: list[PriceRecord]) -> None:
    ensure_parent_dir(path)
    with Path(path).open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["timestamp", "day_ahead_price", "real_time_price"],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "timestamp": row.timestamp,
                    "day_ahead_price": row.day_ahead_price,
                    "real_time_price": row.real_time_price,
                }
            )


def fetch_electricitymaps_carbon_forecast(
    zone: str,
    horizon_hours: int,
    api_key: str,
) -> list[CarbonRecord]:
    """
    Fetch forecast carbon intensity from Electricity Maps.

    Note:
    - endpoint structure may evolve
    - this function is designed to normalize the response into your CSV format
    """
    url = "https://api.electricitymap.org/v3/carbon-intensity/forecast"
    headers = {"auth-token": api_key}
    params = {"zone": zone}

    response = requests.get(url, headers=headers, params=params, timeout=30)
    response.raise_for_status()
    payload = response.json()

    rows: list[CarbonRecord] = []

    # Common EM response shape: list under "forecast" or "history"/"data"
    candidate_series = None
    if isinstance(payload, dict):
        if "forecast" in payload:
            candidate_series = payload["forecast"]
        elif "data" in payload:
            candidate_series = payload["data"]
        elif "history" in payload:
            candidate_series = payload["history"]

    if not isinstance(candidate_series, list):
        raise ValueError(f"Unexpected Electricity Maps carbon payload: {json.dumps(payload)[:500]}")

    for item in candidate_series[:horizon_hours]:
        timestamp = item.get("datetime") or item.get("timestamp")
        value = (
            item.get("carbonIntensity")
            or item.get("carbon_intensity")
            or item.get("value")
        )
        if timestamp is None or value is None:
            continue
        rows.append(CarbonRecord(timestamp=str(timestamp), carbon_intensity=float(value)))

    if not rows:
        raise ValueError("No usable carbon forecast rows returned from Electricity Maps")

    return rows


def copy_price_csv_from_local(
    source_csv: str | Path,
) -> list[PriceRecord]:
    """
    Load a local real-price CSV and normalize it into PriceRecord rows.

    Required columns:
      timestamp, day_ahead_price, real_time_price
    """
    path = Path(source_csv)
    if not path.exists():
        raise FileNotFoundError(f"Price source file not found: {path}")

    rows: list[PriceRecord] = []

    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        required = {"timestamp", "day_ahead_price", "real_time_price"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Missing required columns in {path}: {sorted(missing)}")

        for row in reader:
            rows.append(
                PriceRecord(
                    timestamp=str(row["timestamp"]).strip(),
                    day_ahead_price=float(row["day_ahead_price"]),
                    real_time_price=float(row["real_time_price"]),
                )
            )

    if not rows:
        raise ValueError(f"No rows found in {path}")

    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest real carbon and price traces into local CSVs.")
    parser.add_argument("--cluster-name", required=True)
    parser.add_argument("--carbon-out", required=True)
    parser.add_argument("--price-out", required=True)

    parser.add_argument(
        "--electricitymaps-zone",
        help="Electricity Maps zone code for carbon forecast ingestion",
    )
    parser.add_argument(
        "--horizon-hours",
        type=int,
        default=48,
        help="Number of forecast hours to ingest",
    )
    parser.add_argument(
        "--price-source-csv",
        help="Local CSV path with timestamp,day_ahead_price,real_time_price",
    )

    args = parser.parse_args()

    if not args.electricitymaps_zone:
        raise ValueError("--electricitymaps-zone is required for carbon ingestion")

    api_key = os.environ.get("ELECTRICITYMAPS_API_KEY")
    if not api_key:
        raise ValueError("Set ELECTRICITYMAPS_API_KEY in your environment")

    carbon_rows = fetch_electricitymaps_carbon_forecast(
        zone=args.electricitymaps_zone,
        horizon_hours=args.horizon_hours,
        api_key=api_key,
    )
    write_carbon_csv(args.carbon_out, carbon_rows)

    if args.price_source_csv:
        price_rows = copy_price_csv_from_local(args.price_source_csv)
        write_price_csv(args.price_out, price_rows)
    else:
        raise ValueError(
            "For now, provide --price-source-csv with real market price data normalized to the required format"
        )

    print("Wrote carbon trace to:", args.carbon_out)
    print("Wrote price trace to:", args.price_out)


if __name__ == "__main__":
    main()