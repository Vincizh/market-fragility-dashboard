"""Run-level freshness guard for the GitHub Actions workflow.

Two decisions, both read data/health.json:

  skip   A scheduled run is skipped when the committed page was generated less than
         SKIP_MINUTES ago. Several cron lines fire per hour because GitHub drops many
         scheduled runs; this keeps the ones that do fire from duplicating each other.

  retry  After a run, list the sources that need another attempt:
           * first run (attempt 0): sources that were current before the run and are now
             failed or served from cache, so a source that has been down for days does not
             spawn retries every hour;
           * retry run: the sources it was asked to retry that are still failed or cached.
         A job failure always counts. The workflow re-dispatches itself with a growing delay
         until the list is empty or MAX_ATTEMPTS is reached.

Usage (prints key=value lines for $GITHUB_OUTPUT):
  python refresh_guard.py skip  --health data/health.json --event schedule
  python refresh_guard.py retry --before /tmp/health_before.json --after data/health.json \
                                --attempt 0 --retry-for "" --job-status success
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from typing import Any

SKIP_MINUTES = 25
MAX_ATTEMPTS = 3
DELAYS_MIN = (0, 5, 15, 30)       # wait before attempt 1, 2, 3
BAD = ("failed", "cached")


def _load(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _status(health: dict[str, Any]) -> dict[str, str]:
    return {s.get("name"): s.get("status") for s in health.get("sources", []) if s.get("name")}


def minutes_since(health: dict[str, Any], now: datetime | None = None) -> float | None:
    g = health.get("generated_at")
    if not g:
        return None
    try:
        t = datetime.strptime(g, "%Y-%m-%d %H:%M UTC").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return ((now or datetime.now(timezone.utc)) - t).total_seconds() / 60.0


def should_skip(health: dict[str, Any], event: str, now: datetime | None = None) -> bool:
    if event != "schedule":
        return False
    m = minutes_since(health, now)
    return m is not None and 0 <= m < SKIP_MINUTES


def retry_targets(before: dict[str, Any], after: dict[str, Any], attempt: int, retry_for: list[str],
                  job_status: str) -> list[str]:
    now = _status(after)
    if attempt == 0:
        prev = _status(before)
        targets = sorted(n for n, st in now.items() if st in BAD and prev.get(n, "current") == "current")
    else:
        targets = sorted(n for n in retry_for if n != "job" and now.get(n) in BAD)
    if job_status not in ("success", "skipped"):
        targets = ["job"] + targets
    return targets


def next_attempt(attempt: int, targets: list[str]) -> int | None:
    """Attempt number to dispatch, or None when there is nothing to retry or the budget is spent."""
    if not targets or attempt >= MAX_ATTEMPTS:
        return None
    return attempt + 1


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("skip", "retry", "delay"))
    ap.add_argument("--health")
    ap.add_argument("--before")
    ap.add_argument("--after")
    ap.add_argument("--event", default="")
    ap.add_argument("--attempt", type=int, default=0)
    ap.add_argument("--retry-for", default="")
    ap.add_argument("--job-status", default="success")
    a = ap.parse_args()
    if a.cmd == "skip":
        h = _load(a.health)
        print("skip={}".format("true" if should_skip(h, a.event) else "false"))
        print("age_min={}".format("" if minutes_since(h) is None else round(minutes_since(h), 1)))
    elif a.cmd == "delay":
        print("seconds={}".format(60 * DELAYS_MIN[min(max(a.attempt, 0), len(DELAYS_MIN) - 1)]))
    else:
        rf = [x for x in a.retry_for.split("|") if x]     # source names can contain commas
        t = retry_targets(_load(a.before), _load(a.after), a.attempt, rf, a.job_status)
        n = next_attempt(a.attempt, t)
        print("targets={}".format("|".join(t)))
        print("next_attempt={}".format("" if n is None else n))


if __name__ == "__main__":
    main()
