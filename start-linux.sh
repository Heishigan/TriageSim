#!/bin/bash
# TriageSim: double-click this file to start.
cd "$(dirname "$0")" || exit 1
if ! command -v uv >/dev/null 2>&1; then
    echo "First run: installing uv, which sets up Python and the app. This takes a few minutes."
    curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="$HOME/.local/bin:$PATH"
uv run triagesim ui || read -rp "Press Enter to close."
