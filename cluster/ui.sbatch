#!/bin/bash
# The TriageSim app on a GPU node, with its own Ollama: download models and run
# experiments from your browser, like on your PC. Submit from the TriageSim folder:
#   sbatch cluster/ui.sbatch
# Then read logs/triagesim-ui_<jobid>.out for the tunnel command to run on your laptop.
# The app and Ollama listen on the node itself only (127.0.0.1), never on the network.
#SBATCH --job-name=triagesim-ui
#SBATCH --partition=gpu
#SBATCH --account=slurm-students
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=10:00:00
#SBATCH --output=logs/%x_%j.out
set -uo pipefail
cd "$SLURM_SUBMIT_DIR"
mkdir -p logs
export PATH="$HOME/.local/bin:$PATH"

OLLAMA="${OLLAMA_BIN:-$(command -v ollama || echo "$HOME/bin/ollama")}"
export OLLAMA_MODELS="${OLLAMA_MODELS:-$HOME/.ollama/models}"   # reuses earlier downloads
export OLLAMA_HOST="127.0.0.1:$((20000 + SLURM_JOB_ID % 10000))"
export OLLAMA_KEEP_ALIVE=30m OLLAMA_MAX_LOADED_MODELS=3
export TRIAGESIM_OLLAMA_URL="http://$OLLAMA_HOST"
"$OLLAMA" serve > "logs/ollama_${SLURM_JOB_ID}.log" 2>&1 &
OLLAMA_PID=$!
for _ in $(seq 90); do curl -s "$TRIAGESIM_OLLAMA_URL/api/version" >/dev/null && break; sleep 2; done

PORT=$((30000 + SLURM_JOB_ID % 10000))
NODE=$(hostname)
cat <<MSG
============================================================================
TriageSim is starting on $NODE (job $SLURM_JOB_ID). GPU:
$(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null || echo "  (nvidia-smi not found)")

On your laptop, open a terminal and run (keep it open):
    ssh -N -L 8765:127.0.0.1:$PORT -J $USER@<login address> $USER@$NODE
Then open  http://127.0.0.1:8765  in your browser.

Stop the app when done (frees the GPU):  scancel $SLURM_JOB_ID
Runs started in the app stop with it; resume them later from the app.
============================================================================
MSG
trap 'kill "$OLLAMA_PID" 2>/dev/null' EXIT
uv run --frozen triagesim ui --no-browser --port "$PORT"
