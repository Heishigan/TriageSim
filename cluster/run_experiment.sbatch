#!/bin/bash
# TriageSim experiment on one GPU. Submit from the TriageSim folder:
#   sbatch cluster/run_experiment.sbatch configs/experiments/benchmark/<file>.yaml
#   sbatch cluster/run_experiment.sbatch --resume outputs/runs/<run folder>
# Adjust partition/account/GPU/time to your cluster (see docs/cluster.md).
#SBATCH --job-name=triagesim
#SBATCH --partition=gpu
#SBATCH --account=slurm-students
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=12:00:00
#SBATCH --output=logs/%x_%j.out
#SBATCH --signal=B:TERM@180
set -uo pipefail
cd "$SLURM_SUBMIT_DIR"
mkdir -p logs
export PATH="$HOME/.local/bin:$PATH"

# ---- Ollama: one private server per job, models from a shared folder --------------
OLLAMA="${OLLAMA_BIN:-$(command -v ollama || echo "$HOME/bin/ollama")}"
export OLLAMA_MODELS="${OLLAMA_MODELS:-$HOME/.ollama/models}"   # Ollama's default: reuses earlier downloads
export OLLAMA_HOST="127.0.0.1:$((20000 + SLURM_JOB_ID % 10000))"   # own port per job
export OLLAMA_KEEP_ALIVE=-1          # keep models loaded for the whole job
export OLLAMA_MAX_LOADED_MODELS=3    # nurse, patient and evaluator at once if memory allows
export TRIAGESIM_OLLAMA_URL="http://$OLLAMA_HOST"
"$OLLAMA" serve > "logs/ollama_${SLURM_JOB_ID}.log" 2>&1 &
OLLAMA_PID=$!
trap 'kill "$OLLAMA_PID" 2>/dev/null' EXIT
for _ in $(seq 90); do curl -s "$TRIAGESIM_OLLAMA_URL/api/version" >/dev/null && break; sleep 2; done
echo "Job $SLURM_JOB_ID on $(hostname) | Ollama $("$OLLAMA" --version 2>&1 | tail -1) at $TRIAGESIM_OLLAMA_URL"
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader

# ---- Run (or resume). Slurm sends TERM 3 minutes before the time limit: the run stops
# after the current case and can be resumed with --resume.
if [ "${1:-}" = "--resume" ]; then
  uv run --frozen triagesim run --resume "$2" &
else
  uv run --frozen triagesim models pull --experiment "$1" || exit 1    # no-op if already downloaded
  uv run --frozen triagesim run --experiment "$1" &
fi
RUN_PID=$!
trap 'echo "Time limit near: stopping after the current case"; kill -TERM "$RUN_PID"' TERM
wait "$RUN_PID"; STATUS=$?
if kill -0 "$RUN_PID" 2>/dev/null; then   # the signal interrupted the wait: let the run finish its case
  wait "$RUN_PID"; STATUS=$?
fi
exit $STATUS
