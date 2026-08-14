#!/bin/bash
#SBATCH -J vaani-smoke
#SBATCH -p gpu
#SBATCH --gres=gpu:1g.18gb:1
#SBATCH --mem=32G
#SBATCH --cpus-per-task=8
#SBATCH --time=00:15:00
#SBATCH -o slurm/smoke-%j.out
cd ~/vaani
export HF_HUB_OFFLINE=1
.venv/bin/python scripts/gpu_smoke.py
