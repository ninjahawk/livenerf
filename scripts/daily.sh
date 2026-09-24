#!/usr/bin/env bash
# The daily livenerf run (see livenerf/daily.py). Cron: every hour from 05:07 to 23:07; the script
# does nothing once today's run is in, so a blocked or missed hour catches up at the next one:
#   7 5-23 * * * cd /path/to/livenerf && bash scripts/daily.sh >> logs/daily.log 2>&1
set -euo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python
[ -x "$PY" ] || PY=.venv/Scripts/python.exe  # Windows venv layout
"$PY" -m livenerf.daily
