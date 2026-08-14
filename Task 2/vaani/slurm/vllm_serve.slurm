#!/bin/bash
#SBATCH -J vaani-vllm
#SBATCH -p gpu
#SBATCH --gres=gpu:1g.24gb:1
#SBATCH --mem=48G
#SBATCH --cpus-per-task=12
#SBATCH --time=12:00:00
#SBATCH -o slurm/vllm-%j.out

# Serves Qwen3-1.7B on this compute node. The vaani app runs on the
# login node (it needs internet for Sarvam) and reaches this endpoint
# over the cluster LAN; vllm_host.txt tells it where.
cd ~/vaani
# flashinfer JIT needs nvcc; compute nodes get cuda from the module tree
source /usr/share/Modules/init/bash 2>/dev/null || true
module load cuda-12.8 2>/dev/null || true
if command -v nvcc > /dev/null; then
  export CUDA_HOME=$(dirname "$(dirname "$(command -v nvcc)")")
  echo "cuda at $CUDA_HOME"
fi
export HF_HUB_OFFLINE=1
export PATH=$HOME/vllm-env/bin:$PATH
# flashinfer JIT kernels do not compile on these nodes; use the
# precompiled attention backend and torch sampler instead
export VLLM_ATTENTION_BACKEND=FLASH_ATTN
export VLLM_USE_FLASHINFER_SAMPLER=0
echo "http://$(hostname):8001/v1" > vllm_host.txt
echo "http://$(hostname):8002" > guard_host.txt

# guard sidecar shares the slice; both models together are tiny
PYTHONPATH=src VAANI_GUARD_DEVICE=cuda HF_HUB_OFFLINE=1 \
  ~/vllm-env/bin/python -m uvicorn vaani.guard_service:app \
  --host 0.0.0.0 --port 8002 > slurm/guards-$SLURM_JOB_ID.log 2>&1 &

exec ~/vllm-env/bin/vllm serve "${VAANI_LLM:-Qwen/Qwen3-1.7B}" \
  --host 0.0.0.0 --port 8001 \
  --max-model-len 2048 \
  --gpu-memory-utilization 0.75 \
  --max-num-seqs 16
