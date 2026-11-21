"""Read the Claude plan's usage meters, so livenerf can budget itself against real limits.

    python -m livenerf.usage            # print the 5-hour and weekly utilization (percent)

Max plans don't publish limits in tokens, but Claude Code's /usage reads a percentage from
/api/oauth/usage. livenerf reads the same meter with the local Claude Code login. It is a read-only
GET: the token is read from ~/.claude/.credentials.json (on macOS, from the Keychain item
"Claude Code-credentials" when that file is absent), never refreshed here (a second process
refreshing a single-use refresh token can log Claude Code out) and never logged. If the token has
expired or the call fails, the meter is simply unknown (None).

The endpoint rate-limits (HTTP 429 after a few calls a minute), so readings are cached in
~/.cache/livenerf/usage.json: a reading under FRESH seconds old is reused without a call, and
when a call fails, a reading under STALE seconds old stands in for it.
"""

import getpass
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

URL = "https://api.anthropic.com/api/oauth/usage"
FRESH = 300
STALE = 1800


def _cache() -> Path:
    path = Path(os.environ.get("LIVENERF_CACHE", Path.home() / ".cache" / "livenerf")) / "usage.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _cached(max_age: float) -> dict | None:
    try:
        entry = json.loads(_cache().read_text())
    except (OSError, ValueError):
        return None
    return entry["meters"] if time.time() - entry["at"] < max_age else None


def _token() -> str | None:
    if os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        return os.environ["CLAUDE_CODE_OAUTH_TOKEN"]
    config = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
    try:
        return json.loads((config / ".credentials.json").read_text())["claudeAiOauth"]["accessToken"]
    except (OSError, KeyError, ValueError):
        pass
    if sys.platform != "darwin":
        return None
    # macOS: Claude Code keeps the login in the Keychain, not in .credentials.json
    try:
        out = subprocess.run(["security", "find-generic-password", "-s", "Claude Code-credentials",
                              "-a", getpass.getuser(), "-w"],
                             capture_output=True, text=True, timeout=10)
        return json.loads(out.stdout)["claudeAiOauth"]["accessToken"] if out.returncode == 0 else None
    except (OSError, subprocess.SubprocessError, KeyError, ValueError):
        return None


def meters() -> dict | None:
    """{"five_hour": pct, "weekly": pct, "weekly_resets_at": iso} or None if unavailable."""
    fresh = _cached(FRESH)
    if fresh:
        return fresh
    reading = _read()
    if reading is None:
        return _cached(STALE)
    _cache().write_text(json.dumps({"at": time.time(), "meters": reading}))
    return reading


def _read() -> dict | None:
    token = _token()
    if not token:
        return None
    req = urllib.request.Request(URL, headers={
        "Authorization": f"Bearer {token}", "anthropic-beta": "oauth-2025-04-20", "User-Agent": "livenerf",
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.load(r)
    except Exception:
        return None
    five, week = data.get("five_hour") or {}, data.get("seven_day") or {}
    if week.get("utilization") is None:
        return None
    return {
        # five_hour is null when the plan has no 5-hour limit (the response's "limits" list then has
        # only weekly entries): nothing to cap
        "five_hour": float(five.get("utilization") or 0.0),
        "weekly": float(week["utilization"]),
        "weekly_resets_at": week.get("resets_at"),
        "five_hour_resets_at": five.get("resets_at"),
    }


if __name__ == "__main__":
    print(json.dumps(meters(), indent=2))
