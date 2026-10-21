"""Data-health registry: every data source reports its observation date and status.

The registry is process-global and written once per run to data/health.json. When the
GITHUB_STEP_SUMMARY environment variable is set, stale and failed sources are also written
there as a Markdown table so a silent outage (such as the FRED User-Agent stall) is visible
in the Actions run page.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REGISTRY: dict[str, dict[str, Any]] = {}

STATUSES = ("current", "cached", "stale", "failed")


def reset() -> None:
    _REGISTRY.clear()


def register(name: str, source: str, observation_date: str | None, cadence: str,
             status: str, fetched_at: str | None = None, note: str = "") -> None:
    if status not in STATUSES:
        raise ValueError("status must be one of " + ", ".join(STATUSES))
    _REGISTRY[name] = {
        "name": name, "source": source, "observation_date": observation_date,
        "cadence": cadence, "status": status,
        "fetched_at": fetched_at or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "note": note,
    }


def entries() -> list[dict[str, Any]]:
    return sorted(_REGISTRY.values(), key=lambda e: (e["status"] == "current", e["name"]))


def summary() -> dict[str, Any]:
    items = list(_REGISTRY.values())
    counts = {k: sum(1 for e in items if e["status"] == k) for k in STATUSES}
    n = len(items)
    ok = counts["current"] + counts["cached"]
    return {"total": n, "current": counts["current"], "cached": counts["cached"],
            "stale": counts["stale"], "failed": counts["failed"],
            "chip": "Sources {}/{} current".format(counts["current"], n)
                    + (" · {} cached".format(counts["cached"]) if counts["cached"] else "")
                    + (" · {} stale".format(counts["stale"]) if counts["stale"] else "")
                    + (" · {} failed".format(counts["failed"]) if counts["failed"] else ""),
            "all_current": ok == n and counts["cached"] == 0 and n > 0}


def write_json(path: str | Path = "data/health.json") -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {"generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
               "summary": summary(), "sources": entries()}
    p.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def write_step_summary() -> bool:
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if not target:
        return False
    bad = [e for e in entries() if e["status"] in ("stale", "failed", "cached")]
    s = summary()
    lines = ["## Data health", "", s["chip"], ""]
    if bad:
        lines += ["| Source | Status | Last observation | Cadence | Note |", "|---|---|---|---|---|"]
        for e in bad:
            lines.append("| {} | {} | {} | {} | {} |".format(
                e["name"], e["status"], e["observation_date"] or "none", e["cadence"],
                (e["note"] or "").replace("|", "/")))
    else:
        lines.append("All sources current.")
    with open(target, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return True
