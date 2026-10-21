"""Embedded dashboard state: a rolling daily snapshot of headline readings.

The workflow commits only generated files, so history lives inside index.html in a
<script id="dash-state"> JSON block (same approach as the SPY/QQQ GEX history). Each run reads
the previous page, upserts today's snapshot, keeps 45 days and compares against a snapshot
5 to 10 days old for the "What changed" panel.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import Any

STATE_RE = re.compile(r'<script id="dash-state" type="application/json">(.*?)</script>', re.DOTALL)
KEEP_DAYS = 45


def load(prev_html: str) -> dict[str, dict[str, Any]]:
    if not prev_html:
        return {}
    m = STATE_RE.search(prev_html)
    if not m:
        return {}
    try:
        raw = json.loads(m.group(1))
    except (ValueError, TypeError):
        return {}
    days = raw.get("days") if isinstance(raw, dict) else None
    if not isinstance(days, dict):
        return {}
    return {d: v for d, v in days.items() if isinstance(v, dict)}


def update(days: dict[str, dict[str, Any]], today: str, snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out = dict(days)
    out[today] = snapshot
    keep = sorted(out)[-KEEP_DAYS:]
    return {d: out[d] for d in keep}


def block(days: dict[str, dict[str, Any]]) -> str:
    payload = json.dumps({"v": 1, "days": days}, separators=(",", ":")).replace("</", "<\\/")
    return '<script id="dash-state" type="application/json">' + payload + "</script>"


def pick_base(days: dict[str, dict[str, Any]], today: str, lo: int = 5, hi: int = 10) -> str | None:
    """Snapshot date closest to 7 days before today, accepted when 5 to 10 days old."""
    t = date.fromisoformat(today)
    best, best_gap = None, 99
    for d in days:
        try:
            gap = (t - date.fromisoformat(d)).days
        except ValueError:
            continue
        if lo <= gap <= hi and abs(gap - 7) < best_gap:
            best, best_gap = d, abs(gap - 7)
    return best


def compare(days: dict[str, dict[str, Any]], today: str, snapshot: dict[str, Any]) -> tuple[str | None, list[dict[str, Any]]]:
    """Return (base date, changes). A change is a headline whose state differs from the base."""
    base = pick_base(days, today)
    if base is None:
        return None, []
    prev = days[base]
    out = []
    for key, cur in snapshot.items():
        p = prev.get(key)
        if not isinstance(p, dict) or not isinstance(cur, dict):
            continue
        if p.get("s") != cur.get("s") and p.get("s") and cur.get("s"):
            out.append({"key": key, "label": cur.get("label", key), "from": p["s"], "to": cur["s"],
                        "prev": p.get("t", ""), "now": cur.get("t", "")})
    return base, out
