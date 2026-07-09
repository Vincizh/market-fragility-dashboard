#!/usr/bin/env python3
"""De-Lever Signal Dashboard Generator"""

import yfinance as yf
import requests
import pandas as pd
import numpy as np
import json
import io
import zipfile
import sys
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

# --- COT ---
print("Fetching COT...")
cot_net = cot_change = 0
cot_pct = 0.0
cot_date = "N/A"
cot_dates_list = []
cot_vals_list  = []
cta_covering   = False

def fetch_cot(year):
    url = "https://www.cftc.gov/files/dea/history/fut_fin_txt_{}.zip".format(year)
    r = requests.get(url, timeout=45)
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        with z.open(z.namelist()[0]) as f:
            return pd.read_csv(f, low_memory=False)

try:
    yr = datetime.now().year
    frames = []
    for y in [yr - 1, yr]:
        try:
            frames.append(fetch_cot(y))
        except Exception as e:
            print("COT {} error: {}".format(y, e))
    if frames:
        all_cot = pd.concat(frames)
        ndx = all_cot[all_cot["Market_and_Exchange_Names"] == "NASDAQ-100 Consolidated - CHICAGO MERCANTILE EXCHANGE"].copy()
        ndx = ndx.sort_values("Report_Date_as_YYYY-MM-DD")
        ndx["lev_net"]     = ndx["Lev_Money_Positions_Long_All"] - ndx["Lev_Money_Positions_Short_All"]
        ndx["lev_net_pct"] = ndx["lev_net"] / ndx["Open_Interest_All"] * 100
        recent = ndx.tail(16)
        last = recent.iloc[-1]
        cot_net    = int(last["lev_net"])
        cot_pct    = float(last["lev_net_pct"])
        cot_date   = str(last["Report_Date_as_YYYY-MM-DD"])
        cot_change = cot_net - int(recent.iloc[-2]["lev_net"])
        cot_dates_list = recent["Report_Date_as_YYYY-MM-DD"].tolist()
        cot_vals_list  = [int(x) for x in recent["lev_net"].tolist()]
        cta_covering   = cot_change > 0
except Exception as e:
    print("COT processing error:", e)

print("COT net={:,} pct={:.1f}% change={:+,}".format(cot_net, cot_pct, cot_change))

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

# --- Liquidity Pressure Index (LPI / 流动性压力指数) ---
# 4-factor composite: SOFR + Treasury duration supply + inverted Fed net liquidity + VIX.
# Each factor -> rolling historical percentile (trailing ~560-week window), averaged to 0-100.
# Higher value = higher pressure on equities. Every fetch is guarded so one API failure
# degrades gracefully (factor dropped, LPI computed from the rest).
print("Fetching LPI factors...")
import os

LPI_WINDOW = 560  # ~11 years of weekly observations

def fred_csv(series, start="2010-01-01"):
    url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={}&observation_start={}".format(series, start)
    r = requests.get(url, timeout=30)
    df = pd.read_csv(io.StringIO(r.text))
    df.columns = ["date", "val"]
    df["date"] = pd.to_datetime(df["date"])
    df["val"] = pd.to_numeric(df["val"], errors="coerce")
    return df.dropna().set_index("date")["val"]

def to_weekly(s):
    return s.resample("W-FRI").last().dropna()

def pctile_series(s, window=LPI_WINDOW):
    # percentile rank of each point vs its own trailing window (inclusive)
    vals = s.values
    out = []
    for i in range(len(vals)):
        lo = max(0, i - window + 1)
        w = vals[lo:i + 1]
        out.append(float((w <= vals[i]).sum()) / len(w) * 100.0)
    return pd.Series(out, index=s.index)

lpi_pct   = {}   # factor key -> weekly percentile Series
lpi_raw   = {}   # factor key -> current raw reading (for display)
lpi_ok    = {}   # factor key -> bool availability

# Factor 1 — Short rate (SOFR spliced with DFF/EFFR for pre-2018 depth)
sofr_current = None
try:
    sofr = to_weekly(fred_csv("SOFR"))
    try:
        dff = to_weekly(fred_csv("DFF"))
        short_rate = pd.concat([dff[dff.index < sofr.index.min()], sofr], sort=False).sort_index()
    except Exception as e:
        print("LPI DFF splice error:", e)
        short_rate = sofr
    short_rate = short_rate[short_rate.index >= pd.Timestamp("2010-01-01")]
    lpi_pct["short_rate"] = pctile_series(short_rate)
    sofr_current = float(short_rate.iloc[-1])
    lpi_raw["short_rate"] = sofr_current
    lpi_ok["short_rate"] = True
    print("LPI short_rate weeks={} last={:.3f} pct={:.1f}".format(len(short_rate), sofr_current, lpi_pct["short_rate"].iloc[-1]))
except Exception as e:
    lpi_ok["short_rate"] = False
    print("LPI short_rate error:", e)

# Factor 2 — Duration supply (weekly Treasury coupon issuance, trailing 4-week sum)
issuance_4w = None
try:
    au_rows = []
    for pg in range(1, 11):
        url = ("https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/od/auctions_query"
               "?fields=auction_date,offering_amt,security_term"
               "&filter=security_term:in:(2-Year,3-Year,5-Year,7-Year,10-Year,20-Year,30-Year)"
               "&sort=-auction_date&page[size]=200&page[number]={}".format(pg))
        page = None
        for attempt in range(3):
            try:
                page = requests.get(url, timeout=40).json().get("data", [])
                break
            except Exception as e:
                print("LPI auctions page {} retry {}: {}".format(pg, attempt, e))
        if not page:
            break
        au_rows += page
        if len(page) < 200:
            break
    if not au_rows:
        raise RuntimeError("no auction rows")
    au = pd.DataFrame(au_rows)
    au["auction_date"] = pd.to_datetime(au["auction_date"])
    au["offering_amt"] = pd.to_numeric(au["offering_amt"], errors="coerce")
    au = au.dropna(subset=["offering_amt"])
    wk = au.set_index("auction_date")["offering_amt"].resample("W-FRI").sum().fillna(0)
    iss4 = (wk.rolling(4).sum().dropna()) / 1e9  # -> $ billions
    lpi_pct["duration_supply"] = pctile_series(iss4)
    issuance_4w = float(iss4.iloc[-1])
    lpi_raw["duration_supply"] = issuance_4w
    lpi_ok["duration_supply"] = True
    print("LPI duration_supply weeks={} last_4w=${:.1f}B pct={:.1f}".format(len(iss4), issuance_4w, lpi_pct["duration_supply"].iloc[-1]))
except Exception as e:
    lpi_ok["duration_supply"] = False
    print("LPI duration_supply error:", e)

# Factor 3 — Fed net liquidity (WALCL - TGA), INVERTED
netliq_current_t = None
try:
    walcl = to_weekly(fred_csv("WALCL"))
    tga   = to_weekly(fred_csv("WTREGEN"))
    # Normalize both to $ billions (FRED serves WALCL & WTREGEN in $millions; verify by magnitude).
    def _to_bil(s):
        return s / 1000.0 if float(s.iloc[-1]) > 100000 else s
    walcl_b = _to_bil(walcl)
    tga_b   = _to_bil(tga)
    netliq = (walcl_b - tga_b).dropna()  # $ billions
    lpi_pct["net_liquidity"] = 100.0 - pctile_series(netliq)  # INVERTED: low liquidity = high pressure
    netliq_current_t = float(netliq.iloc[-1]) / 1000.0  # $ trillions
    lpi_raw["net_liquidity"] = netliq_current_t
    lpi_ok["net_liquidity"] = True
    print("LPI net_liquidity weeks={} last=${:.3f}T (WALCL=${:.3f}T TGA=${:.1f}B) pct_inv={:.1f}".format(
        len(netliq), netliq_current_t, float(walcl_b.iloc[-1]) / 1000.0, float(tga_b.iloc[-1]), lpi_pct["net_liquidity"].iloc[-1]))
except Exception as e:
    lpi_ok["net_liquidity"] = False
    print("LPI net_liquidity error:", e)

# Factor 4 — Vol amplifier (VIX percentile; deep history via Yahoo). Primary GEX proxy.
vix_lpi_current = None
try:
    vix_hist = yf.download("^VIX", period="max", auto_adjust=True, progress=False)["Close"]
    vix_hist = to_weekly(vix_hist.squeeze())
    lpi_pct["vol_amplifier"] = pctile_series(vix_hist)
    vix_lpi_current = float(vix_hist.iloc[-1])
    lpi_raw["vol_amplifier"] = vix_lpi_current
    lpi_ok["vol_amplifier"] = True
    print("LPI vol_amplifier weeks={} last={:.2f} pct={:.1f}".format(len(vix_hist), vix_lpi_current, lpi_pct["vol_amplifier"].iloc[-1]))
except Exception as e:
    lpi_ok["vol_amplifier"] = False
    print("LPI vol_amplifier error:", e)

# --- GEX Monitor (Phase 2b, FlashAlpha free tier) ---------------------------
# SPX GEX is tier-restricted on the free plan (and a 403 still burns a quota
# slot), so the old direct-SPX call is gone. We fetch <=5 single-stock readings
# per day on a UTC-hour schedule and repoint the Phase-1 GEX signal to NVDA.
# State survives between hourly CI runs via a JSON block embedded in index.html
# (the workflow commits only index.html, so a side-car file would be dropped).
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

# Phase-1 GEX proxy note (NVDA; SPX unavailable on free tier)
if gex_nvda["has"]:
    gex_note = "NVDA net GEX {} ({})".format(
        gex_monitor.fmt_gex(gex_nvda["net_gex"]),
        "negative = amplifying" if not gex_nvda["positive"] else "positive = dampening")
else:
    gex_note = ""

# Composite: average of available factor percentiles (current reading = last value)
lpi_labels = {
    "short_rate":      "Short Rate 资金价格",
    "duration_supply": "Duration Supply 久期供给",
    "net_liquidity":   "Net Liquidity 银行水位 (inv)",
    "vol_amplifier":   "Vol Amplifier 波动放大器",
}
lpi_order = ["short_rate", "duration_supply", "net_liquidity", "vol_amplifier"]
lpi_current = {k: float(lpi_pct[k].iloc[-1]) for k in lpi_order if lpi_ok.get(k)}
if lpi_current:
    lpi_composite = sum(lpi_current.values()) / len(lpi_current)
else:
    lpi_composite = float("nan")

# 52-week composite history (align available factor percentiles on common weekly index)
lpi_hist_dates = []
lpi_hist_vals  = []
if lpi_current:
    aligned = pd.concat({k: lpi_pct[k] for k in lpi_current}, axis=1, sort=True).dropna()
    if len(aligned):
        lpi_series = aligned.mean(axis=1).tail(52)
        lpi_hist_dates = [d.strftime("%Y-%m-%d") for d in lpi_series.index]
        lpi_hist_vals  = [round(float(v), 1) for v in lpi_series.values]

print("LPI composite={:.1f} factors_used={}/4".format(lpi_composite if lpi_current else float('nan'), len(lpi_current)))

# --- Pre-compute all display values ---
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

txt_vix = "CONTANGO \u2705" if vix_contango   else "BACKWARDATION \u26a0\ufe0f"
txt_cot = "SHORT COVERING \u2705" if cta_covering else "ADDING SHORTS \u26a0\ufe0f"
txt_cor = "DECLINING \u2705"      if corr_declining else "ELEVATED \u26a0\ufe0f"
if btc_pos and eth_pos:
    txt_fun = "BOTH POSITIVE \u2705 \u2014 Risk appetite returning"
elif btc_pos or eth_pos:
    txt_fun = "MIXED \u26a0\ufe0f \u2014 Partial recovery"
else:
    txt_fun = "BOTH NEGATIVE \u26a0\ufe0f \u2014 Still de-risking"

if sig_count <= 1:
    cmsg, ccol = "No signals confirmed \u2014 stay out", "#ef4444"
elif sig_count == 2:
    cmsg, ccol = "Watch closely \u2014 de-lever may be abating", "#f59e0b"
elif sig_count == 3:
    cmsg, ccol = "Threshold reached: mechanical selling likely exhausting", "#10b981"
elif sig_count == 4:
    cmsg, ccol = "Strong confirmation \u2014 consider re-entry on core names", "#10b981"
else:
    cmsg, ccol = "All signals confirmed \u2014 de-lever complete, re-engage", "#10b981"

dots = ""
for lbl, ok in [("VIX Contango", vix_contango), ("BTC FR+", btc_pos),
                ("ETH FR+", eth_pos), ("CTA Covering", cta_covering), ("Corr Declining", corr_declining)]:
    css = "filled" if ok else "empty"
    dots = dots + '<div class="dot ' + css + '" title="' + lbl + '"></div>'

# numeric strings
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

# JSON for charts
j_vd = json.dumps(vix_dates)
j_vv = json.dumps(vix_vals_list)
j_cd = json.dumps(cot_dates_list)
j_cv = json.dumps(cot_vals_list)
j_rd = json.dumps(corr_dates)
j_rh = json.dumps(corr_hist)
j_rf = json.dumps([0.5] * len(corr_dates))

# --- LPI display values ---
def lpi_band(v):
    # returns (hex color, css class suffix, status text)
    if v != v:  # NaN
        return "#64748b", "gray", "Insufficient data"
    if v < 40:
        return "#10b981", "green", "Cushion Thick / Market Resilient 库存充足"
    if v < 60:
        return "#f59e0b", "yellow", "Neutral / Watch for inflection 中性"
    if v < 80:
        return "#f97316", "orange", "Elevated / Reduce leverage, widen hedges 偏高"
    return "#ef4444", "red", "Extreme / Tail risk 5x normal — reduce exposure 极端"

lpi_has = bool(lpi_current)
lpi_col, lpi_cls, lpi_status = lpi_band(lpi_composite)
s_lpi = "{:.1f}".format(lpi_composite) if lpi_has else "N/A"
lpi_pos = max(0.0, min(100.0, lpi_composite)) if lpi_has else 0.0
s_lpi_pos = "{:.1f}".format(lpi_pos)
lpi_factors_used = "{}/4 factors".format(len(lpi_current)) if lpi_has else "no factors available"

# per-factor bar HTML
lpi_bars = ""
for k in lpi_order:
    lbl = lpi_labels[k]
    if lpi_ok.get(k):
        v = float(lpi_pct[k].iloc[-1])
        bcol, bcls, _ = lpi_band(v)
        vtxt = "{:.0f}".format(v)
        wpct = "{:.1f}".format(max(0.0, min(100.0, v)))
    else:
        bcol, vtxt, wpct = "#64748b", "N/A", "0"
    amp_badge = ""
    if k == "vol_amplifier" and gex_nvda["has"] and not gex_nvda["positive"]:
        amp_badge = ('<div class="lpi-amp-badge">NVDA negative gamma — '
                     'shock amplification regime</div>')
    lpi_bars = (lpi_bars
        + '<div class="lpi-factor">'
        + '<div class="lpi-factor-top"><span class="lpi-factor-lbl">' + lbl + '</span>'
        + '<span class="lpi-factor-val" style="color:' + bcol + '">' + vtxt + '</span></div>'
        + '<div class="lpi-track"><div class="lpi-fill" style="width:' + wpct + '%;background:' + bcol + '"></div></div>'
        + amp_badge
        + '</div>')

# raw-reading footnote strings
def _fmt_raw(k, fmt, *args):
    return fmt.format(*args) if lpi_ok.get(k) else "N/A"
s_lpi_sofr   = _fmt_raw("short_rate", "{:.2f}%", lpi_raw.get("short_rate", 0))
s_lpi_iss    = _fmt_raw("duration_supply", "${:.0f}B", lpi_raw.get("duration_supply", 0))
s_lpi_netliq = _fmt_raw("net_liquidity", "${:.2f}T", lpi_raw.get("net_liquidity", 0))
s_lpi_vix    = _fmt_raw("vol_amplifier", "{:.1f}", lpi_raw.get("vol_amplifier", 0))

j_lpi_d = json.dumps(lpi_hist_dates)
j_lpi_v = json.dumps(lpi_hist_vals)

# HTML template — plain string concatenation, zero f-strings, zero backslashes in strings
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
parts.append('.signal-bar{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;padding:16px 20px}')
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
parts.append('.lpi-gauge-top{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;margin-bottom:12px}')
parts.append('.lpi-num{font-size:40px;font-weight:800;line-height:1}')
parts.append('.lpi-scale{font-size:11px;color:#64748b}')
parts.append('.lpi-status{font-size:13px;font-weight:600}')
parts.append('.lpi-meter{position:relative;height:14px;border-radius:7px;background:linear-gradient(90deg,#10b981 0%,#10b981 40%,#f59e0b 40%,#f59e0b 60%,#f97316 60%,#f97316 80%,#ef4444 80%,#ef4444 100%)}')
parts.append('.lpi-marker{position:absolute;top:-4px;width:3px;height:22px;background:#e2e8f0;border-radius:2px;box-shadow:0 0 4px rgba(0,0,0,.6);transform:translateX(-50%)}')
parts.append('.lpi-ticks{display:flex;justify-content:space-between;font-size:9px;color:#475569;margin-top:5px}')
parts.append('.lpi-factors{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:12px}')
parts.append('@media(max-width:900px){.lpi-factors{grid-template-columns:repeat(2,1fr)}}')
parts.append('@media(max-width:480px){.lpi-factors{grid-template-columns:1fr}}')
parts.append('.lpi-factor{background:#141720;border:1px solid #2d3748;border-radius:8px;padding:12px 14px}')
parts.append('.lpi-factor-top{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:8px}')
parts.append('.lpi-factor-lbl{font-size:10px;color:#94a3b8;letter-spacing:.03em}')
parts.append('.lpi-factor-val{font-size:18px;font-weight:700}')
parts.append('.lpi-track{height:6px;border-radius:3px;background:#0a0c10;overflow:hidden}')
parts.append('.lpi-fill{height:100%;border-radius:3px}')
parts.append('.lpi-cal{background:#141720;border:1px solid #2d3748;border-radius:8px;padding:12px 14px;font-size:11px;color:#94a3b8;line-height:1.7}')
parts.append('.lpi-cal b{color:#e2e8f0}.lpi-cal .hot{color:#f97316}.lpi-cal .cool{color:#10b981}')
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
parts.append('<p>5 bottom confirmation signals &middot; auto-updated every hour</p></div>')
parts.append('<div class="header-right"><div class="timestamp">Last updated: ' + now_str + '</div></div></div>')

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

# LPI section
parts.append('<div class="lpi-section">')
parts.append('<div class="lpi-heading">流动性压力指数 <span>(Liquidity Pressure Index)</span></div>')

# gauge card
parts.append('<div class="lpi-gauge ' + lpi_cls + '">')
parts.append('<div class="lpi-gauge-top">')
parts.append('<span class="lpi-num" style="color:' + lpi_col + '">' + s_lpi + '</span>')
parts.append('<span class="lpi-scale">/ 100 &middot; ' + lpi_factors_used + '</span>')
parts.append('<span class="lpi-status" style="color:' + lpi_col + '">' + lpi_status + '</span></div>')
parts.append('<div class="lpi-meter"><div class="lpi-marker" style="left:' + s_lpi_pos + '%"></div></div>')
parts.append('<div class="lpi-ticks"><span>0 Resilient</span><span>40</span><span>60</span><span>80</span><span>100 Extreme</span></div>')
parts.append('</div>')

# sub-factor bars
parts.append('<div class="lpi-factors">' + lpi_bars + '</div>')

# 52-week history chart
parts.append('<div class="chart-card" style="margin-bottom:12px">')
parts.append('<div class="chart-title">LPI &mdash; Trailing 52 Weeks</div>')
parts.append('<div class="chart-subtitle">Composite percentile pressure &middot; thresholds at 60 (elevated) / 80 (extreme)</div>')
parts.append('<div id="chart-lpi"></div></div>')

# stress calendar
parts.append('<div class="lpi-cal">')
parts.append('<b>2026 H2 压力日历 (projected stress calendar)</b><br>')
parts.append('<span class="hot">Sep (~79th pct):</span> FOMC Sep 15-16 &middot; corp estimated tax Sep 15 &middot; quarter-end TGA refill Sep 30 &mdash; 4 simultaneous drains<br>')
parts.append('<span class="hot">Nov (2nd highest):</span> quarterly refunding issuance + FOMC late Oct<br>')
parts.append('<span class="hot">Aug (3rd):</span> refunding settlement peak mid-August<br>')
parts.append('<span class="cool">Jul:</span> lowest pressure month of H2')
parts.append('</div>')

parts.append('</div>')

# GEX Monitor section (between LPI and charts grid)
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
parts.append('<div class="bottom-item">VIX: <span>CBOE via Yahoo Finance</span></div>')
parts.append('<div class="bottom-item">Funding: <span>Binance (CoinGecko) + OKX API</span></div>')
parts.append('<div class="bottom-item">COT: <span>CFTC Disaggregated (~3-day lag)</span></div>')
parts.append('<div class="bottom-item">Correlation: <span>Sector ETFs XLK-XLRE</span></div>')
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
parts.append('Plotly.newPlot("chart-cot",[{x:' + j_cd + ',y:' + j_cv + ',type:"bar",marker:{color:cotColors}}],')
parts.append('  Object.assign({},T,{shapes:[zeroLine],xaxis:Object.assign({},T.xaxis,{tickangle:-35})}),CFG);')
parts.append('Plotly.newPlot("chart-corr",[')
parts.append('  {x:' + j_rd + ',y:' + j_rh + ',type:"scatter",mode:"lines",line:{color:"#6366f1",width:2},fill:"tozeroy",fillcolor:"rgba(99,102,241,0.07)"},')
parts.append('  {x:' + j_rd + ',y:' + j_rf + ',type:"scatter",mode:"lines",line:{color:"#ef4444",width:1,dash:"dash"}}')
parts.append('],Object.assign({},T,{showlegend:false}),CFG);')
parts.append('var lpiD=' + j_lpi_d + ',lpiV=' + j_lpi_v + ';')
parts.append('if(lpiD.length){')
parts.append('  var t60={type:"line",x0:0,x1:1,xref:"paper",y0:60,y1:60,line:{color:"#f97316",width:1,dash:"dash"}};')
parts.append('  var t80={type:"line",x0:0,x1:1,xref:"paper",y0:80,y1:80,line:{color:"#ef4444",width:1,dash:"dash"}};')
parts.append('  Plotly.newPlot("chart-lpi",[{x:lpiD,y:lpiV,type:"scatter",mode:"lines",line:{color:"#6366f1",width:2},fill:"tozeroy",fillcolor:"rgba(99,102,241,0.08)"}],')
parts.append('    Object.assign({},T,{shapes:[t60,t80],yaxis:Object.assign({},T.yaxis,{range:[0,100]})}),CFG);')
parts.append('}else{document.getElementById("chart-lpi").innerHTML="<div style=\\"color:#64748b;font-size:11px;padding:20px 0\\">History unavailable</div>";}')
parts.append('var gexD=' + gex_hist_d + ',gexV=' + gex_hist_v + ';')
parts.append('var gexEl=document.getElementById("chart-gex-nvda");')
parts.append('if(gexEl&&gexD.length>=2){')
parts.append('  var gexColors=gexV.map(function(v){return v>=0?"#10b981":"#ef4444";});')
parts.append('  var gexZero={type:"line",x0:0,x1:1,xref:"paper",y0:0,y1:0,line:{color:"#475569",width:1}};')
parts.append('  Plotly.newPlot("chart-gex-nvda",[{x:gexD,y:gexV,type:"scatter",mode:"lines+markers",')
parts.append('    line:{color:"#6366f1",width:2},marker:{color:gexColors,size:5},fill:"tozeroy",fillcolor:"rgba(99,102,241,0.07)"}],')
parts.append('    Object.assign({},T,{shapes:[gexZero],yaxis:Object.assign({},T.yaxis,{title:{text:"$M",font:{size:9}}}),xaxis:Object.assign({},T.xaxis,{tickangle:-35})}),CFG);')
parts.append('}')
parts.append('window.addEventListener("resize",function(){')
parts.append('  ["chart-vix","chart-vix-term","chart-cot","chart-corr","chart-lpi","chart-gex-nvda"].forEach(function(id){var el=document.getElementById(id);if(el)Plotly.Plots.resize(el);});')
parts.append('});')
parts.append('})();')
parts.append('</script></body></html>')

out = "\n".join(parts)

with open("index.html", "w", encoding="utf-8") as f:
    f.write(out)

print("Done. chars={} signals={}/5".format(len(out), sig_count))
