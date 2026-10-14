#!/bin/bash
# Download the models an experiment needs, on the LOGIN node (no GPU needed, just internet).
# Use this when the GPU nodes have no internet access.
#   bash cluster/pull_models.sh configs/experiments/benchmark/<file>.yaml
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
OLLAMA="${OLLAMA_BIN:-$(command -v ollama || echo "$HOME/bin/ollama")}"
export OLLAMA_MODELS="${OLLAMA_MODELS:-$HOME/ollama-models}"
export OLLAMA_HOST="127.0.0.1:$((20000 + RANDOM % 10000))"
export TRIAGESIM_OLLAMA_URL="http://$OLLAMA_HOST"
"$OLLAMA" serve > /tmp/ollama_pull_$$.log 2>&1 &
PID=$!; trap 'kill $PID 2>/dev/null' EXIT
for _ in $(seq 60); do curl -s "$TRIAGESIM_OLLAMA_URL/api/version" >/dev/null && break; sleep 1; done
uv run --frozen triagesim models pull --experiment "$1"
echo "Models are in $OLLAMA_MODELS"
