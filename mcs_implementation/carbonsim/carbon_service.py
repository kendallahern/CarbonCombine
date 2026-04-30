from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import csv

from .config import ClusterConfig


@dataclass(frozen=True)
class CarbonPoint:
    timestamp: str
    carbon_intensity: float


class CarbonTrace:
    def __init__(self, cluster_name: str, points: list[CarbonPoint]) -> None:
        if not points:
            raise ValueError(f"Carbon trace for cluster '{cluster_name}' is empty")

        self.cluster_name = cluster_name
        self.points = points

    def __len__(self) -> int:
        return len(self.points)

    def at(self, index: int) -> CarbonPoint:
        wrapped = index % len(self.points)
        return self.points[wrapped]


class CarbonService:
    """
    Simulation-only carbon service.

    Each cluster has:
    - a loaded carbon trace
    - a current index into that trace

    The service can return:
    - current carbon intensity
    - a forecast window
    - the timestamp at the current slot
    - advance all clusters by one slot
    """

    def __init__(self, traces: dict[str, CarbonTrace]) -> None:
        if not traces:
            raise ValueError("CarbonService requires at least one cluster trace")

        self._traces = traces
        self._indices: dict[str, int] = {cluster_name: 0 for cluster_name in traces}

    @property
    def cluster_names(self) -> list[str]:
        return list(self._traces.keys())

    def current_index(self, cluster_name: str) -> int:
        self._validate_cluster(cluster_name)
        return self._indices[cluster_name]

    def current_point(self, cluster_name: str) -> CarbonPoint:
        self._validate_cluster(cluster_name)
        idx = self._indices[cluster_name]
        return self._traces[cluster_name].at(idx)

    def current_carbon_intensity(self, cluster_name: str) -> float:
        return self.current_point(cluster_name).carbon_intensity

    def current_timestamp(self, cluster_name: str) -> str:
        return self.current_point(cluster_name).timestamp

    def forecast(self, cluster_name: str, horizon_slots: int) -> list[CarbonPoint]:
        self._validate_cluster(cluster_name)

        if horizon_slots <= 0:
            raise ValueError("horizon_slots must be > 0")

        trace = self._traces[cluster_name]
        start = self._indices[cluster_name]

        return [trace.at(start + offset) for offset in range(horizon_slots)]

    def forecast_values(self, cluster_name: str, horizon_slots: int) -> list[float]:
        return [point.carbon_intensity for point in self.forecast(cluster_name, horizon_slots)]

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


def load_carbon_trace(csv_path: str | Path, cluster_name: str) -> CarbonTrace:
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"Carbon trace not found: {path}")

    points: list[CarbonPoint] = []

    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)

        required_columns = {"timestamp", "carbon_intensity"}
        missing = required_columns - set(reader.fieldnames or [])
        if missing:
            raise ValueError(
                f"Carbon trace {path} is missing required columns: {sorted(missing)}"
            )

        for row in reader:
            timestamp = str(row["timestamp"]).strip()
            carbon_intensity = float(row["carbon_intensity"])
            points.append(
                CarbonPoint(
                    timestamp=timestamp,
                    carbon_intensity=carbon_intensity,
                )
            )

    return CarbonTrace(cluster_name=cluster_name, points=points)


def build_carbon_service(clusters: list[ClusterConfig]) -> CarbonService:
    traces: dict[str, CarbonTrace] = {}

    for cluster in clusters:
        traces[cluster.name] = load_carbon_trace(
            csv_path=cluster.trace_file,
            cluster_name=cluster.name,
        )

    return CarbonService(traces=traces)