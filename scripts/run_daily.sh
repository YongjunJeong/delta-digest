#!/usr/bin/env bash
# Daily pipeline runner — Oracle Cloud ARM (Ubuntu 22.04)
# Cron: 0 5 * * * /home/ubuntu/delta-digest/scripts/run_daily.sh >> /home/ubuntu/delta-digest/outputs/logs/cron.log 2>&1

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

export PATH="/opt/homebrew/opt/openjdk@11/bin:$HOME/.local/bin:$PATH"
export JAVA_HOME="/opt/homebrew/opt/openjdk@11"

echo "=== delta-digest daily run: $(date) ==="

# Activate venv via uv
uv run python src/run_daily.py "$@"

echo "=== done: $(date) ==="
