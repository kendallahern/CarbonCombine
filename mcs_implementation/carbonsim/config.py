from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class ClusterConfig:
    name: str
    region: str
    display_name: str
    slurm_cluster_name: str
    partition: str
    nodes: int
    max_replicas: int
    trace_file: str
    speed_factor: float
    enabled: bool


@dataclass(frozen=True)
class PowerModelConfig:
    cluster_name: str
    display_name: str
    idle_watts_per_node: float
    full_watts_per_node: float
    pue: float
    network_overhead_watts_per_node: float


@dataclass(frozen=True)
class WorkloadConfig:
    name: str
    display_name: str
    type: str
    min_replicas: int
    max_replicas: int
    baseline_runtime_hours: float
    deadline_hours: float
    slot_minutes: int
    total_work_units: float
    throughput_by_scale: dict[int, float]
    utilization_by_scale: dict[int, float]
    checkpointable: bool
    recompute_schedule_each_slot: bool


@dataclass(frozen=True)
class SimulationConfig:
    clusters: list[ClusterConfig]
    power_models: dict[str, PowerModelConfig]
    workloads: dict[str, WorkloadConfig]


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if data is None:
        raise ValueError(f"Config file is empty: {path}")

    if not isinstance(data, dict):
        raise ValueError(f"Expected a YAML dictionary in {path}, got: {type(data)}")

    return data


def _normalize_int_key_dict(raw: dict[Any, Any], field_name: str) -> dict[int, float]:
    normalized: dict[int, float] = {}

    for key, value in raw.items():
        try:
            scale = int(key)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Invalid scale key in '{field_name}': {key!r}. Expected integer-like keys."
            ) from exc

        try:
            normalized[scale] = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Invalid numeric value in '{field_name}' for scale {scale}: {value!r}"
            ) from exc

    return normalized


def load_clusters(config_dir: str | Path) -> list[ClusterConfig]:
    path = Path(config_dir) / "clusters.yaml"
    data = _load_yaml(path)

    raw_clusters = data.get("clusters")
    if not isinstance(raw_clusters, list):
        raise ValueError(f"'clusters' must be a list in {path}")

    clusters: list[ClusterConfig] = []
    for item in raw_clusters:
        clusters.append(
            ClusterConfig(
                name=str(item["name"]),
                region=str(item["region"]),
                display_name=str(item["display_name"]),
                slurm_cluster_name=str(item["slurm_cluster_name"]),
                partition=str(item["partition"]),
                nodes=int(item["nodes"]),
                max_replicas=int(item["max_replicas"]),
                trace_file=str(item["trace_file"]),
                speed_factor=float(item["speed_factor"]),
                enabled=bool(item["enabled"]),
            )
        )

    return clusters


def load_power_models(config_dir: str | Path) -> dict[str, PowerModelConfig]:
    path = Path(config_dir) / "power_models.yaml"
    data = _load_yaml(path)

    raw_models = data.get("power_models")
    if not isinstance(raw_models, dict):
        raise ValueError(f"'power_models' must be a dictionary in {path}")

    models: dict[str, PowerModelConfig] = {}
    for cluster_name, item in raw_models.items():
        models[str(cluster_name)] = PowerModelConfig(
            cluster_name=str(cluster_name),
            display_name=str(item["display_name"]),
            idle_watts_per_node=float(item["idle_watts_per_node"]),
            full_watts_per_node=float(item["full_watts_per_node"]),
            pue=float(item["pue"]),
            network_overhead_watts_per_node=float(item["network_overhead_watts_per_node"]),
        )

    return models


def load_workloads(config_dir: str | Path) -> dict[str, WorkloadConfig]:
    path = Path(config_dir) / "workloads.yaml"
    data = _load_yaml(path)

    raw_workloads = data.get("workloads")
    if not isinstance(raw_workloads, list):
        raise ValueError(f"'workloads' must be a list in {path}")

    workloads: dict[str, WorkloadConfig] = {}
    for item in raw_workloads:
        name = str(item["name"])

        throughput_by_scale = _normalize_int_key_dict(
            item["throughput_by_scale"],
            field_name=f"{name}.throughput_by_scale",
        )
        utilization_by_scale = _normalize_int_key_dict(
            item["utilization_by_scale"],
            field_name=f"{name}.utilization_by_scale",
        )

        workloads[name] = WorkloadConfig(
            name=name,
            display_name=str(item["display_name"]),
            type=str(item["type"]),
            min_replicas=int(item["min_replicas"]),
            max_replicas=int(item["max_replicas"]),
            baseline_runtime_hours=float(item["baseline_runtime_hours"]),
            deadline_hours=float(item["deadline_hours"]),
            slot_minutes=int(item["slot_minutes"]),
            total_work_units=float(item["total_work_units"]),
            throughput_by_scale=throughput_by_scale,
            utilization_by_scale=utilization_by_scale,
            checkpointable=bool(item["checkpointable"]),
            recompute_schedule_each_slot=bool(item["recompute_schedule_each_slot"]),
        )

    return workloads


def load_simulation_config(config_dir: str | Path) -> SimulationConfig:
    clusters = load_clusters(config_dir)
    power_models = load_power_models(config_dir)
    workloads = load_workloads(config_dir)

    enabled_clusters = [cluster for cluster in clusters if cluster.enabled]
    if not enabled_clusters:
        raise ValueError("No enabled clusters found in clusters.yaml")

    for cluster in enabled_clusters:
        if cluster.name not in power_models:
            raise ValueError(
                f"Missing power model for cluster '{cluster.name}' in power_models.yaml"
            )

    return SimulationConfig(
        clusters=enabled_clusters,
        power_models=power_models,
        workloads=workloads,
    )