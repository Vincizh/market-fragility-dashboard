"""Build card and chart payloads for the v2 FRED modules (funding extras, backstops,
Fed balance sheet and RMP, credit, rates). Output is plain dicts; fred_render.py turns them
into HTML. Every card fails independently: a missing or stale series becomes a grey card.
"""
from __future__ import annotations

import re

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
WHERE_SERIES = (("SOFR", "SOFR (all repo)", "#f59e0b"), ("BGCR", "BGCR (tri-party + GCF)", "#a78bfa"),
                ("TGCRRATE", "TGCR (tri-party)", "#38bdf8"), ("OBFR", "OBFR (bank overnight)", "#94a3b8"),
                ("EFFR", "EFFR (fed funds)", "#2dd4bf"))
WHERE_VOL = {"SOFR": "SOFRVOL", "BGCR": "BGCRVOL", "TGCRRATE": "TGCRVOLUME", "OBFR": "OBFRVOL", "EFFR": "EFFRVOL"}


def build_where(S: dict[str, pd.Series], now: datetime) -> dict[str, Any]:
    """Secured vs unsecured diagnostic: each overnight rate minus IORB, plus a classification
    of where the pressure sits (descriptive only; outside the LPI and every composite, D6)."""
    io = _get(S, "IORB")
    rows: list[dict[str, Any]] = []
    spreads: dict[str, pd.Series] = {}
    for sid, name, color in WHERE_SERIES:
        r = _get(S, sid)
        if r is None or io is None:
            rows.append({"id": sid, "name": name, "color": color, "available": False})
            continue
        sp = mon.spread(r, io, 100.0)
        spreads[sid] = sp
        f = _fresh(r, _spec(sid), now)
        vol = _get(S, WHERE_VOL[sid])
        rows.append({"id": sid, "name": name, "color": color, "available": True, "rate": float(r.iloc[-1]),
                     "bp": float(sp.iloc[-1]), "chg5": mon.change_n(sp, 5), "chg20": mon.change_n(sp, 20),
                     "vol": float(vol.iloc[-1]) if vol is not None else NAN,
                     "vol_chg5": mon.change_n(vol, 5) if vol is not None else NAN,
                     "asof": f.observation_date, "stale": f.stale,
                     "secured": sid in ("SOFR", "BGCR", "TGCRRATE")})
    sofr_sp, effr_sp = spreads.get("SOFR"), spreads.get("EFFR")
    stale = any(r.get("stale") for r in rows if r["id"] in ("SOFR", "EFFR") and r["available"])
    sec_med = float(sofr_sp.tail(5).median()) if sofr_sp is not None else NAN
    un_bp = float(effr_sp.iloc[-1]) if effr_sp is not None else NAN
    un_chg = mon.change_n(effr_sp, 20) if effr_sp is not None else NAN
    key = "na" if stale else mon.funding_locus(sec_med, un_bp, un_chg)
    state, label_en, label_zh, why = mon.LOCUS.get(key, ("na", "Unavailable", "不可用", "SOFR, EFFR or IORB is missing or stale this run."))
    chart = None
    if spreads:
        traces = []
        for sid, name, color in WHERE_SERIES:
            if sid in spreads:
                t = _tr(name + " - IORB", color, spreads[sid], digits=0)
                if sid == "BGCR":
                    t["dash"] = "dot"
                if sid == "EFFR":
                    t["width"] = 3
                traces.append(t)
        chart = {"id": "chart-where", "title": "Overnight rates minus IORB · 隔夜利率减 IORB",
                 "subtitle": "bp. Secured repo: SOFR, BGCR, TGCR. Unsecured bank funding: OBFR, EFFR. 0 = IORB.",
                 "unit": "bp", "traces": traces, "default_range": "6M", "initial_range": "6M",
                 "refs": [{"y": 0, "label": "", "color": "#475569"},
                          {"y": mon.SECURED_ON_BP, "label": "+3 bp", "color": "#f59e0b"}]}
    asof = max([r["asof"] for r in rows if r.get("available") and r.get("asof")] or [None]) if rows else None
    return {"key": key, "state": state, "label_en": label_en, "label_zh": label_zh, "why": why,
            "secured_med_bp": sec_med, "unsec_bp": un_bp, "unsec_chg20_bp": un_chg, "rows": rows,
            "chart": chart, "asof": asof,
            "rule": ("Secured on: SOFR - IORB median of the last 5 observations at or above +{:.0f} bp. "
                     "Unsecured on: EFFR - IORB at or above {:.0f} bp, or up {:.0f} bp or more over 20 observations. "
                     "Both on = broad; secured only = repo/collateral; unsecured only = interbank; neither = calm.").format(
                         mon.SECURED_ON_BP, mon.UNSEC_LEVEL_ON_BP, mon.UNSEC_RISE_BP),
            "links": [(i, fc.BY_ID[i].url) for i in ("SOFR", "BGCR", "TGCRRATE", "OBFR", "EFFR", "IORB")]}


def build_funding(S: dict[str, pd.Series], now: datetime) -> dict[str, Any]:
    cards: list[dict[str, Any]] = []
    # EFFR - IORB: the interbank (unsecured) gauge
    ef, io0 = _get(S, "EFFR"), _get(S, "IORB")
    if ef is not None and io0 is not None:
        sp = mon.spread(ef, io0, 100.0)
        f = _fresh(ef, _spec("EFFR"), now)
        v, c20 = float(sp.iloc[-1]), mon.change_n(sp, 20)
        pct, yrs = mon.level_pctile(sp, 3)
        vol = _get(S, "EFFRVOL")
        cards.append(_card(
            "effr-iorb", "EFFR minus IORB · 联邦基金利率减 IORB (银行间)", ["EFFR", "IORB", "EFFRVOL"],
            value=_fmt(v, "bp", 0, True), state=mon.unsecured_state(v, c20),
            sub="20d {} · 3y pctile {} · volume {}".format(_fmt(c20, "bp", 0, True), _num(pct, 0),
                                                          _fmt(float(vol.iloc[-1]), "$B", 0) if vol is not None else "n/a"),
            what="The unsecured overnight rate banks pay each other for reserves, minus the interest the Fed pays on reserves (IORB), in basis points.",
            asof=f.observation_date, cadence=_spec("EFFR").cadence, stale=f.stale,
            why="Any bank can earn IORB by leaving reserves at the Fed, so EFFR usually sits below IORB. When reserves become scarce, banks bid more for them and EFFR rises toward or above IORB. This is the direct reserve-scarcity gauge; SOFR - IORB is a repo and collateral gauge.",
            limits="Fed funds volume is about $0.1T and dominated by FHLB lending, so it is a thin market. EFFR moved from about -7 bp (2023 to Aug 2025) to about -2 bp by Nov 2025 and has stayed there, so the 3y percentile is near the top without a new rise.",
            spark=mon.spark(sp, 20),
            rule="Watch at or above -1 bp or a 20-observation rise of +2 bp or more; elevated at or above 0 bp (EFFR at or above IORB). Uses the IORB anchor, not a percentile, because of the 2025 level shift."))
        cards[-1]["_chart"] = dict(traces=[_tr("EFFR minus IORB", "STATE", _window(sp, 3), digits=0)], unit="bp",
                                   refs=[{"y": 0, "label": "IORB", "color": REF_RED},
                                         {"y": -7, "label": "-7 bp (2023-25 norm)", "color": REF_GREY}])
        cards[-1]["num"], cards[-1]["num_chg20"] = v, c20
    else:
        cards.append(_na_card("effr-iorb", "EFFR minus IORB · 联邦基金利率减 IORB (银行间)", ["EFFR", "IORB"], "Interbank overnight rate against IORB."))
    # BGCR - IORB
    bg = _get(S, "BGCR")
    if bg is not None and io0 is not None:
        sp = mon.spread(bg, io0, 100.0)
        f = _fresh(bg, _spec("BGCR"), now)
        v = float(sp.iloc[-1])
        state = "elevated" if v >= fm.SOFR_REFERENCE_ELEVATED_BP else ("watch" if v >= fm.SOFR_STRATEGY_BP else "normal")
        vol = _get(S, "BGCRVOL")
        cards.append(_card(
            "bgcr-iorb", "BGCR minus IORB · 广义一般担保回购减 IORB", ["BGCR", "IORB", "BGCRVOL"],
            value=_fmt(v, "bp", 0, True), state=state,
            sub="5d median {} · 20d {} · volume {}".format(_fmt(float(sp.tail(5).median()), "bp", 1, True),
                                                         _fmt(mon.change_n(sp, 20), "bp", 0, True),
                                                         _fmt(float(vol.iloc[-1]), "$B", 0) if vol is not None else "n/a"),
            what="Broad general collateral repo rate (tri-party plus GCF, excluding bilateral) minus IORB, in basis points. Published by the NY Fed.",
            asof=f.observation_date, cadence=_spec("BGCR").cadence, stale=f.stale,
            why="Sits between TGCR (tri-party only) and SOFR (all repo). When SOFR rises but BGCR does not, the pressure is in bilateral dealer-cleared repo; when all three rise, cash for Treasury collateral is scarce across platforms.",
            limits="Not calendar-filtered: month-end and Treasury settlement dates print higher. Context only, outside the funding resonance count.",
            spark=mon.spark(sp, 20), rule="Watch at or above +3.0 bp, elevated at or above +5.0 bp (the SOFR strategy lines)."))
        cards[-1]["_chart"] = dict(traces=[_tr("BGCR minus IORB", "STATE", _window(sp, 3), digits=0)], unit="bp",
                                   refs=[{"y": 0, "label": "IORB", "color": REF_GREY}, {"y": 3, "label": "+3 bp", "color": REF_AMBER}])
        cards[-1]["num"], cards[-1]["num_med5"] = v, float(sp.tail(5).median())
    else:
        cards.append(_na_card("bgcr-iorb", "BGCR minus IORB · 广义一般担保回购减 IORB", ["BGCR", "IORB"], "Broad general collateral repo rate against IORB."))
    # SOFR - EFFR: secured minus unsecured in one number
    so = _get(S, "SOFR")
    if so is not None and ef is not None:
        sp = mon.spread(so, ef, 100.0)
        f = _fresh(so, _spec("SOFR"), now)
        pct, yrs = mon.level_pctile(sp, 3)
        c = _card(
            "sofr-effr", "SOFR minus EFFR · 担保减无担保", ["SOFR", "EFFR"],
            value=_fmt(float(sp.iloc[-1]), "bp", 0, True), state="context",
            sub="20d {} · 3y pctile {}".format(_fmt(mon.change_n(sp, 20), "bp", 0, True), _num(pct, 0)),
            what="Secured overnight repo rate minus the unsecured fed funds rate, in basis points.",
            asof=f.observation_date, cadence=_spec("SOFR").cadence, stale=f.stale,
            why="Normally repo trades below fed funds because the lender holds Treasury collateral. A positive and widening gap means cash against collateral has become more expensive than unsecured bank lending, which isolates collateral and dealer balance-sheet pressure.",
            limits="Different borrower mixes (dealers and funds in repo, FHLBs and banks in fed funds). Not calendar-filtered.",
            spark=mon.spark(sp, 20))
        c["_chart"] = dict(traces=[_tr("SOFR minus EFFR", "STATE", _window(sp, 3), digits=0)], unit="bp",
                           refs=[{"y": 0, "label": "0", "color": REF_GREY}])
        cards.append(c)
    else:
        cards.append(_na_card("sofr-effr", "SOFR minus EFFR · 担保减无担保", ["SOFR", "EFFR"], "Secured minus unsecured overnight rate."))
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
        cards[-1]["num"], cards[-1]["num_med5"] = v, float(sp.tail(5).median())
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
        cards[-1]["num"] = float(sp.iloc[-1])
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
        card["num"] = r["value"]
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

    states = [c["state"] for c in cards if c["id"] in ("tgcr-iorb", "sofr-disp", "effr-iorb", "bgcr-iorb")]
    return {"cards": cards, "where": build_where(S, now), "backstops": backs, "backstops_in_use": n_use, "backstops_avail": n_avail,
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
            sub="1w {} · 4w {}".format(_fmt(mon.change_n(t, 1) * 1000.0, "$B", 0, True), _fmt(mon.change_n(t, 4) * 1000.0, "$B", 0, True)),
            what="H.4.1 weekly Wednesday level, shown in $ trillions; changes in $ billions.",
            asof=f.observation_date, cadence=spec.cadence, stale=f.stale, spark=mon.spark(t, 13)))
    # Net liquidity decomposition (weekly, common Wednesdays)
    nl = mon.net_liquidity_decomp(_get(S, "WALCL"), _get(S, "WTREGEN"), _get(S, "RRPONTSYD"))
    netliq_chart = None
    if len(nl) > 5:
        w1, w4 = mon.window_contrib(nl, 1), mon.window_contrib(nl, 4)
        end = nl.index[-1]
        stale = (pd.Timestamp(now.replace(tzinfo=None) if getattr(now, "tzinfo", None) else now) - end).days > 13
        drv = "1w drivers: Fed assets {}, TGA {}, ON RRP {}".format(_fmt(w1["d_assets"], "$B", 0, True), _fmt(w1["d_tga"], "$B", 0, True),
                                                                   _fmt(w1["d_rrp"], "$B", 0, True))
        c = _card(
            "netliq", "Net liquidity (Fed assets - TGA - ON RRP) · 净流动性", ["WALCL", "WTREGEN", "RRPONTSYD"],
            value=_fmt(float(nl["net"].iloc[-1]) / 1000.0, "$T", 2), state="context",
            sub="1w {} · 4w {} · {}".format(_fmt(w1["d_net"], "$B", 0, True), _fmt(w4["d_net"], "$B", 0, True), drv),
            what="Fed total assets minus the Treasury General Account minus overnight reverse repo, on common H.4.1 Wednesdays, in $ trillions. Weekly contributions: +change in Fed assets, -change in TGA, -change in ON RRP.",
            asof=end.strftime("%Y-%m-%d"), cadence="weekly (Wednesday level, H.4.1)", stale=stale,
            why="Shows which balance-sheet item moved cash in or out of the private system this week. A TGA build or a shrinking balance sheet drains reserves and money-fund cash; a falling ON RRP releases cash.",
            limits="Window and end date matter: a 4-week change ending this Wednesday and one ending last Wednesday can differ in sign when a large weekly swing enters or leaves the window. Uses H.4.1 Wednesday TGA, which differs from the daily Treasury statement figure. Same definition as the LPI net-liquidity factor, shown here as a level and flow; it does not add a second LPI input.",
            spark=[round(float(v) / 1000.0, 3) for v in nl["net"].tail(13)],
            unit_note="WALCL and WTREGEN arrive in $ millions; ON RRP in $ billions. All converted to $ billions for the flows and $ trillions for the level.")
        c["_chart"] = dict(traces=[_tr("Net liquidity", "STATE", _window(nl["net"] / 1000.0, 3), digits=3)], unit="$T", refs=[])
        cards.insert(0, c)
        nlp = nl[nl.index >= nl.index[-1] - pd.DateOffset(years=3)].dropna()
        x = [d.strftime("%Y-%m-%d") for d in nlp.index]
        netliq_chart = {"id": "chart-netliq-contrib", "title": "Weekly net-liquidity contributions · 净流动性周度贡献",
                        "subtitle": "$ billions per week. Bars: +change in Fed assets, -change in TGA, -change in ON RRP. Line: net change. Week ending {}.".format(end.strftime("%Y-%m-%d")),
                        "unit": "$B", "barmode": "relative", "default_range": "1Y", "initial_range": "1Y",
                        "traces": [dict(name="Fed assets", color="#6366f1", type="bar", x=x, y=[round(float(v), 1) for v in nlp["d_assets"]]),
                                   dict(name="TGA (inverted)", color="#f59e0b", type="bar", x=x, y=[round(float(v), 1) for v in nlp["d_tga"]]),
                                   dict(name="ON RRP (inverted)", color="#38bdf8", type="bar", x=x, y=[round(float(v), 1) for v in nlp["d_rrp"]]),
                                   dict(name="Net change", color="#e2e8f0", type="scatter", x=x, y=[round(float(v), 1) for v in nlp["d_net"]])],
                        "refs": [{"y": 0, "label": "0", "color": "#475569"}]}
    else:
        cards.insert(0, _na_card("netliq", "Net liquidity (Fed assets - TGA - ON RRP) · 净流动性", ["WALCL", "WTREGEN", "RRPONTSYD"], "Fed assets minus TGA minus ON RRP."))
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
    return {"cards": cards, "charts": charts, "comp_chart": comp_chart, "netliq_chart": netliq_chart, "rmp_avg": rmp_avg, "state": "context",
            "rmp_url": URL_RMP}


# ---------------------------------------------------------------------------
# 4c Credit
# ---------------------------------------------------------------------------
OAS_WHAT = {"HY": "The full US high-yield index: the headline price of junk-bond credit risk.",
            "IG": "The US investment-grade corporate index: the price of credit risk for high-quality issuers.",
            "BBB": "The lowest investment-grade rating, one step above high yield and the largest fallen-angel risk pool.",
            "BB": "The strongest high-yield bucket, the reference for how much safe junk pays over Treasuries.",
            "B": "The middle high-yield bucket, more sensitive to refinancing conditions than BB.",
            "CCC": "The weakest rating bucket, the first place stress shows up when investors stop funding weak balance sheets."}
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
        what=OAS_WHAT.get(tag, "") + " ICE BofA OAS, in basis points.",
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
    hy, ig = _get(S, "BAMLH0A0HYM2"), _get(S, "BAMLC0A0CM")
    if hy is not None and ig is not None:
        q = mon.spread(hy, ig, 100.0)
        f = _fresh(hy, _spec("BAMLH0A0HYM2"), now)
        pct, yrs = mon.level_pctile(q, 3)
        z = mon.change_z(q, 20, 3)
        c = _card(
            "hy-ig", "HY minus IG OAS · 高收益减投资级利差", ["BAMLH0A0HYM2", "BAMLC0A0CM"],
            value=_fmt(float(q.iloc[-1]), "bp", 0), state=mon.credit_state(pct, z, yrs),
            sub="20d {} · 5d change {} · pctile {} vs {}y".format(_fmt(mon.change_n(q, 20), "bp", 0, True), _fmt(mon.change_n(q, 5), "bp", 0, True), _num(pct, 0), yrs),
            what="High-yield index OAS minus investment-grade index OAS, in basis points.",
            asof=f.observation_date, cadence=_spec("BAMLH0A0HYM2").cadence, stale=f.stale,
            why="Removes the part of spread moves shared by all corporate credit (rates volatility, broad risk appetite) and keeps the extra price of default risk. It widens when investors separate weak issuers from strong ones.",
            limits="ICE BofA closes are published with a one-day lag, so a Friday selloff appears on the next business day.",
            spark=mon.spark(q, 20), rule="Percentile of own 3y history plus 20-observation change z (same rule as the OAS ladder).")
        c["_chart"] = dict(traces=[_tr("HY minus IG", "STATE", _window(q, 3), digits=0)], unit="bp", refs=_pct_refs(q, 3, "(3y)"))
        cards.append(c)
    else:
        cards.append(_na_card("hy-ig", "HY minus IG OAS · 高收益减投资级利差", ["BAMLH0A0HYM2", "BAMLC0A0CM"], "High-yield minus investment-grade spread."))
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
    for sid, name, color in (("BAMLH0A1HYBB", "BB", "#38bdf8"), ("BAMLH0A2HYB", "B", "#f59e0b"), ("BAMLH0A3HYC", "CCC and lower", "#ef4444")):
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
    cards.append(_rate_card("DGS2", "dgs2", "2-year Treasury yield · 2年期国债收益率", S, now, state_on=False,
                            what="Constant-maturity 2-year Treasury yield.",
                            why="The 2-year prices the expected path of the policy rate over the next two years. A fall with stocks down points to growth fear; a rise points to inflation or hawkish repricing."))
    rv10, rv2 = mon.realized_vol_bp(_get(S, "DGS10")), mon.realized_vol_bp(_get(S, "DGS2"))
    if len(rv10) > 60:
        f = _fresh(S["DGS10"], _spec("DGS10"), now)
        pct10, yrs10 = mon.level_pctile(rv10, 5)
        pct2, _ = mon.level_pctile(rv2, 5) if len(rv2) > 60 else (NAN, 0)
        c = _card(
            "rvol", "Treasury realized volatility (20d) · 国债已实现波动率", ["DGS10", "DGS2"],
            value="10Y {}".format(_fmt(float(rv10.iloc[-1]), "bp", 0)), state="context",
            sub="20d {} · 10Y pctile {} vs {}y · 2Y {} (pctile {})".format(
                _fmt(mon.change_n(rv10, 20), "bp", 0, True), _num(pct10, 0), yrs10,
                _fmt(float(rv2.iloc[-1]), "bp", 0) if len(rv2) else "n/a", _num(pct2, 0)),
            what="Annualized standard deviation of daily yield changes over the last 20 trading days, in basis points per year: std(daily bp change) x sqrt(252).",
            asof=f.observation_date, cadence=_spec("DGS10").cadence, stale=f.stale,
            why="Bond volatility raises the haircut and VaR cost of holding Treasuries, which shrinks dealer and leveraged balance sheets. It is a realized cousin of the MOVE index, built from free FRED data.",
            limits="Realized, so it lags implied volatility (MOVE). Constant-maturity yields are interpolated by Treasury.",
            spark=mon.spark(rv10, 20))
        c["_chart"] = dict(traces=[_tr("10Y", "STATE", _window(rv10, 3), digits=0), dict(_tr("2Y", "#2dd4bf", _window(rv2, 3), digits=0), nolabel=True)],
                           unit="bp", refs=_pct_refs(rv10, 5, "10Y (5y)"))
        cards.append(c)
    else:
        cards.append(_na_card("rvol", "Treasury realized volatility (20d) · 国债已实现波动率", ["DGS10", "DGS2"], "Realized volatility of daily yield changes."))
    tb, sf = _get(S, "DTB3"), _get(S, "SOFR")
    if tb is not None and sf is not None:
        sp = mon.spread(tb, sf, 100.0)
        f = _fresh(tb, _spec("DTB3"), now)
        pct, yrs = mon.level_pctile(sp, 3)
        c = _card(
            "tbill-sofr", "3m T-bill minus SOFR · 3个月国库券减 SOFR", ["DTB3", "SOFR"],
            value=_fmt(float(sp.iloc[-1]), "bp", 0, True), state="context",
            sub="20d {} · 3y pctile {}".format(_fmt(mon.change_n(sp, 20), "bp", 0, True), _num(pct, 0)),
            what="3-month Treasury bill yield (secondary market, discount basis) minus overnight SOFR, in basis points.",
            asof=f.observation_date, cadence=_spec("DTB3").cadence, stale=f.stale,
            why="Money funds choose between bills and repo. When heavy bill supply pushes bill yields above repo, cash moves out of repo and ON RRP into bills, which can lift repo rates. A positive gap is a supply signal for the front end.",
            limits="A 3-month rate against an overnight rate: expected policy cuts within 3 months pull the gap down. DTB3 is quoted on a discount basis, a few bp below the bond-equivalent yield.",
            spark=mon.spark(sp, 20))
        c["_chart"] = dict(traces=[_tr("T-bill minus SOFR", "STATE", _window(sp, 3), digits=0)], unit="bp", refs=[{"y": 0, "label": "0", "color": REF_GREY}])
        cards.append(c)
    else:
        cards.append(_na_card("tbill-sofr", "3m T-bill minus SOFR · 3个月国库券减 SOFR", ["DTB3", "SOFR"], "Bill yield against repo."))
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


def build_all(S: dict[str, pd.Series], now: datetime, charts: bool = True) -> dict[str, Any]:
    M = {"funding": build_funding(S, now), "fedbs": build_fedbs(S, now),
         "credit": build_credit(S, now), "rates": build_rates(S, now)}
    if charts:
        attach_card_charts(M, S)
    return M


# ---------------------------------------------------------------------------
# Per-card charts: every metric card carries its own time series so the number has context
# ---------------------------------------------------------------------------
CARD_LINE = {"normal": "#10b981", "watch": "#f59e0b", "elevated": "#f97316", "stress": "#ef4444",
             "context": "#a5b4fc", "na": "#64748b"}
REF_GREY, REF_AMBER, REF_RED = "#64748b", "#f59e0b", "#ef4444"


def _thin(s: pd.Series, recent_days: int = 220, how: str = "last") -> pd.Series:
    """Keep the last recent_days at native frequency; thin older daily data to weekly."""
    s = s.dropna()
    if len(s) < 3:
        return s
    spacing = pd.Series(s.index[-60:]).diff().dt.days.median()
    if not (spacing == spacing) or spacing >= 5:
        return s
    cut = s.index[-1] - pd.Timedelta(days=recent_days)
    old, new = s[s.index < cut], s[s.index >= cut]
    if len(old):
        r = old.resample("W-FRI")
        old = (r.max() if how == "max" else r.last()).dropna()
    return pd.concat([old, new])


def _window(s: pd.Series, years: int) -> pd.Series:
    s = s.dropna()
    return s[s.index >= s.index[-1] - pd.DateOffset(years=years)] if len(s) else s


def _tr(name: str, color: str, s: pd.Series, kind: str = "scatter", digits: int = 2, how: str = "last") -> dict[str, Any]:
    t = _thin(s, how=how)
    return dict(name=name, color=color, type=kind, x=[d.strftime("%Y-%m-%d") for d in t.index],
                y=[round(float(v), digits) for v in t.values])


def _pct_refs(s: pd.Series, years: int | None, label: str = "") -> list[dict[str, Any]]:
    w = s.dropna()
    if years:
        w = _window(w, years)
    if len(w) < 30:
        return []
    return [{"y": round(float(w.quantile(0.80)), 2), "label": "80th pctile " + label, "color": REF_AMBER},
            {"y": round(float(w.quantile(0.95)), 2), "label": "95th pctile " + label, "color": REF_RED}]


def _card_chart_spec(cid: str, S: dict[str, pd.Series], card: dict[str, Any]) -> dict[str, Any] | None:
    """Return {series list, unit, refs, years, vlines} for a card id, or None."""
    st = card["state"]
    col = CARD_LINE.get(st, CARD_LINE["context"])
    d = lambda sid: _disp(S, sid)  # noqa: E731
    if card.get("_chart"):
        spec = dict(card["_chart"])
        for t in spec["traces"]:
            if t.get("color") == "STATE":
                t["color"] = col
        return spec
    if cid == "tgcr-iorb":
        tg, io = _get(S, "TGCRRATE"), _get(S, "IORB")
        if tg is None or io is None:
            return None
        sp = mon.spread(tg, io, 100.0)
        return dict(traces=[_tr("TGCR minus IORB", col, _window(sp, 3), digits=1)], unit="bp",
                    refs=[{"y": 0, "label": "IORB", "color": REF_GREY}, {"y": 3, "label": "+3 bp strategy line", "color": REF_AMBER},
                          {"y": 5, "label": "+5 bp", "color": REF_RED}])
    if cid == "sofr-disp":
        a, b = _get(S, "SOFR99"), _get(S, "SOFR")
        if a is None or b is None:
            return None
        sp = mon.spread(a, b, 100.0)
        return dict(traces=[_tr("99th minus median", col, _window(sp, 3), digits=1)], unit="bp", refs=_pct_refs(sp, 2, "(2y)"))
    if cid == "sofr-vol":
        sv = _get(S, "SOFRVOL")
        if sv is None:
            return None
        w = _window(sv, 3)
        return dict(traces=[_tr("Daily", "#475569", w, digits=0), _tr("20d average", "#f59e0b", w.rolling(20).mean(), digits=0)], unit="$B", refs=[])
    if cid in ("srf", "swaps", "fima", "dw", "frrp"):
        sid = {"srf": "RPONTSYD", "swaps": "SWPT", "fima": "H41RESPPALGTRFNWW", "dw": "WLCFLPCL", "frrp": "WLRRAFOIAL"}[cid]
        ser = d(sid)
        if ser is None:
            return None
        if cid == "srf":
            ser = ser.dropna().rolling("7D").sum()
        w = _window(ser, 3)
        refs = []
        if cid in ("srf", "swaps", "fima"):
            fl = mon.BACKSTOP_FLOORS_B[sid]
            refs.append({"y": fl, "label": "floor ${:g}B".format(fl), "color": REF_AMBER})
        if cid in ("srf", "swaps", "fima", "dw"):
            p95 = mon.trailing_p95(ser, 156)
            if p95 == p95:
                refs.append({"y": round(p95, 2), "label": "3y 95th pctile", "color": REF_RED})
        bar = cid in ("srf", "fima", "swaps")
        return dict(traces=[_tr("7-day total" if cid == "srf" else card["title"].split(" · ")[0], col, w,
                                "bar" if bar else "scatter", digits=2, how="max")], unit="$B", refs=refs)
    # level cards from the catalog
    LEVEL = {"wshobl": "WSHOBL", "wshosho": "WSHOSHO", "wsefintl1": "WSEFINTL1", "walcl": "WALCL", "wresbal": "WRESBAL",
             "wtregen": "WTREGEN", "em-oas": "BAMLEMCBPIOAS", "nfci": "NFCI", "anfci": "ANFCI", "stlfsi": "STLFSI4",
             "oas-hy": "BAMLH0A0HYM2", "oas-ig": "BAMLC0A0CM", "oas-bbb": "BAMLC0A4CBBB", "oas-bb": "BAMLH0A1HYBB",
             "oas-b": "BAMLH0A2HYB", "oas-ccc": "BAMLH0A3HYC", "dgs30": "DGS30", "dgs10": "DGS10", "dfii10": "DFII10",
             "tp10": "THREEFYTP10", "t10y2y": "T10Y2Y", "t10y3m": "T10Y3M", "t10yie": "T10YIE", "usd": "DTWEXBGS", "dgs2": "DGS2"}
    if cid in LEVEL:
        sid = LEVEL[cid]
        ser = d(sid)
        if ser is None:
            return None
        spec = _spec(sid)
        years = 5 if cid in ("dgs2", "dgs30", "dgs10", "dfii10", "tp10", "t10y2y", "t10y3m", "t10yie", "usd") else 3
        refs: list[dict[str, Any]] = []
        vl = None
        if cid.startswith("oas-"):
            refs = _pct_refs(ser, 3, "(3y)")
        elif cid in ("dgs30", "dgs10", "dfii10", "tp10"):
            refs = _pct_refs(ser, None, "(since 2010)")
        elif cid in ("nfci", "anfci", "stlfsi"):
            refs = [{"y": 0, "label": "0 = historical average", "color": REF_GREY}, {"y": 1.0, "label": "1.0 tight", "color": REF_AMBER}]
        elif cid in ("t10y2y", "t10y3m"):
            refs = [{"y": 0, "label": "0 = inverted below", "color": REF_GREY}]
        elif cid == "wshobl":
            vl = [{"x": RMP_START, "label": "RMP start"}]
        unit = spec.display
        return dict(traces=[_tr(card["title"].split(" · ")[0], col, _window(ser, years), digits=2 if unit in ("pct", "$T", "index") else 1)],
                    unit=unit, refs=refs, vlines=vl)
    if cid == "ccc-bb":
        a, b = d("BAMLH0A3HYC"), d("BAMLH0A1HYBB")
        if a is None or b is None:
            return None
        q = mon.spread(a, b, 1.0) / 100.0
        return dict(traces=[_tr("CCC minus BB", col, _window(q, 3), digits=2)], unit="pp", refs=_pct_refs(q, 3, "(3y)"))
    if cid == "cp-tbill":
        a, b = _get(S, "DCPF3M"), _get(S, "DTB3")
        if a is None or b is None:
            return None
        sp = mon.spread(a, b, 100.0)
        return dict(traces=[_tr("CP minus T-bill", col, _window(sp, 3), digits=0)], unit="bp", refs=[{"y": 0, "label": "0", "color": REF_GREY}])
    if cid == "s5s30":
        a, b = _get(S, "DGS30"), _get(S, "DGS5")
        if a is None or b is None:
            return None
        sp = mon.spread(a, b, 100.0)
        return dict(traces=[_tr("30Y minus 5Y", col, _window(sp, 5), digits=0)], unit="bp", refs=[{"y": 0, "label": "0", "color": REF_GREY}])
    if cid == "bankts":
        bank = _get(S, "TASACBW027SBOG")
        if bank is None:
            return None
        return dict(traces=[_tr("Bank holdings", col, _window(bank / 1000.0, 5), digits=2)], unit="$T", refs=[])
    return None


_CHG_RE = re.compile(r"(?:^|·\s*)(20d|4w|4-week change|13-week change|5d change)\s+([+\-−][^·]*?)\s*(?:·|$)")
_CHG_OBS = {"20d": 20, "4w": 4, "4-week change": 4, "13-week change": 13, "5d change": 5}
_CHG_LBL = {"20d": "20d", "4w": "4w", "4-week change": "4w", "13-week change": "13w", "5d change": "5d"}


def _add_change_window(c: dict[str, Any], chart: dict[str, Any]) -> None:
    """Pull the headline change (e.g. '20d +63 bp') out of the card text, show it next to the value
    and shade the same window on the chart so the slope is visible without reading."""
    m = None
    for mm in _CHG_RE.finditer(c.get("sub", "")):
        m = mm
        if mm.group(1) in ("20d", "4w", "4-week change"):
            break
    if not m:
        return
    key, val = m.group(1), m.group(2).strip()
    sign = val[:1]
    num = re.sub(r"[^0-9.]", "", val)
    flat = bool(num) and float(num or 0) == 0.0
    c["chg_txt"] = "{} {} {}".format("▲" if sign == "+" else "▼", _CHG_LBL[key], val) if not flat else "{} {}".format(_CHG_LBL[key], val.lstrip("+-−"))
    c["chg_dir"] = "flat" if flat else ("up" if sign == "+" else "down")
    c["chg_color"] = CARD_LINE.get(c["state"], CARD_LINE["context"])
    x = chart["traces"][0]["x"]
    n = _CHG_OBS[key]
    if len(x) > n:
        chart["band"] = {"x0": x[-n - 1], "x1": x[-1], "label": _CHG_LBL[key] + " " + val}


def attach_card_charts(M: dict[str, Any], S: dict[str, pd.Series]) -> None:
    """Give every non-stale card a chart payload (id mcc-<card id>) and collect them per section."""
    for sec in ("funding", "fedbs", "credit", "rates"):
        sec_charts = []
        for key in ("cards", "backstops", "ladder"):
            for c in M[sec].get(key, []):
                c["chart_id"] = None
                if c.get("stale") or c.get("state") == "na":
                    continue
                try:
                    spec = _card_chart_spec(c["id"], S, c)
                except Exception:  # noqa: BLE001
                    spec = None
                if not spec or not spec["traces"] or not spec["traces"][0]["x"]:
                    continue
                cid = "mcc-" + c["id"]
                chart = {"id": cid, "unit": spec["unit"], "traces": spec["traces"], "refs": spec.get("refs", []),
                         "default_range": "1Y", "mini": True}
                if spec.get("vlines"):
                    chart["vlines"] = spec["vlines"]
                c["chart_id"] = cid
                _add_change_window(c, chart)
                sec_charts.append(chart)
        M[sec]["card_charts"] = sec_charts
        have = {c["id"] for c in sec_charts}
        if "mcc-wshobl" in have:
            M[sec]["charts"] = [c for c in M[sec].get("charts", []) if c["id"] != "chart-rmp-level"]
        if "mcc-s5s30" in have:
            M[sec]["charts"] = [c for c in M[sec].get("charts", []) if c["id"] != "chart-rates-5s30s"]


# ---------------------------------------------------------------------------
# What changed: state changes and the largest weekly moves
# ---------------------------------------------------------------------------
def truncate(S: dict[str, pd.Series], cutoff: pd.Timestamp) -> dict[str, pd.Series]:
    """Series as they stood on cutoff (observations on or before that date)."""
    return {k: v[v.index <= cutoff] for k, v in S.items()}


def _cards_of(M: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for key in ("cards", "backstops", "ladder"):
        for sec in ("funding", "fedbs", "credit", "rates"):
            for c in M.get(sec, {}).get(key, []):
                out[c["id"]] = c
    return out


def state_changes(M_now: dict[str, Any], M_prev: dict[str, Any]) -> list[dict[str, Any]]:
    """Cards whose descriptive state differs between now and a week ago (both computed from
    the same FRED series, the earlier one truncated at its date)."""
    now_c, prev_c = _cards_of(M_now), _cards_of(M_prev)
    out = []
    for cid, c in now_c.items():
        p = prev_c.get(cid)
        if not p or c["state"] in ("context", "na") or p["state"] in ("context", "na"):
            continue
        if c["state"] != p["state"]:
            out.append({"id": cid, "title": c["title"].split(" · ")[0], "from": p["state"], "to": c["state"],
                        "value": c["value"], "worse": mon.STATE_RANK[c["state"]] > mon.STATE_RANK[p["state"]]})
    out.sort(key=lambda d: (not d["worse"], d["title"]))
    return out


MOVE_IDS = ("BAMLH0A0HYM2", "BAMLC0A0CM", "BAMLC0A4CBBB", "BAMLH0A1HYBB", "BAMLH0A2HYB", "BAMLH0A3HYC",
            "DGS10", "DGS30", "DFII10", "THREEFYTP10", "T10Y2Y", "NFCI", "STLFSI4", "SOFRVOL",
            "WSHOBL", "WRESBAL", "WTREGEN", "WLCFLPCL")


def weekly_moves(S: dict[str, pd.Series], now: datetime, top: int = 5, min_abs_z: float = 1.5) -> list[dict[str, Any]]:
    """Largest standardized one-week moves among a curated set of series.

    Daily series use a 5-observation change, weekly series a 1-observation change; the z-score
    compares that change with the series' own trailing 3-year distribution of the same change."""
    cands = []
    for sid in MOVE_IDS:
        spec = fc.BY_ID.get(sid)
        s = _get(S, sid)
        if spec is None or s is None:
            continue
        if mon.freshness_of(s, spec, now).stale:
            continue
        weekly = not spec.cadence.startswith("daily")
        n = 1 if weekly else 5
        z = mon.change_z(s * spec.scale, n, 3, min_obs=40)
        if z != z or abs(z) < min_abs_z:
            continue
        chg = mon.change_n(s, n, spec.scale)
        val = float(s.iloc[-1]) * spec.scale
        unit = spec.display
        cands.append({"id": sid, "label": spec.label_en, "z": z, "chg": chg, "value": val, "unit": unit,
                      "window": "1 week" if weekly else "5 trading days"})
    cands.sort(key=lambda d: -abs(d["z"]))
    for c in cands[:top]:
        digits = 2 if c["unit"] in ("pct", "$T", "index") else 0
        c["text"] = "{}: {} {} over {} to {} (z {:+.1f})".format(
            c["label"], "up" if c["chg"] > 0 else "down", _fmt(abs(c["chg"]), c["unit"], digits), c["window"],
            _fmt(c["value"], c["unit"], digits), c["z"])
    return cands[:top]
