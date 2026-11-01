"""Fragility chain: the overview synthesis that connects the dashboard layers.

Pressure usually moves in an order. Repo rates rise above IORB first (collateral and dealer
balance sheets), then banks bid up the fed funds rate as reserves become scarce, then credit
and rates markets reprice, and finally positioning amplifies price moves. The NY Fed described
this sequence for late 2025 (Perli, 2025-11-12) and it matches 2018-2019.

Five stages, each answering one question:
  0 Backdrop        is the cushion thin?            weekly to monthly, can only raise the level one notch
  1 Repo strain     are collateral and dealers tight?
  2 Reserve scarcity are banks bidding for reserves?  hard trigger: EFFR >= IORB, or SRF above floor and p95
  3 Transmission    has pressure reached credit, rates and the dollar?
  4 Amplification   will price moves be amplified?

A stage is confirmed when at least two of its indicators are on. The overall level is the
highest confirmed stage. Partial stages are reported but do not move the level.

The daily Funding Stress Index (FSI) is a separate composite of three funding prices,
each as a causal percentile of its own history since 2018. It sits beside stages 1 and 2.
All functions are pure and unit tested.
"""
from __future__ import annotations

import math
from typing import Any, Iterable

import numpy as np
import pandas as pd

NAN = float("nan")
RANK = {"na": -1, "normal": 0, "watch": 1, "elevated": 2, "stress": 3}
LEVELS = ("normal", "watch", "elevated", "stress")
CONFIRM_N = 2

# Indicator thresholds (operator references unless noted)
SOFR_ON_BP = 3.0            # SOFR - IORB filtered 5-observation median, the strategy line
EFFR_WATCH_BP = -1.0        # EFFR - IORB at or above -1 bp
EFFR_RISE_BP = 2.0          # or up 2 bp over 20 observations
EFFR_HARD_BP = 0.0          # EFFR at or above IORB: hard trigger for stage 2
CHANGE_Z_ON = 1.5           # 20-day change z of credit spreads and the dollar
PCTILE_ON = 90.0            # 3y percentile for T-bill - SOFR and financial CP - T-bill
RVOL_PCTILE_ON = 80.0       # 5y percentile of 10Y realized volatility
CORR_ON = 0.60              # average pairwise sector correlation, 2 weeks, and above the 1-month average
VOLUME_RATIO_ON = 1.5       # SPY volume over its prior 20-day average on a down day
LPI_THIN = 60.0
BASIS_THIN = 80.0

FSI_START = "2018-04-02"
FSI_BURN = 250              # one year of daily observations before a percentile is emitted
FSI_WINDOW = 1260           # five-year cap
FSI_BANDS = ((60.0, "normal"), (80.0, "watch"), (95.0, "elevated"), (math.inf, "stress"))


def _ok(x: Any) -> bool:
    return x is not None and isinstance(x, (int, float, np.floating)) and x == x


def _bp(x: Any, digits: int = 0) -> str:
    return ("{:+." + str(digits) + "f} bp").format(float(x)) if _ok(x) else "n/a"


# ---------------------------------------------------------------------------
# Generic pieces
# ---------------------------------------------------------------------------
def indicator(name: str, value: str, on: bool | None, rule: str = "") -> dict[str, Any]:
    """on=None means unavailable; it counts in neither numerator nor denominator."""
    return {"name": name, "value": value, "on": on, "rule": rule}


def stage_status(inds: list[dict[str, Any]], hard: bool = False, confirm_n: int = CONFIRM_N) -> dict[str, Any]:
    avail = [i for i in inds if i["on"] is not None]
    n_on = sum(1 for i in avail if i["on"])
    if not avail:
        status = "na"
    elif hard or n_on >= confirm_n:
        status = "confirmed"
    elif n_on == 1:
        status = "partial"
    else:
        status = "quiet"
    return {"status": status, "n_on": n_on, "n_avail": len(avail), "hard": bool(hard)}


def breadth_state(states: Iterable[str]) -> str:
    """Layer state from breadth instead of the single worst series. One indicator at watch or
    worse caps the layer at watch, two cap it at elevated, three or more allow the worst state."""
    st = [s for s in states if s in RANK and RANK[s] >= 0]
    if not st:
        return "na"
    on = [s for s in st if RANK[s] >= 1]
    worst = max(st, key=lambda s: RANK[s])
    if not on:
        return "normal"
    cap = {1: "watch", 2: "elevated"}.get(len(on), "stress")
    return worst if RANK[worst] <= RANK[cap] else cap


# ---------------------------------------------------------------------------
# Funding Stress Index
# ---------------------------------------------------------------------------
def anchor_rate(iorb: pd.Series | None, ioer: pd.Series | None) -> pd.Series | None:
    """IORB since 2021-07-29, IOER before it (the two are the same administered rate)."""
    if iorb is None and ioer is None:
        return None
    if ioer is None or ioer.empty:
        return iorb.sort_index()
    if iorb is None or iorb.empty:
        return ioer.sort_index()
    io = iorb.sort_index()
    early = ioer[ioer.index < io.index.min()]
    return pd.concat([early, io]).sort_index()


def _spread_bp(a: pd.Series, b: pd.Series) -> pd.Series:
    a = a.sort_index()
    b = b.sort_index().reindex(a.index.union(b.index)).ffill().reindex(a.index)
    return ((a - b) * 100.0).dropna()


def causal_pctile(s: pd.Series, window: int = FSI_WINDOW, burn: int = FSI_BURN) -> pd.Series:
    """Mid-rank percentile of each observation within its trailing window (no look-ahead).
    Mid-rank keeps long flat stretches, such as EFFR - IORB at -7 bp in 2022-2025, near 50
    instead of pinning them at the top."""
    v = s.to_numpy(dtype=float)
    out = np.full(len(v), np.nan)
    for i in range(len(v)):
        if i + 1 < burn:
            continue
        w = v[max(0, i - window + 1):i + 1]
        out[i] = ((w < v[i]).sum() + 0.5 * (w == v[i]).sum()) / len(w) * 100.0
    return pd.Series(out, index=s.index)


def fsi_state(v: float) -> str:
    if not _ok(v):
        return "na"
    for upper, st in FSI_BANDS:
        if v < upper:
            return st
    return "stress"


def funding_stress_index(sofr: pd.Series | None, effr: pd.Series | None, sofr99: pd.Series | None,
                         anchor: pd.Series | None) -> dict[str, Any]:
    """Daily FSI = mean of available component percentiles (at least 2 of 3).
    Components, in basis points:
      repo     SOFR - IORB, 5-observation median
      interbank EFFR - IORB
      tail     SOFR 99th percentile - SOFR median, 5-observation median
    """
    comps: dict[str, pd.Series] = {}
    raw: dict[str, pd.Series] = {}
    if sofr is not None and anchor is not None:
        r = _spread_bp(sofr, anchor).rolling(5).median().dropna()
        raw["repo"] = r
    if effr is not None and anchor is not None:
        raw["interbank"] = _spread_bp(effr, anchor)
    if sofr99 is not None and sofr is not None:
        raw["tail"] = _spread_bp(sofr99, sofr).rolling(5).median().dropna()
    for k, r in raw.items():
        r = r[r.index >= pd.Timestamp(FSI_START)]
        if len(r) >= FSI_BURN:
            comps[k] = causal_pctile(r)
    if len(comps) < 2:
        return {"available": False, "components": {}, "raw": raw}
    df = pd.concat(comps, axis=1, sort=True).sort_index()
    df = df.ffill(limit=3)                      # holiday mismatch between sources only
    fsi = df.mean(axis=1)[df.notna().sum(axis=1) >= 2].dropna()
    if fsi.empty:
        return {"available": False, "components": {}, "raw": raw}
    last = fsi.index[-1]
    comp_last = {k: (float(df[k].loc[last]) if df[k].loc[last] == df[k].loc[last] else NAN) for k in df.columns}
    raw_last = {k: float(v[v.index <= last].iloc[-1]) if not v[v.index <= last].empty else NAN for k, v in raw.items()}
    return {"available": True, "series": fsi, "components": df, "raw": raw,
            "value": float(fsi.iloc[-1]), "asof": last.strftime("%Y-%m-%d"), "state": fsi_state(float(fsi.iloc[-1])),
            "chg20": float(fsi.iloc[-1] - fsi.iloc[-21]) if len(fsi) > 21 else NAN,
            "comp_last": comp_last, "raw_last": raw_last}


# ---------------------------------------------------------------------------
# Transmission inputs from FRED series
# ---------------------------------------------------------------------------
def change_z(s: pd.Series | None, n: int = 20, years: float = 3.0, min_obs: int = 120) -> float:
    """z of the latest n-observation change against all n-observation changes in the last `years`."""
    if s is None:
        return NAN
    s = s.dropna()
    if len(s) < n + min_obs:
        return NAN
    ch = s.diff(n).dropna()
    ch = ch[ch.index >= ch.index[-1] - pd.Timedelta(days=int(365.25 * years))]
    sd = float(ch.std())
    return float(ch.iloc[-1] / sd) if sd > 0 else NAN


def level_pct(s: pd.Series | None, years: float = 3.0) -> float:
    if s is None:
        return NAN
    s = s.dropna()
    s = s[s.index >= s.index[-1] - pd.Timedelta(days=int(365.25 * years))] if len(s) else s
    if len(s) < 60:
        return NAN
    return float((s <= s.iloc[-1]).mean() * 100.0)


def transmission_inputs(S: dict[str, pd.Series], now: Any = None, max_age_days: int = 10) -> dict[str, float]:
    """Readings for stages 1 and 3. A series whose last observation is more than
    `max_age_days` old is treated as unavailable, so a stale level never reads as current."""
    ref = pd.Timestamp(now).tz_localize(None).normalize() if now is not None else None

    def g(k: str) -> pd.Series | None:
        v = S.get(k)
        if v is None:
            return None
        v = v.dropna()
        if v.empty:
            return None
        if ref is not None and (ref - pd.Timestamp(v.index[-1])).days > max_age_days:
            return None
        return v
    out: dict[str, float] = {}
    hy, ig, ccc, bb = g("BAMLH0A0HYM2"), g("BAMLC0A0CM"), g("BAMLH0A3HYC"), g("BAMLH0A1HYBB")
    if hy is not None:
        out["hy_bp"], out["hy_z"] = float(hy.dropna().iloc[-1]) * 100.0, change_z(hy)
    if hy is not None and ig is not None:
        d = (hy - ig.reindex(hy.index)).dropna() * 100.0
        out["hyig_bp"], out["hyig_z"] = float(d.iloc[-1]), change_z(d)
    if ccc is not None and bb is not None:
        d = (ccc - bb.reindex(ccc.index)).dropna()
        out["cccbb_pp"], out["cccbb_z"] = float(d.iloc[-1]), change_z(d)
    t10 = g("DGS10")
    if t10 is not None and len(t10.dropna()) > 300:
        rv = (t10.dropna().diff() * 100.0).rolling(20).std().dropna() * math.sqrt(252)
        out["rvol_bp"], out["rvol_pct"] = float(rv.iloc[-1]), level_pct(rv, 5)
    usd = g("DTWEXBGS")
    if usd is not None:
        out["usd_z"] = change_z(usd)
        out["usd_chg20"] = float(usd.dropna().diff(20).iloc[-1]) if len(usd.dropna()) > 21 else NAN
    cp, tb = g("DCPF3M"), g("DTB3")
    if cp is not None and tb is not None:
        d = (cp - tb.reindex(cp.index)).dropna() * 100.0
        out["cp_bp"], out["cp_pct"] = float(d.iloc[-1]), level_pct(d, 3)
    so = g("SOFR")
    if tb is not None and so is not None:
        d = (tb - so.reindex(tb.index)).dropna() * 100.0
        out["tbill_bp"], out["tbill_pct"] = float(d.iloc[-1]), level_pct(d, 3)
    return out


# ---------------------------------------------------------------------------
# The chain
# ---------------------------------------------------------------------------
def _on(v: Any, thr: float) -> bool | None:
    return None if not _ok(v) else bool(v >= thr)


def _st_on(state: Any) -> bool | None:
    if state in (None, "na", "unavailable", "context", ""):
        return None
    return state not in ("normal", "quiet", "off")


STAGE_META = (
    ("backdrop", "0", "Backdrop", "背景", "Is the cushion thin?", "缓冲是否变薄"),
    ("repo", "1", "Repo strain", "回购压力", "Are collateral and dealer balance sheets tight?", "抵押品和交易商资产负债表是否紧张"),
    ("reserves", "2", "Reserve scarcity", "准备金稀缺", "Are banks bidding for reserves?", "银行是否开始抢准备金"),
    ("transmission", "3", "Transmission", "风险传导", "Has pressure reached credit, rates and the dollar?", "压力是否传到信用、利率和美元"),
    ("amplification", "4", "Amplification", "价格放大", "Will price moves be amplified?", "下跌是否会被放大"),
)
NEXT_WATCH = {
    "repo": "SOFR - IORB 5-day median at +3 bp or more together with tri-party repo (TGCR or BGCR) at +3 bp",
    "reserves": "EFFR - IORB at -1 bp or higher, a 2 bp rise in 20 days, or SRF use above $1B",
    "transmission": "two of HY OAS, HY - IG, CCC - BB or the dollar with a 20-day change z of 1.5 or more",
    "amplification": "negative dealer gamma together with VIX backwardation or a high-volume down day",
}


def build_chain(x: dict[str, Any]) -> dict[str, Any]:
    """x is a flat dict of current readings (see generate_dashboard). Missing keys are unavailable."""
    g = x.get
    stages: dict[str, dict[str, Any]] = {}

    b = [indicator("LPI (weekly)", "{:.0f}".format(g("lpi")) if _ok(g("lpi")) and not g("lpi_stale") else "n/a",
                   None if (not _ok(g("lpi")) or g("lpi_stale")) else g("lpi") >= LPI_THIN, "at or above 60"),
         indicator("Basis-trade crowding", "{:.0f}".format(g("basis")) if _ok(g("basis")) else "n/a",
                   _on(g("basis"), BASIS_THIN), "proxy at or above 80"),
         indicator("Reserves vs trigger", g("reserves_txt") or "n/a", _st_on(g("reserves_state")), "reserve leg active or elevated (level and 4-week drain)"),
         indicator("Reserves / GDP", g("resgdp_txt") or "n/a", _st_on(g("resgdp_state")), "below its 3y 20th percentile for two weeks")]
    stages["backdrop"] = {"inds": b, **stage_status(b)}

    r = [indicator("SOFR - IORB, 5d median", _bp(g("sofr_med_bp"), 1), _on(g("sofr_med_bp"), SOFR_ON_BP), "+3 bp or more, calendar days skipped"),
         indicator("TGCR - IORB, 5d median", _bp(g("tgcr_bp"), 1), _on(g("tgcr_bp"), SOFR_ON_BP), "+3 bp or more"),
         indicator("BGCR - IORB, 5d median", _bp(g("bgcr_bp"), 1), _on(g("bgcr_bp"), SOFR_ON_BP), "+3 bp or more"),
         indicator("SOFR 99th - median", _bp(g("tail_bp"), 1), _st_on(g("tail_state")), "2y percentile and change rule"),
         indicator("3m T-bill - SOFR", _bp(g("tbill_bp")) + (" (p{:.0f})".format(g("tbill_pct")) if _ok(g("tbill_pct")) else ""),
                   _on(g("tbill_pct"), PCTILE_ON), "3y percentile 90 or more")]
    stages["repo"] = {"inds": r, **stage_status(r)}

    effr, c20 = g("effr_bp"), g("effr_chg20")
    effr_on = None if not _ok(effr) else bool(effr >= EFFR_WATCH_BP or (_ok(c20) and c20 >= EFFR_RISE_BP))
    hard_effr = _ok(effr) and effr >= EFFR_HARD_BP
    hard_srf = g("srf_state") == "elevated"
    s2 = [indicator("EFFR - IORB", _bp(effr) + (" (20d {})".format(_bp(c20)) if _ok(c20) else ""), effr_on,
                    "-1 bp or higher, or +2 bp in 20 days; at or above 0 is a hard trigger"),
          indicator("Standing repo facility", "${:.1f}B".format(g("srf_b")) if _ok(g("srf_b")) else "n/a",
                    None if g("srf_state") in (None, "unavailable", "na") else g("srf_state") in ("in_use", "elevated"),
                    "above $1B; above $1B and its 3y p95 is a hard trigger"),
          indicator("Discount window", "${:.1f}B".format(g("dw_b")) if _ok(g("dw_b")) else "n/a",
                    None if g("dw_state") in (None, "unavailable", "na") else g("dw_state") in ("in_use", "elevated"),
                    "above its own 3y p95 and rising")]
    stages["reserves"] = {"inds": s2, **stage_status(s2, hard=bool(hard_effr or hard_srf))}
    stages["reserves"]["hard_reason"] = ("EFFR at or above IORB" if hard_effr else ("SRF above $1B and its p95" if hard_srf else ""))

    t = [indicator("HY OAS, 20d change z", ("{:.0f} bp, z {:+.1f}".format(g("hy_bp"), g("hy_z")) if _ok(g("hy_z")) else "n/a"), _on(g("hy_z"), CHANGE_Z_ON), "z 1.5 or more"),
         indicator("HY - IG, 20d change z", ("{:.0f} bp, z {:+.1f}".format(g("hyig_bp"), g("hyig_z")) if _ok(g("hyig_z")) else "n/a"), _on(g("hyig_z"), CHANGE_Z_ON), "z 1.5 or more"),
         indicator("CCC - BB, 20d change z", ("{:.2f} pp, z {:+.1f}".format(g("cccbb_pp"), g("cccbb_z")) if _ok(g("cccbb_z")) else "n/a"), _on(g("cccbb_z"), CHANGE_Z_ON), "z 1.5 or more"),
         indicator("10Y realized vol", ("{:.0f} bp (p{:.0f})".format(g("rvol_bp"), g("rvol_pct")) if _ok(g("rvol_pct")) else "n/a"), _on(g("rvol_pct"), RVOL_PCTILE_ON), "5y percentile 80 or more"),
         indicator("Broad dollar, 20d change z", ("z {:+.1f}".format(g("usd_z")) if _ok(g("usd_z")) else "n/a"), _on(g("usd_z"), CHANGE_Z_ON), "z 1.5 or more"),
         indicator("Financial CP - T-bill", (_bp(g("cp_bp")) + " (p{:.0f})".format(g("cp_pct")) if _ok(g("cp_pct")) else "n/a"), _on(g("cp_pct"), PCTILE_ON), "3y percentile 90 or more")]
    stages["transmission"] = {"inds": t, **stage_status(t)}

    gamma = g("gamma")
    vs = g("vix_state")
    c2, c1 = g("corr2w"), g("corr1m")
    corr_on = None if not (_ok(c2) and _ok(c1)) else bool(c2 >= CORR_ON and c2 >= c1)
    vr, r1 = g("spy_vol_ratio"), g("spy_ret1")
    vol_on = None if not (_ok(vr) and _ok(r1)) else bool(vr >= VOLUME_RATIO_ON and r1 < 0)
    a = [indicator("Dealer gamma (SPY)", {"negative": "negative", "positive": "positive"}.get(gamma, "n/a"),
                   None if gamma not in ("negative", "positive") else gamma == "negative", "negative"),
         indicator("VIX term structure", vs if vs in ("contango", "backwardation") else "n/a",
                   None if vs not in ("contango", "backwardation") else vs == "backwardation", "backwardation"),
         indicator("Sector correlation", ("{:.2f} (1M {:.2f})".format(c2, c1) if corr_on is not None else "n/a"), corr_on, "2w average 0.60 or more and above 1M"),
         indicator("SPY down-day volume", ("{:.2f}x on {:+.2f}%".format(vr, r1) if vol_on is not None else "n/a"), vol_on, "1.5x the prior 20-day average on a down day")]
    stages["amplification"] = {"inds": a, **stage_status(a)}

    for key, num, en, zh, q_en, q_zh in STAGE_META:
        stages[key].update({"key": key, "num": num, "title": en, "title_zh": zh, "q": q_en, "q_zh": q_zh})

    level, reasons = chain_level(stages)
    return {"stages": [stages[k[0]] for k in STAGE_META], "by_key": stages, "level": level, "reasons": reasons,
            "headline": chain_headline(stages, level), "next_watch": next_watch(stages)}


def chain_level(stages: dict[str, dict[str, Any]]) -> tuple[str, list[str]]:
    conf = {k for k, v in stages.items() if v["status"] == "confirmed"}
    reasons: list[str] = []
    rank = 0
    if "repo" in conf:
        rank = max(rank, 1)
        reasons.append("stage 1 confirmed")
    for k, n in (("reserves", 2), ("transmission", 3), ("amplification", 4)):
        if k in conf:
            rank = max(rank, 2)
            reasons.append("stage {} confirmed".format(n) + (" (hard trigger: {})".format(stages[k].get("hard_reason")) if stages[k].get("hard") and stages[k].get("hard_reason") else ""))
    if len(conf & {"reserves", "transmission", "amplification"}) >= 2:
        rank = 3
        reasons.append("two or more of stages 2 to 4 confirmed")
    if "backdrop" in conf and rank < 2:
        rank += 1
        reasons.append("thin backdrop raises the level one notch")
    if all(v["status"] == "na" for v in stages.values()):
        return "na", ["no stage could be evaluated"]
    return LEVELS[rank], reasons


def _drivers(st: dict[str, Any], only_on: bool = True, limit: int = 3) -> str:
    items = [i for i in st["inds"] if (i["on"] if only_on else i["on"] is not None)]
    return ", ".join("{} {}".format(i["name"], i["value"]) for i in items[:limit])


def chain_headline(stages: dict[str, dict[str, Any]], level: str) -> list[str]:
    """One plain sentence per stage, in chain order, for the overview banner."""
    words = {"confirmed": "confirmed", "partial": "partial", "quiet": "quiet", "na": "unavailable"}
    out = []
    for key, num, en, *_ in STAGE_META:
        st = stages[key]
        s = "Stage {} {}: {} ({} of {} on)".format(num, en.lower(), words[st["status"]], st["n_on"], st["n_avail"])
        d = _drivers(st)
        if d:
            s += ". On: " + d
        elif st["status"] == "quiet":
            off = [i for i in st["inds"] if i["on"] is False][:2]
            if off:
                s += ". " + ", ".join("{} {}".format(i["name"], i["value"]) for i in off)
        out.append(s + ".")
    return out


def next_watch(stages: dict[str, dict[str, Any]]) -> str:
    for key in ("repo", "reserves", "transmission", "amplification"):
        if stages[key]["status"] != "confirmed":
            return "Next stage to watch: stage {} {}. Trigger: {}.".format(
                stages[key]["num"], stages[key]["title"].lower(), NEXT_WATCH[key])
    return "All stages are confirmed."


def stance(level: str) -> tuple[str, str, str]:
    """(english, chinese tag, color). Sizing and hedging language only, never directional."""
    return {
        "normal": ("No stage confirmed: funding, transmission and amplification are quiet.", "无确认阶段", "#10b981"),
        "watch": ("Early-stage pressure: keep hedges staged and watch the next stage trigger.", "早期压力-准备对冲", "#f59e0b"),
        "elevated": ("Elevated fragility: size moderately and keep hedges on.", "脆弱度偏高-控制仓位", "#f97316"),
        "stress": ("Pressure has passed through several stages: defensive sizing.", "多阶段确认-防守", "#ef4444"),
        "na": ("Chain unavailable this run: no stance is issued.", "数据不足", "#64748b"),
    }[level]


def contradiction_note(level: str, lpi: float, lpi_stale: bool, fsi: dict[str, Any]) -> str:
    """Explicit statement when the weekly backdrop and the daily chain disagree."""
    notes = []
    if _ok(lpi) and not lpi_stale and level in RANK and RANK[level] >= 0:
        lpi_rank = 0 if lpi < 40 else (1 if lpi < 60 else (2 if lpi < 80 else 3))
        if abs(lpi_rank - RANK[level]) >= 2:
            notes.append("The weekly LPI ({:.0f}) and the daily chain ({}) disagree by two levels or more; "
                         "the chain uses daily prices and is more current, the LPI describes the slower backdrop.".format(lpi, level))
    if fsi.get("available") and RANK.get(fsi.get("state", "na"), -1) >= 2 and RANK.get(level, -1) <= 1:
        notes.append("The funding stress index is {} ({:.0f}) while the chain reads {}: one funding price is far from its history "
                     "but fewer than two stage indicators are on.".format(fsi["state"], fsi["value"], level))
    return " ".join(notes)


# ---------------------------------------------------------------------------
# Stage-change history (data/chain-state.json)
# ---------------------------------------------------------------------------
HISTORY_KEEP = 200


def snapshot(chain: dict[str, Any], fsi: dict[str, Any], when: str) -> dict[str, Any]:
    """Compact record of one run: overall level, each stage status and the FSI reading."""
    return {"when": when, "level": chain["level"],
            "stages": {st["key"]: st["status"] for st in chain["stages"]},
            "fsi": round(float(fsi["value"]), 1) if fsi.get("available") and not fsi.get("stale") else None,
            "fsi_state": fsi.get("state", "na") if fsi.get("available") else "na"}


def update_history(hist: dict[str, Any] | None, snap: dict[str, Any], keep: int = HISTORY_KEEP) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Compare this run with the last stored run and append an event per change.
    Unavailable readings ('na') never create an event, so a data outage does not look like relief."""
    hist = dict(hist or {})
    events = list(hist.get("events") or [])
    prev = hist.get("current") if isinstance(hist.get("current"), dict) else None
    new: list[dict[str, Any]] = []
    if prev:
        if prev.get("level") != snap["level"] and "na" not in (prev.get("level"), snap["level"]):
            new.append({"when": snap["when"], "kind": "level", "key": "level", "from": prev.get("level"), "to": snap["level"],
                        "worse": RANK.get(snap["level"], -1) > RANK.get(prev.get("level"), -1)})
        order = {"na": -1, "quiet": 0, "partial": 1, "confirmed": 2}
        for k, v in snap["stages"].items():
            p = (prev.get("stages") or {}).get(k)
            if p and p != v and "na" not in (p, v):
                new.append({"when": snap["when"], "kind": "stage", "key": k, "from": p, "to": v,
                            "worse": order.get(v, -1) > order.get(p, -1)})
        if prev.get("fsi_state") != snap["fsi_state"] and "na" not in (prev.get("fsi_state"), snap["fsi_state"]):
            new.append({"when": snap["when"], "kind": "fsi", "key": "fsi", "from": prev.get("fsi_state"), "to": snap["fsi_state"],
                        "worse": RANK.get(snap["fsi_state"], -1) > RANK.get(prev.get("fsi_state"), -1)})
    events = (events + new)[-keep:]
    stored = {**snap, "stages": dict(snap["stages"])}
    if prev:   # carry the last known value through an outage so the next real reading is compared with it
        for k, v in stored["stages"].items():
            if v == "na" and (prev.get("stages") or {}).get(k) not in (None, "na"):
                stored["stages"][k] = prev["stages"][k]
        for k in ("level", "fsi_state"):
            if stored.get(k) == "na" and prev.get(k) not in (None, "na"):
                stored[k] = prev[k]
    hist.update({"v": 1, "current": stored, "events": events})
    if not prev:
        hist.setdefault("started", snap["when"])
    return hist, new


def event_text(e: dict[str, Any]) -> str:
    names = {k[0]: "Stage {} {}".format(k[1], k[2].lower()) for k in STAGE_META}
    names.update({"level": "Chain level", "fsi": "Funding stress index"})
    return "{}: {} moved from {} to {}.".format(e.get("when", "")[:16].replace("T", " "), names.get(e.get("key"), e.get("key")),
                                                e.get("from"), e.get("to"))
