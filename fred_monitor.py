"""FRED fetch layer, transforms and descriptive state rules for the v2 modules.

Pure functions only (no HTML). Rendering lives in fred_render.py. Nothing here feeds the
LPI composite or the de-leveraging tally (decision D6): states are descriptive labels for
each indicator against its own history.
"""
from __future__ import annotations

import concurrent.futures as cf
from datetime import datetime
from typing import Any, Iterable

import numpy as np
import pandas as pd

import fast_metrics as fm
import fred_catalog as fc
import health

NAN = float("nan")

# Global five-level status vocabulary shared by every module (see plan section 6.2).
STATES = ("normal", "watch", "elevated", "stress", "na", "context")
STATE_LABEL = {"normal": "Normal 正常", "watch": "Watch 观察", "elevated": "Elevated 偏高",
               "stress": "Stress 压力", "na": "Unavailable 不可用", "context": "Context 参考"}
STATE_RANK = {"na": -1, "context": -1, "normal": 0, "watch": 1, "elevated": 2, "stress": 3}


def worst(states: Iterable[str]) -> str:
    known = [s for s in states if s in STATE_RANK and STATE_RANK[s] >= 0]
    return max(known, key=lambda s: STATE_RANK[s]) if known else "na"


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------
def fetch_catalog(specs: Iterable[fc.FredSpec] | None = None, *, max_workers: int = 4,
                  now: datetime | None = None) -> tuple[dict[str, pd.Series], dict[str, str]]:
    """Fetch every spec concurrently. One failure never blocks the others.

    Returns (series by id, errors by id). series.attrs['source'] is 'FRED live' or
    'FRED cached official CSV'. Each series is also registered in the health registry.
    """
    current = now or fm.utc_now()
    every = list(specs if specs is not None else fc.CATALOG)
    chosen = [s for s in every if s.source == "fred"]
    out: dict[str, pd.Series] = {}
    errors: dict[str, str] = {}
    ny = [s for s in every if s.source == "nyfed"]
    if ny:
        got, errs = fetch_nyfed(ny, now=current)
        out.update(got)
        errors.update(errs)

    def one(spec: fc.FredSpec):
        try:
            return spec, fm.fetch_fred_series(spec.id, start=spec.start, trim=True), None
        except Exception as exc:  # noqa: BLE001
            return spec, None, str(exc)[:200]

    with cf.ThreadPoolExecutor(max_workers=max_workers) as pool:
        for spec, s, err in pool.map(one, chosen):
            if s is None or s.empty:
                errors[spec.id] = err or "empty"
                health.register("FRED " + spec.id, "FRED fredgraph.csv", None, spec.cadence, "failed",
                                current.strftime("%Y-%m-%d %H:%M UTC"), err or "empty")
                continue
            out[spec.id] = s
            f = freshness_of(s, spec, current)
            if f.stale:
                status = "stale"
            elif s.attrs.get("source") == "FRED live":
                status = "current"
            else:
                status = "cached"
            health.register("FRED " + spec.id, "FRED fredgraph.csv", f.observation_date, spec.cadence,
                            status, current.strftime("%Y-%m-%d %H:%M UTC"), s.attrs.get("source", ""))
    return out, errors


NYFED_SECURED_URL = "https://markets.newyorkfed.org/api/rates/secured/{rate}/search.json?startDate={start}&endDate={end}"
NYFED_CACHE_FMT = "NYFED_{id}.csv"


def parse_nyfed_secured(payload: dict[str, Any]) -> tuple[pd.Series, pd.Series]:
    """(rate in percent, volume in $ billions) from a NY Fed secured reference-rate payload."""
    rows = payload.get("refRates") or []
    rate, vol = {}, {}
    for r in rows:
        d = pd.to_datetime(r.get("effectiveDate"), errors="coerce")
        if d is pd.NaT or d != d:
            continue
        try:
            rate[d] = float(r["percentRate"])
        except (KeyError, TypeError, ValueError):
            pass
        try:
            vol[d] = float(r["volumeInBillions"])
        except (KeyError, TypeError, ValueError):
            pass
    return pd.Series(rate, dtype=float).sort_index(), pd.Series(vol, dtype=float).sort_index()


def _series_csv(s: pd.Series, name: str) -> str:
    return "observation_date," + name + "\n" + "".join("{},{}\n".format(d.strftime("%Y-%m-%d"), repr(float(v)) if v != int(v) else int(v))
                                                       for d, v in s.dropna().items())


def fetch_nyfed(specs: Iterable[fc.FredSpec], *, now: datetime | None = None) -> tuple[dict[str, pd.Series], dict[str, str]]:
    """BGCR rate and volume from the NY Fed Markets API, with a merge-only CSV cache in
    data/fred-cache (NYFED_<id>.csv). The cache never shrinks and is never forward-filled."""
    import os
    current = now or fm.utc_now()
    specs = list(specs)
    out: dict[str, pd.Series] = {}
    errors: dict[str, str] = {}
    live: dict[str, pd.Series] = {}
    err = ""
    try:
        if os.environ.get("MFD_FORCE_FRED_CACHE") == "1":
            raise RuntimeError("MFD_FORCE_FRED_CACHE=1: live NY Fed request skipped (degraded-source test)")
        start = min(s.start for s in specs)
        url = NYFED_SECURED_URL.format(rate="bgcr", start=start, end=current.strftime("%Y-%m-%d"))
        rate, vol = parse_nyfed_secured(fm._get(url, timeout=40, retries=2).json())
        if rate.empty:
            raise ValueError("NY Fed BGCR returned no observations")
        live = {"BGCR": rate, "BGCRVOL": vol}
    except Exception as exc:  # noqa: BLE001
        err = str(exc)[:200]
    for spec in specs:
        cache = fm.FRED_CACHE_DIR / NYFED_CACHE_FMT.format(id=spec.id)
        s = live.get(spec.id)
        try:
            if s is not None and not s.empty:
                cache.parent.mkdir(parents=True, exist_ok=True)
                old = cache.read_text(encoding="utf-8") if cache.exists() else ""
                cache.write_text(fm.merge_fred_csv(old, _series_csv(s, spec.id)), encoding="utf-8")
                s = fm._parse_fred_csv(cache.read_text(encoding="utf-8"), spec.id)
                s = s[s.index >= pd.Timestamp(spec.start)]
                s.attrs["source"] = "NY Fed live"
            elif cache.exists():
                s = fm._parse_fred_csv(cache.read_text(encoding="utf-8"), spec.id)
                s = s[s.index >= pd.Timestamp(spec.start)]
                s.attrs["source"] = "NY Fed cached official CSV"
            else:
                raise RuntimeError(err or "no data")
        except Exception as exc:  # noqa: BLE001
            errors[spec.id] = str(exc)[:200]
            health.register("NY Fed " + spec.id, "NY Fed reference rates API", None, spec.cadence, "failed",
                            current.strftime("%Y-%m-%d %H:%M UTC"), errors[spec.id])
            continue
        out[spec.id] = s
        f = freshness_of(s, spec, current)
        status = "stale" if f.stale else ("current" if s.attrs["source"] == "NY Fed live" else "cached")
        health.register("NY Fed " + spec.id, "NY Fed reference rates API", f.observation_date, spec.cadence,
                        status, current.strftime("%Y-%m-%d %H:%M UTC"), s.attrs["source"])
    return out, errors


def freshness_of(series: pd.Series | None, spec: fc.FredSpec, now: datetime | None = None) -> fm.Freshness:
    last = series.dropna().index[-1] if series is not None and len(series.dropna()) else None
    return fm.freshness(last, spec.cadence, spec.max_age_days, now)


# ---------------------------------------------------------------------------
# Transforms
# ---------------------------------------------------------------------------
def spread(a: pd.Series, b: pd.Series, scale: float = 1.0) -> pd.Series:
    """(a - b) * scale on the dates both series share."""
    df = pd.concat([a, b], axis=1, join="inner").dropna()
    if df.empty:
        return pd.Series(dtype=float)
    return ((df.iloc[:, 0] - df.iloc[:, 1]) * scale).rename("spread")


def change_n(series: pd.Series, n: int, scale: float = 1.0) -> float:
    """Change over the last n observations, in display units. NaN if too short."""
    s = series.dropna()
    if len(s) <= n:
        return NAN
    return float((s.iloc[-1] - s.iloc[-1 - n]) * scale)


def change_z(series: pd.Series, n: int, window_years: float = 3.0, min_obs: int = 60) -> float:
    """z-score of the latest n-observation change against its own distribution over the
    trailing window (overlapping changes). NaN when fewer than min_obs changes exist."""
    s = series.dropna()
    if len(s) <= n:
        return NAN
    cutoff = s.index[-1] - pd.DateOffset(years=int(window_years)) if window_years else s.index[0]
    ch = s.diff(n).dropna()
    ch = ch[ch.index >= cutoff]
    if len(ch) < min_obs:
        return NAN
    sd = float(ch.std(ddof=1))
    if sd == 0 or sd != sd:
        return NAN
    return float((ch.iloc[-1] - ch.mean()) / sd)


def level_pctile(series: pd.Series, years: float | None = None) -> tuple[float, float]:
    """Percentile rank (0-100) of the latest value within the trailing window, and the
    window length actually used in years (limited by available history)."""
    s = series.dropna()
    if len(s) < 2:
        return NAN, 0.0
    start = s.index[0] if years is None else max(s.index[0], s.index[-1] - pd.DateOffset(years=int(years)))
    w = s[s.index >= start]
    if len(w) < 2:
        return NAN, 0.0
    pct = float((w <= w.iloc[-1]).mean() * 100.0)
    span = (w.index[-1] - w.index[0]).days / 365.25
    return pct, round(span, 1)


def weekly_delta(series: pd.Series) -> pd.Series:
    return series.dropna().diff().dropna()


def trailing_p95(series: pd.Series, weeks: int = 156) -> float:
    s = series.dropna()
    if s.empty:
        return NAN
    w = s[s.index >= s.index[-1] - pd.Timedelta(weeks=weeks)]
    return float(w.quantile(0.95))


def spark(series: pd.Series, n: int = 13, scale: float = 1.0) -> list[float]:
    s = series.dropna().tail(n)
    return [round(float(v) * scale, 4) for v in s.values]


def sample_series(series: pd.Series, scale: float = 1.0, max_points: int = 400, since: str | None = None,
                  digits: int = 4) -> dict[str, list]:
    """Chart payload: ISO dates and rounded display values, thinned to max_points."""
    s = series.dropna()
    if since:
        s = s[s.index >= pd.Timestamp(since)]
    if len(s) > max_points:
        idx = np.unique(np.linspace(0, len(s) - 1, max_points).round().astype(int))
        s = s.iloc[idx]
    return {"x": [d.strftime("%Y-%m-%d") for d in s.index],
            "y": [round(float(v) * scale, digits) for v in s.values]}


# ---------------------------------------------------------------------------
# State rules (descriptive; see plan sections 5.2 to 5.5)
# ---------------------------------------------------------------------------
def pct_state(level_pct: float, chg_z: float, hist_years: float, *, min_years: float = 1.0) -> str:
    """Percentile + change-z state used for spreads and rates.

    stress   : level percentile >= 95 and change z >= 2
    elevated : level percentile >= 90 and change z >= 1
    watch    : level percentile >= 80 or change z >= 2
    normal   : otherwise; na when history is shorter than min_years or inputs are NaN.
    """
    if hist_years < min_years or level_pct != level_pct:
        return "na"
    z = chg_z if chg_z == chg_z else 0.0
    if level_pct >= 95 and z >= 2:
        return "stress"
    if level_pct >= 90 and z >= 1:
        return "elevated"
    if level_pct >= 80 or z >= 2:
        return "watch"
    return "normal"


credit_state = pct_state


# Secured vs unsecured funding diagnostic (descriptive, D6).
SECURED_ON_BP = 3.0        # SOFR - IORB 5-observation median at or above the +3 bp strategy line
UNSEC_LEVEL_WATCH_BP = -1.0
UNSEC_LEVEL_ON_BP = 0.0    # EFFR at or above IORB: banks pay more for reserves than the Fed pays on them
UNSEC_RISE_BP = 2.0        # EFFR - IORB up 2 bp or more over 20 observations


def unsecured_state(level_bp: float, chg20_bp: float) -> str:
    """EFFR - IORB state. Uses the IORB anchor and the 20-observation change instead of a
    percentile: the spread stepped from about -7 bp to about -2 bp in Sep-Nov 2025, so a
    3-year percentile would sit near 100 for a year without saying anything new."""
    if level_bp != level_bp:
        return "na"
    if level_bp >= UNSEC_LEVEL_ON_BP:
        return "elevated"
    if level_bp >= UNSEC_LEVEL_WATCH_BP or (chg20_bp == chg20_bp and chg20_bp >= UNSEC_RISE_BP):
        return "watch"
    return "normal"


LOCUS = {
    "broad": ("elevated", "Broad: repo and interbank both tight", "全面偏紧:回购与银行间同时承压",
              "Secured repo trades above IORB and EFFR is at or rising toward IORB. This is the pattern of scarce reserves."),
    "secured": ("watch", "Secured repo pressure; interbank calm", "担保回购承压,银行间平稳",
                "Repo rates trade above IORB while EFFR stays below IORB and is not rising. The pressure sits in collateral and dealer balance sheets (Treasury settlement, TGA build), not in bank reserves."),
    "unsecured": ("watch", "Interbank pressure without repo pressure", "银行间承压,回购未承压",
                  "EFFR is at or rising toward IORB while repo is calm. This is unusual; check bank-specific funding and FHLB activity."),
    "calm": ("normal", "Calm: neither market above its anchor", "平稳:两个市场都未高于锚",
             "Repo is below the +3 bp line and EFFR is below IORB without a rise."),
}


def funding_locus(secured_med_bp: float, unsec_bp: float, unsec_chg20_bp: float) -> str:
    """Classify where overnight funding pressure sits: broad / secured / unsecured / calm / na."""
    if secured_med_bp != secured_med_bp or unsec_bp != unsec_bp:
        return "na"
    sec_on = secured_med_bp >= SECURED_ON_BP
    unsec_on = unsec_bp >= UNSEC_LEVEL_ON_BP or (unsec_chg20_bp == unsec_chg20_bp and unsec_chg20_bp >= UNSEC_RISE_BP)
    if sec_on and unsec_on:
        return "broad"
    if sec_on:
        return "secured"
    if unsec_on:
        return "unsecured"
    return "calm"


def net_liquidity_decomp(walcl_m: pd.Series | None, tga_m: pd.Series | None, rrp_b: pd.Series | None,
                         *, rrp_lookback_days: int = 3) -> pd.DataFrame:
    """Weekly net liquidity (Fed assets - TGA - ON RRP) in $ billions on common Wednesdays.

    WALCL and WTREGEN are H.4.1 Wednesday levels ($ millions). ON RRP is daily ($ billions);
    the Wednesday value is used, or the latest print within rrp_lookback_days before it when
    Wednesday is a holiday. Rows end at the last Wednesday where all three exist (no forward
    fill past a series' last print). Columns: assets, tga, rrp, net, and the weekly
    contributions d_assets (= +dWALCL), d_tga (= -dTGA), d_rrp (= -dRRP), d_net.
    """
    cols = ["assets", "tga", "rrp", "net", "d_assets", "d_tga", "d_rrp", "d_net"]
    if walcl_m is None or tga_m is None or rrp_b is None:
        return pd.DataFrame(columns=cols)
    a = walcl_m.dropna() / 1000.0
    t = tga_m.dropna() / 1000.0
    r = rrp_b.dropna().sort_index()
    if a.empty or t.empty or r.empty:
        return pd.DataFrame(columns=cols)
    idx = a.index.intersection(t.index)
    idx = idx[idx <= r.index[-1]]
    rr = {}
    for d in idx:
        w = r[(r.index <= d) & (r.index >= d - pd.Timedelta(days=rrp_lookback_days))]
        if len(w):
            rr[d] = float(w.iloc[-1])
    df = pd.DataFrame({"assets": a.reindex(idx), "tga": t.reindex(idx), "rrp": pd.Series(rr)}).dropna()
    df["net"] = df["assets"] - df["tga"] - df["rrp"]
    df["d_assets"] = df["assets"].diff()
    df["d_tga"] = -df["tga"].diff()
    df["d_rrp"] = -df["rrp"].diff()
    df["d_net"] = df["net"].diff()
    return df[cols]


def window_contrib(df: pd.DataFrame, weeks: int) -> dict[str, float]:
    """Sum of weekly contributions over the last `weeks` rows ($ billions)."""
    if df is None or len(df) <= weeks:
        return {k: NAN for k in ("d_assets", "d_tga", "d_rrp", "d_net")}
    end, start = df.iloc[-1], df.iloc[-1 - weeks]
    return {"d_assets": float(end.assets - start.assets), "d_tga": float(-(end.tga - start.tga)),
            "d_rrp": float(-(end.rrp - start.rrp)), "d_net": float(end.net - start.net)}


def realized_vol_bp(yield_pct: pd.Series | None, window: int = 20) -> pd.Series:
    """Annualized realized volatility of daily yield changes, in bp: std(daily bp change) x sqrt(252)."""
    if yield_pct is None:
        return pd.Series(dtype=float)
    d = yield_pct.dropna().diff() * 100.0
    return (d.rolling(window).std() * np.sqrt(252.0)).dropna()


def rates_state(level_pct: float, chg_z: float, hist_years: float) -> tuple[str, str]:
    """Descriptive rates state: returns (global state, wording)."""
    if hist_years < 1.0 or level_pct != level_pct:
        return "na", "insufficient history"
    z = chg_z if chg_z == chg_z else 0.0
    if level_pct >= 80 and z >= 1:
        return "elevated", "high and rising"
    if level_pct >= 80:
        return "watch", "high"
    if z <= -1:
        return "normal", "falling"
    return "normal", "normal"


def conditions_state(value: float) -> str:
    """NFCI, ANFCI and STLFSI4 are constructed with 0 as the historical average, so the sign
    is an objective cut: above 0 is tighter (or more stressed) than average. The 1.0 line is
    an operator-set heuristic for clearly tight conditions."""
    if value != value:
        return "na"
    if value > 1.0:
        return "elevated"
    if value > 0:
        return "watch"
    return "normal"


# Backstop floors in $ billions (decision D3, operator-set heuristics).
BACKSTOP_FLOORS_B = {"RPONTSYD": 1.0, "H41RESPPALGTRFNWW": 1.0, "SWPT": 5.0, "WLCFLPCL": None}


def backstop_state(series_b: pd.Series | None, floor_b: float | None, spec: fc.FredSpec,
                   now: datetime | None = None, *, weekly_p95_weeks: int = 156,
                   seven_day_sum: bool = False) -> dict[str, Any]:
    """Backstop-facility state.

    quiet    : usage below the floor
    in_use   : usage at or above the floor
    elevated : usage at or above the floor and at or above its own trailing 95th percentile
    Discount-window primary credit has no floor (it carries a standing balance): it is
    elevated only when at or above its own 95th percentile AND its 4-week change is positive,
    otherwise quiet. stale / unavailable are explicit and never read as quiet.
    """
    if series_b is None or series_b.dropna().empty:
        return {"state": "unavailable", "value": NAN, "floor": floor_b, "p95": NAN, "obs": None, "stale": True}
    s = series_b.dropna()
    f = freshness_of(s, spec, now)
    work = s
    if seven_day_sum:
        work = s.rolling("7D").sum()
    value = float(work.iloc[-1])
    p95 = trailing_p95(work, weekly_p95_weeks)
    if f.stale:
        state = "stale"
    elif floor_b is None:
        chg4 = change_n(s, 4)
        state = "elevated" if (value >= p95 and chg4 == chg4 and chg4 > 0) else "quiet"
    elif value < floor_b:
        state = "quiet"
    elif p95 == p95 and value >= p95:
        state = "elevated"
    else:
        state = "in_use"
    return {"state": state, "value": value, "floor": floor_b, "p95": p95, "obs": f.observation_date,
            "stale": f.stale, "age_days": f.age_days}


BACKSTOP_TO_GLOBAL = {"quiet": "normal", "in_use": "elevated", "elevated": "stress",
                      "stale": "na", "unavailable": "na"}


def backstops_in_use(states: Iterable[str]) -> int:
    return sum(1 for s in states if s in ("in_use", "elevated"))
