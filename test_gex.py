#!/usr/bin/env python3
"""Mock-based tests for gex_monitor (no live FlashAlpha calls).

Covers: front-weekly expiry, schedule gating over a full 24h day (exactly <=5
attempts), quota hard-stop, permanent exclusion list, cache round-trip through
the embedded JSON block, and HTML rendering in fresh / cached / quota / no-key /
excluded states. Run: python test_gex.py
"""

import json
from datetime import datetime, timezone

import gex_monitor as gm

PASS = 0
FAIL = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok   -", name)
    else:
        FAIL += 1
        print("  FAIL -", name)


# ---------------------------------------------------------------------------
# Mock HTTP client returning FlashAlpha-schema responses.
# ---------------------------------------------------------------------------
class MockResp:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def success_payload(symbol, net_gex, spot, flip):
    return {
        "symbol": symbol,
        "underlying_price": spot,
        "as_of": "2026-07-10T14:05:00Z",
        "gamma_flip": flip,
        "net_gex": net_gex,
        "net_gex_label": "positive" if net_gex >= 0 else "negative",
        "strikes": [
            {"strike": flip - 5, "call_gex": 1e7, "put_gex": -3e7, "net_gex": -2e7,
             "call_oi": 100, "put_oi": 300, "call_volume": 50, "put_volume": 90},
            {"strike": flip,     "call_gex": 5e7, "put_gex": -1e7, "net_gex":  4e7,
             "call_oi": 400, "put_oi": 120, "call_volume": 80, "put_volume": 40},
            {"strike": flip + 5, "call_gex": 9e7, "put_gex": -2e7, "net_gex":  7e7,
             "call_oi": 600, "put_oi": 150, "call_volume": 90, "put_volume": 30},
            {"strike": flip + 10, "call_gex": 2e7, "put_gex": -8e7, "net_gex": -6e7,
             "call_oi": 200, "put_oi": 700, "call_volume": 20, "put_volume": 88},
        ],
    }


class SuccessHttp:
    """Always returns a 200 success for whatever symbol is requested."""
    def __init__(self):
        self.calls = []

    def get(self, url, headers=None, timeout=None):
        self.calls.append(url)
        sym = url.split("/gex/")[1].split("?")[0]
        return MockResp(200, success_payload(sym, 4.87e8, 203.6, 193.8))


class QuotaHttp:
    def __init__(self):
        self.calls = []

    def get(self, url, headers=None, timeout=None):
        self.calls.append(url)
        return MockResp(429, {"error": "Quota exceeded", "reset_at": "2026-07-11T00:00:00Z"})


class TierHttp:
    def __init__(self, err="tier_restricted"):
        self.calls = []
        self.err = err

    def get(self, url, headers=None, timeout=None):
        self.calls.append(url)
        return MockResp(403, {"error": self.err})


class NegNvdaHttp:
    def __init__(self):
        self.calls = []

    def get(self, url, headers=None, timeout=None):
        self.calls.append(url)
        sym = url.split("/gex/")[1].split("?")[0]
        ng = -3.2e8 if sym == "NVDA" else 1.0e8
        return MockResp(200, success_payload(sym, ng, 180.0, 190.0))


# ---------------------------------------------------------------------------
def test_expiry():
    print("[expiry] front_weekly_expiry")
    # Wed 2026-07-08 -> Fri 2026-07-10
    check("wed -> upcoming fri", gm.front_weekly_expiry(
        datetime(2026, 7, 8, 14, 0, tzinfo=timezone.utc)) == "2026-07-10")
    # Fri 2026-07-10 morning (pre-close) -> today
    check("fri pre-close -> today", gm.front_weekly_expiry(
        datetime(2026, 7, 10, 14, 0, tzinfo=timezone.utc)) == "2026-07-10")
    # Fri 2026-07-10 after close (22:00 UTC) -> next fri
    check("fri post-close -> next fri", gm.front_weekly_expiry(
        datetime(2026, 7, 10, 22, 0, tzinfo=timezone.utc)) == "2026-07-17")
    # Sat 2026-07-11 -> Fri 2026-07-17
    check("sat -> next fri", gm.front_weekly_expiry(
        datetime(2026, 7, 11, 14, 0, tzinfo=timezone.utc)) == "2026-07-17")


def test_schedule_full_day():
    print("[schedule] 24 hourly runs -> exactly 5 attempts on a weekday")
    http = SuccessHttp()
    html = ""  # first run, no prior state
    attempts = []
    # Friday 2026-07-10 but keep expiry stable; use a Thursday to avoid fri-close edge
    day = datetime(2026, 7, 9, 0, 0, tzinfo=timezone.utc)  # Thu 2026-07-09
    for h in range(24):
        now = day.replace(hour=h)
        state, meta = gm.run_gex_update(now, html, "KEY", http=http)
        if meta["fetched"]:
            attempts.append((h, meta["fetched"]))
        html = _wrap(gm.state_to_html_block(state))  # persist like index.html
    check("exactly 5 HTTP calls", len(http.calls) == 5)
    check("attempts on scheduled hours", [h for h, _ in attempts] == [14, 15, 16, 18, 19])
    check("symbols per schedule",
          [s for _, s in attempts] == ["NVDA", "AAPL", "AMD", "MU", "NVDA"])
    check("daily count == 5", state["daily"]["count"] == 5)
    check("NVDA has 2 history records",
          len([r for r in state["history"] if r["symbol"] == "NVDA"]) == 2)


def test_weekend_skip():
    print("[schedule] weekend runs never fetch")
    http = SuccessHttp()
    sat = datetime(2026, 7, 11, 14, 0, tzinfo=timezone.utc)  # Saturday
    state, meta = gm.run_gex_update(sat, "", "KEY", http=http)
    check("no fetch on saturday", meta["fetched"] is None and len(http.calls) == 0)


def test_no_double_burn_same_hour():
    print("[schedule] manual re-run in same hour does not re-fetch")
    http = SuccessHttp()
    now = datetime(2026, 7, 9, 14, 0, tzinfo=timezone.utc)
    state, meta = gm.run_gex_update(now, "", "KEY", http=http)
    html = _wrap(gm.state_to_html_block(state))
    state2, meta2 = gm.run_gex_update(now, html, "KEY", http=http)
    check("first run fetched", meta["fetched"] == "NVDA")
    check("second run same hour skipped", meta2["fetched"] is None)
    check("only 1 HTTP call total", len(http.calls) == 1)


def test_quota_guard():
    print("[quota] hard stop + 429 handled silently")
    http = QuotaHttp()
    day = datetime(2026, 7, 9, 0, 0, tzinfo=timezone.utc)
    html = ""
    for h in range(24):
        state, meta = gm.run_gex_update(day.replace(hour=h), html, "KEY", http=http)
        html = _wrap(gm.state_to_html_block(state))
    check("5 attempts even though all 429", len(http.calls) == 5)
    check("count capped at 5", state["daily"]["count"] == 5)
    check("no history recorded on quota", state["history"] == [])
    check("nothing excluded on quota", state["excluded"] == [])
    # a 6th scheduled-like manual attempt cannot exceed cap
    extra = SuccessHttp()
    state2, meta2 = gm.run_gex_update(day.replace(hour=19), html, "KEY", http=extra)
    check("hard cap blocks further fetch", meta2["fetched"] is None and len(extra.calls) == 0)


def test_exclusion():
    print("[exclusion] 403 tier/universe -> permanent exclude, never re-request")
    http = TierHttp("symbol_not_in_free_universe")
    now14 = datetime(2026, 7, 9, 14, 0, tzinfo=timezone.utc)
    state, meta = gm.run_gex_update(now14, "", "KEY", http=http)
    check("NVDA excluded after 403", "NVDA" in state["excluded"])
    check("counted the 403 attempt", state["daily"]["count"] == 1)
    # next day: NVDA still excluded, must not be requested at hour 14 or 19
    http2 = SuccessHttp()
    html = _wrap(gm.state_to_html_block(state))
    nextday = datetime(2026, 7, 10, 14, 0, tzinfo=timezone.utc)
    state2, meta2 = gm.run_gex_update(nextday, html, "KEY", http=http2)
    check("excluded NVDA not requested next day", meta2["fetched"] is None)
    check("exclusion persisted across day reset", "NVDA" in state2["excluded"])


def test_cache_roundtrip():
    print("[cache] state survives embed -> parse from index.html")
    http = SuccessHttp()
    now = datetime(2026, 7, 9, 14, 0, tzinfo=timezone.utc)
    state, meta = gm.run_gex_update(now, "", "KEY", http=http)
    full_html = _wrap(gm.state_to_html_block(state))
    reloaded = gm.load_state(full_html)
    check("history round-trips", len(reloaded["history"]) == 1)
    check("card round-trips", reloaded["cards"]["NVDA"]["net_gex"] == 4.87e8)
    check("daily count round-trips", reloaded["daily"]["count"] == 1)
    check("hours round-trip", reloaded["daily"]["hours"] == [14])
    # malformed / missing block -> default
    check("missing block -> default", gm.load_state("<html></html>")["history"] == [])
    check("empty html -> default", gm.load_state("")["daily"]["count"] == 0)


def test_history_no_script_break():
    print("[cache] embedded JSON cannot break out of <script>")
    state = gm.default_state()
    state["history"].append({"symbol": "NVDA", "net_gex": 1.0, "note": "</script><b>x"})
    block = gm.state_to_html_block(state)
    check("no raw </script> in block", "</script>" not in block[:-len("</script>")])
    check("escaped </ present", "<\\/" in block)
    check("still parses back", gm.load_state(_wrap(block))["history"][0]["symbol"] == "NVDA")


def test_render_states():
    print("[render] fresh / cached / quota / no-key / excluded")
    now = datetime(2026, 7, 9, 14, 0, tzinfo=timezone.utc)

    # no key
    st = gm.default_state()
    html = gm.render_section(st, {"api_key": False, "fresh": set(), "status": None}, now)
    check("no-key shows message", "API key not configured" in html)
    check("no-key still embeds state block", 'id="gex-state"' in html)

    # fresh
    http = SuccessHttp()
    st, meta = gm.run_gex_update(now, "", "KEY", http=http)
    html = gm.render_section(st, meta, now)
    check("fresh shows NVDA card", "NVDA" in html)
    check("fresh shows live badge", "gex-fresh" in html and ">live<" in html)
    check("fresh formats $487M", "$487M" in html)
    check("fresh flip distance shown", "flip" in html and "Spot" in html)
    check("quota footnote 1/5", "1 / 5" in html)

    # cached (next scheduled hour, quota-blocked so NVDA not refreshed)
    qhttp = QuotaHttp()
    html2 = _wrap(gm.state_to_html_block(st))
    st2, meta2 = gm.run_gex_update(now.replace(hour=15), html2, "KEY", http=qhttp)
    render2 = gm.render_section(st2, meta2, now.replace(hour=15))
    check("cached indicator for NVDA", "cached" in render2)

    # quota-exceeded banner when this run hit 429
    check("quota banner shown", "quota exhausted" in render2)

    # excluded card note
    thttp = TierHttp("tier_restricted")
    st3, meta3 = gm.run_gex_update(now, "", "KEY", http=thttp)
    render3 = gm.render_section(st3, meta3, now)
    check("excluded note on card", "tier-restricted" in render3)
    check("excluded listed in footnote", "excluded: NVDA" in render3)


def test_proxy_and_sparkline():
    print("[proxy] NVDA sign wiring + sparkline threshold")
    now = datetime(2026, 7, 9, 14, 0, tzinfo=timezone.utc)
    # negative NVDA
    http = NegNvdaHttp()
    st, meta = gm.run_gex_update(now, "", "KEY", http=http)
    prox = gm.nvda_proxy(st)
    check("negative NVDA detected", prox["has"] and not prox["positive"])
    render = gm.render_section(st, meta, now)
    check("proxy shows NEGATIVE", "NEGATIVE" in render)
    check("sparkline waits for >=2 (shows accumulating)", "accumulating history" in render)

    # accumulate a 2nd NVDA reading at hour 19
    html = _wrap(gm.state_to_html_block(st))
    st2, meta2 = gm.run_gex_update(now.replace(hour=19), html, "KEY", http=NegNvdaHttp())
    d, v = gm.nvda_history_json(st2)
    check("sparkline has 2 points", len(json.loads(v)) == 2)
    render2 = gm.render_section(st2, meta2, now.replace(hour=19))
    check("sparkline div rendered at >=2", "chart-gex-nvda" in render2)


def test_fmt():
    print("[fmt] fmt_gex human formatting")
    check("487M", gm.fmt_gex(4.87e8) == "$487M")
    check("neg 3.20B", gm.fmt_gex(-3.2e9) == "-$3.20B")
    check("None -> N/A", gm.fmt_gex(None) == "N/A")


def _wrap(block):
    """Emulate index.html carrying the embedded state block."""
    return "<html><body>...dashboard...\n" + block + "\n</body></html>"


def main():
    for fn in (test_expiry, test_schedule_full_day, test_weekend_skip,
               test_no_double_burn_same_hour, test_quota_guard, test_exclusion,
               test_cache_roundtrip, test_history_no_script_break,
               test_render_states, test_proxy_and_sparkline, test_fmt):
        fn()
    print("\n{} passed, {} failed".format(PASS, FAIL))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
