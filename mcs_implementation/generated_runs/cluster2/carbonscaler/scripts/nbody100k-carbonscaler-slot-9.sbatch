#!/bin/bash
#SBATCH --job-name=nbody100k-carbonscaler-slot-9
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --time=01:00:00
#SBATCH --output=/tmp/nbody100k-carbonscaler-slot-9.out
#SBATCH --error=/tmp/nbody100k-carbonscaler-slot-9.err

echo "Starting job: nbody100k-carbonscaler-slot-9"
echo "Cluster: cluster2"
echo "Nodes: 1"
echo "Slot minutes: 60"
echo "Checkpoint path: /tmp/mcs_checkpoints/nbody100k.ckpt"
echo "Slot index: 9"
echo "Scale: 1"
echo "Work per slot: 1.0"
echo "Remaining work: 24.0"

python3 /tmp/nbody_slot_runner.py \
  --checkpoint-path "/tmp/mcs_checkpoints/nbody100k.ckpt" \
  --slot-index "9" \
  --scale "1" \
  --work-per-slot "1.0" \
  --remaining-work "24.0"

echo "Completed job: nbody100k-carbonscaler-slot-9"