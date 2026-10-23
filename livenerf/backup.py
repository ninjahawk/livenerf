"""python -m livenerf.backup: copy the raw logs to a folder outside the repo.

The .eval logs are gitignored (GPQA must not be republished), so the repo alone can't restore them.
Copies every file under logs/, calibration/, confirmation/ and validation/ that the backup doesn't
have yet. It never overwrites and never deletes. Destination: $LIVENERF_BACKUP or ~/livenerf-backup.
daily.jsonl is appended to, so it is re-copied whenever it grew.
"""

import os
import shutil
import sys
from pathlib import Path

from .common import REPO_ROOT

DIRS = ("logs", "calibration", "confirmation", "validation")


def backup(dest: Path) -> int:
    copied = 0
    for d in DIRS:
        for src in (REPO_ROOT / d).rglob("*"):
            if not src.is_file():
                continue
            dst = dest / src.relative_to(REPO_ROOT)
            grew = src.name == "daily.jsonl" and dst.exists() and src.stat().st_size > dst.stat().st_size
            if dst.exists() and not grew:
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            copied += 1
    return copied


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to cp1252
    dest = Path(os.environ.get("LIVENERF_BACKUP") or Path.home() / "livenerf-backup")
    print(f"backed up {backup(dest)} new files to {dest}")


if __name__ == "__main__":
    main()
