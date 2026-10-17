#!/bin/bash
# The TriageSim app on a GPU node, with its own Ollama: download models and run
# experiments from your browser, like on your PC. Submit from the TriageSim folder:
#   sbatch cluster/ui.sbatch
# Then read logs/triagesim-ui_<jobid>.out for the tunnel command to run on your laptop.
# Users cannot ssh into the GPU nodes here, so the app listens on the node's internal
# address, protected by a random access token that only you can read
# (~/.triagesim/ui-<jobid>.url). Ollama stays on the node itself (127.0.0.1).
# Set LOGIN_HOST if your login node has another address.
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
NODE_IP=$(hostname -I | awk '{print $1}')
LOGIN_HOST="${LOGIN_HOST:-slurm-login.dsv.su.se}"
export TRIAGESIM_ACCESS_TOKEN=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
umask 077
mkdir -p "$HOME/.triagesim"
URL_FILE="$HOME/.triagesim/ui-$SLURM_JOB_ID.url"
echo "http://127.0.0.1:18765/?token=$TRIAGESIM_ACCESS_TOKEN" > "$URL_FILE"
umask 022
cat <<MSG
============================================================================
TriageSim is starting on $NODE (job $SLURM_JOB_ID). GPU:
$(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null || echo "  (nvidia-smi not found)")

1. On your laptop, open a terminal and run (keep it open):
       ssh -N -L 18765:$NODE_IP:$PORT $USER@$LOGIN_HOST
2. On the login node, get your private address (contains the access token):
       cat ~/.triagesim/ui-$SLURM_JOB_ID.url
   and open it in your browser. Afterwards http://127.0.0.1:18765 is enough.

Stop the app when done (frees the GPU):  scancel $SLURM_JOB_ID
Restart only the app, e.g. after 'git pull' (same address, same job; on the login node):
    srun --jobid=$SLURM_JOB_ID --overlap pkill -f "uvicorn triagesim.server.app"
Runs started in the app stop with it; resume them later from the app.
============================================================================
MSG
trap 'kill "$OLLAMA_PID" 2>/dev/null; rm -f "$URL_FILE"' EXIT
# The app restarts by itself when it stops (see the restart command above); scancel ends the job.
while true; do
    uv run --frozen triagesim ui --no-browser --host "$NODE_IP" --port "$PORT"
    echo "$(date +%H:%M:%S)  TriageSim stopped; restarting in 3 s (scancel $SLURM_JOB_ID ends the job)"
    sleep 3
done
