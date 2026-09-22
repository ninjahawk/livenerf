#!/usr/bin/env bash
# One hourly livenerf batch. Cron example (runs at minute 7 of every hour):
#   7 * * * * cd /path/to/livenerf && bash scripts/hourly.sh 5 >> logs/cron.log 2>&1
set -euo pipefail
cd "$(dirname "$0")/.."
N="${1:-5}"
export DISABLE_AUTOUPDATER=1
# refuse to run if the CLI drifted from the pinned version (see CLAUDE_CLI_VERSION)
PIN="$(cat CLAUDE_CLI_VERSION)"
exec .venv/bin/python -m livenerf.schedule --n "$N" -M expect_cli_version="$PIN"
