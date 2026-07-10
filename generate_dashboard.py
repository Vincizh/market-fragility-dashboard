#!/usr/bin/env python3
"""De-Lever Signal Dashboard Generator.

Phase 3 adds a stateless, recompute-from-scratch analytics layer:
  * Part 0 : Net Liquidity = WALCL - TGA - RRP (FRED RRPONTSYD).
  * Part A : Historical LPI reconstruction (expanding no-look-ahead percentiles),
             a conditional forward-return / tail-risk table vs the S&P 500, and a
             momentum / breadth / regime layer.
  * Part B : CFTC COT crowding layer (TFF + Disaggregated via Socrata) plus a
             Treasury basis-trade proxy gauge.
  * Part C : Three-layer page architecture (Fragility / Crowding / Amplifiers).

Everything is derived from full-history API pulls each run; no committed state
files, no workflow changes. Every fetch degrades gracefully in isolation.
"""

import yfinance as yf
import requests
import pandas as pd
import numpy as np
import json
import io
import zipfile
import os
import re
import sys
import time
from math import log, sqrt, exp, pi
from datetime import datetime, timezone

print("Starting dashboard generation...")

# --- VIX ---
print("Fetching VIX...")
try:
    vix_spot   = yf.download("^VIX",   period="30d", auto_adjust=True, progress=False)["Close"]
    vix3m_hist = yf.download("^VIX3M", period="30d", auto_adjust=True, progress=False)["Close"]
    vix9d_hist = yf.download("^VIX9D", period="30d", auto_adjust=True, progress=False)["Close"]
    def lv(df):
        v = df.iloc[-1]
        return float(v.iloc[0]) if hasattr(v, "iloc") else float(v)
    vix_val   = lv(vix_spot)
    vix3m_val = lv(vix3m_hist)
    vix9d_val = lv(vix9d_hist)
    vix_dates     = [d.strftime("%Y-%m-%d") for d in vix_spot.index]
    vix_vals_list = [round(float(v), 2) for v in vix_spot.values.flatten()]
except Exception as e:
    print("VIX error:", e); sys.exit(1)

vix_contango = vix3m_val > vix_val
print("VIX={:.2f} VIX3M={:.2f} VIX9D={:.2f} contango={}".format(vix_val, vix3m_val, vix9d_val, vix_contango))

# --- Funding ---
print("Fetching funding rates...")
bnb_btc_fr = bnb_eth_fr = okx_btc_fr = okx_eth_fr = None
try:
    cg = requests.get("https://api.coingecko.com/api/v3/derivatives?include_tickers=unexpired", timeout=25).json()
    bb = next((x for x in cg if x.get("market") == "Binance (Futures)" and x.get("symbol") == "BTCUSDT"), None)
    be = next((x for x in cg if x.get("market") == "Binance (Futures)" and x.get("symbol") == "ETHUSDT"), None)
    if bb: bnb_btc_fr = bb["funding_rate"] * 100
    if be: bnb_eth_fr = be["funding_rate"] * 100
    print("CoinGecko BTC={} ETH={}".format(bnb_btc_fr, bnb_eth_fr))
except Exception as e:
    print("CoinGecko error:", e)
try:
    okx_btc_fr = float(requests.get("https://www.okx.com/api/v5/public/funding-rate?instId=BTC-USDT-SWAP", timeout=12).json()["data"][0]["fundingRate"]) * 100
    okx_eth_fr = float(requests.get("https://www.okx.com/api/v5/public/funding-rate?instId=ETH-USDT-SWAP", timeout=12).json()["data"][0]["fundingRate"]) * 100
    print("OKX BTC={} ETH={}".format(okx_btc_fr, okx_eth_fr))
except Exception as e:
    print("OKX error:", e)

btc_fr   = bnb_btc_fr if bnb_btc_fr is not None else (okx_btc_fr if okx_btc_fr is not None else 0.0)
eth_fr   = bnb_eth_fr if bnb_eth_fr is not None else (okx_eth_fr if okx_eth_fr is not None else 0.0)
okx_disp = okx_btc_fr if okx_btc_fr is not None else 0.0
src_lbl  = "Binance" if bnb_btc_fr is not None else "OKX"
btc_pos  = btc_fr > 0
eth_pos  = eth_fr > 0

# ---------------------------------------------------------------------------
# COT crowding layer (Part B) — unified CFTC Socrata fetch
# ---------------------------------------------------------------------------
# One generalized fetcher replaces the old NQ-only legacy-zip pull. It feeds
# both the Phase-1 CTA/NQ signal (kept identical) and the new crowding panel.
print("Fetching COT (CFTC Socrata)...")

SOCRATA_BASE = "https://publicreporting.cftc.gov/resource/{}.json"
# Candidate dataset IDs verified at build time (columns checked, not trusted blindly).
COT_TFF_CANDIDATES = ["gpe5-46if"]   # Traders in Financial Futures, Futures-Only
COT_DIS_CANDIDATES = ["72hh-3qpy"]   # Disaggregated, Futures-Only


def socrata_get(ds, params, retries=3):
    url = SOCRATA_BASE.format(ds)
    last = None
    for a in range(retries):
        try:
            r = requests.get(url, params=params, timeout=45)
            if r.status_code == 200:
                return r.json()
            last = "HTTP {}".format(r.status_code)
        except Exception as e:
            last = str(e)
    raise RuntimeError("socrata {} failed: {}".format(ds, last))


def discover_dataset(candidates, required_cols):
    """Return the first candidate id whose columns include required_cols."""
    for ds in candidates:
        try:
            row = socrata_get(ds, {"$limit": 1})
            if row and all(c in row[0] for c in required_cols):
                return ds
        except Exception as e:
            print("  dataset probe {} failed: {}".format(ds, e))
    return None


def distinct_names(ds):
    try:
        res = socrata_get(ds, {"$select": "distinct contract_market_name", "$limit": 8000})
        return [x["contract_market_name"] for x in res if x.get("contract_market_name")]
    except Exception as e:
        print("  distinct_names {} failed: {}".format(ds, e))
        return []


def match_contract(ds, primary, keywords, names_cache):
    """Prefer the exact primary name; else contains-match keywords, newest wins."""
    try:
        r = socrata_get(ds, {"contract_market_name": primary,
                             "$order": "report_date_as_yyyy_mm_dd DESC", "$limit": 1})
        if r:
            return primary
    except Exception:
        pass
    cands = [n for n in names_cache if all(k.lower() in n.lower() for k in keywords)]
    best, best_date = None, ""
    for n in cands:
        try:
            r = socrata_get(ds, {"contract_market_name": n,
                                 "$order": "report_date_as_yyyy_mm_dd DESC", "$limit": 1})
            if r:
                d = str(r[0].get("report_date_as_yyyy_mm_dd", ""))
                if d > best_date:
                    best, best_date = n, d
        except Exception:
            continue
    return best


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return np.nan


def fetch_cot_series(ds, contract, kind):
    """Return a DataFrame indexed by report date with net-position columns.

    kind='tff'  -> lev_net (+ am_net) from Leveraged Funds / Asset Managers.
    kind='dis'  -> mm_net from Managed Money.
    """
    if kind == "tff":
        sel = ("report_date_as_yyyy_mm_dd,open_interest_all,"
               "lev_money_positions_long,lev_money_positions_short,"
               "asset_mgr_positions_long,asset_mgr_positions_short")
    else:
        sel = ("report_date_as_yyyy_mm_dd,open_interest_all,"
               "m_money_positions_long_all,m_money_positions_short_all")
    res = socrata_get(ds, {"contract_market_name": contract, "$select": sel,
                           "$order": "report_date_as_yyyy_mm_dd ASC", "$limit": 6000})
    df = pd.DataFrame(res)
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["report_date_as_yyyy_mm_dd"])
    df = df.sort_values("date").set_index("date")
    df["oi"] = df["open_interest_all"].map(_num)
    if kind == "tff":
        df["lev_long"]  = df["lev_money_positions_long"].map(_num)
        df["lev_short"] = df["lev_money_positions_short"].map(_num)
        df["lev_net"]   = df["lev_long"] - df["lev_short"]
        df["am_net"]    = df["asset_mgr_positions_long"].map(_num) - df["asset_mgr_positions_short"].map(_num)
    else:
        df["mm_long"]  = df["m_money_positions_long_all"].map(_num)
        df["mm_short"] = df["m_money_positions_short_all"].map(_num)
        df["mm_net"]   = df["mm_long"] - df["mm_short"]
    return df


def pct_of(arr, val):
    a = np.asarray(arr, dtype=float)
    a = a[~np.isnan(a)]
    if len(a) == 0 or val != val:
        return float("nan")
    return float((a <= val).sum()) / len(a) * 100.0


def zscore_156(series):
    s = series.dropna().tail(156)
    if len(s) < 20 or s.std(ddof=0) == 0:
        return float("nan")
    return float((s.iloc[-1] - s.mean()) / s.std(ddof=0))


# Phase-1 NQ signal defaults (kept identical to prior behaviour)
cot_net = cot_change = 0
cot_pct = 0.0
cot_date = "N/A"
cot_dates_list = []
cot_vals_list  = []
cta_covering   = False

# Crowding-layer market definitions (WHO to track per spec)
EQUITY_MARKETS = [  # (key, label, primary contract, keyword fallback)
    ("SPX", "E-mini S&P 500",  "E-MINI S&P 500",           ["e-mini", "s&p 500"]),
    ("NQ",  "Nasdaq-100",      "NASDAQ-100 Consolidated",  ["nasdaq", "consolidated"]),
    ("RTY", "E-mini Russell 2000", "RUSSELL E-MINI",       ["russell", "e-mini"]),
]
RATES_MARKETS = [
    ("UST2Y",  "2-Year UST",  "UST 2Y NOTE",  ["ust", "2y"]),
    ("UST5Y",  "5-Year UST",  "UST 5Y NOTE",  ["ust", "5y"]),
    ("UST10Y", "10-Year UST", "UST 10Y NOTE", ["ust", "10y"]),
]
USD_MARKET = ("USD", "US Dollar Index", "USD INDEX", ["dollar", "index"])
CONTEXT_MARKETS = [  # Disaggregated / Managed Money
    ("WTI",  "WTI Crude", "CRUDE OIL, LIGHT SWEET-WTI", ["crude", "wti"]),
    ("GOLD", "Gold",      "GOLD",                       ["gold"]),
]

cot_markets = {}     # key -> computed reading dict
cot_matched = {}     # key -> matched contract name (logged)
cot_report_date = None
cot_ok = False
basis_proxy = float("nan")
basis_tenors = {}    # tenor key -> {am_pct, lev_short_pct, score}

try:
    tff_cols = ["contract_market_name", "report_date_as_yyyy_mm_dd", "open_interest_all",
                "lev_money_positions_long", "lev_money_positions_short",
                "asset_mgr_positions_long", "asset_mgr_positions_short"]
    dis_cols = ["contract_market_name", "report_date_as_yyyy_mm_dd",
                "m_money_positions_long_all", "m_money_positions_short_all"]
    ds_tff = discover_dataset(COT_TFF_CANDIDATES, tff_cols)
    ds_dis = discover_dataset(COT_DIS_CANDIDATES, dis_cols)
    print("COT datasets: TFF={} DIS={}".format(ds_tff, ds_dis))
    tff_names = distinct_names(ds_tff) if ds_tff else []
    dis_names = distinct_names(ds_dis) if ds_dis else []

    def build_market(key, label, primary, kw, ds, names, kind):
        matched = match_contract(ds, primary, kw, names)
        if not matched:
            print("  COT {}: no contract matched".format(key))
            return
        df = fetch_cot_series(ds, matched, kind)
        if df.empty:
            print("  COT {}: no rows for {}".format(key, matched))
            return
        col = "lev_net" if kind == "tff" else "mm_net"
        net = df[col]
        cur = float(net.iloc[-1])
        chg4 = float(net.iloc[-1] - net.iloc[-5]) if len(net) >= 5 else float("nan")
        rec = {
            "label": label, "contract": matched, "kind": kind,
            "net": cur, "chg4": chg4,
            "pct": pct_of(net.values, cur),
            "z": zscore_156(net),
            "date": str(df.index[-1].date()),
            "oi": float(df["oi"].iloc[-1]) if "oi" in df else float("nan"),
        }
        if kind == "tff":
            rec["am_net"] = float(df["am_net"].iloc[-1])
            rec["am_pct"] = pct_of(df["am_net"].values, df["am_net"].iloc[-1])
            rec["lev_short_pct"] = pct_of((-net).values, -cur)  # crowding of SHORT side
            rec["_am_series"] = df["am_net"]
            rec["_lev_series"] = net
        # Phase 5: per-instrument weekly chart series (last 104 weeks).
        # Percentile per week uses the SAME full-history methodology as the
        # header chip (pct_of over the whole net series) so the last point
        # equals the header percentile exactly.
        rec["key"] = key
        disp = net.tail(104)
        long_col, short_col = ("lev_long", "lev_short") if kind == "tff" else ("mm_long", "mm_short")
        long_s = df[long_col].tail(104)
        short_s = df[short_col].tail(104)
        full_vals = net.values

        def _oi(x):
            return int(round(x)) if x == x else None

        rec["_chart"] = {
            "dates": [d.strftime("%Y-%m-%d") for d in disp.index],
            "long": [_oi(x) for x in long_s.tolist()],
            "short": [(-_oi(x) if _oi(x) is not None else None) for x in short_s.tolist()],
            "net": [_oi(x) for x in disp.tolist()],
            "pctile": [round(pct_of(full_vals, v), 1) if v == v else None for v in disp.tolist()],
            "z": round(rec["z"], 2) if rec["z"] == rec["z"] else None,
        }
        cot_markets[key] = rec
        cot_matched[key] = matched
        print("  COT {} [{}] net={:,.0f} pct={:.0f} z={:.2f} d4={:+,.0f} as_of={}".format(
            key, matched, cur, rec["pct"], rec["z"] if rec["z"] == rec["z"] else float('nan'),
            chg4 if chg4 == chg4 else 0, rec["date"]))

    if ds_tff:
        for k, lbl, pri, kw in EQUITY_MARKETS + RATES_MARKETS + [USD_MARKET]:
            try:
                build_market(k, lbl, pri, kw, ds_tff, tff_names, "tff")
            except Exception as e:
                print("  COT {} error: {}".format(k, e))
    if ds_dis:
        for k, lbl, pri, kw in CONTEXT_MARKETS:
            try:
                build_market(k, lbl, pri, kw, ds_dis, dis_names, "dis")
            except Exception as e:
                print("  COT {} error: {}".format(k, e))

    # Phase-1 NQ signal from the unified pull (identical definition to before)
    if "NQ" in cot_markets:
        nq = cot_markets["NQ"]
        df_nq = fetch_cot_series(ds_tff, nq["contract"], "tff").tail(16)
        cot_net    = int(nq["net"])
        cot_pct    = float(nq["net"] / nq["oi"] * 100.0) if nq.get("oi") else 0.0
        cot_date   = nq["date"]
        cot_change = int(nq["chg4"] / 4) if False else int(df_nq["lev_net"].iloc[-1] - df_nq["lev_net"].iloc[-2])
        cot_dates_list = [d.strftime("%Y-%m-%d") for d in df_nq.index]
        cot_vals_list  = [int(x) for x in df_nq["lev_net"].tolist()]
        cta_covering   = cot_change > 0

    # Basis-trade proxy (Part B3): AM-long crowding vs LF-short crowding across tenors
    tenor_scores = []
    for tk in ["UST2Y", "UST5Y", "UST10Y"]:
        m = cot_markets.get(tk)
        if not m:
            continue
        am_p = m.get("am_pct", float("nan"))
        lev_short_p = m.get("lev_short_pct", float("nan"))
        if am_p == am_p and lev_short_p == lev_short_p:
            sc = (am_p + lev_short_p) / 2.0
            basis_tenors[tk] = {"am_pct": am_p, "lev_short_pct": lev_short_p, "score": sc}
            tenor_scores.append(sc)
    if tenor_scores:
        basis_proxy = float(np.mean(tenor_scores))

    dates_all = [m["date"] for m in cot_markets.values()]
    if dates_all:
        cot_report_date = max(dates_all)
    cot_ok = bool(cot_markets)
except Exception as e:
    print("COT layer error (non-fatal):", e)

print("COT net={:,} pct={:.1f}% change={:+,} markets={} basis_proxy={}".format(
    cot_net, cot_pct, cot_change, len(cot_markets),
    "{:.1f}".format(basis_proxy) if basis_proxy == basis_proxy else "N/A"))

# COT freshness
cot_stale = False
if cot_report_date:
    try:
        age_days = (datetime.now(timezone.utc).date() - datetime.strptime(cot_report_date, "%Y-%m-%d").date()).days
        cot_stale = age_days > 10
    except Exception:
        age_days = None
else:
    age_days = None

# --- Correlation ---
print("Fetching correlation...")
tickers = ["XLK","XLF","XLV","XLE","XLI","XLC","XLY","XLP","XLB","XLU","XLRE"]
n = len(tickers)
sec  = yf.download(tickers, period="2mo", auto_adjust=True, progress=False)["Close"]
rets = sec.pct_change().dropna()

def avg_corr(df):
    cm = df.corr().values
    return (cm.sum() - n) / (n * (n - 1))

avg_c1m = avg_corr(rets.tail(21))
avg_c2w = avg_corr(rets.tail(10))
corr_hist  = []
corr_dates = []
for i in range(21, len(rets) + 1):
    corr_hist.append(round(avg_corr(rets.iloc[i-21:i]), 4))
    corr_dates.append(rets.index[i-1].strftime("%Y-%m-%d"))
corr_declining = avg_c2w < avg_c1m
print("Corr 1M={:.3f} 2W={:.3f} declining={}".format(avg_c1m, avg_c2w, corr_declining))

# ---------------------------------------------------------------------------
# Liquidity Pressure Index (LPI) — historical reconstruction (Part A1)
# ---------------------------------------------------------------------------
# 4 factors -> weekly (W-WED) -> expanding-window, no-look-ahead percentile with
# a 156-week burn-in and a 560-week lookback cap. LPI = mean of available factor
# percentiles (net liquidity inverted), emitted where >=3 factors are valid.
print("Fetching LPI factors + reconstructing history...")

LPI_WINDOW   = 560   # ~11y lookback cap
LPI_BURN     = 156   # 3y burn-in before a percentile is emitted
FACTOR_START = "2003-01-01"


def fred_csv(series, start=FACTOR_START):
    url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={}&observation_start={}".format(series, start)
    r = requests.get(url, timeout=30)
    df = pd.read_csv(io.StringIO(r.text))
    df.columns = ["date", "val"]
    df["date"] = pd.to_datetime(df["date"])
    df["val"] = pd.to_numeric(df["val"], errors="coerce")
    return df.dropna().set_index("date")["val"]


def to_weekly(s):
    # W-WED alignment: WALCL/WTREGEN are Wednesday-dated; RRP/SOFR/VIX resample cleanly.
    return s.resample("W-WED").last().dropna()


def pctile_series(s, window=LPI_WINDOW, burn=LPI_BURN):
    """Expanding/rolling causal percentile. Each point uses ONLY data at or before
    it (no look-ahead). Emits NaN until `burn` observations exist."""
    vals = s.values
    out = []
    for i in range(len(vals)):
        if i + 1 < burn:
            out.append(np.nan)
            continue
        lo = max(0, i - window + 1)
        w = vals[lo:i + 1]
        out.append(float((w <= vals[i]).sum()) / len(w) * 100.0)
    return pd.Series(out, index=s.index)


lpi_pct   = {}   # factor key -> weekly percentile Series (with burn-in NaNs)
lpi_raw   = {}   # factor key -> current raw reading
lpi_ok    = {}   # factor key -> availability
netliq_pct_norrp = None   # for before/after RRP comparison

# Factor 1 — Short rate (SOFR spliced with DFF pre-2018)
sofr_current = None
try:
    sofr = to_weekly(fred_csv("SOFR"))
    try:
        dff = to_weekly(fred_csv("DFF"))
        short_rate = pd.concat([dff[dff.index < sofr.index.min()], sofr], sort=False).sort_index()
    except Exception as e:
        print("LPI DFF splice error:", e)
        short_rate = sofr
    short_rate = short_rate[short_rate.index >= pd.Timestamp(FACTOR_START)]
    lpi_pct["short_rate"] = pctile_series(short_rate)
    sofr_current = float(short_rate.iloc[-1])
    lpi_raw["short_rate"] = sofr_current
    lpi_ok["short_rate"] = True
    print("LPI short_rate weeks={} last={:.3f} pct={:.1f}".format(
        len(short_rate), sofr_current, lpi_pct["short_rate"].iloc[-1]))
except Exception as e:
    lpi_ok["short_rate"] = False
    print("LPI short_rate error:", e)

# Factor 2 — Duration supply (coupon issuance, trailing 4-week sum)
issuance_4w = None
try:
    au_rows = []
    for attempt in range(3):
        try:
            url = ("https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/od/auctions_query"
                   "?fields=auction_date,offering_amt,security_term"
                   "&filter=security_term:in:(2-Year,3-Year,5-Year,7-Year,10-Year,20-Year,30-Year)"
                   "&sort=-auction_date&page[size]=10000&page[number]=1")
            au_rows = requests.get(url, timeout=50).json().get("data", [])
            break
        except Exception as e:
            print("LPI auctions retry {}: {}".format(attempt, e))
    if not au_rows:
        raise RuntimeError("no auction rows")
    au = pd.DataFrame(au_rows)
    au["auction_date"] = pd.to_datetime(au["auction_date"])
    au["offering_amt"] = pd.to_numeric(au["offering_amt"], errors="coerce")
    au = au.dropna(subset=["offering_amt"])
    au = au[au["auction_date"] >= pd.Timestamp(FACTOR_START)]
    wk = au.set_index("auction_date")["offering_amt"].resample("W-WED").sum().fillna(0)
    iss4 = (wk.rolling(4).sum().dropna()) / 1e9  # -> $ billions
    lpi_pct["duration_supply"] = pctile_series(iss4)
    issuance_4w = float(iss4.iloc[-1])
    lpi_raw["duration_supply"] = issuance_4w
    lpi_ok["duration_supply"] = True
    print("LPI duration_supply weeks={} last_4w=${:.1f}B pct={:.1f}".format(
        len(iss4), issuance_4w, lpi_pct["duration_supply"].iloc[-1]))
except Exception as e:
    lpi_ok["duration_supply"] = False
    print("LPI duration_supply error:", e)

# Factor 3 — Fed net liquidity = WALCL - TGA - RRP (Part 0), INVERTED
netliq_current_t = None
netliq_norrp_t = None
rrp_current_b = None
try:
    walcl = to_weekly(fred_csv("WALCL"))
    tga   = to_weekly(fred_csv("WTREGEN"))
    # Normalize all to $ billions. WALCL/WTREGEN arrive in $millions; RRP in $billions.
    def _to_bil(s):
        return s / 1000.0 if float(s.iloc[-1]) > 100000 else s
    walcl_b = _to_bil(walcl)
    tga_b   = _to_bil(tga)
    try:
        rrp = to_weekly(fred_csv("RRPONTSYD"))
        rrp_b = rrp / 1000.0 if float(rrp.iloc[-1]) > 100000 else rrp  # already $B
        rrp_current_b = float(rrp_b.iloc[-1])
    except Exception as e:
        print("LPI RRP error (degrading to WALCL-TGA):", e)
        rrp_b = pd.Series(0.0, index=walcl_b.index)
    idx = walcl_b.index.union(tga_b.index).union(rrp_b.index)
    walcl_a = walcl_b.reindex(idx).ffill()
    tga_a   = tga_b.reindex(idx).ffill()
    rrp_a   = rrp_b.reindex(idx).ffill().fillna(0.0)
    netliq = (walcl_a - tga_a - rrp_a).dropna()          # $B, with RRP
    netliq_norrp = (walcl_a - tga_a).dropna()             # $B, legacy (no RRP)
    lpi_pct["net_liquidity"] = 100.0 - pctile_series(netliq)   # INVERTED
    netliq_pct_norrp = 100.0 - pctile_series(netliq_norrp)
    netliq_current_t = float(netliq.iloc[-1]) / 1000.0    # $T
    netliq_norrp_t = float(netliq_norrp.iloc[-1]) / 1000.0
    lpi_raw["net_liquidity"] = netliq_current_t
    lpi_ok["net_liquidity"] = True
    print("LPI net_liquidity weeks={} last=${:.3f}T (WALCL=${:.3f}T TGA=${:.0f}B RRP=${:.0f}B) pct_inv={:.1f}".format(
        len(netliq), netliq_current_t, float(walcl_a.iloc[-1]) / 1000.0,
        float(tga_a.iloc[-1]), float(rrp_a.iloc[-1]), lpi_pct["net_liquidity"].iloc[-1]))
except Exception as e:
    lpi_ok["net_liquidity"] = False
    print("LPI net_liquidity error:", e)

# Factor 4 — Vol amplifier (VIX percentile, deep history via Yahoo)
vix_lpi_current = None
try:
    vix_hist = yf.download("^VIX", period="max", auto_adjust=True, progress=False)["Close"]
    vix_hist = to_weekly(vix_hist.squeeze())
    vix_hist = vix_hist[vix_hist.index >= pd.Timestamp(FACTOR_START)]
    lpi_pct["vol_amplifier"] = pctile_series(vix_hist)
    vix_lpi_current = float(vix_hist.iloc[-1])
    lpi_raw["vol_amplifier"] = vix_lpi_current
    lpi_ok["vol_amplifier"] = True
    print("LPI vol_amplifier weeks={} last={:.2f} pct={:.1f}".format(
        len(vix_hist), vix_lpi_current, lpi_pct["vol_amplifier"].iloc[-1]))
except Exception as e:
    lpi_ok["vol_amplifier"] = False
    print("LPI vol_amplifier error:", e)

lpi_order = ["short_rate", "duration_supply", "net_liquidity", "vol_amplifier"]
lpi_labels = {
    "short_rate":      "Short Rate 资金价格",
    "duration_supply": "Duration Supply 久期供给",
    "net_liquidity":   "Net Liquidity 银行水位 (inv)",
    "vol_amplifier":   "Vol Amplifier 波动放大器",
}


def reconstruct_lpi(pct_dict):
    """Mean of available factor percentiles, requiring >=3 valid factors per week."""
    if not pct_dict:
        return pd.Series(dtype=float), pd.Series(dtype=float)
    df = pd.concat(pct_dict, axis=1, sort=True).sort_index()
    valid = df.notna().sum(axis=1)
    comp = df.mean(axis=1)
    comp = comp[valid >= 3]
    return comp.dropna(), valid


avail_pct = {k: lpi_pct[k] for k in lpi_order if lpi_ok.get(k)}
lpi_series_full, lpi_valid_count = reconstruct_lpi(avail_pct)
lpi_has = len(lpi_series_full) > 0
lpi_composite = float(lpi_series_full.iloc[-1]) if lpi_has else float("nan")

# LPI "before RRP fix" (net_liquidity without RRP) for reporting
lpi_composite_before = float("nan")
if lpi_has and netliq_pct_norrp is not None:
    pct_before = dict(avail_pct)
    pct_before["net_liquidity"] = netliq_pct_norrp
    lpi_before_series, _ = reconstruct_lpi(pct_before)
    if len(lpi_before_series):
        lpi_composite_before = float(lpi_before_series.iloc[-1])

# Reconstruction diagnostics
recon_earliest = lpi_series_full.index[0].strftime("%Y-%m-%d") if lpi_has else "N/A"
recon_n = len(lpi_series_full)
top10 = []
if lpi_has:
    for d, v in lpi_series_full.sort_values(ascending=False).head(10).items():
        top10.append((d.strftime("%Y-%m-%d"), round(float(v), 1)))
print("LPI reconstruction: earliest={} weeks={} composite={:.1f} (before RRP={:.1f})".format(
    recon_earliest, recon_n, lpi_composite if lpi_has else float("nan"),
    lpi_composite_before if lpi_composite_before == lpi_composite_before else float("nan")))
print("LPI top-10 weeks:", top10)

# ---------------------------------------------------------------------------
# Conditional tail table (Part A2) — forward S&P 500 stats bucketed by LPI band
# ---------------------------------------------------------------------------
LPI_BANDS = [(0, 40, "0-40"), (40, 60, "40-60"), (60, 80, "60-80"), (80, 100.01, "80-100")]


def band_key(v):
    if v != v:
        return None
    for lo, hi, name in LPI_BANDS:
        if lo <= v < hi:
            return name
    return "80-100"


tail_table = {}     # band -> horizon -> stats dict
tail_ok = False
spx_weekly = None
try:
    spx = yf.download("^GSPC", period="max", auto_adjust=True, progress=False)["Close"]
    spx_weekly = to_weekly(spx.squeeze())
    if lpi_has:
        df = pd.DataFrame({"lpi": lpi_series_full}).join(
            pd.DataFrame({"spx": spx_weekly}), how="inner").dropna()
        closes = df["spx"].values
        lpis = df["lpi"].values
        rows = {h: {"ALL": []} for h in (4, 8)}
        for name in [b[2] for b in LPI_BANDS]:
            for h in (4, 8):
                rows[h][name] = []
        nrec = len(df)
        for i in range(nrec):
            bk = band_key(lpis[i])
            for h in (4, 8):
                if i + h >= nrec:
                    continue
                base = closes[i]
                path = closes[i:i + h + 1]                # includes week t
                fwd_ret = closes[i + h] / base - 1.0
                wret = np.diff(path) / path[:-1]
                vol = float(np.std(wret, ddof=1) * np.sqrt(52)) if len(wret) > 1 else float("nan")
                peak = np.maximum.accumulate(path)
                mdd = float(np.min(path / peak - 1.0))
                rec = (fwd_ret, vol, mdd)
                rows[h]["ALL"].append(rec)
                if bk:
                    rows[h][bk].append(rec)

        def agg(recs):
            if not recs:
                return None
            r = np.array([x[0] for x in recs], dtype=float)
            v = np.array([x[1] for x in recs], dtype=float)
            d = np.array([x[2] for x in recs], dtype=float)
            v = v[~np.isnan(v)]
            return {
                "n": len(recs),
                "mean_ret": float(np.mean(r)),
                "med_ret": float(np.median(r)),
                "vol": float(np.mean(v)) if len(v) else float("nan"),
                "p5": float((d < -0.05).mean() * 100.0),
                "p10": float((d < -0.10).mean() * 100.0),
                "avg_dd": float(np.mean(d) * 100.0),
            }

        for name in ["ALL"] + [b[2] for b in LPI_BANDS]:
            tail_table[name] = {h: agg(rows[h][name]) for h in (4, 8)}
        tail_ok = True
        print("Tail table built. N(ALL,4w)={} N(ALL,8w)={}".format(
            tail_table["ALL"][4]["n"], tail_table["ALL"][8]["n"]))
except Exception as e:
    print("Tail table error (non-fatal):", e)

current_band = band_key(lpi_composite) if lpi_has else None

# ---------------------------------------------------------------------------
# Momentum + breadth + regime (Part A3)
# ---------------------------------------------------------------------------
dlpi_13w = dlpi_4w = float("nan")
breadth = 0
factor_dir = {}   # factor -> "up"/"down"/"flat" over last 4 weeks
if lpi_has:
    s = lpi_series_full
    if len(s) >= 14:
        dlpi_13w = float(s.iloc[-1] - s.iloc[-14])
    if len(s) >= 5:
        dlpi_4w = float(s.iloc[-1] - s.iloc[-5])
for k in lpi_order:
    if not lpi_ok.get(k):
        continue
    ps = lpi_pct[k].dropna()
    if len(ps) >= 5:
        now, ago = float(ps.iloc[-1]), float(ps.iloc[-5])
        factor_dir[k] = "up" if now > ago + 0.5 else ("down" if now < ago - 0.5 else "flat")
        if now > 70 and now > ago:
            breadth += 1
    else:
        factor_dir[k] = "flat"


def regime_cell(lpi, d13):
    level = "High" if lpi >= 60 else "Low"
    if d13 != d13:
        direction = "Flat"
    elif d13 > 2:
        direction = "Rising"
    elif d13 < -2:
        direction = "Falling"
    else:
        direction = "Flat"
    if level == "Low" and direction in ("Falling", "Flat"):
        return level, direction, "Cushion thick, stable — full risk budget", "#10b981", "green"
    if level == "Low" and direction == "Rising":
        return level, direction, "Inflection watch — pressure building from low base", "#f59e0b", "yellow"
    if level == "High" and direction == "Falling":
        return level, direction, "Decompressing — pressure receding from highs", "#14b8a6", "teal"
    if level == "High" and direction == "Rising":
        return level, direction, "Danger zone — cut leverage, add hedges", "#ef4444", "red"
    return level, direction, "Elevated but stable — keep hedges on", "#f97316", "orange"


if lpi_has:
    reg_level, reg_dir, reg_msg, reg_col, reg_cls = regime_cell(lpi_composite, dlpi_13w)
else:
    reg_level, reg_dir, reg_msg, reg_col, reg_cls = "N/A", "N/A", "Insufficient data", "#64748b", "gray"
print("Regime: {} & {} -> {} | breadth={}/4 | dLPI13w={} dLPI4w={}".format(
    reg_level, reg_dir, reg_msg, breadth,
    round(dlpi_13w, 1) if dlpi_13w == dlpi_13w else "NA",
    round(dlpi_4w, 1) if dlpi_4w == dlpi_4w else "NA"))

# Full-history + 52w LPI chart series
lpi_hist_dates = lpi_hist_vals = []
lpi_full_dates = lpi_full_vals = []
if lpi_has:
    s52 = lpi_series_full.tail(52)
    lpi_hist_dates = [d.strftime("%Y-%m-%d") for d in s52.index]
    lpi_hist_vals  = [round(float(v), 1) for v in s52.values]
    lpi_full_dates = [d.strftime("%Y-%m-%d") for d in lpi_series_full.index]
    lpi_full_vals  = [round(float(v), 1) for v in lpi_series_full.values]

# --- GEX Monitor (Phase 2b, FlashAlpha free tier) ---------------------------
print("Running GEX monitor...")
import gex_monitor

try:
    with open("index.html", "r", encoding="utf-8") as _f:
        _prev_html = _f.read()
except Exception:
    _prev_html = ""

gex_now = datetime.now(timezone.utc)
gex_key = os.environ.get("FLASHALPHA_API_KEY")
try:
    gex_state, gex_meta = gex_monitor.run_gex_update(gex_now, _prev_html, gex_key)
except Exception as e:
    print("GEX monitor error (non-fatal):", e)
    gex_state, gex_meta = gex_monitor.default_state(), {
        "fetched": None, "status": "error", "expiration": "",
        "fresh": set(), "api_key": bool(gex_key)}

gex_nvda = gex_monitor.nvda_proxy(gex_state)
gex_section_html = gex_monitor.render_section(gex_state, gex_meta, gex_now)
gex_hist_d, gex_hist_v = gex_monitor.nvda_history_json(gex_state)
print("GEX monitor: fetched={} status={} used={}/{} nvda_has={} excluded={}".format(
    gex_meta.get("fetched"), gex_meta.get("status"),
    gex_state["daily"]["count"], gex_monitor.GEX_DAILY_LIMIT,
    gex_nvda["has"], gex_state.get("excluded")))

if gex_nvda["has"]:
    gex_note = "NVDA net GEX {} ({})".format(
        gex_monitor.fmt_gex(gex_nvda["net_gex"]),
        "negative = amplifying" if not gex_nvda["positive"] else "positive = dampening")
else:
    gex_note = ""

# ---------------------------------------------------------------------------
# Homebrew Index GEX (Part A) — SPY + QQQ dealer gamma from yfinance chains
# ---------------------------------------------------------------------------
# SqueezeMetrics naive convention: dealers long calls (+), short puts (-),
# OI-weighted Black-Scholes gamma expressed in $bn per 1% underlying move.
# Daily snapshots persist inside an embedded <script id="hgex-state"> JSON block
# (the workflow only commits index.html, so no side-car file survives).
print("Computing homebrew index GEX (SPY/QQQ)...")

HOMEBREW_GEX_SYMBOLS = ["SPY", "QQQ"]
HGEX_LOOKAHEAD_DAYS  = 45
HGEX_MAX_EXPIRIES    = 10
HGEX_SNAP_MAX        = 400        # rolling daily-snapshot cap per symbol
HGEX_PCTILE_MIN_DAYS = 60         # suppress percentile until this much history
HGEX_STATE_RE = re.compile(
    r'<script id="hgex-state" type="application/json">(.*?)</script>', re.DOTALL)


def load_hgex_state(prev_html):
    """Extract {symbol: {date: snapshot}} from a prior index.html string."""
    if not prev_html:
        return {}
    m = HGEX_STATE_RE.search(prev_html)
    if not m:
        return {}
    try:
        raw = json.loads(m.group(1))
    except (ValueError, TypeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    out = {}
    for sym, snaps in raw.items():
        if isinstance(snaps, dict):
            out[sym] = {d: v for d, v in snaps.items() if isinstance(v, dict)}
    return out


def hgex_state_block(state):
    payload = json.dumps(state, separators=(",", ":")).replace("</", "<\\/")
    return '<script id="hgex-state" type="application/json">' + payload + '</script>'


def _norm_pdf(x):
    return exp(-0.5 * x * x) / sqrt(2.0 * pi)


def bs_gamma(S, K, T, sigma, r):
    """Black-Scholes gamma = phi(d1) / (S*sigma*sqrt(T))."""
    if S <= 0 or K <= 0 or T <= 0 or sigma <= 0:
        return 0.0
    d1 = (log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * sqrt(T))
    return _norm_pdf(d1) / (S * sigma * sqrt(T))


def _option_chain_retry(tk, expiry, retries=2):
    last = None
    for a in range(retries + 1):
        try:
            return tk.option_chain(expiry)
        except Exception as e:                       # noqa: BLE001
            last = e
            time.sleep(0.4 * (a + 1))
    raise last if last else RuntimeError("option_chain failed")


def compute_homebrew_gex(symbol, now_utc, r):
    """Return (reading dict | None, n_expiries_succeeded)."""
    tk = yf.Ticker(symbol)
    spot = None
    try:
        spot = float(tk.fast_info["last_price"])
    except Exception:
        pass
    if not spot or spot <= 0:
        spot = float(tk.history(period="1d")["Close"].iloc[-1])

    exps = tk.options or []
    sel = []
    for e in exps:
        try:
            days = (datetime.strptime(e, "%Y-%m-%d").date() - now_utc.date()).days
        except Exception:
            continue
        if 0 <= days <= HGEX_LOOKAHEAD_DAYS:
            sel.append(e)
    sel = sel[:HGEX_MAX_EXPIRIES]

    by_strike, call_by, put_by = {}, {}, {}
    n_contracts = 0
    n_ok_exp = 0
    dbg = None
    for e in sel:
        try:
            oc = _option_chain_retry(tk, e, 2)
        except Exception as ex:                      # noqa: BLE001
            print("  hgex {} expiry {} failed: {}".format(symbol, e, ex))
            continue
        exp_dt = datetime.strptime(e, "%Y-%m-%d").replace(
            hour=20, minute=0, tzinfo=timezone.utc)   # ~16:00 ET
        T = (exp_dt - now_utc).total_seconds() / (365.0 * 86400.0)
        if T < 1.0 / 365.0:
            T = 1.0 / 365.0
        n_ok_exp += 1
        for df, is_call in [(oc.calls, True), (oc.puts, False)]:
            if df is None or df.empty:
                continue
            for K, oi, iv in zip(df["strike"], df["openInterest"], df["impliedVolatility"]):
                try:
                    K, oi, iv = float(K), float(oi), float(iv)
                except (TypeError, ValueError):
                    continue
                # NaN-safe: NaN fails every comparison, so reject explicitly.
                if not (K == K and oi == oi and iv == iv):
                    continue
                if oi <= 0 or iv <= 0.001 or iv > 5.0:
                    continue
                g = bs_gamma(spot, K, T, iv, r)
                dollar = g * oi * 100.0 * spot * spot * 0.01   # $ per 1% move
                signed = dollar if is_call else -dollar
                by_strike[K] = by_strike.get(K, 0.0) + signed
                (call_by if is_call else put_by)[K] = \
                    (call_by if is_call else put_by).get(K, 0.0) + dollar
                n_contracts += 1
                if dbg is None:
                    dbg = (e, is_call, K, oi, iv, T, g, signed)
        time.sleep(0.25)                             # gentle on Yahoo in CI

    if n_ok_exp < 3:
        return None, n_ok_exp

    net_gex = sum(by_strike.values()) / 1e9          # $bn per 1% move
    strikes = sorted(by_strike.keys())

    # Gamma flip: zero crossing of cumulative-from-low profile nearest spot.
    flip, cum, prev_s, prev_c, crossings = None, 0.0, None, None, []
    for K in strikes:
        cum += by_strike[K]
        if prev_c is not None and prev_c != 0 and (prev_c < 0) != (cum < 0):
            x = prev_s + (K - prev_s) * (0.0 - prev_c) / (cum - prev_c) if cum != prev_c else K
            crossings.append(x)
        prev_s, prev_c = K, cum
    if crossings:
        flip = min(crossings, key=lambda x: abs(x - spot))

    walls = [(round(k, 2), v / 1e9) for k, v in
             sorted(by_strike.items(), key=lambda kv: -abs(kv[1]))[:3]]
    call_wall = max(call_by.items(), key=lambda kv: kv[1])[0] if call_by else None
    put_wall  = max(put_by.items(),  key=lambda kv: kv[1])[0] if put_by  else None
    lo, hi = spot * 0.9, spot * 1.1
    profile = [(round(k, 2), round(by_strike[k] / 1e9, 4)) for k in strikes if lo <= k <= hi]

    if dbg:
        print("  hgex BS check {}: exp={} {} K={} OI={:.0f} IV={:.3f} T={:.4f} "
              "gamma={:.3e} $gamma/1%={:+.3e}".format(
                  symbol, dbg[0], "call" if dbg[1] else "put", dbg[2],
                  dbg[3], dbg[4], dbg[5], dbg[6], dbg[7]))
    return {
        "symbol": symbol, "spot": spot, "net_gex": net_gex, "flip": flip,
        "call_wall": call_wall, "put_wall": put_wall, "walls": walls,
        "n_expiries": n_ok_exp, "n_contracts": n_contracts, "profile": profile,
    }, n_ok_exp


hgex_state = load_hgex_state(_prev_html)
hgex_results = {}
r_gex = (sofr_current / 100.0) if sofr_current else 0.05
hgex_today = gex_now.strftime("%Y-%m-%d")
for _sym in HOMEBREW_GEX_SYMBOLS:
    _reading, _nexp = None, 0
    try:
        _reading, _nexp = compute_homebrew_gex(_sym, gex_now, r_gex)
    except Exception as e:                           # noqa: BLE001
        print("hgex {} error (non-fatal): {}".format(_sym, e))
    snaps = hgex_state.get(_sym, {})
    cached = False
    if _reading:
        snaps[hgex_today] = {
            "net_gex": _reading["net_gex"], "flip": _reading["flip"],
            "spot": _reading["spot"], "n_expiries": _reading["n_expiries"],
            "n_contracts": _reading["n_contracts"]}
        if len(snaps) > HGEX_SNAP_MAX:
            for d in sorted(snaps.keys())[:-HGEX_SNAP_MAX]:
                del snaps[d]
        hgex_state[_sym] = snaps
    elif snaps:
        last = sorted(snaps.keys())[-1]
        s = snaps[last]
        _reading = {"symbol": _sym, "spot": s.get("spot"), "net_gex": s.get("net_gex"),
                    "flip": s.get("flip"), "call_wall": None, "put_wall": None,
                    "walls": [], "n_expiries": s.get("n_expiries", 0),
                    "n_contracts": s.get("n_contracts", 0), "profile": [], "cached_date": last}
        cached = True
    else:
        hgex_results[_sym] = {"ok": False, "n_expiries": _nexp}
        print("  hgex {}: no data (expiries ok={}), no cached snapshot".format(_sym, _nexp))
        continue
    hist_vals = [v["net_gex"] for v in snaps.values() if v.get("net_gex") is not None]
    n_days = len(snaps)
    pctile = pct_of(hist_vals, _reading["net_gex"]) if n_days >= HGEX_PCTILE_MIN_DAYS else float("nan")
    rec = {"ok": True, "cached": cached, "pctile": pctile, "n_days": n_days}
    rec.update(_reading)
    hgex_results[_sym] = rec
    print("  hgex {} net={:+.2f}$bn/1% spot={:.2f} flip={} walls={} exp={} contracts={} days={} cached={}".format(
        _sym, _reading["net_gex"], _reading["spot"],
        "{:.2f}".format(_reading["flip"]) if _reading.get("flip") else "none",
        [w[0] for w in _reading.get("walls", [])], _reading["n_expiries"],
        _reading["n_contracts"], n_days, cached))

# Dealer-gamma signal source resolution (Part A4): homebrew SPY -> NVDA -> N/A
spy_res = hgex_results.get("SPY", {})
qqq_res = hgex_results.get("QQQ", {})
hgex_spy_has = bool(spy_res.get("ok")) and spy_res.get("net_gex") is not None
hgex_spy_net = spy_res.get("net_gex") if hgex_spy_has else None
if hgex_spy_has:
    dg_has, dg_source = True, "SPY GEX (homebrew)"
    dg_positive = hgex_spy_net >= 0
    dg_val_txt = "{:+.2f} $bn/1%".format(hgex_spy_net)
elif gex_nvda["has"]:
    dg_has, dg_source = True, "NVDA proxy (fallback)"
    dg_positive = gex_nvda["positive"]
    dg_val_txt = gex_monitor.fmt_gex(gex_nvda["net_gex"])
else:
    dg_has, dg_source, dg_positive, dg_val_txt = False, "N/A", False, "N/A"

# Amplification badge source (homebrew SPY/QQQ negative -> else NVDA)
_hb_any = hgex_spy_has or (qqq_res.get("ok") and qqq_res.get("net_gex") is not None)
if _hb_any:
    amp_neg = (hgex_spy_has and hgex_spy_net < 0) or \
              (qqq_res.get("ok") and qqq_res.get("net_gex") is not None and qqq_res["net_gex"] < 0)
    amp_src = "SPY/QQQ"
else:
    amp_neg = gex_nvda["has"] and not gex_nvda["positive"]
    amp_src = "NVDA"
print("Dealer-gamma signal: source={} positive={} amp_neg={} ({})".format(
    dg_source, dg_positive if dg_has else "N/A", amp_neg, amp_src))

# ---------------------------------------------------------------------------
# Pre-compute display values
# ---------------------------------------------------------------------------
sig_count = sum([vix_contango, btc_pos, eth_pos, cta_covering, corr_declining])
now_str   = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

cls_vix = "green" if vix_contango   else "red"
cls_btc = "green" if btc_pos        else "red"
cls_cot = "green" if cta_covering   else "red"
cls_cor = "green" if corr_declining else "yellow"
cls_fun = "green" if (btc_pos and eth_pos) else ("yellow" if (btc_pos or eth_pos) else "red")

bdg_vix = "badge-green" if vix_contango   else "badge-red"
bdg_cot = "badge-green" if cta_covering   else "badge-red"
bdg_cor = "badge-green" if corr_declining else "badge-yellow"
bdg_fun = "badge-green" if (btc_pos and eth_pos) else ("badge-yellow" if (btc_pos or eth_pos) else "badge-red")

txt_vix = "CONTANGO ✅" if vix_contango   else "BACKWARDATION ⚠️"
txt_cot = "SHORT COVERING ✅" if cta_covering else "ADDING SHORTS ⚠️"
txt_cor = "DECLINING ✅"      if corr_declining else "ELEVATED ⚠️"
if btc_pos and eth_pos:
    txt_fun = "BOTH POSITIVE ✅ — Risk appetite returning"
elif btc_pos or eth_pos:
    txt_fun = "MIXED ⚠️ — Partial recovery"
else:
    txt_fun = "BOTH NEGATIVE ⚠️ — Still de-risking"

if sig_count <= 1:
    cmsg, ccol = "No signals confirmed — stay out", "#ef4444"
elif sig_count == 2:
    cmsg, ccol = "Watch closely — de-lever may be abating", "#f59e0b"
elif sig_count == 3:
    cmsg, ccol = "Threshold reached: mechanical selling likely exhausting", "#10b981"
elif sig_count == 4:
    cmsg, ccol = "Strong confirmation — consider re-entry on core names", "#10b981"
else:
    cmsg, ccol = "All signals confirmed — de-lever complete, re-engage", "#10b981"

dots = ""
for lbl, ok in [("VIX Contango", vix_contango), ("BTC FR+", btc_pos),
                ("ETH FR+", eth_pos), ("CTA Covering", cta_covering), ("Corr Declining", corr_declining)]:
    css = "filled" if ok else "empty"
    dots = dots + '<div class="dot ' + css + '" title="' + lbl + '"></div>'

s_vdiff = "{:+.2f}".format(vix3m_val - vix_val)
s_v9d   = "{:.1f}".format(vix9d_val)
s_vix   = "{:.1f}".format(vix_val)
s_v3m   = "{:.1f}".format(vix3m_val)
s_btc   = "{:+.4f}".format(btc_fr)
s_eth   = "{:+.4f}".format(eth_fr)
s_okx   = "{:+.4f}".format(okx_disp)
s_cnet  = "{:,}".format(cot_net)
s_cpct  = "{:.1f}".format(cot_pct)
s_cchg  = "{:+,}".format(cot_change)
s_c2w   = "{:.3f}".format(avg_c2w)
s_c1m   = "{:.3f}".format(avg_c1m)
s_ymax  = "{:.2f}".format(max(vix9d_val, vix_val, vix3m_val) * 1.25)
s_v9d_n = str(round(vix9d_val, 2))
s_vix_n = str(round(vix_val,   2))
s_v3m_n = str(round(vix3m_val, 2))

j_vd = json.dumps(vix_dates)
j_vv = json.dumps(vix_vals_list)
j_cd = json.dumps(cot_dates_list)
j_cv = json.dumps(cot_vals_list)
j_cot_charts = json.dumps({k: m["_chart"] for k, m in cot_markets.items() if "_chart" in m},
                          separators=(",", ":")).replace("</", "<\\/")
j_rd = json.dumps(corr_dates)
j_rh = json.dumps(corr_hist)
j_rf = json.dumps([0.5] * len(corr_dates))


def lpi_band(v):
    if v != v:
        return "#64748b", "gray", "Insufficient data"
    if v < 40:
        return "#10b981", "green", "Cushion Thick / Market Resilient 库存充足"
    if v < 60:
        return "#f59e0b", "yellow", "Neutral / Watch for inflection 中性"
    if v < 80:
        return "#f97316", "orange", "Elevated / Reduce leverage, widen hedges 偏高"
    return "#ef4444", "red", "Extreme / Tail risk 5x normal — reduce exposure 极端"


lpi_col, lpi_cls, lpi_status = lpi_band(lpi_composite)
s_lpi = "{:.1f}".format(lpi_composite) if lpi_has else "N/A"
lpi_pos = max(0.0, min(100.0, lpi_composite)) if lpi_has else 0.0
s_lpi_pos = "{:.1f}".format(lpi_pos)
lpi_factors_used = "{}/4 factors".format(len(avail_pct)) if lpi_has else "no factors available"

ARROW = {"up": "▲", "down": "▼", "flat": "▬"}
ARROW_COL = {"up": "#ef4444", "down": "#10b981", "flat": "#64748b"}

lpi_bars = ""
for k in lpi_order:
    lbl = lpi_labels[k]
    if lpi_ok.get(k):
        v = float(lpi_pct[k].dropna().iloc[-1])
        bcol, bcls, _ = lpi_band(v)
        vtxt = "{:.0f}".format(v)
        wpct = "{:.1f}".format(max(0.0, min(100.0, v)))
        d = factor_dir.get(k, "flat")
        arr = ('<span style="color:' + ARROW_COL[d] + ';font-size:11px;margin-left:5px">'
               + ARROW[d] + '</span>')
    else:
        bcol, vtxt, wpct, arr = "#64748b", "N/A", "0", ""
    amp_badge = ""
    if k == "vol_amplifier" and amp_neg:
        amp_badge = ('<div class="lpi-amp-badge">' + amp_src + ' negative gamma — '
                     'shock amplification regime</div>')
    lpi_bars = (lpi_bars
        + '<div class="lpi-factor">'
        + '<div class="lpi-factor-top"><span class="lpi-factor-lbl">' + lbl + '</span>'
        + '<span class="lpi-factor-val" style="color:' + bcol + '">' + vtxt + arr + '</span></div>'
        + '<div class="lpi-track"><div class="lpi-fill" style="width:' + wpct + '%;background:' + bcol + '"></div></div>'
        + amp_badge
        + '</div>')


def _fmt_raw(k, fmt, *args):
    return fmt.format(*args) if lpi_ok.get(k) else "N/A"
s_lpi_sofr   = _fmt_raw("short_rate", "{:.2f}%", lpi_raw.get("short_rate", 0))
s_lpi_iss    = _fmt_raw("duration_supply", "${:.0f}B", lpi_raw.get("duration_supply", 0))
s_lpi_netliq = _fmt_raw("net_liquidity", "${:.2f}T", lpi_raw.get("net_liquidity", 0))
s_lpi_vix    = _fmt_raw("vol_amplifier", "{:.1f}", lpi_raw.get("vol_amplifier", 0))

j_lpi_d = json.dumps(lpi_hist_dates)
j_lpi_v = json.dumps(lpi_hist_vals)
j_lpi_fd = json.dumps(lpi_full_dates)
j_lpi_fv = json.dumps(lpi_full_vals)

# --- Tail table HTML ---
def _pct(x, dp=1):
    return ("{:+." + str(dp) + "f}%").format(x) if x == x else "N/A"
def _pctu(x, dp=1):
    return ("{:." + str(dp) + "f}%").format(x) if x == x else "N/A"

tail_rows_html = ""
tail_readout = ""
if tail_ok:
    row_defs = [("ALL", "All weeks (baseline)")] + [(b[2], b[2]) for b in LPI_BANDS]
    for key, label in row_defs:
        for h in (4, 8):
            st = tail_table.get(key, {}).get(h)
            hl = (key == current_band and key != "ALL")
            rcls = ' class="tail-hl"' if hl else ''
            if not st:
                tail_rows_html += ('<tr' + rcls + '><td>' + label + '</td><td>' + str(h) + 'w</td>'
                                   + '<td colspan="6" style="color:#64748b">insufficient</td></tr>')
                continue
            tail_rows_html += ('<tr' + rcls + '>'
                + '<td>' + label + '</td>'
                + '<td>' + str(h) + 'w</td>'
                + '<td>' + str(st["n"]) + '</td>'
                + '<td>' + _pct(st["mean_ret"] * 100) + '</td>'
                + '<td>' + _pct(st["med_ret"] * 100) + '</td>'
                + '<td>' + _pctu(st["vol"] * 100.0) + '</td>'
                + '<td>' + _pctu(st["p5"]) + '</td>'
                + '<td>' + _pctu(st["p10"]) + '</td>'
                + '<td>' + _pct(st["avg_dd"]) + '</td>'
                + '</tr>')
    # auto readout for current band (4w) vs baseline
    if current_band and current_band in tail_table:
        cur = tail_table[current_band][4]
        base = tail_table["ALL"][4]
        if cur and base:
            ratio = (cur["p10"] / base["p10"]) if base["p10"] > 0 else float("nan")
            ratio_txt = ("{:.1f}×".format(ratio) if ratio == ratio else "n/a")
            tail_readout = ("Current LPI {:.0f} → band {}: historically mean 4-week return {} "
                            "(vs {} baseline) but P(&gt;10% drawdown) {} vs {} baseline — "
                            "tail risk ~{} normal.").format(
                lpi_composite, current_band,
                _pct(cur["mean_ret"] * 100), _pct(base["mean_ret"] * 100),
                _pctu(cur["p10"]), _pctu(base["p10"]), ratio_txt)

# --- Regime + breadth HTML ---
s_d13 = ("{:+.1f}".format(dlpi_13w) if dlpi_13w == dlpi_13w else "N/A")
s_d4  = ("{:+.1f}".format(dlpi_4w) if dlpi_4w == dlpi_4w else "N/A")
breadth_txt = "{}/4 factors &gt;70th and rising".format(breadth)

# 2x2 matrix quadrant highlight: rows High(top)/Low(bottom), cols Falling-Flat / Rising
mtx_active = None
if lpi_has:
    col = "R" if reg_dir == "Rising" else "L"
    mtx_active = reg_level[0] + col   # e.g. 'HR','HL','LR','LL'
mtx_cells = [
    ("HL", "High · Fall/Flat", "Decompress / stable", "#14b8a6"),
    ("HR", "High · Rising", "Danger zone", "#ef4444"),
    ("LL", "Low · Fall/Flat", "Cushion thick", "#10b981"),
    ("LR", "Low · Rising", "Inflection watch", "#f59e0b"),
]
mtx_html = ""
for cellkey, top, sub, ccol_ in mtx_cells:
    active = (cellkey == mtx_active)
    style = ("background:" + ccol_ + ";color:#0d0f14" if active
             else "background:#0f131b;color:#64748b;border:1px solid #2d3748")
    mtx_html += ('<div class="mtx-cell" style="' + style + '">'
                 + '<div class="mtx-top">' + top + '</div>'
                 + '<div class="mtx-sub">' + sub + '</div></div>')

# --- COT crowding HTML ---
def _cot_card(m):
    net = m["net"]
    chg = m.get("chg4", float("nan"))
    cls = "green" if net >= 0 else "red"
    arrow = "▲" if (chg == chg and chg > 0) else ("▼" if (chg == chg and chg < 0) else "▬")
    acol = "#10b981" if (chg == chg and chg > 0) else ("#ef4444" if (chg == chg and chg < 0) else "#64748b")
    pct = m.get("pct", float("nan"))
    z = m.get("z", float("nan"))
    p = []
    p.append('<div class="cot-card ' + cls + '">')
    p.append('<div class="cot-card-head"><span class="cot-sym">' + m["label"] + '</span>'
             + '<span class="cot-arrow" style="color:' + acol + '">' + arrow + '</span></div>')
    p.append('<div class="cot-net ' + cls + '">' + "{:+,}".format(int(net)) + '</div>')
    net_lbl = "MM net contracts" if m.get("kind") == "dis" else "lev net contracts"
    p.append('<div class="cot-sub">' + net_lbl + ' · 4w '
             + ("{:+,}".format(int(chg)) if chg == chg else "N/A") + '</div>')
    p.append('<div class="cot-metrics"><span>pctile <b>' + ("{:.0f}".format(pct) if pct == pct else "N/A")
             + '</b></span><span>z <b>' + ("{:+.1f}".format(z) if z == z else "N/A") + '</b></span></div>')
    p.append('<div class="cot-track"><div class="cot-fill" style="width:'
             + ("{:.0f}".format(max(0, min(100, pct))) if pct == pct else "0")
             + '%;background:' + ("#ef4444" if pct == pct and pct >= 80 else "#6366f1") + '"></div></div>')
    if m.get("_chart"):
        p.append('<div class="cot-chart" id="cot-chart-' + m["key"] + '"></div>')
    else:
        p.append('<div class="cot-chart cot-chart-empty">chart data unavailable</div>')
    p.append('<div class="cot-foot">' + m["contract"] + '</div>')
    p.append('</div>')
    return "".join(p)

cot_equity_html = "".join(_cot_card(cot_markets[k]) for k, *_ in EQUITY_MARKETS if k in cot_markets)
cot_rates_html  = "".join(_cot_card(cot_markets[k]) for k, *_ in RATES_MARKETS if k in cot_markets)
cot_ctx_list = [c for c in CONTEXT_MARKETS] + [USD_MARKET]
cot_ctx_html = "".join(_cot_card(cot_markets[k]) for k, *_ in cot_ctx_list if k in cot_markets)

# COT freshness banner
if cot_report_date:
    fresh_cls = "cot-stale" if cot_stale else "cot-fresh"
    fresh_txt = ("as of " + cot_report_date
                 + (" — STALE (" + str(age_days) + "d, holiday delay?)" if cot_stale
                    else " — " + (str(age_days) + "d old" if age_days is not None else "")))
else:
    fresh_cls, fresh_txt = "cot-stale", "COT unavailable"

# --- Basis-trade proxy HTML ---
basis_has = basis_proxy == basis_proxy
s_basis = "{:.0f}".format(basis_proxy) if basis_has else "N/A"
if not basis_has:
    basis_col, basis_msg = "#64748b", "Insufficient rates COT data"
elif basis_proxy >= 80:
    basis_col, basis_msg = "#ef4444", "Basis trade crowded — issuance shocks amplified"
elif basis_proxy >= 60:
    basis_col, basis_msg = "#f97316", "Elevated AM-long / LF-short configuration"
elif basis_proxy >= 40:
    basis_col, basis_msg = "#f59e0b", "Moderate positioning"
else:
    basis_col, basis_msg = "#10b981", "Positioning benign vs history"
s_basis_pos = "{:.1f}".format(max(0.0, min(100.0, basis_proxy))) if basis_has else "0"

basis_bars_html = ""
tenor_lbls = {"UST2Y": "2Y", "UST5Y": "5Y", "UST10Y": "10Y"}
for tk in ["UST2Y", "UST5Y", "UST10Y"]:
    t = basis_tenors.get(tk)
    if not t:
        continue
    sc = t["score"]
    basis_bars_html += ('<div class="lpi-factor">'
        + '<div class="lpi-factor-top"><span class="lpi-factor-lbl">' + tenor_lbls[tk]
        + ' (AM long ' + "{:.0f}".format(t["am_pct"]) + ' / LF short ' + "{:.0f}".format(t["lev_short_pct"]) + ')</span>'
        + '<span class="lpi-factor-val" style="color:' + basis_col + '">' + "{:.0f}".format(sc) + '</span></div>'
        + '<div class="lpi-track"><div class="lpi-fill" style="width:' + "{:.1f}".format(max(0, min(100, sc)))
        + '%;background:' + basis_col + '"></div></div></div>')

# --- Summary strip ---
strip_lpi = (s_lpi + " <span style=\"color:" + reg_col + "\">" + reg_dir + "</span>") if lpi_has else "N/A"

# ---------------------------------------------------------------------------
# Key Takeaway (Part B) — deterministic, rule-based, bilingual. No LLM.
# One sentence per layer + a synthesis stance from a decision table. Every
# clause degrades to "data unavailable" rather than crashing or fabricating.
# Language is strictly about sizing / hedging / fragility — never directional.
# ---------------------------------------------------------------------------
def takeaway_stance(level, direction, basis, gex_sign, lpi):
    """Return (english_stance, chinese_tag, color) from the decision table."""
    crowded = (basis == basis) and basis >= 80
    gex_neg = gex_sign == "negative"
    if lpi == lpi and lpi >= 80:
        return ("Extreme fragility — defensive posture: minimize leverage and carry robust hedges.",
                "极端压力—防守", "#ef4444")
    if (gex_neg and lpi == lpi and lpi >= 60):
        return ("Reduce leverage and widen hedges — dealer gamma is negative into an elevated-fragility tape (amplification regime).",
                "降杠杆加对冲", "#ef4444")
    if level == "High" and direction == "Rising":
        return ("Reduce leverage and widen hedges — fragility is high and still rising (amplification regime).",
                "降杠杆加对冲", "#ef4444")
    if level == "High" and direction == "Falling":
        return ("Decompression: pressure receding from highs — a measured re-engagement window per the de-lever signals.",
                "关注拐点", "#14b8a6")
    if level == "Low" and direction == "Rising":
        return ("Inflection watch: pressure is building from a low base — begin staging hedges.",
                "关注拐点", "#f59e0b")
    if level == "Low" and crowded:
        return ("Cushion is thick today, but crowded basis positioning makes issuance events the tail to watch — keep calendar hedges around auction / refunding windows.",
                "保持仓位—关注基差", "#f59e0b")
    if level == "Low":
        base = "Full risk budget; the liquidity cushion is thick"
        return ((base + " and dealers are dampening.") if gex_sign == "positive" else (base + "."),
                "保持仓位", "#10b981")
    return ("Elevated but stable — keep hedges on and size moderately.", "关注拐点", "#f97316")


def build_takeaway():
    sents = []
    # 1 — Fragility
    if lpi_has:
        s = ("Fragility: LPI {:.0f} ({} · {}), ΔLPI 13w {}, breadth {}/4 factors "
             "elevated-and-rising.").format(lpi_composite, reg_level, reg_dir, s_d13, breadth)
        t8 = tail_table.get(current_band, {}).get(8) if tail_ok else None
        b8 = tail_table.get("ALL", {}).get(8) if tail_ok else None
        if t8 and b8:
            s += (" In band {}, 8-week P(>10% drawdown) was {} vs {} baseline.").format(
                current_band, _pctu(t8["p10"]), _pctu(b8["p10"]))
        sents.append(s)
    else:
        sents.append("Fragility: LPI data unavailable this run.")

    # 2 — Crowding
    bits2 = []
    if basis_has:
        bits2.append("basis-trade proxy {:.0f} ({})".format(basis_proxy, basis_msg[0].lower() + basis_msg[1:]))
    eq = [(k, cot_markets[k]) for k in ["SPX", "NQ", "RTY"] if k in cot_markets]
    if eq:
        k, m = max(eq, key=lambda km: abs((km[1].get("pct", 50) or 50) - 50))
        ztxt = "{:+.1f}".format(m["z"]) if m.get("z") == m.get("z") else "n/a"
        pv = m.get("pct", float("nan"))
        bits2.append("most-extreme equity positioning {} at {} pctile (z {})".format(
            m["label"], "{:.0f}th".format(pv) if pv == pv else "n/a", ztxt))
    sents.append(("Crowding: " + "; ".join(bits2) + ".") if bits2
                 else "Crowding: positioning data unavailable this run.")

    # 3 — Amplifiers
    bits3 = []
    if dg_has:
        tag = "positive / dampening" if dg_positive else "negative / amplifying"
        if hgex_spy_has and spy_res.get("flip") and spy_res.get("spot"):
            fp = (spy_res["flip"] - spy_res["spot"]) / spy_res["spot"] * 100.0
            flip_clause = "flip {:+.1f}% vs spot".format(fp)
            if dg_source.endswith(")"):
                src = dg_source[:-1] + ", " + flip_clause + ")"
            else:
                src = dg_source + " (" + flip_clause + ")"
            bits3.append("dealer gamma {} via {}".format(tag, src))
        else:
            bits3.append("dealer gamma {} via {}".format(tag, dg_source))
    else:
        bits3.append("dealer gamma unavailable")
    bits3.append("VIX term structure in " + ("contango" if vix_contango else "backwardation"))
    bits3.append("crypto funding " + ("positive" if (btc_pos and eth_pos)
                 else ("mixed" if (btc_pos or eth_pos) else "negative")))
    bits3.append("{}/5 de-lever signals confirmed".format(sig_count))
    sents.append("Amplifiers: " + "; ".join(bits3) + ".")

    gsign = ("positive" if dg_positive else "negative") if dg_has else None
    st_en, st_cn, st_col = takeaway_stance(
        reg_level, reg_dir, basis_proxy, gsign, lpi_composite if lpi_has else float("nan"))
    return sents, st_en, st_cn, st_col


tk_sents, tk_stance_en, tk_stance_cn, tk_stance_col = build_takeaway()
print("Key Takeaway stance:", tk_stance_en, "|", tk_stance_cn)

# Decision-table demonstration (forced combos) + degraded-mode check for logs
for _combo in [("Low", "Falling", 40.0, "positive", 35.0),
               ("Low", "Rising", 50.0, "positive", 45.0),
               ("High", "Rising", 85.0, "negative", 72.0),
               ("High", "Falling", 60.0, "positive", 66.0),
               ("Low", "Falling", 92.0, "positive", 38.0)]:
    print("  stance{} -> {} | {}".format(_combo, *takeaway_stance(*_combo)[:2]))

j_gex_d = gex_hist_d
j_gex_v = gex_hist_v

# Homebrew GEX display precompute
def _fmt_bn(v):
    return "{:+.2f}".format(v) if (v is not None and v == v) else "N/A"

hgex_spy_profile = spy_res.get("profile", []) if spy_res.get("ok") else []
j_hgex_strk = json.dumps([p[0] for p in hgex_spy_profile])
j_hgex_val  = json.dumps([p[1] for p in hgex_spy_profile])
hgex_spy_spot = spy_res.get("spot") if spy_res.get("ok") else None
hgex_spy_flip = spy_res.get("flip") if spy_res.get("ok") else None
j_hgex_spot = json.dumps(hgex_spy_spot if (hgex_spy_spot and hgex_spy_spot == hgex_spy_spot) else None)
j_hgex_flip = json.dumps(hgex_spy_flip if (hgex_spy_flip and hgex_spy_flip == hgex_spy_flip) else None)

# ---------------------------------------------------------------------------
# HTML assembly (Part C: three-layer architecture)
# ---------------------------------------------------------------------------
parts = []
parts.append('<!DOCTYPE html>')
parts.append('<html lang="en"><head>')
parts.append('<meta charset="UTF-8">')
parts.append('<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0">')
parts.append('<title>De-Lever Signal Dashboard</title>')
parts.append('<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>')
parts.append('<style>')
parts.append('*{box-sizing:border-box;margin:0;padding:0}')
parts.append('body{background:#0d0f14;color:#e2e8f0;font-family:-apple-system,BlinkMacSystemFont,sans-serif}')
parts.append('.header{background:#141720;border-bottom:1px solid #2d3748;padding:14px 20px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px}')
parts.append('.header-left h1{font-size:16px;font-weight:700}')
parts.append('.header-left h1 span{color:#6366f1}')
parts.append('.header-left p{font-size:11px;color:#475569;margin-top:2px}')
parts.append('.timestamp{font-size:11px;color:#64748b}')
parts.append('.summary-strip{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;padding:14px 20px}')
parts.append('@media(max-width:600px){.summary-strip{grid-template-columns:1fr}}')
parts.append('.summary-cell{background:#141720;border:1px solid #2d3748;border-radius:10px;padding:12px 16px}')
parts.append('.summary-cell .lbl{font-size:10px;color:#64748b;text-transform:uppercase;letter-spacing:.08em}')
parts.append('.summary-cell .val{font-size:26px;font-weight:800;margin-top:4px;line-height:1}')
parts.append('.summary-cell .sub{font-size:11px;color:#94a3b8;margin-top:4px}')
parts.append('.layer-header{margin:24px 20px 12px;padding-bottom:7px;border-bottom:2px solid #2d3748;font-size:15px;font-weight:800;color:#e2e8f0}')
parts.append('.layer-header span{color:#6366f1;font-size:12px;font-weight:600}')
parts.append('.layer-header .tf{float:right;font-size:10px;color:#475569;font-weight:500;text-transform:uppercase;letter-spacing:.06em}')
parts.append('.signal-bar{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;padding:0 20px 16px}')
parts.append('@media(max-width:900px){.signal-bar{grid-template-columns:repeat(2,1fr)}}')
parts.append('@media(max-width:480px){.signal-bar{grid-template-columns:1fr}}')
parts.append('.signal-card{background:#141720;border:1px solid #2d3748;border-radius:10px;padding:14px 16px}')
parts.append('.signal-card.green{border-left:3px solid #10b981}')
parts.append('.signal-card.red{border-left:3px solid #ef4444}')
parts.append('.signal-card.yellow{border-left:3px solid #f59e0b}')
parts.append('.signal-label{font-size:10px;color:#64748b;text-transform:uppercase;letter-spacing:.08em;margin-bottom:5px}')
parts.append('.signal-value{font-size:20px;font-weight:700;margin-bottom:3px;line-height:1.2}')
parts.append('.signal-value.green{color:#10b981}.signal-value.red{color:#ef4444}.signal-value.yellow{color:#f59e0b}')
parts.append('.signal-sub{font-size:11px;color:#64748b;line-height:1.4}')
parts.append('.signal-badge{display:inline-block;font-size:10px;font-weight:600;padding:3px 8px;border-radius:4px;margin-top:7px}')
parts.append('.badge-green{background:rgba(16,185,129,.15);color:#10b981}')
parts.append('.badge-red{background:rgba(239,68,68,.15);color:#ef4444}')
parts.append('.badge-yellow{background:rgba(245,158,11,.15);color:#f59e0b}')
parts.append('.confirm-counter{background:#141720;border:1px solid #2d3748;border-radius:8px;margin:0 20px 16px;padding:12px 16px;display:flex;align-items:center;gap:12px;flex-wrap:wrap}')
parts.append('.confirm-label{font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:.06em;white-space:nowrap}')
parts.append('.confirm-dots{display:flex;gap:6px;flex-shrink:0}')
parts.append('.dot{width:11px;height:11px;border-radius:50%}')
parts.append('.dot.filled{background:#10b981}.dot.empty{background:#2d3748}')
parts.append('.confirm-text{font-size:12px;color:#94a3b8}')
parts.append('.confirm-text strong{color:#e2e8f0}')
parts.append('.lpi-section{margin:0 20px 16px}')
parts.append('.lpi-heading{font-size:13px;font-weight:700;color:#e2e8f0;text-transform:uppercase;letter-spacing:.05em;margin-bottom:10px}')
parts.append('.lpi-heading span{color:#6366f1}')
parts.append('.lpi-gauge{background:#141720;border:1px solid #2d3748;border-radius:10px;padding:16px 18px;margin-bottom:12px}')
parts.append('.lpi-gauge.green{border-left:3px solid #10b981}.lpi-gauge.yellow{border-left:3px solid #f59e0b}')
parts.append('.lpi-gauge.orange{border-left:3px solid #f97316}.lpi-gauge.red{border-left:3px solid #ef4444}.lpi-gauge.gray{border-left:3px solid #64748b}')
parts.append('.lpi-gauge.teal{border-left:3px solid #14b8a6}')
parts.append('.lpi-gauge-top{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;margin-bottom:12px}')
parts.append('.lpi-num{font-size:40px;font-weight:800;line-height:1}')
parts.append('.lpi-scale{font-size:11px;color:#64748b}')
parts.append('.lpi-status{font-size:13px;font-weight:600}')
parts.append('.regime-badge{display:inline-block;font-size:11px;font-weight:700;padding:5px 11px;border-radius:6px;margin-left:auto}')
parts.append('.lpi-meter{position:relative;height:14px;border-radius:7px;background:linear-gradient(90deg,#10b981 0%,#10b981 40%,#f59e0b 40%,#f59e0b 60%,#f97316 60%,#f97316 80%,#ef4444 80%,#ef4444 100%)}')
parts.append('.lpi-marker{position:absolute;top:-4px;width:3px;height:22px;background:#e2e8f0;border-radius:2px;box-shadow:0 0 4px rgba(0,0,0,.6);transform:translateX(-50%)}')
parts.append('.lpi-ticks{display:flex;justify-content:space-between;font-size:9px;color:#475569;margin-top:5px}')
parts.append('.regime-wrap{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px}')
parts.append('@media(max-width:700px){.regime-wrap{grid-template-columns:1fr}}')
parts.append('.regime-box{background:#141720;border:1px solid #2d3748;border-radius:10px;padding:14px 16px}')
parts.append('.regime-box .rb-title{font-size:10px;color:#64748b;text-transform:uppercase;letter-spacing:.06em;margin-bottom:8px}')
parts.append('.regime-msg{font-size:13px;font-weight:600;margin-bottom:6px}')
parts.append('.regime-delta{font-size:11px;color:#94a3b8}')
parts.append('.mtx{display:grid;grid-template-columns:1fr 1fr;gap:6px}')
parts.append('.mtx-cell{border-radius:7px;padding:9px 10px;min-height:52px}')
parts.append('.mtx-top{font-size:10px;font-weight:700}')
parts.append('.mtx-sub{font-size:10px;margin-top:3px;opacity:.85}')
parts.append('.lpi-factors{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:12px}')
parts.append('@media(max-width:900px){.lpi-factors{grid-template-columns:repeat(2,1fr)}}')
parts.append('@media(max-width:480px){.lpi-factors{grid-template-columns:1fr}}')
parts.append('.lpi-factor{background:#141720;border:1px solid #2d3748;border-radius:8px;padding:12px 14px}')
parts.append('.lpi-factor-top{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:8px}')
parts.append('.lpi-factor-lbl{font-size:10px;color:#94a3b8;letter-spacing:.03em}')
parts.append('.lpi-factor-val{font-size:18px;font-weight:700}')
parts.append('.lpi-track{height:6px;border-radius:3px;background:#0a0c10;overflow:hidden}')
parts.append('.lpi-fill{height:100%;border-radius:3px}')
parts.append('.tail-wrap{background:#141720;border:1px solid #2d3748;border-radius:10px;padding:14px 16px;margin-bottom:12px;overflow-x:auto}')
parts.append('.tail-title{font-size:12px;font-weight:700;color:#e2e8f0;text-transform:uppercase;letter-spacing:.04em;margin-bottom:4px}')
parts.append('.tail-readout{font-size:12px;color:#cbd5e1;line-height:1.5;margin-bottom:10px;background:#0f131b;border-left:3px solid #6366f1;padding:8px 11px;border-radius:0 6px 6px 0}')
parts.append('table.tail{width:100%;border-collapse:collapse;font-size:11px;min-width:640px}')
parts.append('table.tail th{text-align:right;color:#64748b;font-weight:600;padding:6px 8px;border-bottom:1px solid #2d3748;font-size:10px;text-transform:uppercase;letter-spacing:.03em}')
parts.append('table.tail th:first-child,table.tail td:first-child{text-align:left}')
parts.append('table.tail td{text-align:right;padding:6px 8px;border-bottom:1px solid #1a1f2b;color:#cbd5e1}')
parts.append('table.tail tr.tail-hl td{background:rgba(99,102,241,.15);color:#e2e8f0;font-weight:700}')
parts.append('.tail-foot{font-size:9px;color:#475569;margin-top:8px;line-height:1.5}')
parts.append('.lpi-cal{background:#141720;border:1px solid #2d3748;border-radius:8px;padding:12px 14px;font-size:11px;color:#94a3b8;line-height:1.7}')
parts.append('.lpi-cal b{color:#e2e8f0}.lpi-cal .hot{color:#f97316}.lpi-cal .cool{color:#10b981}')
parts.append('.cot-section{margin:0 20px 16px}')
parts.append('.cot-fresh{font-size:10px;color:#10b981;background:rgba(16,185,129,.12);padding:4px 9px;border-radius:5px;display:inline-block;margin-bottom:10px}')
parts.append('.cot-stale{font-size:10px;color:#f59e0b;background:rgba(245,158,11,.12);padding:4px 9px;border-radius:5px;display:inline-block;margin-bottom:10px}')
parts.append('.cot-grouplbl{font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:.05em;margin:6px 0 8px}')
parts.append('.cot-cards{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:12px}')
parts.append('@media(max-width:900px){.cot-cards{grid-template-columns:repeat(2,1fr)}}')
parts.append('@media(max-width:480px){.cot-cards{grid-template-columns:1fr}}')
parts.append('.cot-card{background:#141720;border:1px solid #2d3748;border-radius:10px;padding:13px 15px}')
parts.append('.cot-card.green{border-left:3px solid #10b981}.cot-card.red{border-left:3px solid #ef4444}')
parts.append('.cot-card-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:5px}')
parts.append('.cot-sym{font-size:13px;font-weight:700;color:#e2e8f0}')
parts.append('.cot-arrow{font-size:13px}')
parts.append('.cot-net{font-size:21px;font-weight:800;line-height:1.1}')
parts.append('.cot-net.green{color:#10b981}.cot-net.red{color:#ef4444}')
parts.append('.cot-sub{font-size:10px;color:#64748b;margin:3px 0 7px}')
parts.append('.cot-metrics{display:flex;gap:14px;font-size:10px;color:#94a3b8;margin-bottom:7px}')
parts.append('.cot-metrics b{color:#e2e8f0}')
parts.append('.cot-track{height:5px;border-radius:3px;background:#0a0c10;overflow:hidden}')
parts.append('.cot-fill{height:100%;border-radius:3px}')
parts.append('.cot-chart{width:100%;height:230px;margin:8px 0 2px}')
parts.append('.cot-chart-empty{display:flex;align-items:center;justify-content:center;color:#475569;font-size:11px}')
parts.append('.cot-foot{font-size:9px;color:#475569;margin-top:6px}')
parts.append('.gex-section{margin:0 20px 16px}')
parts.append('.gex-heading{font-size:13px;font-weight:700;color:#e2e8f0;text-transform:uppercase;letter-spacing:.05em;margin-bottom:10px}')
parts.append('.gex-heading span{color:#6366f1}')
parts.append('.gex-note-box{background:#141720;border:1px solid #2d3748;border-radius:8px;padding:14px 16px;font-size:12px;color:#94a3b8}')
parts.append('.gex-cards{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:12px}')
parts.append('@media(max-width:900px){.gex-cards{grid-template-columns:repeat(2,1fr)}}')
parts.append('@media(max-width:480px){.gex-cards{grid-template-columns:1fr}}')
parts.append('.gex-card{background:#141720;border:1px solid #2d3748;border-radius:10px;padding:13px 15px}')
parts.append('.gex-card.green{border-left:3px solid #10b981}.gex-card.red{border-left:3px solid #ef4444}.gex-card.gray{border-left:3px solid #64748b}')
parts.append('.gex-card-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:6px}')
parts.append('.gex-card-sym{font-size:14px;font-weight:700;color:#e2e8f0}')
parts.append('.gex-fresh{font-size:9px;color:#10b981;background:rgba(16,185,129,.12);padding:2px 6px;border-radius:4px}')
parts.append('.gex-cached{font-size:9px;color:#f59e0b}')
parts.append('.gex-card-val{font-size:22px;font-weight:800;line-height:1.1}')
parts.append('.gex-card-val.green{color:#10b981}.gex-card-val.red{color:#ef4444}')
parts.append('.gex-card-na{font-size:22px;font-weight:800;color:#64748b}')
parts.append('.gex-card-lbl{font-size:10px;color:#64748b;margin:3px 0 8px}')
parts.append('.gex-flip-txt{font-size:10px;color:#94a3b8;margin-bottom:5px}')
parts.append('.gex-flip-txt .green{color:#10b981}.gex-flip-txt .red{color:#ef4444}')
parts.append('.gex-flip-track{position:relative;height:8px;border-radius:4px;background:linear-gradient(90deg,#ef4444 0%,#ef4444 48%,#334155 48%,#334155 52%,#10b981 52%,#10b981 100%)}')
parts.append('.gex-flip-mid{position:absolute;left:50%;top:-2px;width:1px;height:12px;background:#64748b;transform:translateX(-50%)}')
parts.append('.gex-flip-marker{position:absolute;top:-3px;width:4px;height:14px;border-radius:2px;transform:translateX(-50%)}')
parts.append('.gex-flip-marker.green{background:#10b981}.gex-flip-marker.red{background:#ef4444}')
parts.append('.gex-card-foot{font-size:9px;color:#475569;margin-top:7px}')
parts.append('.gex-card-note{font-size:9px;color:#f59e0b;margin-top:4px}')
parts.append('.gex-quota{font-size:10px;color:#64748b;background:#141720;border:1px solid #2d3748;border-radius:8px;padding:9px 13px}')
parts.append('.gex-quota b{color:#94a3b8}.gex-quota .red{color:#ef4444}.gex-quota .green{color:#10b981}.gex-quota .gray{color:#64748b}')
parts.append('.lpi-amp-badge{display:inline-block;font-size:9px;font-weight:600;color:#ef4444;background:rgba(239,68,68,.15);padding:2px 7px;border-radius:4px;margin-top:6px}')
parts.append('.takeaway{margin:14px 20px 4px;background:#141720;border:1px solid #2d3748;border-radius:12px;padding:16px 18px}')
parts.append('.takeaway-title{font-size:14px;font-weight:800;color:#e2e8f0;margin-bottom:3px}')
parts.append('.takeaway-title span{color:#6366f1;font-size:12px;font-weight:600}')
parts.append('.takeaway-ts{font-size:10px;color:#475569;margin-bottom:10px}')
parts.append('.takeaway-body{font-size:12px;color:#cbd5e1;line-height:1.65;margin-bottom:11px}')
parts.append('.takeaway-body div{margin-bottom:4px}')
parts.append('.takeaway-stance{font-size:13px;font-weight:700;padding:10px 13px;border-radius:0 8px 8px 0;line-height:1.5}')
parts.append('.takeaway-stance .tk-cn{font-weight:800;margin-left:6px}')
parts.append('.hgex-sig{font-size:11px;color:#94a3b8;background:#141720;border:1px solid #2d3748;border-radius:8px;padding:9px 13px;margin-bottom:12px}')
parts.append('.hgex-sig .green{color:#10b981;font-weight:700}.hgex-sig .red{color:#ef4444;font-weight:700}.hgex-sig .gray{color:#64748b;font-weight:700}')
parts.append('.charts-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;padding:0 20px 16px}')
parts.append('@media(max-width:700px){.charts-grid{grid-template-columns:1fr}}')
parts.append('.chart-card{background:#141720;border:1px solid #2d3748;border-radius:10px;padding:14px;min-width:0}')
parts.append('.chart-title{font-size:12px;font-weight:600;color:#94a3b8;text-transform:uppercase;letter-spacing:.05em}')
parts.append('.chart-subtitle{font-size:10px;color:#475569;margin:3px 0 10px;line-height:1.4}')
parts.append('.bottom-bar{background:#0a0c10;border-top:1px solid #1e2433;padding:10px 20px;display:flex;flex-wrap:wrap;gap:16px}')
parts.append('.bottom-item{font-size:10px;color:#475569}.bottom-item span{color:#64748b}')
parts.append('</style></head><body>')

# header
parts.append('<div class="header"><div class="header-left">')
parts.append('<h1>De-Lever Signal Dashboard <span>/ NDX</span></h1>')
parts.append('<p>3-layer risk stack: fragility · crowding · amplifiers &middot; auto-updated every hour</p></div>')
parts.append('<div class="header-right"><div class="timestamp">Last updated: ' + now_str + '</div></div></div>')

# summary strip
parts.append('<div class="summary-strip">')
parts.append('<div class="summary-cell"><div class="lbl">Fragility · LPI + Regime</div>'
             + '<div class="val" style="color:' + lpi_col + '">' + strip_lpi + '</div>'
             + '<div class="sub">' + (reg_msg if lpi_has else "insufficient data") + '</div></div>')
parts.append('<div class="summary-cell"><div class="lbl">Crowding · Basis-Trade Proxy</div>'
             + '<div class="val" style="color:' + basis_col + '">' + s_basis + '</div>'
             + '<div class="sub">' + basis_msg + '</div></div>')
parts.append('<div class="summary-cell"><div class="lbl">Amplifiers · Signals Confirmed</div>'
             + '<div class="val" style="color:' + ccol + '">' + str(sig_count) + '/5</div>'
             + '<div class="sub">' + cmsg + '</div></div>')
parts.append('</div>')

# Key Takeaway card (below summary strip, above Layer 1)
parts.append('<div class="takeaway">')
parts.append('<div class="takeaway-title">关键结论 Key Takeaway <span>rule-based · sizing &amp; hedging only</span></div>')
parts.append('<div class="takeaway-ts">generated ' + now_str + ' &middot; deterministic (no forecast)</div>')
parts.append('<div class="takeaway-body">')
for _s in tk_sents:
    parts.append('<div>' + _s + '</div>')
parts.append('</div>')
parts.append('<div class="takeaway-stance" style="background:' + tk_stance_col
             + '22;border-left:4px solid ' + tk_stance_col + ';color:' + tk_stance_col + '">'
             + 'Stance: ' + tk_stance_en
             + '<span class="tk-cn">' + tk_stance_cn + '</span></div>')
parts.append('</div>')

# ===================== LAYER 1 — FRAGILITY =====================
parts.append('<div class="layer-header">第一层 · 脆弱度 Fragility <span>Liquidity Pressure Index</span>'
             + '<span class="tf">weeks–months</span></div>')

parts.append('<div class="lpi-section">')

# gauge card with regime badge
parts.append('<div class="lpi-gauge ' + reg_cls + '">')
parts.append('<div class="lpi-gauge-top">')
parts.append('<span class="lpi-num" style="color:' + lpi_col + '">' + s_lpi + '</span>')
parts.append('<span class="lpi-scale">/ 100 &middot; ' + lpi_factors_used + '</span>')
parts.append('<span class="lpi-status" style="color:' + lpi_col + '">' + lpi_status + '</span>')
if lpi_has:
    parts.append('<span class="regime-badge" style="background:' + reg_col + ';color:#0d0f14">'
                 + reg_level + ' &middot; ' + reg_dir + '</span>')
parts.append('</div>')
parts.append('<div class="lpi-meter"><div class="lpi-marker" style="left:' + s_lpi_pos + '%"></div></div>')
parts.append('<div class="lpi-ticks"><span>0 Resilient</span><span>40</span><span>60</span><span>80</span><span>100 Extreme</span></div>')
parts.append('</div>')

# regime message + 2x2 matrix
parts.append('<div class="regime-wrap">')
parts.append('<div class="regime-box"><div class="rb-title">Regime &middot; 状态</div>'
             + '<div class="regime-msg" style="color:' + reg_col + '">' + reg_msg + '</div>'
             + '<div class="regime-delta">&Delta;LPI 13w <b style="color:#e2e8f0">' + s_d13
             + '</b> &middot; &Delta;LPI 4w <b style="color:#e2e8f0">' + s_d4
             + '</b> &middot; breadth ' + breadth_txt + '</div></div>')
parts.append('<div class="regime-box"><div class="rb-title">Level × Direction</div>'
             + '<div class="mtx">' + mtx_html + '</div></div>')
parts.append('</div>')

# sub-factor bars (with 4w direction arrows)
parts.append('<div class="lpi-factors">' + lpi_bars + '</div>')

# conditional tail table
if tail_ok:
    parts.append('<div class="tail-wrap">')
    parts.append('<div class="tail-title">Conditional Tail Table &mdash; forward S&amp;P 500 by LPI band</div>')
    if tail_readout:
        parts.append('<div class="tail-readout">' + tail_readout + '</div>')
    parts.append('<table class="tail"><thead><tr>'
                 + '<th>LPI band</th><th>Horizon</th><th>N</th><th>Mean ret</th><th>Median</th>'
                 + '<th>Fwd vol (ann.)</th><th>P(&lt;-5%)</th><th>P(&lt;-10%)</th><th>Avg MaxDD</th>'
                 + '</tr></thead><tbody>' + tail_rows_html + '</tbody></table>')
    parts.append('<div class="tail-foot">Forward windows overlap weekly, which inflates effective N '
                 '(observations are not independent). Max drawdown uses weekly closes and therefore '
                 'understates intraweek troughs. Percentiles feeding each week&rsquo;s LPI are expanding '
                 'and strictly causal (no look-ahead); forward returns are realized outcomes.</div>')
    parts.append('</div>')
else:
    parts.append('<div class="tail-wrap"><div class="tail-title">Conditional Tail Table</div>'
                 '<div style="color:#64748b;font-size:11px">Unavailable (S&amp;P 500 or LPI history missing).</div></div>')

# LPI history charts (52w + full reconstructed)
parts.append('<div class="charts-grid" style="padding:0 0 12px">')
parts.append('<div class="chart-card"><div class="chart-title">LPI &mdash; Trailing 52 Weeks</div>')
parts.append('<div class="chart-subtitle">Composite percentile pressure &middot; thresholds at 60 / 80</div>')
parts.append('<div id="chart-lpi"></div></div>')
parts.append('<div class="chart-card"><div class="chart-title">LPI &mdash; Full Reconstruction</div>')
parts.append('<div class="chart-subtitle">' + str(recon_n) + ' weeks from ' + recon_earliest
             + ' &middot; expanding no-look-ahead percentiles &middot; use range selector</div>')
parts.append('<div id="chart-lpi-full"></div></div>')
parts.append('</div>')

# stress calendar
parts.append('<div class="lpi-cal">')
parts.append('<b>2026 H2 压力日历 (projected stress calendar)</b><br>')
parts.append('<span class="hot">Sep (~79th pct):</span> FOMC Sep 15-16 &middot; corp estimated tax Sep 15 &middot; quarter-end TGA refill Sep 30 &mdash; 4 simultaneous drains<br>')
parts.append('<span class="hot">Nov (2nd highest):</span> quarterly refunding issuance + FOMC late Oct<br>')
parts.append('<span class="hot">Aug (3rd):</span> refunding settlement peak mid-August<br>')
parts.append('<span class="cool">Jul:</span> lowest pressure month of H2')
parts.append('</div>')

parts.append('</div>')  # lpi-section

# ===================== LAYER 2 — CROWDING =====================
parts.append('<div class="layer-header">第二层 · 拥挤度 Crowding <span>CFTC COT positioning</span>'
             + '<span class="tf">weeks</span></div>')
parts.append('<div class="cot-section">')
parts.append('<div class="' + fresh_cls + '">COT ' + fresh_txt + '</div>')

if cot_ok:
    if cot_equity_html:
        parts.append('<div class="cot-grouplbl">Equity index &middot; Leveraged Funds net</div>')
        parts.append('<div class="cot-cards">' + cot_equity_html + '</div>')
    if cot_rates_html:
        parts.append('<div class="cot-grouplbl">Treasury notes &middot; Leveraged Funds net (basis-trade legs)</div>')
        parts.append('<div class="cot-cards">' + cot_rates_html + '</div>')
    if cot_ctx_html:
        parts.append('<div class="cot-grouplbl">Context &middot; Managed Money / lev net</div>')
        parts.append('<div class="cot-cards">' + cot_ctx_html + '</div>')
else:
    parts.append('<div class="gex-note-box">COT data unavailable this run (CFTC outage) '
                 '&mdash; crowding layer degraded, other layers unaffected.</div>')

# basis-trade proxy gauge
parts.append('<div class="lpi-gauge" style="border-left:3px solid ' + basis_col + '">')
parts.append('<div class="lpi-gauge-top">')
parts.append('<span class="lpi-num" style="color:' + basis_col + '">' + s_basis + '</span>')
parts.append('<span class="lpi-scale">/ 100 &middot; basis-trade proxy 基差交易拥挤度</span>')
parts.append('<span class="lpi-status" style="color:' + basis_col + '">' + basis_msg + '</span></div>')
parts.append('<div class="lpi-meter"><div class="lpi-marker" style="left:' + s_basis_pos + '%"></div></div>')
parts.append('<div class="lpi-ticks"><span>0 Benign</span><span>40</span><span>60</span><span>80 Crowded</span><span>100</span></div>')
if basis_bars_html:
    parts.append('<div class="lpi-factors" style="margin-top:12px;margin-bottom:0">' + basis_bars_html + '</div>')
parts.append('<div class="tail-foot">Proxy = mean over 2y/5y/10y of [pctile(Asset-Mgr net long) + pctile(Lev-Fund net short)] / 2, '
             'measuring how extreme the AM-long / LF-short configuration is vs its own history. Not added to the 4-factor LPI '
             'composite (a 5-factor variant is a future option).</div>')
parts.append('</div>')
parts.append('</div>')  # cot-section

# ===================== LAYER 3 — AMPLIFIERS & TRIGGERS =====================
parts.append('<div class="layer-header">第三层 · 放大器与触发器 Amplifiers &amp; Triggers '
             + '<span>de-lever bottom signals + dealer gamma</span><span class="tf">hours–days</span></div>')

# signal bar
parts.append('<div class="signal-bar">')
parts.append('<div class="signal-card ' + cls_vix + '">')
parts.append('<div class="signal-label">&#9312; VIX Term Structure</div>')
parts.append('<div class="signal-value ' + cls_vix + '">' + s_vdiff + ' pts</div>')
parts.append('<div class="signal-sub">VIX9D ' + s_v9d + ' &rarr; VIX ' + s_vix + ' &rarr; VIX3M ' + s_v3m + '</div>')
parts.append('<div class="signal-badge ' + bdg_vix + '">' + txt_vix + '</div></div>')

parts.append('<div class="signal-card ' + cls_fun + '">')
parts.append('<div class="signal-label">&#9313; Crypto Funding (' + src_lbl + ')</div>')
parts.append('<div class="signal-value ' + cls_btc + '">BTC ' + s_btc + '%</div>')
parts.append('<div class="signal-sub">ETH ' + s_eth + '% &middot; OKX BTC ' + s_okx + '%</div>')
parts.append('<div class="signal-badge ' + bdg_fun + '">' + txt_fun + '</div></div>')

parts.append('<div class="signal-card ' + cls_cot + '">')
parts.append('<div class="signal-label">&#9314; CTA Proxy (CFTC COT)</div>')
parts.append('<div class="signal-value ' + cls_cot + '">' + s_cnet + '</div>')
parts.append('<div class="signal-sub">' + s_cpct + '% OI &middot; as of ' + cot_date + '<br>WoW: ' + s_cchg + ' contracts</div>')
parts.append('<div class="signal-badge ' + bdg_cot + '">' + txt_cot + '</div></div>')

parts.append('<div class="signal-card ' + cls_cor + '">')
parts.append('<div class="signal-label">&#9315; Cross-Sector Correlation</div>')
parts.append('<div class="signal-value ' + cls_cor + '">' + s_c2w + '</div>')
parts.append('<div class="signal-sub">2W vs 1M avg: ' + s_c1m + ' &rarr; ' + s_c2w + '</div>')
parts.append('<div class="signal-badge ' + bdg_cor + '">' + txt_cor + '</div></div>')
parts.append('</div>')

# confirm counter
parts.append('<div class="confirm-counter">')
parts.append('<div class="confirm-label">Signals confirmed</div>')
parts.append('<div class="confirm-dots">' + dots + '</div>')
parts.append('<div class="confirm-text"><strong>' + str(sig_count) + '/5</strong> &mdash; <span style="color:' + ccol + '">' + cmsg + '</span></div>')
parts.append('</div>')

# Homebrew Index GEX section (SPY + QQQ)
def _hgex_card(sym):
    res = hgex_results.get(sym, {})
    if not res.get("ok"):
        return ('<div class="gex-card gray"><div class="gex-card-sym">' + sym + '</div>'
                '<div class="gex-card-na">N/A</div>'
                '<div class="gex-card-note">homebrew GEX unavailable (Yahoo options)</div></div>')
    ng = res["net_gex"]
    pos = ng >= 0
    cls = "green" if pos else "red"
    spot, flip = res.get("spot"), res.get("flip")
    q = []
    q.append('<div class="gex-card ' + cls + '">')
    fresh = ('<span class="gex-cached">cached ' + str(res.get("cached_date", "")) + '</span>'
             if res.get("cached") else '<span class="gex-fresh">live</span>')
    q.append('<div class="gex-card-head"><span class="gex-card-sym">' + sym + '</span>' + fresh + '</div>')
    q.append('<div class="gex-card-val ' + cls + '">' + _fmt_bn(ng)
             + ' <span style="font-size:11px;color:#64748b">$bn/1%</span></div>')
    q.append('<div class="gex-card-lbl">net GEX &middot; '
             + ('positive — dealers dampen vol' if pos else 'negative — dealers amplify') + '</div>')
    if flip and spot:
        pctd = (spot - flip) / flip * 100.0
        dcls = "green" if pctd >= 0 else "red"
        dirn = "above" if pctd >= 0 else "below"
        q.append('<div class="gex-flip-txt">Flip ' + "{:.2f}".format(flip) + ' &middot; Spot '
                 + "{:.2f}".format(spot) + ' &middot; <span class="' + dcls + '">spot '
                 + "{:+.1f}%".format(pctd) + ' ' + dirn + ' flip</span></div>')
    elif spot:
        q.append('<div class="gex-flip-txt">Spot ' + "{:.2f}".format(spot)
                 + ' &middot; no gamma flip in range</div>')
    else:
        q.append('<div class="gex-flip-txt">flip / spot unavailable</div>')
    if res.get("walls"):
        wtxt = ", ".join("{:.0f} ({})".format(k, _fmt_bn(v)) for k, v in res["walls"])
        q.append('<div class="gex-card-lbl">gamma walls: ' + wtxt + '</div>')
    cw, pw = res.get("call_wall"), res.get("put_wall")
    if cw and pw:
        q.append('<div class="gex-flip-txt">call wall ' + "{:.0f}".format(cw)
                 + ' &middot; put wall ' + "{:.0f}".format(pw) + '</div>')
    q.append('<div class="gex-card-foot">front ' + str(HGEX_LOOKAHEAD_DAYS) + 'd &middot; '
             + str(res.get("n_expiries", 0)) + ' exp &middot; '
             + str(res.get("n_contracts", 0)) + ' contracts</div>')
    nd = res.get("n_days", 0)
    if nd >= HGEX_PCTILE_MIN_DAYS and res.get("pctile") == res.get("pctile"):
        q.append('<div class="gex-card-note" style="color:#94a3b8">history percentile '
                 + "{:.0f}".format(res["pctile"]) + 'th (' + str(nd) + ' days)</div>')
    else:
        q.append('<div class="gex-card-note" style="color:#64748b">accumulating history ('
                 + str(nd) + '/' + str(HGEX_PCTILE_MIN_DAYS) + ' days)</div>')
    q.append('</div>')
    return "".join(q)

parts.append('<div class="gex-section">')
parts.append('<div class="gex-heading">Index GEX (homebrew) <span>指数伽马 · SqueezeMetrics 约定 · $bn / 1% move</span></div>')
_dg_cls = "green" if (dg_has and dg_positive) else ("red" if dg_has else "gray")
_dg_txt = (("POSITIVE ✅ dealers dampening" if dg_positive else "NEGATIVE ❌ dealers amplifying")
           if dg_has else "N/A — no source available")
parts.append('<div class="hgex-sig">De-lever signal #5 &mdash; Dealer Gamma &middot; source <b>' + dg_source
             + '</b> (' + dg_val_txt + '): <span class="' + _dg_cls + '">' + _dg_txt + '</span></div>')
parts.append('<div class="gex-cards">' + "".join(_hgex_card(s) for s in HOMEBREW_GEX_SYMBOLS) + '</div>')
parts.append('<div class="chart-card" style="margin-bottom:12px"><div class="chart-title">SPY Net GEX by Strike (&plusmn;10% of spot)</div>')
if hgex_spy_profile:
    parts.append('<div class="chart-subtitle">Green = positive gamma (dampening) &middot; red = negative &middot; dashed = spot, solid = gamma flip</div>')
    parts.append('<div id="chart-hgex-spy"></div>')
else:
    parts.append('<div class="chart-subtitle">strike profile unavailable this run</div>')
parts.append('</div>')
parts.append('</div>')  # gex-section (homebrew)
parts.append(hgex_state_block(hgex_state))

# FlashAlpha single-stock GEX Monitor section (unchanged)
parts.append(gex_section_html)

# charts grid
parts.append('<div class="charts-grid">')
parts.append('<div class="chart-card"><div class="chart-title">VIX 30-Day History</div>')
parts.append('<div class="chart-subtitle">Spot VIX above 20 = elevated fear regime</div><div id="chart-vix"></div></div>')
parts.append('<div class="chart-card"><div class="chart-title">VIX Term Structure Snapshot</div>')
parts.append('<div class="chart-subtitle">Upward slope = contango = panic receding</div><div id="chart-vix-term"></div></div>')
parts.append('<div class="chart-card"><div class="chart-title">NDX Leveraged Money Net (COT)</div>')
parts.append('<div class="chart-subtitle">CTA proxy covering = selling abating</div><div id="chart-cot"></div></div>')
parts.append('<div class="chart-card"><div class="chart-title">Cross-Sector Correlation (Rolling 21D)</div>')
parts.append('<div class="chart-subtitle">Declining = stocks re-dispersing to fundamentals</div><div id="chart-corr"></div></div>')
parts.append('</div>')

# bottom bar
parts.append('<div class="bottom-bar">')
parts.append('<div class="bottom-item">LPI: <span>FRED (WALCL/WTREGEN/RRPONTSYD/SOFR/DFF) + FiscalData + Yahoo VIX</span></div>')
parts.append('<div class="bottom-item">Tail table: <span>Yahoo ^GSPC weekly</span></div>')
parts.append('<div class="bottom-item">COT: <span>CFTC Socrata TFF + Disaggregated</span></div>')
parts.append('<div class="bottom-item">Funding: <span>Binance (CoinGecko) + OKX API</span></div>')
parts.append('<div class="bottom-item">Index GEX: <span>homebrew SPY/QQQ (Yahoo option chains, BS gamma)</span></div>')
parts.append('<div class="bottom-item">GEX: <span>FlashAlpha free tier (NVDA/AAPL/AMD/MU, 5 req/day)</span></div>')
parts.append('</div>')

# JS
parts.append('<script>')
parts.append('(function(){')
parts.append('var T={paper_bgcolor:"rgba(0,0,0,0)",plot_bgcolor:"rgba(0,0,0,0)",')
parts.append('  font:{color:"#94a3b8",size:10},')
parts.append('  xaxis:{gridcolor:"#1e2433",zerolinecolor:"#2d3748",tickfont:{size:9},automargin:true,fixedrange:true},')
parts.append('  yaxis:{gridcolor:"#1e2433",zerolinecolor:"#2d3748",tickfont:{size:9},automargin:true,fixedrange:true},')
parts.append('  margin:{l:40,r:8,t:8,b:40},showlegend:false,height:190,autosize:true};')
parts.append('var CFG={responsive:true,displayModeBar:false};')
parts.append('var vixShape={type:"line",x0:0,x1:1,xref:"paper",y0:20,y1:20,line:{color:"#ef4444",width:1,dash:"dot"}};')
parts.append('Plotly.newPlot("chart-vix",[{x:' + j_vd + ',y:' + j_vv + ',type:"scatter",mode:"lines",')
parts.append('  line:{color:"#f59e0b",width:2},fill:"tozeroy",fillcolor:"rgba(245,158,11,0.07)"}],')
parts.append('  Object.assign({},T,{shapes:[vixShape]}),CFG);')
parts.append('Plotly.newPlot("chart-vix-term",[{x:["VIX9D","VIX spot","VIX3M"],y:[' + s_v9d_n + ',' + s_vix_n + ',' + s_v3m_n + '],')
parts.append('  type:"bar",marker:{color:["#ef4444","#f59e0b","#10b981"],line:{width:0}},')
parts.append('  text:["' + s_v9d_n + '","' + s_vix_n + '","' + s_v3m_n + '"],textposition:"outside",textfont:{color:"#e2e8f0",size:12},')
parts.append('  width:[0.5,0.5,0.5]}],')
parts.append('  {paper_bgcolor:"rgba(0,0,0,0)",plot_bgcolor:"rgba(0,0,0,0)",font:{color:"#94a3b8",size:10},')
parts.append('   xaxis:{type:"category",gridcolor:"#1e2433",tickfont:{size:11,color:"#94a3b8"},fixedrange:true},')
parts.append('   yaxis:{gridcolor:"#1e2433",tickfont:{size:9},range:[0,' + s_ymax + '],automargin:true,fixedrange:true},')
parts.append('   margin:{l:30,r:8,t:28,b:36},showlegend:false,height:190,autosize:true},CFG);')
parts.append('var cotColors=' + j_cv + '.map(function(v){return v>=0?"#10b981":"#ef4444";});')
parts.append('var zeroLine={type:"line",x0:0,x1:1,xref:"paper",y0:0,y1:0,line:{color:"#475569",width:1}};')
parts.append('if(' + j_cd + '.length){Plotly.newPlot("chart-cot",[{x:' + j_cd + ',y:' + j_cv + ',type:"bar",marker:{color:cotColors}}],')
parts.append('  Object.assign({},T,{shapes:[zeroLine],xaxis:Object.assign({},T.xaxis,{tickangle:-35})}),CFG);}')
parts.append('Plotly.newPlot("chart-corr",[')
parts.append('  {x:' + j_rd + ',y:' + j_rh + ',type:"scatter",mode:"lines",line:{color:"#6366f1",width:2},fill:"tozeroy",fillcolor:"rgba(99,102,241,0.07)"},')
parts.append('  {x:' + j_rd + ',y:' + j_rf + ',type:"scatter",mode:"lines",line:{color:"#ef4444",width:1,dash:"dash"}}')
parts.append('],Object.assign({},T,{showlegend:false}),CFG);')
parts.append('var t60={type:"line",x0:0,x1:1,xref:"paper",y0:60,y1:60,line:{color:"#f97316",width:1,dash:"dash"}};')
parts.append('var t80={type:"line",x0:0,x1:1,xref:"paper",y0:80,y1:80,line:{color:"#ef4444",width:1,dash:"dash"}};')
parts.append('var lpiD=' + j_lpi_d + ',lpiV=' + j_lpi_v + ';')
parts.append('if(lpiD.length){')
parts.append('  Plotly.newPlot("chart-lpi",[{x:lpiD,y:lpiV,type:"scatter",mode:"lines",line:{color:"#6366f1",width:2},fill:"tozeroy",fillcolor:"rgba(99,102,241,0.08)"}],')
parts.append('    Object.assign({},T,{shapes:[t60,t80],yaxis:Object.assign({},T.yaxis,{range:[0,100]})}),CFG);')
parts.append('}else{document.getElementById("chart-lpi").innerHTML="<div style=\\"color:#64748b;font-size:11px;padding:20px 0\\">History unavailable</div>";}')
parts.append('var lpiFD=' + j_lpi_fd + ',lpiFV=' + j_lpi_fv + ';')
parts.append('if(lpiFD.length){')
parts.append('  var Tf=Object.assign({},T,{shapes:[t60,t80],yaxis:Object.assign({},T.yaxis,{range:[0,100]}),')
parts.append('    xaxis:Object.assign({},T.xaxis,{fixedrange:false,rangeselector:{buttons:[')
parts.append('      {count:1,label:"1y",step:"year",stepmode:"backward"},')
parts.append('      {count:3,label:"3y",step:"year",stepmode:"backward"},')
parts.append('      {count:5,label:"5y",step:"year",stepmode:"backward"},')
parts.append('      {step:"all",label:"all"}],font:{size:9,color:"#94a3b8"},bgcolor:"#1e2433",activecolor:"#6366f1"},')
parts.append('    rangeslider:{visible:false}})});')
parts.append('  Plotly.newPlot("chart-lpi-full",[{x:lpiFD,y:lpiFV,type:"scatter",mode:"lines",line:{color:"#8b5cf6",width:1.5},fill:"tozeroy",fillcolor:"rgba(139,92,246,0.08)"}],Tf,CFG);')
parts.append('}else{var ef=document.getElementById("chart-lpi-full");if(ef)ef.innerHTML="<div style=\\"color:#64748b;font-size:11px;padding:20px 0\\">History unavailable</div>";}')
parts.append('var gexD=' + j_gex_d + ',gexV=' + j_gex_v + ';')
parts.append('var gexEl=document.getElementById("chart-gex-nvda");')
parts.append('if(gexEl&&gexD.length>=2){')
parts.append('  var gexColors=gexV.map(function(v){return v>=0?"#10b981":"#ef4444";});')
parts.append('  var gexZero={type:"line",x0:0,x1:1,xref:"paper",y0:0,y1:0,line:{color:"#475569",width:1}};')
parts.append('  Plotly.newPlot("chart-gex-nvda",[{x:gexD,y:gexV,type:"scatter",mode:"lines+markers",')
parts.append('    line:{color:"#6366f1",width:2},marker:{color:gexColors,size:5},fill:"tozeroy",fillcolor:"rgba(99,102,241,0.07)"}],')
parts.append('    Object.assign({},T,{shapes:[gexZero],yaxis:Object.assign({},T.yaxis,{title:{text:"$M",font:{size:9}}}),xaxis:Object.assign({},T.xaxis,{tickangle:-35})}),CFG);')
parts.append('}')
parts.append('var hgS=' + j_hgex_strk + ',hgV=' + j_hgex_val + ',hgSpot=' + j_hgex_spot + ',hgFlip=' + j_hgex_flip + ';')
parts.append('var hgEl=document.getElementById("chart-hgex-spy");')
parts.append('if(hgEl&&hgS.length){')
parts.append('  var hgColors=hgV.map(function(v){return v>=0?"#10b981":"#ef4444";});')
parts.append('  var hgShapes=[{type:"line",x0:0,x1:1,xref:"paper",y0:0,y1:0,line:{color:"#475569",width:1}}];')
parts.append('  if(hgSpot!==null){hgShapes.push({type:"line",x0:hgSpot,x1:hgSpot,yref:"paper",y0:0,y1:1,line:{color:"#e2e8f0",width:1,dash:"dash"}});}')
parts.append('  if(hgFlip!==null){hgShapes.push({type:"line",x0:hgFlip,x1:hgFlip,yref:"paper",y0:0,y1:1,line:{color:"#6366f1",width:1.5}});}')
parts.append('  Plotly.newPlot("chart-hgex-spy",[{x:hgS,y:hgV,type:"bar",marker:{color:hgColors}}],')
parts.append('    Object.assign({},T,{shapes:hgShapes,xaxis:Object.assign({},T.xaxis,{type:"linear",tickformat:"d"}),yaxis:Object.assign({},T.yaxis,{title:{text:"$bn/1%",font:{size:9}}})}),CFG);')
parts.append('}')
# Phase 5 — per-instrument COT weekly charts (diverging long/short bars,
# bold net line, dashed percentile line on a right-hand 0-100 axis, z annotation).
parts.append('var COTC=' + j_cot_charts + ';')
parts.append('var cotChartIds=[];')
parts.append('Object.keys(COTC).forEach(function(k){')
parts.append('  var el=document.getElementById("cot-chart-"+k);if(!el)return;')
parts.append('  var d=COTC[k];')
parts.append('  if(!d||!d.dates||!d.dates.length){el.innerHTML="<div style=\\"color:#475569;font-size:11px;padding:20px 0\\">chart data unavailable</div>";return;}')
parts.append('  var traces=[')
parts.append('    {x:d.dates,y:d.long,type:"bar",name:"long",marker:{color:"rgba(16,185,129,0.42)"},hovertemplate:"%{x}<br>long %{y:,}<extra></extra>"},')
parts.append('    {x:d.dates,y:d.short,type:"bar",name:"short",marker:{color:"rgba(239,68,68,0.42)"},hovertemplate:"%{x}<br>short %{y:,}<extra></extra>"},')
parts.append('    {x:d.dates,y:d.net,type:"scatter",mode:"lines",name:"net",line:{color:"#e2e8f0",width:2},hovertemplate:"%{x}<br>net %{y:,}<extra></extra>"},')
parts.append('    {x:d.dates,y:d.pctile,type:"scatter",mode:"lines",name:"pctile",yaxis:"y2",line:{color:"#f59e0b",width:1.5,dash:"dash"},hovertemplate:"%{x}<br>pctile %{y:.0f}<extra></extra>"}')
parts.append('  ];')
parts.append('  var ann=[];')
parts.append('  if(d.z!==null&&d.z!==undefined){ann.push({xref:"paper",yref:"paper",x:0.02,y:0.98,xanchor:"left",yanchor:"top",text:"z "+(d.z>=0?"+":"")+d.z.toFixed(1),showarrow:false,font:{size:11,color:"#cbd5e1"},bgcolor:"rgba(20,23,32,0.72)"});}')
parts.append('  var lastP=d.pctile.length?d.pctile[d.pctile.length-1]:null;')
parts.append('  if(lastP!==null&&lastP!==undefined){ann.push({xref:"paper",yref:"paper",x:0.98,y:0.98,xanchor:"right",yanchor:"top",text:"pctl "+lastP.toFixed(0),showarrow:false,font:{size:10,color:"#f59e0b"}});}')
parts.append('  var lay=Object.assign({},T,{barmode:"relative",height:230,hovermode:"x unified",')
parts.append('    shapes:[{type:"line",x0:0,x1:1,xref:"paper",y0:0,y1:0,line:{color:"#475569",width:1}}],')
parts.append('    annotations:ann,')
parts.append('    xaxis:Object.assign({},T.xaxis,{type:"date",tickangle:-30,nticks:6}),')
parts.append('    yaxis:Object.assign({},T.yaxis,{title:{text:"contracts",font:{size:9}},zerolinecolor:"#475569"}),')
parts.append('    yaxis2:{overlaying:"y",side:"right",range:[0,100],showgrid:false,zeroline:false,tickfont:{size:8,color:"#f59e0b"},fixedrange:true}});')
parts.append('  Plotly.newPlot("cot-chart-"+k,traces,lay,CFG);')
parts.append('  cotChartIds.push("cot-chart-"+k);')
parts.append('});')
parts.append('window.addEventListener("resize",function(){')
parts.append('  ["chart-vix","chart-vix-term","chart-cot","chart-corr","chart-lpi","chart-lpi-full","chart-gex-nvda","chart-hgex-spy"].concat(cotChartIds).forEach(function(id){var el=document.getElementById(id);if(el)Plotly.Plots.resize(el);});')
parts.append('});')
parts.append('})();')
parts.append('</script></body></html>')

out = "\n".join(parts)

with open("index.html", "w", encoding="utf-8") as f:
    f.write(out)

print("Done. chars={} signals={}/5 LPI={} regime={}/{} basis={}".format(
    len(out), sig_count, s_lpi, reg_level, reg_dir, s_basis))
