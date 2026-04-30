from __future__ import annotations

import argparse
import csv
import datetime as dt
from collections import defaultdict
from pathlib import Path
import xml.etree.ElementTree as ET

import requests


DA_BASE_URL = "https://reports-public.ieso.ca/public/DAHourlyOntarioZonalPrice/"
RT_BASE_URL = "https://reports-public.ieso.ca/public/RealtimeOntarioZonalPrice/"


def ensure_parent_dir(path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)


def strip_ns(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def find_first_text(root: ET.Element, candidates: list[str]) -> str | None:
    for elem in root.iter():
        if strip_ns(elem.tag) in candidates and elem.text and elem.text.strip():
            return elem.text.strip()
    return None


def fetch_text(url: str) -> str:
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return resp.text


def write_price_csv(path: str | Path, rows: list[dict[str, object]]) -> None:
    ensure_parent_dir(path)
    with Path(path).open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["timestamp", "day_ahead_price", "real_time_price"],
        )
        writer.writeheader()
        writer.writerows(rows)


def parse_day_ahead_xml(xml_text: str) -> list[tuple[str, float]]:
    """
    Returns hourly rows:
      [(timestamp_iso_utc, day_ahead_price), ...]

    Expected Ontario day-ahead structure:
    - DeliveryDate
    - HourlyPriceComponents
    - PricingHour
    - ZonalPrice
    """
    root = ET.fromstring(xml_text)

    date_text = find_first_text(root, ["DeliveryDate", "TradeDate", "Date"])
    if not date_text:
        raise ValueError("Could not find a date in day-ahead Ontario price XML")

    delivery_date = dt.date.fromisoformat(date_text[:10])
    rows: list[tuple[str, float]] = []

    for parent in root.iter():
        child_map: dict[str, str] = {}
        for child in list(parent):
            name = strip_ns(child.tag)
            if child.text and child.text.strip():
                child_map[name] = child.text.strip()

        hour_text = (
            child_map.get("PricingHour")
            or child_map.get("DeliveryHour")
            or child_map.get("Hour")
        )
        if not hour_text:
            continue

        price_text = child_map.get("ZonalPrice")
        if not price_text:
            continue

        hour = int(hour_text)
        price = float(price_text)

        ts = dt.datetime.combine(
            delivery_date,
            dt.time(hour=(hour - 1) % 24, minute=0),
            tzinfo=dt.timezone.utc,
        )
        rows.append((ts.isoformat().replace("+00:00", "Z"), price))

    if not rows:
        raise ValueError("No usable hourly prices found in day-ahead Ontario XML")

    dedup: dict[str, float] = {}
    for ts, price in rows:
        dedup[ts] = price

    return sorted(dedup.items(), key=lambda x: x[0])


def parse_realtime_xml(xml_text: str) -> list[tuple[str, float]]:
    """
    Returns 5-minute rows:
      [(timestamp_iso_utc, real_time_price), ...]

    Expected Ontario realtime structure:
    - DeliveryDate
    - DeliveryHour at DocBody level
    - repeated ZonalPrice blocks
      - Interval
      - LmpCap
      - LossPriceCap
      - CongPriceCap
    """
    root = ET.fromstring(xml_text)

    date_text = find_first_text(root, ["DeliveryDate", "TradeDate", "Date"])
    if not date_text:
        raise ValueError("Could not find a date in realtime Ontario XML")

    delivery_date = dt.date.fromisoformat(date_text[:10])

    delivery_hour_text = find_first_text(root, ["DeliveryHour", "PricingHour", "Hour"])
    if not delivery_hour_text:
        raise ValueError("Could not find DeliveryHour in realtime Ontario XML")

    delivery_hour = int(delivery_hour_text)

    rows: list[tuple[str, float]] = []

    for elem in root.iter():
        if strip_ns(elem.tag) != "ZonalPrice":
            continue

        child_map: dict[str, str] = {}
        for child in list(elem):
            name = strip_ns(child.tag)
            if child.text and child.text.strip():
                child_map[name] = child.text.strip()

        interval_text = child_map.get("Interval")
        if not interval_text:
            continue

        interval = int(interval_text)

        lmp = float(child_map.get("LmpCap", child_map.get("LMP", child_map.get("Lmp", "0"))))
        loss = float(child_map.get("LossPriceCap", child_map.get("LossPrice", "0")))
        cong = float(child_map.get("CongPriceCap", child_map.get("CongPrice", "0")))

        price = lmp + loss + cong

        minute = (interval - 1) * 5
        ts = dt.datetime.combine(
            delivery_date,
            dt.time(hour=(delivery_hour - 1) % 24, minute=minute),
            tzinfo=dt.timezone.utc,
        )
        rows.append((ts.isoformat().replace("+00:00", "Z"), price))

    if not rows:
        raise ValueError("No usable 5-minute prices found in realtime Ontario XML")

    dedup: dict[str, float] = {}
    for ts, price in rows:
        dedup[ts] = price

    return sorted(dedup.items(), key=lambda x: x[0])


def hourly_average_realtime(rt_rows: list[tuple[str, float]]) -> list[tuple[str, float]]:
    buckets: dict[str, list[float]] = defaultdict(list)

    for ts_text, price in rt_rows:
        ts = dt.datetime.fromisoformat(ts_text.replace("Z", "+00:00"))
        hour_ts = ts.replace(minute=0, second=0, microsecond=0)
        key = hour_ts.isoformat().replace("+00:00", "Z")
        buckets[key].append(price)

    hourly = []
    for key in sorted(buckets.keys()):
        vals = buckets[key]
        hourly.append((key, sum(vals) / len(vals)))

    return hourly


def build_day_ahead_url(delivery_date: dt.date) -> str:
    stamp = delivery_date.strftime("%Y%m%d")
    return f"{DA_BASE_URL}PUB_DAHourlyOntarioZonalPrice_{stamp}.xml"


def build_realtime_hour_url(delivery_date: dt.date, hour_1_to_24: int) -> str:
    # File naming convention uses YYYYMMDDHH where HH is 01..24
    stamp = delivery_date.strftime("%Y%m%d") + f"{hour_1_to_24:02d}"
    return f"{RT_BASE_URL}PUB_RealtimeOntarioZonalPrice_{stamp}.xml"


def fetch_day_ahead_rows_for_delivery_date(delivery_date: dt.date) -> list[tuple[str, float]]:
    url = build_day_ahead_url(delivery_date)
    xml_text = fetch_text(url)
    rows = parse_day_ahead_xml(xml_text)
    if not rows:
        raise ValueError(f"No day-ahead rows found for {delivery_date}")
    return rows


def fetch_realtime_rows_for_delivery_date(delivery_date: dt.date) -> list[tuple[str, float]]:
    rows_5min: list[tuple[str, float]] = []

    for hour in range(1, 25):
        url = build_realtime_hour_url(delivery_date, hour)
        try:
            xml_text = fetch_text(url)
        except requests.HTTPError:
            continue

        try:
            rows_5min.extend(parse_realtime_xml(xml_text))
        except Exception:
            continue

    if not rows_5min:
        raise ValueError(f"No realtime rows found for {delivery_date}")

    return hourly_average_realtime(rows_5min)


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch single-day historical Ontario day-ahead and realtime price traces")
    parser.add_argument("--output", required=True, help="Output CSV path")
    parser.add_argument("--delivery-date", required=True, help="Delivery date in YYYY-MM-DD format")
    args = parser.parse_args()

    delivery_date = dt.date.fromisoformat(args.delivery_date)

    da_rows = fetch_day_ahead_rows_for_delivery_date(delivery_date)
    rt_rows = fetch_realtime_rows_for_delivery_date(delivery_date)

    da_map = {ts: price for ts, price in da_rows}
    rt_map = {ts: price for ts, price in rt_rows}

    common_timestamps = sorted(set(da_map.keys()) & set(rt_map.keys()))
    if not common_timestamps:
        raise ValueError(f"No overlapping hourly timestamps for {delivery_date}")

    output_rows = []
    for ts in common_timestamps:
        output_rows.append(
            {
                "timestamp": ts,
                "day_ahead_price": da_map[ts],
                "real_time_price": rt_map[ts],
            }
        )

    write_price_csv(args.output, output_rows)
    print("Wrote:", args.output)
    print("Rows:", len(output_rows))


if __name__ == "__main__":
    main()