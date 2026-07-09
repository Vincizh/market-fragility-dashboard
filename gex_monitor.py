#!/usr/bin/env python3
"""FlashAlpha GEX Monitor (Phase 2b).

Free-tier constrained: 5 requests/day, EVERY request counts (even 403/429).
Only single stocks from the free universe work, WITH a mandatory ?expiration=
filter. Index/ETF symbols (SPX/SPY/QQQ/SOX...) are tier-blocked and must never
be requested (a 403 still burns a quota slot).

State persists between hourly CI runs by embedding a JSON block inside
index.html (the workflow commits only index.html, so a separate gex_history.json
would be lost). generate_dashboard.py re-reads the previous index.html at
startup and passes its text to load_state().

All functions here are pure/side-effect-light and injectable (http client, clock)
so they can be exercised with mocked API responses in test_gex.py.
"""

import json
import re
from datetime import datetime, timezone, timedelta

import requests

# ---------------------------------------------------------------------------
# Config (edit here if the account is upgraded to Basic/Growth later)
# ---------------------------------------------------------------------------
GEX_API_BASE   = "https://lab.flashalpha.com/v1/exposure/gex/"
GEX_SCHEDULE   = {          # UTC hour -> symbol fetched on that hourly (:05) run
    14: "NVDA",             # ~10:05 ET post-open  (QQQ/NDX gamma bellwether proxy)
    15: "AAPL",             # ~11:05 ET            (SPX mega-cap proxy)
    16: "AMD",              # ~12:05 ET            (SOX/semis proxy)
    18: "MU",               # ~14:05 ET            (SOX/memory proxy)
    19: "NVDA",             # ~15:05 ET pre-close  (2nd NVDA reading)
}
GEX_SYMBOLS      = ["NVDA", "AAPL", "AMD", "MU"]   # card display order
GEX_EXPIRY_MODE  = "front_weekly"
GEX_DAILY_LIMIT  = 5
GEX_HISTORY_MAX  = 400        # cap embedded history records (keeps index.html small)
GEX_TIMEOUT      = 15
GEX_US_CLOSE_UTC = 21         # ~16:00 ET; Friday before close still uses today's expiry
GEX_STATE_RE     = re.compile(
    r'<script id="gex-state" type="application/json">(.*?)</script>', re.DOTALL)


# ---------------------------------------------------------------------------
# State container (serialised into index.html, round-tripped each run)
# ---------------------------------------------------------------------------
def default_state():
    return {
        "history":  [],   # list of fetch records (see _make_record)
        "excluded": [],   # symbols permanently blocked (403 tier/universe)
        "cards":    {},    # symbol -> last known card dict (for cached display)
        "daily":    {"date": None, "count": 0, "hours": []},
    }


def load_state(prev_html):
    """Extract the embedded gex-state JSON from a prior index.html string."""
    if not prev_html:
        return default_state()
    m = GEX_STATE_RE.search(prev_html)
    if not m:
        return default_state()
    try:
        raw = json.loads(m.group(1))
    except (ValueError, TypeError):
        return default_state()
    st = default_state()
    if isinstance(raw, dict):
        st["history"]  = raw.get("history", []) or []
        st["excluded"] = raw.get("excluded", []) or []
        st["cards"]    = raw.get("cards", {}) or {}
        d = raw.get("daily") or {}
        st["daily"] = {
            "date":  d.get("date"),
            "count": int(d.get("count", 0) or 0),
            "hours": list(d.get("hours", []) or []),
        }
    return st


def state_to_html_block(state):
    """Serialise state into the <script> block embedded in index.html.

    History is trimmed to the newest GEX_HISTORY_MAX records. '</' is escaped so
    the JSON can never prematurely close the surrounding <script> element.
    """
    trimmed = dict(state)
    trimmed["history"] = state.get("history", [])[-GEX_HISTORY_MAX:]
    payload = json.dumps(trimmed, separators=(",", ":")).replace("</", "<\\/")
    return '<script id="gex-state" type="application/json">' + payload + '</script>'


# ---------------------------------------------------------------------------
# Scheduling / quota logic
# ---------------------------------------------------------------------------
def front_weekly_expiry(now):
    """Nearest upcoming Friday (front weekly), as yyyy-MM-dd.

    If today is Friday before the US close, use today; otherwise the next Friday.
    """
    wd = now.weekday()  # Mon=0 .. Sun=6
    if wd == 4 and now.hour < GEX_US_CLOSE_UTC:
        target = now
    else:
        days = (4 - wd) % 7
        if days == 0:      # Friday at/after close -> next Friday
            days = 7
        target = now + timedelta(days=days)
    return target.strftime("%Y-%m-%d")


def reset_daily_if_needed(state, now):
    today = now.strftime("%Y-%m-%d")
    if state["daily"].get("date") != today:
        state["daily"] = {"date": today, "count": 0, "hours": []}


def choose_symbol(now, state):
    """Return the symbol to fetch this run, or None. Guarantees <=5 fetches/day.

    Skips: weekends, non-scheduled hours, excluded symbols, hours already
    attempted today (avoids double-burn on manual re-runs), and any run once the
    daily hard cap is reached.
    """
    if now.weekday() >= 5:                       # skip Sat/Sun to save quota
        return None
    hour = now.hour
    if hour not in GEX_SCHEDULE:
        return None
    if state["daily"]["count"] >= GEX_DAILY_LIMIT:
        return None
    if hour in state["daily"]["hours"]:          # already attempted this slot today
        return None
    sym = GEX_SCHEDULE[hour]
    if sym in state["excluded"]:
        return None
    return sym


# ---------------------------------------------------------------------------
# Fetch + parse
# ---------------------------------------------------------------------------
def _top_strikes(strikes):
    """Top 3 positive + top 3 negative strikes by |net_gex|."""
    def g(row):
        try:
            return float(row.get("net_gex", 0) or 0)
        except (TypeError, ValueError):
            return 0.0
    pos = sorted([s for s in strikes if g(s) > 0], key=lambda s: -g(s))[:3]
    neg = sorted([s for s in strikes if g(s) < 0], key=lambda s:  g(s))[:3]
    keep = ("strike", "call_gex", "put_gex", "net_gex", "call_oi",
            "put_oi", "call_volume", "put_volume")
    slim = lambda s: {k: s.get(k) for k in keep if k in s}
    return [slim(s) for s in pos], [slim(s) for s in neg]


def _make_record(ts, symbol, expiration, data):
    strikes = data.get("strikes", []) or []
    top_pos, top_neg = _top_strikes(strikes)
    return {
        "ts":              ts,
        "symbol":          symbol,
        "expiration":      expiration,
        "underlying_price": data.get("underlying_price"),
        "net_gex":         float(data.get("net_gex")),
        "net_gex_label":   data.get("net_gex_label"),
        "gamma_flip":      data.get("gamma_flip"),
        "as_of":           data.get("as_of"),
        "top_pos":         top_pos,
        "top_neg":         top_neg,
    }


def fetch_gex(symbol, expiration, api_key, http=requests):
    """Perform one API request. Returns (status, payload).

    status in {"success", "quota", "tier_restricted", "symbol_not_in_free_universe",
    "http_error", "network_error"}. The CALLER is responsible for having already
    counted this against the daily quota (every attempt counts, even errors).
    """
    url = GEX_API_BASE + symbol + "?expiration=" + expiration
    try:
        r = http.get(url, headers={"X-API-KEY": api_key}, timeout=GEX_TIMEOUT)
    except Exception as e:                       # noqa: BLE001 (network/timeout)
        return "network_error", {"error": str(e)}
    try:
        body = r.json()
    except Exception:                            # noqa: BLE001
        body = {}
    code = getattr(r, "status_code", None)
    if code == 200 and "net_gex" in body:
        return "success", body
    if code == 429 or body.get("error") == "Quota exceeded":
        return "quota", body
    err = body.get("error")
    if err in ("tier_restricted", "symbol_not_in_free_universe"):
        return err, body
    return "http_error", body


# ---------------------------------------------------------------------------
# Orchestration (the main testable entry point)
# ---------------------------------------------------------------------------
def run_gex_update(now, prev_html, api_key, http=requests):
    """Load state, maybe fetch one symbol per the schedule, return updated state.

    Returns (state, meta) where meta = {
        "fetched": symbol|None, "status": str|None, "expiration": str,
        "fresh": set(symbols updated this run), "api_key": bool }.
    Never raises: all fetch failures degrade to cached/N/A display.
    """
    state = load_state(prev_html)
    reset_daily_if_needed(state, now)
    now_iso = now.strftime("%Y-%m-%d %H:%M UTC")
    expiration = front_weekly_expiry(now)
    meta = {"fetched": None, "status": None, "expiration": expiration,
            "fresh": set(), "api_key": bool(api_key)}

    if not api_key:
        return state, meta

    sym = choose_symbol(now, state)
    if not sym:
        return state, meta

    # Reserve the quota slot BEFORE the request — even an error counts.
    state["daily"]["count"] += 1
    state["daily"]["hours"].append(now.hour)
    meta["fetched"] = sym

    status, body = fetch_gex(sym, expiration, api_key, http)
    meta["status"] = status

    if status == "success":
        rec = _make_record(now_iso, sym, expiration, body)
        state["history"].append(rec)
        state["cards"][sym] = {
            "symbol":          sym,
            "net_gex":         rec["net_gex"],
            "net_gex_label":   rec["net_gex_label"],
            "gamma_flip":      rec["gamma_flip"],
            "underlying_price": rec["underlying_price"],
            "as_of":           rec["as_of"],
            "expiration":      expiration,
            "ts":              now_iso,
            "note":            "",
        }
        meta["fresh"].add(sym)
    elif status in ("tier_restricted", "symbol_not_in_free_universe"):
        if sym not in state["excluded"]:
            state["excluded"].append(sym)
        prev = state["cards"].get(sym, {})
        prev["note"] = ("excluded: tier-restricted" if status == "tier_restricted"
                        else "excluded: not in free universe")
        prev.setdefault("symbol", sym)
        state["cards"][sym] = prev
    elif status == "quota":
        # Silent: keep cached values, do not exclude. (Happens all day 2026-07-09.)
        pass
    else:
        # network/http error: cached fallback, no exclusion.
        pass

    return state, meta


def nvda_proxy(state):
    """NVDA net-GEX proxy used to repoint the Phase-1 GEX signal + LPI badge.

    Returns dict {has, positive, net_gex, label, ts} from the latest NVDA card.
    """
    card = state.get("cards", {}).get("NVDA")
    if not card or card.get("net_gex") is None:
        return {"has": False, "positive": False, "net_gex": None,
                "label": None, "ts": None}
    ng = float(card["net_gex"])
    return {"has": True, "positive": ng >= 0, "net_gex": ng,
            "label": card.get("net_gex_label"), "ts": card.get("ts")}


def nvda_history(state):
    """Chronological (ts, net_gex) points for the NVDA sparkline."""
    pts = [(r.get("ts"), float(r["net_gex"]))
           for r in state.get("history", [])
           if r.get("symbol") == "NVDA" and r.get("net_gex") is not None]
    return pts


# ---------------------------------------------------------------------------
# Formatting + HTML rendering
# ---------------------------------------------------------------------------
def fmt_gex(v):
    """Human-format a net GEX float, e.g. 4.87e8 -> '$487M'. Sign preserved."""
    if v is None:
        return "N/A"
    a = abs(float(v))
    sign = "-" if v < 0 else ""
    if a >= 1e9:
        return sign + "${:.2f}B".format(a / 1e9)
    if a >= 1e6:
        return sign + "${:.0f}M".format(a / 1e6)
    if a >= 1e3:
        return sign + "${:.0f}K".format(a / 1e3)
    return sign + "${:.0f}".format(a)


def _flip_distance(spot, flip):
    """(% distance, direction str). Positive => spot above flip (stabilising)."""
    try:
        spot = float(spot)
        flip = float(flip)
    except (TypeError, ValueError):
        return None, ""
    if not flip:
        return None, ""
    pct = (spot - flip) / flip * 100.0
    return pct, ("above" if pct >= 0 else "below")


def render_section(state, meta, now):
    """Return the '<div class="gex-section">...' HTML block (plus its state script).

    Rendered states handled: no key, fresh, cached, quota-exceeded, excluded.
    """
    p = []
    p.append('<div class="gex-section">')
    p.append('<div class="gex-heading">GEX Monitor <span>做市商伽马监控 (Dealer Gamma)</span></div>')

    if not meta.get("api_key"):
        p.append('<div class="gex-note-box">FlashAlpha API key not configured '
                 '&mdash; GEX monitor idle. Set <b>FLASHALPHA_API_KEY</b> to enable.</div>')
        p.append('</div>')
        return "\n".join(p) + "\n" + state_to_html_block(state)

    # --- per-symbol cards ---
    fresh = meta.get("fresh", set())
    p.append('<div class="gex-cards">')
    for sym in GEX_SYMBOLS:
        card = state.get("cards", {}).get(sym)
        excluded = sym in state.get("excluded", [])
        if not card or card.get("net_gex") is None:
            note = (card.get("note") if card else "") or (
                "excluded" if excluded else "awaiting first fetch")
            p.append('<div class="gex-card gray">')
            p.append('<div class="gex-card-sym">' + sym + '</div>')
            p.append('<div class="gex-card-na">N/A</div>')
            p.append('<div class="gex-card-note">' + note + '</div>')
            p.append('</div>')
            continue

        ng = float(card["net_gex"])
        pos = ng >= 0
        cls = "green" if pos else "red"
        label = card.get("net_gex_label") or ("positive" if pos else "negative")
        regime = "dealers stabilize" if pos else "dealers amplify"
        pct, direction = _flip_distance(card.get("underlying_price"), card.get("gamma_flip"))
        is_cached = sym not in fresh

        p.append('<div class="gex-card ' + cls + '">')
        p.append('<div class="gex-card-head"><span class="gex-card-sym">' + sym + '</span>')
        fresh_lbl = ('<span class="gex-cached">cached ' + str(card.get("ts", "")) + '</span>'
                     if is_cached else '<span class="gex-fresh">live</span>')
        p.append(fresh_lbl + '</div>')
        p.append('<div class="gex-card-val ' + cls + '">' + fmt_gex(ng) + '</div>')
        p.append('<div class="gex-card-lbl">net GEX &middot; ' + label + ' (' + regime + ')</div>')

        if pct is not None:
            spot = float(card["underlying_price"]); flip = float(card["gamma_flip"])
            zone_cls = "green" if pct >= 0 else "red"
            # proximity bar: 50% = flip, +/-15% maps to full width
            fillpos = max(0.0, min(100.0, 50.0 + (pct / 15.0) * 50.0))
            p.append('<div class="gex-flip-txt">Flip ' + "{:.1f}".format(flip) +
                     ' &middot; Spot ' + "{:.1f}".format(spot) +
                     ' &middot; <span class="' + zone_cls + '">' + "{:+.1f}%".format(pct) +
                     ' ' + direction + ' flip</span></div>')
            p.append('<div class="gex-flip-track"><div class="gex-flip-mid"></div>'
                     '<div class="gex-flip-marker ' + zone_cls + '" style="left:' +
                     "{:.1f}".format(fillpos) + '%"></div></div>')
        else:
            p.append('<div class="gex-flip-txt">flip distance unavailable</div>')

        p.append('<div class="gex-card-foot">exp ' + str(card.get("expiration", "?")) +
                 ' &middot; as of ' + str(card.get("as_of", "?")) +
                 (' &middot; <span class="gex-cached">cached</span>' if is_cached else '') +
                 '</div>')
        if card.get("note"):
            p.append('<div class="gex-card-note">' + card["note"] + '</div>')
        p.append('</div>')
    p.append('</div>')  # gex-cards

    # --- Phase-1 GEX proxy signal (repointed SPX -> NVDA; count stays /5) ---
    prox = nvda_proxy(state)
    if not prox["has"]:
        prox_txt, prox_cls = "N/A — no NVDA reading yet", "gray"
    elif prox["positive"]:
        prox_txt, prox_cls = "POSITIVE ✅ dealers dampening (confirmed)", "green"
    else:
        prox_txt, prox_cls = "NEGATIVE ❌ dealers amplifying", "red"
    p.append('<div class="gex-quota" style="margin-bottom:12px">Phase-1 GEX signal '
             '&mdash; <b>NVDA proxy</b> (free-tier: SPX unavailable): '
             '<span class="' + prox_cls + '">' + prox_txt + '</span></div>')

    # --- NVDA history sparkline ---
    hist = nvda_history(state)
    p.append('<div class="chart-card" style="margin-bottom:12px">')
    p.append('<div class="chart-title">NVDA Net GEX &mdash; History</div>')
    if len(hist) >= 2:
        p.append('<div class="chart-subtitle">Positive = dealer long gamma (dampening) '
                 '&middot; negative = short gamma (amplifying)</div>')
        p.append('<div id="chart-gex-nvda"></div>')
    else:
        p.append('<div class="chart-subtitle">accumulating history &mdash; ' +
                 str(len(hist)) + ' reading' + ('' if len(hist) == 1 else 's') +
                 ' (need ≥2)</div>')
    p.append('</div>')

    # --- quota footnote ---
    used = state["daily"]["count"]
    p.append('<div class="gex-quota">Requests used today: <b>' + str(used) + ' / ' +
             str(GEX_DAILY_LIMIT) + '</b> &middot; free tier resets 00:00 UTC')
    if state.get("excluded"):
        p.append(' &middot; excluded: ' + ", ".join(state["excluded"]))
    if meta.get("status") == "quota":
        p.append(' &middot; <span class="red">quota exhausted — showing cached</span>')
    p.append('</div>')

    p.append('</div>')  # gex-section
    return "\n".join(p) + "\n" + state_to_html_block(state)


def nvda_history_json(state):
    """(dates_json, values_json) for the NVDA sparkline Plotly call."""
    pts = nvda_history(state)
    dates = [t for (t, _) in pts]
    vals  = [round(v / 1e6, 2) for (_, v) in pts]  # $ millions
    return json.dumps(dates), json.dumps(vals)
