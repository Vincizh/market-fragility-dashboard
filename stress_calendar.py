"""Rolling 120-day liquidity calendar.

Every event carries a status:
  announced  published by the issuer (Treasury upcoming auctions)
  scheduled  fixed by rule or by the Fed's published meeting calendar
  estimated  derived from the usual pattern, not yet announced

No severity percentiles are invented: the weekly load is simply the number of events,
with quarter-end and refunding settlement counted twice because they move the most cash.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Iterable

import pandas as pd

import fast_metrics as fm

# Source: https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm (second day = decision day).
FOMC_DECISION_DAYS = [
    date(2026, 1, 28), date(2026, 3, 18), date(2026, 4, 29), date(2026, 6, 17),
    date(2026, 7, 29), date(2026, 9, 16), date(2026, 10, 28), date(2026, 12, 9),
    date(2027, 1, 27), date(2027, 3, 17), date(2027, 4, 28), date(2027, 6, 9),
    date(2027, 7, 28), date(2027, 9, 15), date(2027, 10, 27), date(2027, 12, 8),
]
FOMC_SOURCE = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
UPCOMING_URL = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/od/upcoming_auctions"
COUPON_TYPES = {"Note", "Bond", "TIPS", "FRN", "TIPS Note", "TIPS Bond"}


def _bday_on_or_after(d: date) -> date:
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def _month_end_business_day(year: int, month: int) -> date:
    nxt = date(year + (month == 12), month % 12 + 1, 1)
    d = nxt - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def fomc_covers(today: date, horizon_days: int = 120) -> bool:
    """False when the hard-coded FOMC list ends before the end of the calendar window."""
    return max(FOMC_DECISION_DAYS) >= today + timedelta(days=horizon_days)


TD_UPCOMING_URL = "https://www.treasurydirect.gov/TA_WS/securities/upcoming"


def _td_security_type(r: dict[str, Any]) -> str:
    t = str(r.get("securityType") or "")
    if str(r.get("floatingRate")) == "Yes":
        return "FRN"
    if str(r.get("inflationProtected")) == "Yes" and t in ("Note", "Bond"):
        return "TIPS " + t
    return t


def treasurydirect_upcoming_frame(rows: Iterable[dict[str, Any]]) -> pd.DataFrame:
    """TreasuryDirect upcoming auctions mapped onto the FiscalData column names."""
    out = []
    for r in rows or []:
        out.append({"cusip": r.get("cusip"), "security_type": _td_security_type(r), "security_term": r.get("securityTerm"),
                    "reopening": r.get("reopening"), "auction_date": r.get("competitiveAuctionCloseDate") or r.get("auctionDate"),
                    "issue_date": r.get("issueDate"), "announcemt_date": r.get("announcementDate"),
                    "offering_amt": r.get("offeringAmount") or None, "source": "TreasuryDirect"})
    return pd.DataFrame(out)


def merge_upcoming(fiscal: pd.DataFrame | None, td: pd.DataFrame | None) -> pd.DataFrame:
    """Union of both feeds. On the same (cusip, issue date) TreasuryDirect wins, because FiscalData's
    upcoming_auctions table can stop updating for weeks (it froze at record date 2026-10-16)."""
    frames = []
    for f, src in ((td, "TreasuryDirect"), (fiscal, "FiscalData")):
        if f is not None and not f.empty:
            f = f.copy()
            f["source"] = f["source"] if "source" in f else src
            for c in ("auction_date", "issue_date", "announcemt_date"):
                if c in f:
                    f[c] = pd.to_datetime(f[c], errors="coerce")
            f["offering_amt"] = pd.to_numeric(f.get("offering_amt"), errors="coerce")
            frames.append(f)
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    df["_k"] = df["cusip"].astype(str) + "|" + df["issue_date"].astype(str)
    df = df.drop_duplicates("_k", keep="first").drop(columns="_k")
    return df.sort_values("auction_date").reset_index(drop=True)


def fetch_upcoming(today: date, horizon_days: int = 120) -> pd.DataFrame:
    """Announced Treasury auctions from TreasuryDirect and FiscalData (empty frame when both fail)."""
    fiscal = td = None
    errors = []
    try:
        params = {"filter": "auction_date:gte:{}".format((today - timedelta(days=3)).isoformat()),
                  "sort": "auction_date", "page[size]": "500"}
        fiscal = pd.DataFrame(fm._get(UPCOMING_URL, params=params, timeout=40).json().get("data", []))
    except Exception as exc:  # noqa: BLE001
        errors.append("FiscalData: " + str(exc)[:80])
    try:
        td = treasurydirect_upcoming_frame(fm._get(TD_UPCOMING_URL, params={"format": "json"}, timeout=40).json())
    except Exception as exc:  # noqa: BLE001
        errors.append("TreasuryDirect: " + str(exc)[:80])
    df = merge_upcoming(fiscal, td)
    if df.empty and errors:
        raise RuntimeError("; ".join(errors))
    if not df.empty:
        df = df[df["auction_date"].isna() | (df["auction_date"] >= pd.Timestamp(today - timedelta(days=3)))]
    return df.reset_index(drop=True)


def coupon_settlements(upcoming: pd.DataFrame, start: date, end: date) -> list[dict[str, Any]]:
    if upcoming is None or upcoming.empty or "issue_date" not in upcoming:
        return []
    u = upcoming[upcoming["security_type"].isin(COUPON_TYPES)].dropna(subset=["issue_date"])
    out = []
    for issue, g in u.groupby("issue_date"):
        d = issue.date()
        if not (start <= d <= end):
            continue
        terms = sorted(set(str(t) for t in g["security_term"]), key=lambda t: (len(t), t))
        known = g["offering_amt"].dropna()
        amt = " ($%.0fB announced)" % (known.sum() / 1e9) if len(known) == len(g) and len(g) else " (amount not yet announced)"
        out.append({"date": d, "kind": "coupon", "weight": 1, "status": "announced",
                    "label": "Treasury coupon settlement: " + ", ".join(terms) + amt})
    return out


def build_events(today: date, upcoming: pd.DataFrame | None = None, horizon_days: int = 120) -> list[dict[str, Any]]:
    start, end = today - timedelta(days=7), today + timedelta(days=horizon_days)
    ev: list[dict[str, Any]] = []
    for d in FOMC_DECISION_DAYS:
        if start <= d <= end:
            ev.append({"date": d, "kind": "fomc", "weight": 1, "status": "scheduled", "label": "FOMC decision day"})
    for y in range(start.year, end.year + 1):
        for d in sorted(fm.tax_dates(y)):
            if start <= d <= end:
                ev.append({"date": d, "kind": "tax", "weight": 1, "status": "scheduled", "label": "Corporate estimated tax date (TGA inflow)"})
        for m in range(1, 13):
            d = _month_end_business_day(y, m)
            if start <= d <= end:
                q = m in (3, 6, 9, 12)
                ev.append({"date": d, "kind": "quarter_end" if q else "month_end", "weight": 2 if q else 1, "status": "scheduled",
                           "label": "Quarter-end balance-sheet date" if q else "Month-end settlement date"})
        for m in (2, 5, 8, 11):
            # Quarterly refunding: announcement on the first Wednesday, settlement on the 15th (business day).
            first = date(y, m, 1)
            wed = first + timedelta(days=(2 - first.weekday()) % 7)
            if start <= wed <= end:
                ev.append({"date": wed, "kind": "refunding_ann", "weight": 1, "status": "estimated",
                           "label": "Quarterly refunding announcement (first Wednesday pattern)"})
            settle = _bday_on_or_after(date(y, m, 15))
            if start <= settle <= end:
                ev.append({"date": settle, "kind": "refunding_settle", "weight": 2, "status": "estimated",
                           "label": "Quarterly refunding settlement (15th, next business day)"})
    ev.extend(coupon_settlements(upcoming if upcoming is not None else pd.DataFrame(), start, end))
    ev.sort(key=lambda e: (e["date"], -e["weight"]))
    return ev


def weekly_load(events: Iterable[dict[str, Any]], today: date, horizon_days: int = 120) -> list[dict[str, Any]]:
    """Event weight per ISO week (Monday start) from the week before today through the horizon."""
    first = today - timedelta(days=today.weekday() + 7)
    weeks = []
    n = (horizon_days + 14) // 7 + 1
    for i in range(n):
        ws = first + timedelta(days=7 * i)
        weeks.append({"week": ws, "load": 0, "events": []})
    for e in events:
        idx = (e["date"] - first).days // 7
        if 0 <= idx < len(weeks):
            weeks[idx]["load"] += e["weight"]
            weeks[idx]["events"].append(e)
    return weeks


def chart_payload(weeks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for w in weeks:
        load = w["load"]
        color = "#334155" if load == 0 else ("#f59e0b" if load <= 2 else ("#f97316" if load <= 4 else "#ef4444"))
        text = "<br>".join("{} {}: {} [{}]".format(e["date"].strftime("%b %d"), e["kind"].replace("_", " "), e["label"], e["status"]) for e in w["events"]) or "no scheduled events"
        out.append({"d": w["week"].isoformat(), "v": load, "c": color, "t": text})
    return out
