#!/bin/bash
#SBATCH -J vaani-vllm
#SBATCH -p gpu
#SBATCH --gres=gpu:1g.18gb:1
#SBATCH --mem=48G
#SBATCH --cpus-per-task=12
#SBATCH --time=12:00:00
#SBATCH -o slurm/vllm-%j.out

# Serves Qwen3-1.7B on this compute node. The vaani app runs on the
# login node (it needs internet for Sarvam) and reaches this endpoint
# over the cluster LAN; vllm_host.txt tells it where.
cd ~/vaani
export HF_HUB_OFFLINE=1
echo "http://$(hostname):8001/v1" > vllm_host.txt
echo "http://$(hostname):8002" > guard_host.txt

# guard sidecar shares the slice; both models together are tiny
PYTHONPATH=src VAANI_GUARD_DEVICE=cuda HF_HUB_OFFLINE=1 \
  ~/vllm-env/bin/python -m uvicorn vaani.guard_service:app \
  --host 0.0.0.0 --port 8002 > slurm/guards-$SLURM_JOB_ID.log 2>&1 &

exec ~/vllm-env/bin/vllm serve Qwen/Qwen3-1.7B \
  --host 0.0.0.0 --port 8001 \
  --max-model-len 2048 \
  --gpu-memory-utilization 0.75 \
  --max-num-seqs 16
