#!/bin/bash
#SBATCH --job-name=nbody100k-carbonscaler-slot-39
#SBATCH --nodes=2
#SBATCH --ntasks-per-node=1
#SBATCH --time=01:00:00
#SBATCH --output=/tmp/nbody100k-carbonscaler-slot-39.out
#SBATCH --error=/tmp/nbody100k-carbonscaler-slot-39.err

echo "Starting job: nbody100k-carbonscaler-slot-39"
echo "Cluster: cluster2"
echo "Nodes: 2"
echo "Slot minutes: 60"
echo "Checkpoint path: /tmp/mcs_checkpoints/nbody100k.ckpt"
echo "Slot index: 39"
echo "Scale: 2"
echo "Work per slot: 1.87"
echo "Remaining work: 1.4299999999999926"

python3 /tmp/nbody_slot_runner.py \
  --checkpoint-path "/tmp/mcs_checkpoints/nbody100k.ckpt" \
  --slot-index "39" \
  --scale "2" \
  --work-per-slot "1.87" \
  --remaining-work "1.4299999999999926"

echo "Completed job: nbody100k-carbonscaler-slot-39"