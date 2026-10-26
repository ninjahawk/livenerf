"""python -m livenerf.merge_runner SRC: bring a fallback runner's daily runs into this repo's logs/.

SRC is the fallback runner's logs directory (its daily.jsonl and .eval files, e.g. copied from the
Conductor VM's checkout). For each "ran" line there from a runner other than "host":

- refused if this repo already has that UTC day, as a "ran" line in logs/daily.jsonl or as any
  .eval log in logs/ for that day: at most one run per UTC day, and the first one in wins. A host
  run that broke off part-way blocks the day until its logs are listed in
  livenerf.analysis.EXCLUDED_RUNS (2026-10-05 rule), with a deviations-log entry;
- refused if a listed log is missing, names another day or runner, or has a harness hash other than
  data/harness.lock;
- otherwise its .eval logs are copied into logs/ (never overwriting) and its line is appended to
  logs/daily.jsonl with a "merged_at" time.

A refused run's logs stay where they are (never under logs/, which analysis reads recursively).
Afterwards run livenerf.plot, livenerf.record and livenerf.backup as after a daily run.

    python -m livenerf.merge_runner /path/to/vm-logs            # merge
    python -m livenerf.merge_runner /path/to/vm-logs --dry-run  # say what would happen
"""

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from .common import REPO_ROOT
from .daily import HARNESS_LOCK, HOST, ran_days

LOGS = REPO_ROOT / "logs"


def eval_days(log_dir: Path) -> set:
    """UTC days (livenerf_day metadata) of every .eval log under log_dir, except excluded runs."""
    from inspect_ai.log import list_eval_logs, read_eval_log

    from .analysis import EXCLUDED_RUNS

    if not log_dir.exists():
        return set()
    return {(read_eval_log(i, header_only=True).eval.metadata or {}).get("livenerf_day")
            for i in list_eval_logs(str(log_dir))
            if i.name.replace("\\", "/").rsplit("/", 1)[-1] not in EXCLUDED_RUNS} - {None}


def check(entry: dict, src: Path, lock: str, logs: Path) -> str | None:
    """Why this run can't be merged, or None."""
    from inspect_ai.log import read_eval_log

    if not entry.get("logs"):
        return "the ran line lists no logs"
    for name in entry["logs"]:
        f = src / name
        if not f.exists():
            return f"missing log {name}"
        meta = read_eval_log(str(f), header_only=True).eval.metadata or {}
        if meta.get("livenerf_day") != entry["day"] or meta.get("runner") != entry.get("runner"):
            return f"{name} is day {meta.get('livenerf_day')!r} runner {meta.get('runner')!r}"
        if (meta.get("harness_sha") or "").partition("+")[2] != lock:
            return f"{name} harness {meta.get('harness_sha')!r}, lock {lock}"
        if (logs / name).exists():
            return f"{name} already in logs/"
    return None


def merge(src: Path, dry_run: bool = False, logs: Path = LOGS) -> list:
    """Merge every new fallback day from src into logs; returns [(day, runner, outcome)]."""
    daily = logs / "daily.jsonl"
    lock = HARNESS_LOCK.read_text().strip()
    have = set(ran_days(daily)) | eval_days(logs)
    out = []
    for line in (src / "daily.jsonl").read_text().splitlines():
        e = json.loads(line) if line.strip() else {}
        if e.get("status") != "ran" or e.get("runner", HOST) == HOST:
            continue
        day, runner = e["day"], e["runner"]
        if day in have:
            out.append((day, runner, "refused: this repo already has that day"))
            continue
        why = check(e, src, lock, logs)
        if why:
            out.append((day, runner, f"refused: {why}"))
            continue
        if not dry_run:
            for name in e["logs"]:
                shutil.copy2(src / name, logs / name)
            with daily.open("a") as f:
                f.write(json.dumps({**e, "merged_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}) + "\n")
        have.add(day)
        out.append((day, runner, "merged" if not dry_run else "would merge"))
    return out


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to cp1252
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src", type=Path, help="the fallback runner's logs directory")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    results = merge(args.src, args.dry_run)
    for day, runner, outcome in results:
        print(f"{day} {runner}: {outcome}")
    if not results:
        print("nothing to merge: no fallback ran lines in", args.src / "daily.jsonl")


if __name__ == "__main__":
    main()
