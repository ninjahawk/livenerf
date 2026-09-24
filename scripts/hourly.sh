#!/usr/bin/env bash
# One hourly livenerf batch (see livenerf/hourly.py). Cron example, minute 7 of every hour:
#   7 * * * * cd /path/to/livenerf && bash scripts/hourly.sh >> logs/cron.log 2>&1
set -euo pipefail
cd "$(dirname "$0")/.."
export DISABLE_AUTOUPDATER=1
PY=.venv/bin/python
[ -x "$PY" ] || PY=.venv/Scripts/python.exe  # Windows venv layout
"$PY" -m livenerf.hourly
