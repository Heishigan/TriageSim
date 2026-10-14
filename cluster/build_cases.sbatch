#!/bin/bash
# Build the cohort and its case files on a compute node (needs ~16 GB memory, no GPU).
#   sbatch cluster/build_cases.sbatch configs/cohorts/elderly_falls.yaml
#SBATCH --job-name=triagesim-cases
#SBATCH --partition=gpu
#SBATCH --account=slurm-students
#SBATCH --cpus-per-task=2
#SBATCH --mem=24G
#SBATCH --time=01:00:00
#SBATCH --output=logs/%x_%j.out
set -euo pipefail
cd "$SLURM_SUBMIT_DIR"
export PATH="$HOME/.local/bin:$PATH"
uv run --frozen triagesim cohort check
OUT=$(uv run --frozen triagesim cohort build --settings "$1" | tee /dev/stderr | sed -n 's/^Saved to //p')
uv run --frozen triagesim cases build --cohort "$OUT"
