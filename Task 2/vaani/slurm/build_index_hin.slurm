#!/bin/bash
#SBATCH -J vaani-index
#SBATCH -p gpu
#SBATCH --gres=gpu:1g.18gb:1
#SBATCH --mem=96G
#SBATCH --cpus-per-task=16
#SBATCH --time=03:00:00
#SBATCH -o slurm/index-%j.out
cd ~/vaani
export HF_HUB_OFFLINE=1
.venv/bin/python scripts/build_indexes.py --corpus data/corpus/hin_val --out indexes/hin_val --strategy passage --batch 512
.venv/bin/python scripts/build_indexes.py --corpus data/corpus/hin_val --out indexes/hin_val --strategy sentence --batch 512
