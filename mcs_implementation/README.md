# MCS Implementation

This folder contains a Slurm-based implementation of the CarbonScaler idea from the CarbonScaler paper and repository.

## Goal

Implement a multi-cluster carbon-aware scheduler using:

- **PySlurm**
- **Slurm Workload Manager**
- **5 clusters**
- **simulated power models**
- **carbon traces / forecasts**
- **checkpointed or slot-based execution**

This implementation is intentionally separate from the original Kubernetes / Kubeflow-based CarbonScaler code in the repository.

## High-Level Design

The implementation has four major parts:

1. **Configuration**
   - Cluster definitions
   - Power models
   - Workload definitions

2. **Simulation / Scheduling Core**
   - Carbon trace service
   - Power simulation
   - Throughput and marginal capacity profiling
   - Carbon-aware greedy scheduler
   - Metrics and evaluation

3. **Execution Layer**
   - Slurm adapter using PySlurm
   - Slot-by-slot job submission
   - Progress tracking
   - Optional schedule recomputation

4. **Entry Points**
   - A local simulation runner
   - Later, a real Slurm-backed controller

## Initial Scope

The first working version will support:

- 1 workload:
  - `nbody100k`
- 5 clusters
- fixed time slots
- simulated carbon traces
- simulated power per cluster
- comparison of:
  - carbon-agnostic
  - suspend-resume
  - static scaling
  - CarbonScaler-style dynamic scaling

## Folder Layout

```text
mcs_implementation/
  README.md
  config/
    clusters.yaml
    power_models.yaml
    workloads.yaml
  traces/
  profiles/
  jobs/
    nbody.sbatch.j2
  carbonsim/
    __init__.py
    config.py
    carbon_service.py
    power_sim.py
    profiler.py
    scheduler.py
    metrics.py
    cluster_state.py
    slurm_adapter.py
    controller.py
  run_simulation.py

## Using rsync
Connect to CU VPN: Cisco Client with server address `vpn.colorado.edu`
Kendall: 

rsync -avz --progress ~/Desktop/CarbonScaler/ keah6866@ecen5033-03.int.colorado.edu:~/CarbonScaler/
ssh keah6866@ecen5033-03.int.colorado.edu