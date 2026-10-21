"""Build card and chart payloads for the v2 FRED modules (funding extras, backstops,
Fed balance sheet and RMP, credit, rates). Output is plain dicts; fred_render.py turns them
into HTML. Every card fails independently: a missing or stale series becomes a grey card.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

import fast_metrics as fm
import fred_catalog as fc
import fred_monitor as mon

NAN = float("nan")
RMP_START = "2025-12-12"            # NY Fed: reserve management purchases begin 2025-12-12
RMP_FIRST_WEEK = "2025-12-17"       # first H.4.1 Wednesday level after the start
OPERATOR_REF = "operator reference"

URL_RMP = "https://www.newyorkfed.org/markets/opolicy/operating_policy_251210a"


def _num(v: float, digits: int = 0, signed: bool = False) -> str:
    if v != v:
        return "n/a"
    fmt = "{:" + ("+" if signed else "") + ",." + str(digits) + "f}"
    return fmt.format(v)


def _fmt(v: float, unit: str, digits: int | None = None, signed: bool = False) -> str:
    if v != v:
        return "n/a"
    if unit == "bp":
        return _num(v, 0 if digits is None else digits, signed) + " bp"
    if unit == "pct":
        return _num(v, 2 if digits is None else digits, signed) + "%"
    if unit == "$B":
        return ("-" if v < 0 else ("+" if signed and v > 0 else "")) + "$" + _num(abs(v), 0 if digits is None else digits) + "B"
    if unit == "$T":
        return ("-" if v < 0 else ("+" if signed and v > 0 else "")) + "$" + _num(abs(v), 2 if digits is None else digits) + "T"
    return _num(v, 2 if digits is None else digits, signed)


def _spec(sid: str) -> fc.FredSpec:
    return fc.BY_ID[sid]


def _get(S: dict[str, pd.Series], sid: str) -> pd.Series | None:
    s = S.get(sid)
    return s.dropna() if s is not None and len(s.dropna()) else None


def _disp(S: dict[str, pd.Series], sid: str) -> pd.Series | None:
    s = _get(S, sid)
    return None if s is None else s * _spec(sid).scale


def _card(cid: str, title: str, spec_ids: list[str], *, value: str, state: str, sub: str, what: str,
          asof: str | None, cadence: str, stale: bool, unit_note: str = "", limits: str = "",
          why: str = "", spark: list[float] | None = None, rule: str = "") -> dict[str, Any]:
    ids = spec_ids
    links = [(i, fc.BY_ID[i].url) for i in ids if i in fc.BY_ID]
    return {"id": cid, "title": title, "value": value, "state": "na" if stale else state,
            "state_label": mon.STATE_LABEL["na" if stale else state],
            "sub": sub, "what": what, "asof": asof or "unavailable", "cadence": cadence,
            "stale": stale, "unit_note": unit_note, "limits": limits, "why": why, "rule": rule,
            "links": links, "spark": spark or []}


def _na_card(cid: str, title: str, spec_ids: list[str], what: str) -> dict[str, Any]:
    c = _card(cid, title, spec_ids, value="n/a", state="na", sub="No data this run", what=what,
              asof=None, cadence="", stale=True)
    return c


def _fresh(s: pd.Series, spec: fc.FredSpec, now: datetime) -> fm.Freshness:
    return mon.freshness_of(s, spec, now)


# ---------------------------------------------------------------------------
# 4a Funding extras and backstops
# ---------------------------------------------------------------------------
def build_funding(S: dict[str, pd.Series], now: datetime) -> dict[str, Any]:
    cards: list[dict[str, Any]] = []
    # TGCR - IORB
    tg, io = _get(S, "TGCRRATE"), _get(S, "IORB")
    if tg is not None and io is not None:
        sp = mon.spread(tg, io, 100.0)
        f = _fresh(tg, _spec("TGCRRATE"), now)
        v = float(sp.iloc[-1])
        state = "elevated" if v >= fm.SOFR_REFERENCE_ELEVATED_BP else ("watch" if v >= fm.SOFR_STRATEGY_BP else "normal")
        cards.append(_card(
            "tgcr-iorb", "TGCR minus IORB · 三方回购利率减 IORB", ["TGCRRATE", "IORB"],
            value=_fmt(v, "bp", 1, True), state=state,
            sub="5d median {}".format(_fmt(float(sp.tail(5).median()), "bp", 1, True)),
            what="Tri-party repo rate against the Fed's administered floor-side rate, in basis points.",
            asof=f.observation_date, cadence=_spec("TGCRRATE").cadence, stale=f.stale,
            why="Tri-party repo has no bilateral dealer-balance-sheet noise, so a persistent premium to IORB points to collateral-financing pressure rather than sponsored-repo mix.",
            limits="Not calendar-filtered: month-end and Treasury settlement dates print higher. Context only, outside the funding resonance count.",
            spark=mon.spark(sp, 20), rule="Watch at or above +3.0 bp, elevated at or above +5.0 bp (the SOFR strategy lines)."))
    else:
        cards.append(_na_card("tgcr-iorb", "TGCR minus IORB · 三方回购利率减 IORB", ["TGCRRATE", "IORB"], "Tri-party repo rate against IORB."))
    # SOFR 99th minus median
    s99, sofr = _get(S, "SOFR99"), _get(S, "SOFR")
    if s99 is not None and sofr is not None:
        sp = mon.spread(s99, sofr, 100.0)
        f = _fresh(s99, _spec("SOFR99"), now)
        pct, yrs = mon.level_pctile(sp, 2)
        z = mon.change_z(sp, 5, 2)
        state = mon.pct_state(pct, z, yrs)
        cards.append(_card(
            "sofr-disp", "SOFR 99th percentile minus median · SOFR 第99分位减中位数", ["SOFR99", "SOFR"],
            value=_fmt(float(sp.iloc[-1]), "bp", 1, True), state=state,
            sub="pctile {} vs {}y, 5d change z {}".format(_num(pct, 0), yrs, _num(z, 1, True)),
            what="Width of the upper tail of overnight repo rates over the SOFR median, in basis points.",
            asof=f.observation_date, cadence=_spec("SOFR99").cadence, stale=f.stale,
            why="Measures how far the most expensive overnight repo trades sit above the typical trade. It reflects the dispersion of rates paid by balance-sheet-constrained borrowers.",
            limits="A statistic of the rate distribution. It does not identify which participants borrow at the tail.",
            spark=mon.spark(sp, 20), rule="Percentile of own 2y history plus 5-observation change z (see methodology)."))
    else:
        cards.append(_na_card("sofr-disp", "SOFR 99th percentile minus median · SOFR 第99分位减中位数", ["SOFR99", "SOFR"], "Upper-tail repo rate dispersion."))
    # SOFR volume
    sv = _get(S, "SOFRVOL")
    if sv is not None:
        f = _fresh(sv, _spec("SOFRVOL"), now)
        ma20 = float(sv.tail(20).mean())
        pct, yrs = mon.level_pctile(sv, 2)
        cards.append(_card(
            "sofr-vol", "SOFR transaction volume · SOFR 成交量", ["SOFRVOL"],
            value="${}T".format(_num(float(sv.iloc[-1]) / 1000.0, 2)), state="context",
            sub="20d average ${}T, pctile {} vs {}y".format(_num(ma20 / 1000.0, 2), _num(pct, 0), yrs),
            what="Daily volume behind the SOFR benchmark, published in $ billions and shown in $ trillions.",
            asof=f.observation_date, cadence=_spec("SOFRVOL").cadence, stale=f.stale,
            why="Falling volume with a rising rate means fewer trades are clearing at higher prices. Rising volume with a stable rate is normal month-start rollover.",
            limits="Volume has a strong calendar pattern; compare with the 20-day average, not with the prior day.",
            spark=mon.spark(sv, 20, 0.001), unit_note="FRED unit: billions of dollars."))
    else:
        cards.append(_na_card("sofr-vol", "SOFR transaction volume · SOFR 成交量", ["SOFRVOL"], "Daily SOFR volume."))

    # Backstops
    backs: list[dict[str, Any]] = []
    plan = [
        ("srf", "Standing repo facility, 7-day total · 常备回购便利 7日合计", "RPONTSYD", mon.BACKSTOP_FLOORS_B["RPONTSYD"], True,
         "Treasury collateral borrowed from the Fed's overnight repo operations over the last 7 calendar days."),
        ("dw", "Discount window primary credit · 贴现窗口", "WLCFLPCL", mon.BACKSTOP_FLOORS_B["WLCFLPCL"], False,
         "Primary credit outstanding at the Fed's discount window (weekly Wednesday level)."),
        ("swaps", "Central bank liquidity swaps · 央行流动性互换", "SWPT", mon.BACKSTOP_FLOORS_B["SWPT"], False,
         "Dollar liquidity provided to foreign central banks through swap lines."),
        ("fima", "FIMA repo facility, actual usage · FIMA 回购便利用量", "H41RESPPALGTRFNWW", mon.BACKSTOP_FLOORS_B["H41RESPPALGTRFNWW"], False,
         "Repo borrowing by foreign official accounts against Treasuries. Zero in normal conditions."),
    ]
    for cid, title, sid, floor, seven, what in plan:
        spec = _spec(sid)
        raw = _get(S, sid)
        if raw is None:
            backs.append(_na_card(cid, title, [sid], what))
            continue
        ser = raw * spec.scale
        r = mon.backstop_state(ser, floor, spec, now, seven_day_sum=seven)
        gstate = mon.BACKSTOP_TO_GLOBAL.get(r["state"], "na")
        if cid == "dw" and r["state"] == "elevated":
            gstate = "elevated"     # a standing balance at a 3y high is notable, not a stress print
        floor_txt = "no floor, judged against own 95th percentile with a positive 4-week change" if floor is None \
            else "floor ${}B".format(_num(floor, 0))
        p95_txt = "3y p95 ${}B".format(_num(r["p95"], 1)) if r["p95"] == r["p95"] else ""
        card = _card(
            cid, title, [sid], value=_fmt(r["value"], "$B", 1), state=gstate,
            sub="state: {} · {}{}".format(r["state"].replace("_", " "), floor_txt, ("; " + p95_txt) if p95_txt else ""),
            what=what, asof=r["obs"], cadence=spec.cadence, stale=bool(r["stale"]),
            why="Backstop usage shows where private funding markets failed to clear and borrowers went to the central bank.",
            limits="Floors are operator-set heuristics (decision D3), not empirical laws. Small residual balances can sit below the floor without meaning.",
            spark=mon.spark(ser, 13), rule="quiet below the floor, in use at or above it, elevated when also at or above the 3y 95th percentile.")
        card["backstop"] = r["state"]
        backs.append(card)
    # Foreign official RRP pool: liability, no state
    fr = _get(S, "WLRRAFOIAL")
    if fr is not None:
        spec = _spec("WLRRAFOIAL")
        f = _fresh(fr, spec, now)
        ser = fr * spec.scale
        chg4 = mon.change_n(ser, 4)
        card = _card(
            "frrp", "Foreign official reverse repo pool · 外国官方逆回购池", ["WLRRAFOIAL"],
            value=_fmt(float(ser.iloc[-1]), "$B", 0), state="context",
            sub="4-week change {}".format(_fmt(chg4, "$B", 0, True)),
            what="Cash that foreign official accounts park at the Fed overnight. It is a Fed liability, not emergency liquidity.",
            asof=f.observation_date, cadence=spec.cadence, stale=f.stale,
            why="A fast drop can mean foreign official holders moved cash into other uses, so it is tracked for change rather than level.",
            limits="Not the FIMA repo facility. The two are different H.4.1 lines.", spark=mon.spark(ser, 13))
        card["alert_drop"] = (chg4 == chg4 and chg4 <= -50.0)
        backs.append(card)
    else:
        backs.append(_na_card("frrp", "Foreign official reverse repo pool · 外国官方逆回购池", ["WLRRAFOIAL"], "Foreign official RRP pool."))
    # Discount-window primary credit carries a standing balance, so it is reported by its own
    # state and is not counted in "facilities in use" (SRF, swaps, FIMA).
    floored = [c for c in backs if c["id"] in ("srf", "swaps", "fima")]
    n_use = mon.backstops_in_use(c.get("backstop", "") for c in floored)
    n_avail = sum(1 for c in floored if c.get("backstop") not in (None, "stale", "unavailable"))
    dw_card = next((c for c in backs if c["id"] == "dw"), None)

    # Chart: SOFR percentile band minus IORB (bp) and SOFR volume
    chart_disp = None
    if io is not None and all(_get(S, k) is not None for k in ("SOFR1", "SOFR25", "SOFR75", "SOFR99", "SOFR")):
        traces = []
        for sid, name, color in (("SOFR99", "99th", "#ef4444"), ("SOFR75", "75th", "#f59e0b"),
                                 ("SOFR", "Median (SOFR)", "#e2e8f0"), ("SOFR25", "25th", "#38bdf8"),
                                 ("SOFR1", "1st", "#6366f1")):
            sp = mon.spread(_get(S, sid), io, 100.0)
            traces.append(dict(name=name, color=color, type="scatter", **mon.sample_series(sp.tail(520), 1.0, 260, digits=1)))
        chart_disp = {"id": "chart-sofr-dispersion", "title": "SOFR percentiles minus IORB · SOFR 分位数减 IORB",
                      "subtitle": "Basis points. 99th above 75th above median shows the tail widening.",
                      "unit": "bp", "traces": traces, "refs": [{"y": 0, "label": "IORB", "color": "#475569"}], "default_range": "6M"}
    chart_vol = None
    if sv is not None:
        sub = sv.tail(520)
        traces = [dict(name="Daily volume ($B)", color="#6366f1", type="bar", **mon.sample_series(sub, 1.0, 260, digits=0)),
                  dict(name="20d average", color="#f59e0b", type="scatter", **mon.sample_series(sub.rolling(20).mean(), 1.0, 260, digits=0))]
        chart_vol = {"id": "chart-sofr-volume", "title": "SOFR transaction volume · SOFR 成交量",
                     "subtitle": "$ billions per day.", "unit": "$B", "traces": traces, "refs": [], "default_range": "6M"}

    states = [c["state"] for c in cards if c["id"] in ("tgcr-iorb", "sofr-disp")]
    return {"cards": cards, "backstops": backs, "backstops_in_use": n_use, "backstops_avail": n_avail,
            "dw_state": (dw_card or {}).get("backstop", "unavailable"),
            "charts": [c for c in (chart_disp, chart_vol) if c], "state": mon.worst(states),
            "iorb_ok": io is not None}


# ---------------------------------------------------------------------------
# 4b Fed balance sheet and RMP
# ---------------------------------------------------------------------------
def build_fedbs(S: dict[str, pd.Series], now: datetime) -> dict[str, Any]:
    cards: list[dict[str, Any]] = []
    bills = _disp(S, "WSHOBL")
    rmp_avg = NAN
    if bills is not None:
        spec = _spec("WSHOBL")
        f = _fresh(S["WSHOBL"], spec, now)
        d1 = mon.change_n(bills, 1)
        d4 = mon.change_n(bills, 4)
        wk = mon.weekly_delta(bills)
        since = wk[wk.index >= pd.Timestamp(RMP_FIRST_WEEK)]
        rmp_avg = float(since.mean()) if len(since) else NAN
        sub = "1w {} · 4w {}".format(_fmt(d1, "$B", 0, True), _fmt(d4, "$B", 0, True))
        if rmp_avg == rmp_avg:
            sub += " · average weekly pace since RMP start {}".format(_fmt(rmp_avg, "$B", 1, True))
        cards.append(_card(
            "wshobl", "SOMA Treasury bills · SOMA 持有 T-bill", ["WSHOBL"],
            value=_fmt(float(bills.iloc[-1]), "$B", 0), state="context", sub=sub,
            what="Treasury bills held outright by the Fed (weekly Wednesday level, $ billions).",
            asof=f.observation_date, cadence=spec.cadence, stale=f.stale,
            why="Reserve management purchases add bills to keep reserves ample. The weekly change shows the pace of that support.",
            limits="Includes reinvestment of maturing securities into bills, so not every increase is a net purchase.",
            spark=mon.spark(bills, 13), unit_note="FRED unit: millions of dollars, shown in $ billions."))
    else:
        cards.append(_na_card("wshobl", "SOMA Treasury bills · SOMA 持有 T-bill", ["WSHOBL"], "Treasury bills held by the Fed."))
    for sid, cid, title, what in (
            ("WSHOSHO", "wshosho", "SOMA securities held outright · SOMA 持有证券总额", "Total securities held outright by the Fed."),
            ("WSEFINTL1", "wsefintl1", "Custody holdings for foreign official accounts · 外国官方托管证券", "Securities the Fed holds in custody for foreign official and international accounts.")):
        spec = _spec(sid)
        t = _disp(S, sid)
        if t is None:
            cards.append(_na_card(cid, title, [sid], what))
            continue
        f = _fresh(S[sid], spec, now)
        cards.append(_card(
            cid, title, [sid], value=_fmt(float(t.iloc[-1]), "$T", 2), state="context",
            sub="13-week change {}".format(_fmt(mon.change_n(t, 13), "$T", 2, True)),
            what=what + " Weekly Wednesday level, shown in $ trillions.", asof=f.observation_date,
            cadence=spec.cadence, stale=f.stale,
            why="Changes in foreign official custody holdings show whether foreign holders are adding or reducing U.S. Treasury exposure held at the Fed." if sid == "WSEFINTL1"
            else "The total sets the backdrop for how much of the balance sheet is bills versus longer maturities.",
            limits="A balance, not a flow; custody holdings move with prices as well as with transactions." if sid == "WSEFINTL1" else "",
            spark=mon.spark(t, 13)))
    for sid, cid, title in (("WALCL", "walcl", "Fed total assets · 美联储总资产"),
                            ("WRESBAL", "wresbal", "Reserve balances · 准备金余额"),
                            ("WTREGEN", "wtregen", "Treasury General Account · 财政部 TGA")):
        spec = _spec(sid)
        t = _disp(S, sid)
        if t is None:
            cards.append(_na_card(cid, title, [sid], "H.4.1 balance."))
            continue
        f = _fresh(S[sid], spec, now)
        cards.append(_card(
            cid, title, [sid], value=_fmt(float(t.iloc[-1]), "$T", 2), state="context",
            sub="4-week change {}".format(_fmt(mon.change_n(t, 4), "$T", 2, True)),
            what="H.4.1 weekly Wednesday level, $ trillions. Reserves and the TGA are charted in the funding panel.",
            asof=f.observation_date, cadence=spec.cadence, stale=f.stale, spark=mon.spark(t, 13)))
    charts: list[dict[str, Any]] = []
    if bills is not None:
        since_chart = "2024-10-01"
        lv = dict(name="T-bills ($B)", color="#38bdf8", type="scatter", **mon.sample_series(bills, 1.0, 300, since_chart, 1))
        wk = mon.weekly_delta(bills)
        wkp = wk[wk.index >= pd.Timestamp(since_chart)]
        dl = dict(name="Weekly change ($B)", color="#6366f1", type="bar",
                  x=[d.strftime("%Y-%m-%d") for d in wkp.index], y=[round(float(v), 1) for v in wkp.values])
        charts.append({"id": "chart-rmp-level", "title": "SOMA Treasury bills · SOMA T-bill 持仓", "subtitle": "$ billions. Dashed line: reserve management purchases begin {}.".format(RMP_START),
                       "unit": "$B", "traces": [lv], "refs": [], "vlines": [{"x": RMP_START, "label": "RMP start"}], "default_range": "1Y"})
        charts.append({"id": "chart-rmp-weekly", "title": "Weekly change in T-bill holdings · T-bill 周变化 (RMP flow)", "subtitle": "$ billions per week.",
                       "unit": "$B", "traces": [dl], "refs": [{"y": 0, "label": "0", "color": "#475569"}],
                       "vlines": [{"x": RMP_START, "label": "RMP start"}], "default_range": "1Y"})
    comp = {k: _disp(S, k) for k in ("WSHOBL", "WSHONBNL", "WSHOMCB")}
    comp_chart = None
    if all(v is not None for v in comp.values()):
        traces = []
        for k, name, color in (("WSHONBNL", "Notes and bonds", "#6366f1"), ("WSHOMCB", "MBS", "#f59e0b"), ("WSHOBL", "T-bills", "#38bdf8")):
            traces.append(dict(name=name, color=color, type="scatter", stack=True, **mon.sample_series(comp[k], 1.0, 200, "2023-01-01", 0)))
        comp_chart = {"id": "chart-soma-comp", "title": "SOMA composition · SOMA 构成", "subtitle": "$ billions, stacked.",
                      "unit": "$B", "traces": traces, "refs": [], "default_range": "Max", "stacked": True}
    return {"cards": cards, "charts": charts, "comp_chart": comp_chart, "rmp_avg": rmp_avg, "state": "context",
            "rmp_url": URL_RMP}


# ---------------------------------------------------------------------------
# 4c Credit
# ---------------------------------------------------------------------------
OAS_ORDER = (("BAMLH0A0HYM2", "HY", "High yield OAS · 高收益债 OAS"),
             ("BAMLC0A0CM", "IG", "Investment grade OAS · 投资级 OAS"),
             ("BAMLC0A4CBBB", "BBB", "BBB OAS"),
             ("BAMLH0A1HYBB", "BB", "BB OAS"),
             ("BAMLH0A2HYB", "B", "Single-B OAS · B OAS"),
             ("BAMLH0A3HYC", "CCC", "CCC and lower OAS · CCC及以下 OAS"))


def _oas_card(sid: str, tag: str, title: str, S, now) -> dict[str, Any]:
    spec = _spec(sid)
    bp = _disp(S, sid)
    if bp is None:
        return _na_card("oas-" + tag.lower(), title, [sid], "ICE BofA option-adjusted spread.")
    f = _fresh(S[sid], spec, now)
    chg20 = mon.change_n(bp, 20)
    z = mon.change_z(bp, 20, 3)
    pct, yrs = mon.level_pctile(bp, 3)
    state = mon.credit_state(pct, z, yrs)
    return _card(
        "oas-" + tag.lower(), title, [sid], value=_fmt(float(bp.iloc[-1]), "bp", 0), state=state,
        sub="20d {} · pctile {} vs {}y · change z {}".format(_fmt(chg20, "bp", 0, True), _num(pct, 0), yrs, _num(z, 1, True)),
        what="ICE BofA option-adjusted spread over Treasuries, in basis points (FRED publishes percent).",
        asof=f.observation_date, cadence=spec.cadence, stale=f.stale,
        why="Credit spreads price default and liquidity risk. A widening that starts in the weakest rating bucket tends to precede a broad move.",
        limits="Index-level OAS is not an AI-issuer credit spread. FRED carries only about 3 years of ICE BofA history, so percentiles use that window.",
        spark=mon.spark(bp, 20), unit_note="FRED unit: percent. Shown in bp.",
        rule="watch: pctile >= 80 or change z >= 2. elevated: pctile >= 90 and z >= 1. stress: pctile >= 95 and z >= 2.")


def build_credit(S: dict[str, pd.Series], now: datetime) -> dict[str, Any]:
    ladder = [_oas_card(sid, tag, title, S, now) for sid, tag, title in OAS_ORDER]
    cards: list[dict[str, Any]] = []
    ccc, bb = _get(S, "BAMLH0A3HYC"), _get(S, "BAMLH0A1HYBB")
    quality = None
    if ccc is not None and bb is not None:
        quality = mon.spread(ccc, bb, 100.0)
        f = _fresh(S["BAMLH0A3HYC"], _spec("BAMLH0A3HYC"), now)
        chg20 = mon.change_n(quality, 20)
        z = mon.change_z(quality, 20, 3)
        pct, yrs = mon.level_pctile(quality, 3)
        state = mon.credit_state(pct, z, yrs)
        cards.append(_card(
            "ccc-bb", "CCC minus BB OAS · CCC 减 BB 质量利差", ["BAMLH0A3HYC", "BAMLH0A1HYBB"],
            value=_fmt(float(quality.iloc[-1]) / 100.0, "pct", 2) .replace("%", " pp"), state=state,
            sub="20d {} · pctile {} vs {}y · change z {}".format(_fmt(chg20, "bp", 0, True), _num(pct, 0), yrs, _num(z, 1, True)),
            what="Gap between the weakest and the strongest high-yield rating buckets, in percentage points.",
            asof=f.observation_date, cadence=_spec("BAMLH0A3HYC").cadence, stale=f.stale,
            why="Investors pay up to leave CCC credits before they leave BB credits. A rising gap means selectivity is turning into avoidance of weak balance sheets.",
            limits="Both legs are index OAS. A difference of two spreads, so units are percentage points, not percent.",
            spark=mon.spark(quality, 20, 0.01),
            rule="Reference lines at 5, 8 and 10 pp are operator references from the Weekly Crisis Tracker, not statistical thresholds."))
    else:
        cards.append(_na_card("ccc-bb", "CCC minus BB OAS · CCC 减 BB 质量利差", ["BAMLH0A3HYC", "BAMLH0A1HYBB"], "Rating-quality spread."))
    for sid, cid, title in (("NFCI", "nfci", "Chicago Fed NFCI · 芝加哥联储金融条件指数"),
                            ("ANFCI", "anfci", "Adjusted NFCI (ANFCI) · 调整后 NFCI"),
                            ("STLFSI4", "stlfsi", "St. Louis Fed Financial Stress Index · 圣路易斯联储金融压力指数")):
        spec = _spec(sid)
        t = _get(S, sid)
        if t is None:
            cards.append(_na_card(cid, title, [sid], "Official financial conditions index."))
            continue
        f = _fresh(t, spec, now)
        v = float(t.iloc[-1])
        state = mon.conditions_state(v)
        cards.append(_card(
            cid, title, [sid], value=_num(v, 3, True), state=state,
            sub="4-week change {} · 0 = historical average".format(_num(mon.change_n(t, 4), 3, True)),
            what="Weekly index built from many financial-market series. Above 0 means tighter (or more stressed) than the long-run average.",
            asof=f.observation_date, cadence=spec.cadence, stale=f.stale,
            why="An official, model-based cross-check on whether credit, funding and equity conditions are tightening together.",
            limits="Weekly, with a publication lag of about 5 days. Sign is objective; the 1.0 elevated line is an operator-set heuristic.",
            spark=mon.spark(t, 26), rule="watch above 0, elevated above 1.0."))
    cp, tb = _get(S, "DCPF3M"), _get(S, "DTB3")
    if cp is not None and tb is not None:
        sp = mon.spread(cp, tb, 100.0)
        f = _fresh(cp, _spec("DCPF3M"), now)
        pct, yrs = mon.level_pctile(sp, 3)
        cards.append(_card(
            "cp-tbill", "Financial CP minus 3m T-bill · 金融 CP 减 3个月 T-bill", ["DCPF3M", "DTB3"],
            value=_fmt(float(sp.iloc[-1]), "bp", 0, True), state="context",
            sub="pctile {} vs {}y".format(_num(pct, 0), yrs),
            what="Premium that AA-rated financial issuers pay over the Treasury bill for 3-month money.",
            asof=f.observation_date, cadence=_spec("DCPF3M").cadence, stale=f.stale,
            why="Short-term bank funding stress appears here before it shows up in longer credit spreads.",
            limits="Rates are from different series and may be dated one day apart; context only.", spark=mon.spark(sp, 20)))
    else:
        cards.append(_na_card("cp-tbill", "Financial CP minus 3m T-bill · 金融 CP 减 3个月 T-bill", ["DCPF3M", "DTB3"], "Short-term bank funding premium."))
    em = _disp(S, "BAMLEMCBPIOAS")
    if em is not None:
        f = _fresh(S["BAMLEMCBPIOAS"], _spec("BAMLEMCBPIOAS"), now)
        pct, yrs = mon.level_pctile(em, 3)
        cards.append(_card(
            "em-oas", "EM corporate OAS · 新兴市场公司债 OAS", ["BAMLEMCBPIOAS"], value=_fmt(float(em.iloc[-1]), "bp", 0),
            state="context", sub="20d {} · pctile {} vs {}y".format(_fmt(mon.change_n(em, 20), "bp", 0, True), _num(pct, 0), yrs),
            what="ICE BofA emerging markets corporate plus index OAS.", asof=f.observation_date,
            cadence=_spec("BAMLEMCBPIOAS").cadence, stale=f.stale, spark=mon.spark(em, 20)))
    # charts
    charts: list[dict[str, Any]] = []
    traces = []
    for sid, name, color in (("BAMLH0A1HYBB", "BB", "#f59e0b"), ("BAMLH0A2HYB", "B", "#f97316"), ("BAMLH0A3HYC", "CCC and lower", "#ef4444")):
        t = _disp(S, sid)
        if t is not None:
            traces.append(dict(name=name, color=color, type="scatter", **mon.sample_series(t, 1.0, 300, digits=0)))
    if traces:
        charts.append({"id": "chart-oas-ladder", "title": "High-yield rating ladder · 高收益评级梯度 OAS", "subtitle": "Basis points. Weaker buckets widen first.",
                       "unit": "bp", "traces": traces, "refs": [], "default_range": "1Y"})
    if quality is not None:
        charts.append({"id": "chart-ccc-bb", "title": "CCC minus BB · 质量利差", "subtitle": "Basis points; lines at 500, 800 and 1,000 bp are operator references.",
                       "unit": "bp", "traces": [dict(name="CCC minus BB", color="#ef4444", type="scatter", **mon.sample_series(quality, 1.0, 300, digits=0))],
                       "refs": [{"y": 500, "label": "5 pp " + OPERATOR_REF, "color": "#64748b"},
                                {"y": 800, "label": "8 pp " + OPERATOR_REF, "color": "#f59e0b"},
                                {"y": 1000, "label": "10 pp " + OPERATOR_REF, "color": "#ef4444"}], "default_range": "1Y"})
        ch = quality.diff(20).dropna()
        charts.append({"id": "chart-ccc-bb-chg", "title": "CCC minus BB, 20-day change · 20日变化", "subtitle": "Basis points.", "unit": "bp",
                       "traces": [dict(name="20d change", color="#6366f1", type="bar", **mon.sample_series(ch, 1.0, 260, digits=0))],
                       "refs": [{"y": 0, "label": "0", "color": "#475569"}], "default_range": "1Y", "collapsed": True})
    states = [c["state"] for c in ladder + cards if c["state"] in mon.STATE_RANK and c["id"] != "cp-tbill"]
    hy = next((c for c in ladder if c["id"] == "oas-hy"), None)
    return {"ladder": ladder, "cards": cards, "charts": charts, "state": mon.worst(states),
            "hy_value": hy["value"] if hy else "n/a", "ccc_bb": cards[0]["value"] if cards else "n/a",
            "ccc_bb_sub": cards[0]["sub"] if cards else ""}


# ---------------------------------------------------------------------------
# 4d Rates and term premium
# ---------------------------------------------------------------------------
RATES_REFS = {"DGS30": (5.50, "5.50% " + OPERATOR_REF), "THREEFYTP10": (1.00, "1.00% " + OPERATOR_REF),
              "DFII10": (2.25, "2.25% " + OPERATOR_REF)}


def _rate_card(sid: str, cid: str, title: str, S, now, *, state_on: bool, unit: str = "pct",
               series: pd.Series | None = None, what: str = "", why: str = "", limits: str = "",
               ids: list[str] | None = None, cadence: str | None = None) -> dict[str, Any]:
    spec = _spec(sid)
    s = series if series is not None else _disp(S, sid)
    ids = ids or [sid]
    if s is None or s.dropna().empty:
        return _na_card(cid, title, ids, what)
    f = _fresh(S[sid], spec, now)
    chg = mon.change_n(s, 20)
    z = mon.change_z(s, 20, 5)
    pct, yrs = mon.level_pctile(s, None)
    if state_on:
        state, word = mon.rates_state(pct, z, yrs)
    else:
        state, word = "context", ""
    unit_chg = "bp" if unit == "pct" else unit
    chg_bp = chg * 100.0 if unit == "pct" else chg
    sub = "20d {} · pctile {} vs {}y".format(_fmt(chg_bp, unit_chg, 0, True), _num(pct, 0), yrs)
    if word:
        sub = word + " · " + sub
    ref = RATES_REFS.get(sid)
    c = _card(cid, title, ids, value=_fmt(float(s.iloc[-1]), unit, 2 if unit in ("pct", "index") else 0), state=state, sub=sub, what=what,
              asof=f.observation_date, cadence=cadence or spec.cadence, stale=f.stale, why=why, limits=limits,
              spark=mon.spark(s, 20),
              rule=("watch when high (pctile >= 80), elevated when high and rising (20-obs change z >= 1). "
                    + ("Reference line {} is an {}.".format(ref[1].split(" ")[0], OPERATOR_REF) if ref else "")) if state_on else "")
    return c


def build_rates(S: dict[str, pd.Series], now: datetime) -> dict[str, Any]:
    cards: list[dict[str, Any]] = []
    cards.append(_rate_card("DGS30", "dgs30", "30-year Treasury yield · 30年期国债收益率", S, now, state_on=True,
                            what="Constant-maturity 30-year Treasury yield.",
                            why="The long end prices term premium and fiscal supply. A sustained rise tightens financial conditions for every duration-sensitive asset.",
                            limits="Level state uses percentiles since 2010, a period that includes the zero-rate years."))
    cards.append(_rate_card("DGS10", "dgs10", "10-year Treasury yield · 10年期国债收益率", S, now, state_on=True,
                            what="Constant-maturity 10-year Treasury yield.", why="Benchmark discount rate for mortgages and equity valuation."))
    d30, d5 = _get(S, "DGS30"), _get(S, "DGS5")
    if d30 is not None and d5 is not None:
        sp = mon.spread(d30, d5, 100.0)
        cards.append(_rate_card("DGS30", "s5s30", "5s30s slope · 5年至30年期限利差", S, now, state_on=False, unit="bp", series=sp,
                                what="30-year minus 5-year Treasury yield, in basis points.",
                                why="A steepening driven by the long end points to term premium rather than expected policy rates.",
                                limits="Derived from two constant-maturity series on the same dates.", ids=["DGS30", "DGS5"]))
    else:
        cards.append(_na_card("s5s30", "5s30s slope · 5年至30年期限利差", ["DGS30", "DGS5"], "30-year minus 5-year yield."))
    for sid, cid, title, what in (("T10Y2Y", "t10y2y", "2s10s slope · 2年至10年期限利差", "10-year minus 2-year Treasury spread, in basis points."),
                                  ("T10Y3M", "t10y3m", "3m10y slope · 3个月至10年期限利差", "10-year minus 3-month Treasury spread, in basis points.")):
        cards.append(_rate_card(sid, cid, title, S, now, state_on=False, unit="bp", what=what))
    cards.append(_rate_card("DFII10", "dfii10", "10-year real yield · 10年期实际利率", S, now, state_on=True,
                            what="10-year TIPS yield, constant maturity.",
                            why="Real yields are the cost of capital after inflation. Rising real yields pressure long-duration equity."))
    cards.append(_rate_card("T10YIE", "t10yie", "10-year breakeven inflation · 10年期盈亏平衡通胀", S, now, state_on=False,
                            what="Nominal 10-year yield minus the 10-year TIPS yield."))
    cards.append(_rate_card("THREEFYTP10", "tp10", "10-year term premium (Kim-Wright) · 10年期期限溢价", S, now, state_on=True,
                            what="Model estimate of the extra yield investors require to hold a 10-year Treasury instead of rolling short bills.",
                            why="Term premium is the clearest read on supply and duration-risk compensation, and links directly to the LPI duration supply factor.",
                            limits="Model estimate with a publication lag of a few days; values can be revised."))
    bank = _get(S, "TASACBW027SBOG")
    if bank is not None:
        spec = _spec("TASACBW027SBOG")
        f = _fresh(bank, spec, now)
        cards.append(_card("bankts", "Bank holdings of Treasuries and agencies · 商业银行持有国债和机构债", ["TASACBW027SBOG"],
                           value=_fmt(float(bank.iloc[-1]) / 1000.0, "$T", 2), state="context",
                           sub="13-week change {}".format(_fmt(mon.change_n(bank, 13) / 1000.0, "$T", 2, True)),
                           what="Treasury and agency securities held by all commercial banks (H.8, weekly, $ billions, shown in $ trillions).",
                           asof=f.observation_date, cadence=spec.cadence, stale=f.stale,
                           why="Bank demand is a marginal buyer of duration. Falling holdings with a rising term premium point to supply that private balance sheets are not absorbing.",
                           limits="Includes agency MBS; not seasonally adjusted differences are noted by the Fed.", spark=mon.spark(bank / 1000.0, 26)))
    else:
        cards.append(_na_card("bankts", "Bank holdings of Treasuries and agencies · 商业银行持有国债和机构债", ["TASACBW027SBOG"], "H.8 bank securities."))
    cards.append(_rate_card("DTWEXBGS", "usd", "Broad dollar index · 广义美元指数", S, now, state_on=False, unit="index",
                            what="Federal Reserve nominal broad U.S. dollar index.", limits="Lags by about a week."))
    charts: list[dict[str, Any]] = []
    t = []
    for sid, name, color in (("DGS30", "30Y", "#ef4444"), ("DGS10", "10Y", "#38bdf8")):
        s = _disp(S, sid)
        if s is not None:
            t.append(dict(name=name, color=color, type="scatter", **mon.sample_series(s, 1.0, 320, "2022-01-01", 2)))
    if t:
        charts.append({"id": "chart-rates-yields", "title": "30Y and 10Y yields · 30年与10年期收益率", "subtitle": "Percent. Line: 5.50% is an " + OPERATOR_REF + " on the 30Y.",
                       "unit": "pct", "traces": t, "refs": [{"y": 5.5, "label": "5.50% " + OPERATOR_REF, "color": "#64748b"}], "default_range": "1Y"})
    t = []
    for sid, name, color in (("THREEFYTP10", "Term premium (10Y)", "#f59e0b"), ("DFII10", "Real yield (10Y)", "#6366f1")):
        s = _disp(S, sid)
        if s is not None:
            t.append(dict(name=name, color=color, type="scatter", **mon.sample_series(s, 1.0, 320, "2022-01-01", 2)))
    if t:
        charts.append({"id": "chart-rates-tp", "title": "Term premium and real yield · 期限溢价与实际利率", "subtitle": "Percent. Lines: 1.00% and 2.25% are " + OPERATOR_REF + "s.",
                       "unit": "pct", "traces": t, "refs": [{"y": 1.0, "label": "1.00% " + OPERATOR_REF, "color": "#f59e0b"}, {"y": 2.25, "label": "2.25% " + OPERATOR_REF, "color": "#6366f1"}],
                       "default_range": "1Y"})
    if d30 is not None and d5 is not None:
        sp = mon.spread(d30, d5, 100.0)
        charts.append({"id": "chart-rates-5s30s", "title": "5s30s slope · 5年至30年利差", "subtitle": "Basis points.", "unit": "bp",
                       "traces": [dict(name="5s30s", color="#38bdf8", type="scatter", **mon.sample_series(sp, 1.0, 320, "2022-01-01", 0))],
                       "refs": [{"y": 0, "label": "0", "color": "#475569"}], "default_range": "1Y"})
    states = [c["state"] for c in cards if c["id"] in ("dgs30", "dgs10", "dfii10", "tp10")]
    d30c = next((c for c in cards if c["id"] == "dgs30"), None)
    tpc = next((c for c in cards if c["id"] == "tp10"), None)
    return {"cards": cards, "charts": charts, "state": mon.worst(states),
            "dgs30": d30c["value"] if d30c else "n/a", "tp": tpc["value"] if tpc else "n/a"}


def build_all(S: dict[str, pd.Series], now: datetime) -> dict[str, Any]:
    return {"funding": build_funding(S, now), "fedbs": build_fedbs(S, now),
            "credit": build_credit(S, now), "rates": build_rates(S, now)}
