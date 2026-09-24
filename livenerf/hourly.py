"""One hourly livenerf batch: the entry point for cron or Windows Task Scheduler.

    python -m livenerf.hourly

1. Refuses to run if `claude --version` differs from CLAUDE_CLI_VERSION (the harness is pinned).
2. Skips the batch if the plan's usage is already high (livenerf.usage), so the benchmark never
   competes with normal use: weekly meter at or above --weekly-cap, or 5-hour meter at or above
   --five-hour-cap. A skipped hour is logged, not retried.
3. Runs this hour's slice of each arm (livenerf.schedule, at the rates livenerf.design wrote to
   data/standard_panel.json), then refreshes the README charts.

Every run appends one line to logs/hourly.jsonl with the meters before and after, which is the
running record of what the series costs in plan terms.
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone

from .common import REPO_ROOT, claude_cli
from .usage import meters

LOG = REPO_ROOT / "logs" / "hourly.jsonl"


def record(entry: dict) -> None:
    LOG.parent.mkdir(exist_ok=True)
    entry = {"time": datetime.now(timezone.utc).isoformat(timespec="seconds"), **entry}
    with LOG.open("a") as f:
        f.write(json.dumps(entry) + "\n")
    print(json.dumps(entry), flush=True)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to cp1252
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--weekly-cap", type=float, default=75, help="skip if the weekly meter is at or above this")
    ap.add_argument("--five-hour-cap", type=float, default=60, help="skip if the 5-hour meter is at or above this")
    ap.add_argument("--dry-run", action="store_true", help="check the pin and meters, show the slice, run nothing")
    args = ap.parse_args()

    pin = (REPO_ROOT / "CLAUDE_CLI_VERSION").read_text().strip()
    version = subprocess.run([claude_cli(), "--version"], capture_output=True, text=True).stdout.strip()
    if pin not in version:
        record({"status": "refused", "reason": f"claude CLI is {version!r}, pinned {pin!r}"})
        sys.exit(1)
    from .design import lock_ok

    locked, detail = lock_ok()
    if not locked:
        record({"status": "refused", "reason": f"panel not frozen or changed: {detail}"})
        sys.exit(1)

    before = meters()
    if before is None:
        record({"status": "skipped", "reason": "usage meter unavailable"})
        return
    if before["weekly"] >= args.weekly_cap or before["five_hour"] >= args.five_hour_cap:
        record({"status": "skipped", "reason": "usage above cap", "before": before})
        return

    if args.dry_run:
        subprocess.run([sys.executable, "-m", "livenerf.schedule", "--dry-run"], cwd=REPO_ROOT)
        print(f"dry run: meters {before}", flush=True)
        return

    run = subprocess.run(
        [sys.executable, "-m", "livenerf.schedule", "-M", f"expect_cli_version={pin}"],
        cwd=REPO_ROOT,
    )
    subprocess.run([sys.executable, "-m", "livenerf.plot"], cwd=REPO_ROOT)
    record({"status": "ran" if run.returncode == 0 else "failed", "returncode": run.returncode,
            "before": before, "after": meters()})


if __name__ == "__main__":
    main()
