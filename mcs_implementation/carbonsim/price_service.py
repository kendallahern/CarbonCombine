from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import csv


@dataclass(frozen=True)
class PricePoint:
    timestamp: str
    day_ahead_price: float
    real_time_price: float


class PriceTrace:
    def __init__(self, cluster_name: str, points: list[PricePoint]) -> None:
        if not points:
            raise ValueError(f"Price trace for cluster '{cluster_name}' is empty")

        self.cluster_name = cluster_name
        self.points = points

    def __len__(self) -> int:
        return len(self.points)

    def at(self, index: int) -> PricePoint:
        wrapped = index % len(self.points)
        return self.points[wrapped]


class PriceService:
    """
    Simulation-only price service.

    Each cluster has:
    - a loaded price trace
    - a current index into that trace

    The service can return:
    - current day-ahead and real-time prices
    - a day-ahead forecast window
    - a real-time forecast/value window
    - the timestamp at the current slot
    - advance all clusters by one slot
    """

    def __init__(self, traces: dict[str, PriceTrace]) -> None:
        if not traces:
            raise ValueError("PriceService requires at least one cluster trace")

        self._traces = traces
        self._indices: dict[str, int] = {cluster_name: 0 for cluster_name in traces}

    @property
    def cluster_names(self) -> list[str]:
        return list(self._traces.keys())

    def current_index(self, cluster_name: str) -> int:
        self._validate_cluster(cluster_name)
        return self._indices[cluster_name]

    def current_point(self, cluster_name: str) -> PricePoint:
        self._validate_cluster(cluster_name)
        idx = self._indices[cluster_name]
        return self._traces[cluster_name].at(idx)

    def current_timestamp(self, cluster_name: str) -> str:
        return self.current_point(cluster_name).timestamp

    def current_day_ahead_price(self, cluster_name: str) -> float:
        return self.current_point(cluster_name).day_ahead_price

    def current_real_time_price(self, cluster_name: str) -> float:
        return self.current_point(cluster_name).real_time_price

    def forecast(self, cluster_name: str, horizon_slots: int) -> list[PricePoint]:
        self._validate_cluster(cluster_name)

        if horizon_slots <= 0:
            raise ValueError("horizon_slots must be > 0")

        trace = self._traces[cluster_name]
        start = self._indices[cluster_name]

        return [trace.at(start + offset) for offset in range(horizon_slots)]

    def day_ahead_forecast_values(self, cluster_name: str, horizon_slots: int) -> list[float]:
        return [point.day_ahead_price for point in self.forecast(cluster_name, horizon_slots)]

    def real_time_forecast_values(self, cluster_name: str, horizon_slots: int) -> list[float]:
        return [point.real_time_price for point in self.forecast(cluster_name, horizon_slots)]

    def advance(self, steps: int = 1) -> None:
        if steps < 0:
            raise ValueError("steps must be >= 0")

        for cluster_name, trace in self._traces.items():
            self._indices[cluster_name] = (self._indices[cluster_name] + steps) % len(trace)

    def set_index(self, cluster_name: str, index: int) -> None:
        self._validate_cluster(cluster_name)

        trace_len = len(self._traces[cluster_name])
        self._indices[cluster_name] = index % trace_len

    def _validate_cluster(self, cluster_name: str) -> None:
        if cluster_name not in self._traces:
            raise KeyError(f"Unknown cluster '{cluster_name}'")


def load_price_trace(csv_path: str | Path, cluster_name: str) -> PriceTrace:
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"Price trace not found: {path}")

    points: list[PricePoint] = []

    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)

        required_columns = {"timestamp", "day_ahead_price", "real_time_price"}
        missing = required_columns - set(reader.fieldnames or [])
        if missing:
            raise ValueError(
                f"Price trace {path} is missing required columns: {sorted(missing)}"
            )

        for row in reader:
            timestamp = str(row["timestamp"]).strip()
            day_ahead_price = float(row["day_ahead_price"])
            real_time_price = float(row["real_time_price"])

            points.append(
                PricePoint(
                    timestamp=timestamp,
                    day_ahead_price=day_ahead_price,
                    real_time_price=real_time_price,
                )
            )

    return PriceTrace(cluster_name=cluster_name, points=points)


def load_price_trace_config(config_path: str | Path) -> dict[str, str]:
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Price trace config not found: {path}")

    import yaml

    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        raise ValueError(f"Expected YAML dictionary in {path}")

    raw = data.get("price_traces")
    if not isinstance(raw, dict):
        raise ValueError(f"'price_traces' must be a dictionary in {path}")

    normalized: dict[str, str] = {}
    for cluster_name, trace_path in raw.items():
        normalized[str(cluster_name)] = str(trace_path)

    return normalized


def build_price_service(config_path: str | Path) -> PriceService:
    trace_map = load_price_trace_config(config_path)

    traces: dict[str, PriceTrace] = {}
    for cluster_name, trace_path in trace_map.items():
        traces[cluster_name] = load_price_trace(
            csv_path=trace_path,
            cluster_name=cluster_name,
        )

    return PriceService(traces=traces)