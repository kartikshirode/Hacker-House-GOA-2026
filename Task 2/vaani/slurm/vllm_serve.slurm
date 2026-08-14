#!/bin/bash
#SBATCH -J vaani-vllm
#SBATCH -p gpu
#SBATCH --gres=gpu:1g.24gb:1
#SBATCH --mem=48G
#SBATCH --cpus-per-task=12
#SBATCH --time=12:00:00
#SBATCH -o slurm/vllm-%j.out

# Serves the answer model on this compute node. The vaani app runs on
# the login node (it needs internet for Sarvam) and reaches this over
# the cluster LAN; vllm_host.txt tells it where. Host files publish only
# after the services answer, so a file that exists means a service that
# works.
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

rm -f vllm_host.txt guard_host.txt
~/vllm-env/bin/python -c 'import vllm; print("vllm", vllm.__version__)'

# guard sidecar shares the slice; both models together are tiny.
# it runs in guard-env: hhem's remote code needs transformers 4.x
PYTHONPATH=src VAANI_GUARD_DEVICE=cuda HF_HUB_OFFLINE=1 \
  ~/guard-env/bin/python -m uvicorn vaani.guard_service:app \
  --host 0.0.0.0 --port 8002 > slurm/guards-$SLURM_JOB_ID.log 2>&1 &

# ngram speculative decoding: answers copy context spans, and prompt
# lookup feeds on exactly that. Override with VAANI_SPEC, disable with
# VAANI_SPEC=off to get the baseline.
SPEC=${VAANI_SPEC:-'{"method":"ngram","num_speculative_tokens":4,"prompt_lookup_max":4,"prompt_lookup_min":2}'}
SPEC_ARGS=()
if [ "$SPEC" != "off" ]; then
  SPEC_ARGS=(--speculative-config "$SPEC")
  echo "speculative config: $SPEC"
else
  echo "speculative decoding off"
fi

~/vllm-env/bin/vllm serve "${VAANI_LLM:-Qwen/Qwen3-0.6B}" \
  --host 0.0.0.0 --port 8001 \
  --max-model-len 2048 \
  --gpu-memory-utilization 0.75 \
  --max-num-seqs 16 \
  "${SPEC_ARGS[@]}" &
VLLM_PID=$!

for i in $(seq 1 120); do
  if curl -sf "http://localhost:8001/v1/models" > /dev/null; then
    echo "http://$(hostname):8001/v1" > vllm_host.txt
    echo "vllm ready after ~$((i * 5))s"
    break
  fi
  sleep 5
done
for i in $(seq 1 60); do
  if curl -sf "http://localhost:8002/healthz" > /dev/null; then
    echo "http://$(hostname):8002" > guard_host.txt
    echo "guards ready"
    break
  fi
  sleep 5
done

wait $VLLM_PID
