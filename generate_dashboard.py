#!/usr/bin/env python3
"""
De-Lever Signal Dashboard Generator
Runs via GitHub Actions on a schedule, writes index.html
"""

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

# ============================================================
# METRIC 1: VIX Term Structure
# ============================================================
print("Fetching VIX data...")
try:
    vix_spot   = yf.download("^VIX",  period="30d", auto_adjust=True, progress=False)["Close"]
    vix3m_hist = yf.download("^VIX3M",period="30d", auto_adjust=True, progress=False)["Close"]
    vix9d_hist = yf.download("^VIX9D",period="30d", auto_adjust=True, progress=False)["Close"]

    def last_val(df):
        v = df.iloc[-1]
        return float(v.iloc[0]) if hasattr(v, "iloc") else float(v)

    vix_val   = last_val(vix_spot)
    vix3m_val = last_val(vix3m_hist)
    vix9d_val = last_val(vix9d_hist)

    vix_dates     = [d.strftime("%Y-%m-%d") for d in vix_spot.index]
    vix_vals_list = [round(float(v), 2) for v in vix_spot.values.flatten()]
except Exception as e:
    print(f"VIX error: {e}")
    sys.exit(1)

vix_contango = vix3m_val > vix_val
print(f"VIX={vix_val:.2f}, VIX3M={vix3m_val:.2f}, VIX9D={vix9d_val:.2f}, Contango={vix_contango}")

# ============================================================
# METRIC 2: Crypto Funding Rates
# ============================================================
print("Fetching crypto funding rates...")
bnb_btc_fr = bnb_eth_fr = okx_btc_fr = okx_eth_fr = None

try:
    cg = requests.get(
        "https://api.coingecko.com/api/v3/derivatives?include_tickers=unexpired",
        timeout=25
    ).json()
    bb = next((x for x in cg if x.get("market") == "Binance (Futures)" and x.get("symbol") == "BTCUSDT"), None)
    be = next((x for x in cg if x.get("market") == "Binance (Futures)" and x.get("symbol") == "ETHUSDT"), None)
    if bb:
        bnb_btc_fr = bb["funding_rate"] * 100
    if be:
        bnb_eth_fr = be["funding_rate"] * 100
    print(f"CoinGecko OK: BTC={bnb_btc_fr}, ETH={bnb_eth_fr}")
except Exception as e:
    print(f"CoinGecko error: {e}")

try:
    okx_btc_fr = float(requests.get(
        "https://www.okx.com/api/v5/public/funding-rate?instId=BTC-USDT-SWAP", timeout=12
    ).json()["data"][0]["fundingRate"]) * 100
    okx_eth_fr = float(requests.get(
        "https://www.okx.com/api/v5/public/funding-rate?instId=ETH-USDT-SWAP", timeout=12
    ).json()["data"][0]["fundingRate"]) * 100
    print(f"OKX OK: BTC={okx_btc_fr}, ETH={okx_eth_fr}")
except Exception as e:
    print(f"OKX error: {e}")

btc_fr = bnb_btc_fr if bnb_btc_fr is not None else okx_btc_fr if okx_btc_fr is not None else 0.0
eth_fr = bnb_eth_fr if bnb_eth_fr is not None else okx_eth_fr if okx_eth_fr is not None else 0.0
okx_btc_display = okx_btc_fr if okx_btc_fr is not None else 0.0
btc_source_lbl  = "Binance" if bnb_btc_fr is not None else "OKX"

btc_positive = btc_fr > 0
eth_positive = eth_fr > 0
print(f"BTC FR={btc_fr:.4f}% ({btc_source_lbl}), ETH FR={eth_fr:.4f}%")

# ============================================================
# METRIC 3: CFTC COT
# ============================================================
print("Fetching CFTC COT data...")

def fetch_cot(year):
    url = f"https://www.cftc.gov/files/dea/history/fut_fin_txt_{year}.zip"
    r = requests.get(url, timeout=45)
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        with z.open(z.namelist()[0]) as f:
            return pd.read_csv(f, low_memory=False)

cot_net = cot_change = 0
cot_pct = 0.0
cot_date = "N/A"
cot_chart_dates = []
cot_chart_vals  = []
cta_covering = False

try:
    yr = datetime.now().year
    frames = []
    for y in [yr - 1, yr]:
        try:
            frames.append(fetch_cot(y))
        except Exception as e:
            print(f"COT {y} fetch error: {e}")
    if frames:
        all_cot = pd.concat(frames)
        ndx = all_cot[
            all_cot["Market_and_Exchange_Names"] == "NASDAQ-100 Consolidated - CHICAGO MERCANTILE EXCHANGE"
        ].copy()
        ndx = ndx.sort_values("Report_Date_as_YYYY-MM-DD")
        ndx["lev_net"]     = ndx["Lev_Money_Positions_Long_All"] - ndx["Lev_Money_Positions_Short_All"]
        ndx["lev_net_pct"] = ndx["lev_net"] / ndx["Open_Interest_All"] * 100
        recent = ndx.tail(16)
        last = recent.iloc[-1]
        cot_net    = int(last["lev_net"])
        cot_pct    = float(last["lev_net_pct"])
        cot_date   = str(last["Report_Date_as_YYYY-MM-DD"])
        cot_change = cot_net - int(recent.iloc[-2]["lev_net"])
        cot_chart_dates = recent["Report_Date_as_YYYY-MM-DD"].tolist()
        cot_chart_vals  = [int(x) for x in recent["lev_net"].tolist()]
        cta_covering = cot_change > 0
except Exception as e:
    print(f"COT processing error: {e}")

print(f"COT net={cot_net:,}, pct={cot_pct:.1f}%, change={cot_change:+,}")

# ============================================================
# METRIC 4: Cross-sector correlation
# ============================================================
print("Fetching sector correlation data...")
tickers = ["XLK","XLF","XLV","XLE","XLI","XLC","XLY","XLP","XLB","XLU","XLRE"]
n = len(tickers)
sec  = yf.download(tickers, period="2mo", auto_adjust=True, progress=False)["Close"]
rets = sec.pct_change().dropna()

def avg_corr(df):
    cm = df.corr().values
    return (cm.sum() - n) / (n * (n - 1))

avg_corr_1m = avg_corr(rets.tail(21))
avg_corr_2w = avg_corr(rets.tail(10))

corr_history = []
dates_hist   = []
for i in range(21, len(rets) + 1):
    corr_history.append(round(avg_corr(rets.iloc[i-21:i]), 4))
    dates_hist.append(rets.index[i-1].strftime("%Y-%m-%d"))

corr_declining = avg_corr_2w < avg_corr_1m
print(f"Corr 1M={avg_corr_1m:.3f}, 2W={avg_corr_2w:.3f}, declining={corr_declining}")

# ============================================================
# PRE-COMPUTE all display strings
# ============================================================
signals_count = sum([vix_contango, btc_positive, eth_positive, cta_covering, corr_declining])
now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

cls_vix     = "green" if vix_contango  else "red"
cls_btc     = "green" if btc_positive  else "red"
cls_cot     = "green" if cta_covering  else "red"
cls_corr    = "green" if corr_declining else "yellow"
cls_funding = "green" if (btc_positive and eth_positive) else ("yellow" if (btc_positive or eth_positive) else "red")

bdg_vix     = "badge-green" if vix_contango  else "badge-red"
bdg_cot     = "badge-green" if cta_covering  else "badge-red"
bdg_corr    = "badge-green" if corr_declining else "badge-yellow"
bdg_funding = "badge-green" if (btc_positive and eth_positive) else ("badge-yellow" if (btc_positive or eth_positive) else "badge-red")

txt_vix     = "CONTANGO \u2705" if vix_contango else "BACKWARDATION \u26a0\ufe0f"
txt_cot     = "SHORT COVERING \u2705" if cta_covering  else "ADDING SHORTS \u26a0\ufe0f"
txt_corr    = "DECLINING \u2705"   if corr_declining else "ELEVATED \u26a0\ufe0f"
txt_funding = ("BOTH POSITIVE \u2705 \u2014 Risk appetite returning" if btc_positive and eth_positive
               else "MIXED \u26a0\ufe0f \u2014 Partial recovery" if btc_positive or eth_positive
               else "BOTH NEGATIVE \u26a0\ufe0f \u2014 Still de-risking")

if signals_count <= 1:
    confirm_msg, confirm_color = "No signals confirmed \u2014 stay out", "#ef4444"
elif signals_count == 2:
    confirm_msg, confirm_color = "Watch closely \u2014 de-lever may be abating", "#f59e0b"
elif signals_count == 3:
    confirm_msg, confirm_color = "Threshold reached: mechanical selling likely exhausting", "#10b981"
elif signals_count == 4:
    confirm_msg, confirm_color = "Strong confirmation \u2014 consider re-entry on core names", "#10b981"
else:
    confirm_msg, confirm_color = "All signals confirmed \u2014 de-lever complete, re-engage", "#10b981"

dots_html = "".join(
    '<div class="dot {}" title="{}"></div>'.format("filled" if ok else "empty", lbl)
    for lbl, ok in [("VIX Contango", vix_contango),("BTC FR+", btc_positive),
                    ("ETH FR+", eth_positive),("CTA Covering", cta_covering),("Corr Declining", corr_declining)]
)

vix_diff_str   = "{:+.2f}".format(vix3m_val - vix_val)
vix9d_str      = "{:.1f}".format(vix9d_val)
vix_str        = "{:.1f}".format(vix_val)
vix3m_str      = "{:.1f}".format(vix3m_val)
btc_fr_str     = "{:+.4f}".format(btc_fr)
eth_fr_str     = "{:+.4f}".format(eth_fr)
okx_btc_str    = "{:+.4f}".format(okx_btc_display)
cot_net_str    = "{:,}".format(cot_net)
cot_pct_str    = "{:.1f}".format(cot_pct)
cot_change_str = "{:+,}".format(cot_change)
corr2w_str     = "{:.3f}".format(avg_corr_2w)
corr1m_str     = "{:.3f}".format(avg_corr_1m)
vix_ymax       = "{:.2f}".format(max(vix9d_val, vix_val, vix3m_val) * 1.25)
vix9d_r        = str(round(vix9d_val, 2))
vix_r          = str(round(vix_val,   2))
vix3m_r        = str(round(vix3m_val, 2))

j_vix_dates  = json.dumps(vix_dates)
j_vix_vals   = json.dumps(vix_vals_list)
j_cot_dates  = json.dumps(cot_chart_dates)
j_cot_vals   = json.dumps(cot_chart_vals)
j_corr_dates = json.dumps(dates_hist)
j_corr_hist  = json.dumps(corr_history)
j_corr_flat  = json.dumps([0.5] * len(dates_hist))

# ============================================================
# HTML TEMPLATE (string substitution, no f-string conditionals)
# ============================================================
html_out = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
<title>De-Lever Signal Dashboard</title>
<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: #0d0f14; color: #e2e8f0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }
.header { background: #141720; border-bottom: 1px solid #2d3748; padding: 14px 20px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; }
.header-left h1 { font-size: 16px; font-weight: 700; }
.header-left h1 span { color: #6366f1; }
.header-left p { font-size: 11px; color: #475569; margin-top: 2px; }
.header-right { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.timestamp { font-size: 11px; color: #64748b; }
.signal-bar { display: grid; grid-template-columns: repeat(4,1fr); gap: 12px; padding: 16px 20px; }
@media(max-width:900px){.signal-bar{grid-template-columns:repeat(2,1fr);}}
@media(max-width:480px){.signal-bar{grid-template-columns:1fr;}}
.signal-card { background: #141720; border: 1px solid #2d3748; border-radius: 10px; padding: 14px 16px; }
.signal-card.green { border-left: 3px solid #10b981; }
.signal-card.red   { border-left: 3px solid #ef4444; }
.signal-card.yellow{ border-left: 3px solid #f59e0b; }
.signal-label { font-size: 10px; color: #64748b; text-transform: uppercase; letter-spacing: .08em; margin-bottom: 5px; }
.signal-value { font-size: 20px; font-weight: 700; margin-bottom: 3px; line-height: 1.2; }
.signal-value.green { color: #10b981; }
.signal-value.red   { color: #ef4444; }
.signal-value.yellow{ color: #f59e0b; }
.signal-sub { font-size: 11px; color: #64748b; line-height: 1.4; }
.signal-badge { display: inline-block; font-size: 10px; font-weight: 600; padding: 3px 8px; border-radius: 4px; margin-top: 7px; }
.badge-green  { background: rgba(16,185,129,.15); color: #10b981; }
.badge-red    { background: rgba(239,68,68,.15);  color: #ef4444; }
.badge-yellow { background: rgba(245,158,11,.15); color: #f59e0b; }
.confirm-counter { background: #141720; border: 1px solid #2d3748; border-radius: 8px; margin: 0 20px 16px; padding: 12px 16px; display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.confirm-label { font-size: 11px; color: #64748b; text-transform: uppercase; letter-spacing: .06em; white-space: nowrap; }
.confirm-dots  { display: flex; gap: 6px; flex-shrink: 0; }
.dot { width: 11px; height: 11px; border-radius: 50%; }
.dot.filled { background: #10b981; }
.dot.empty  { background: #2d3748; }
.confirm-text { font-size: 12px; color: #94a3b8; }
.confirm-text strong { color: #e2e8f0; }
.charts-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; padding: 0 20px 16px; }
@media(max-width:700px){.charts-grid{grid-template-columns:1fr;}}
.chart-card { background: #141720; border: 1px solid #2d3748; border-radius: 10px; padding: 14px; min-width: 0; }
.chart-title    { font-size: 12px; font-weight: 600; color: #94a3b8; text-transform: uppercase; letter-spacing: .05em; }
.chart-subtitle { font-size: 10px; color: #475569; margin: 3px 0 10px; line-height: 1.4; }
.bottom-bar { background: #0a0c10; border-top: 1px solid #1e2433; padding: 10px 20px; display: flex; flex-wrap: wrap; gap: 16px; }
.bottom-item { font-size: 10px; color: #475569; }
.bottom-item span { color: #64748b; }
</style>
</head>
<body>
<div class="header">
  <div class="header-left">
    <h1>De-Lever Signal Dashboard <span>/ NDX</span></h1>
    <p>5 bottom confirmation signals &middot; auto-updated every hour</p>
  </div>
  <div class="header-right">
    <div class="timestamp">Last updated: NOWSTR</div>
  </div>
</div>
<div class="signal-bar">
  <div class="signal-card CLS_VIX">
    <div class="signal-label">&#9312; VIX Term Structure</div>
    <div class="signal-value CLS_VIX">VIX_DIFF pts</div>
    <div class="signal-sub">VIX9D VIX9D_V &rarr; VIX VIX_V &rarr; VIX3M VIX3M_V</div>
    <div class="signal-badge BDG_VIX">TXT_VIX</div>
  </div>
  <div class="signal-card CLS_FUNDING">
    <div class="signal-label">&#9313; Crypto Funding (BTC_SRC)</div>
    <div class="signal-value CLS_BTC">BTC BTC_FR_STR%</div>
    <div class="signal-sub">ETH ETH_FR_STR% &middot; OKX BTC OKX_BTC_STR%</div>
    <div class="signal-badge BDG_FUNDING">TXT_FUNDING</div>
  </div>
  <div class="signal-card CLS_COT">
    <div class="signal-label">&#9314; CTA Proxy (CFTC COT)</div>
    <div class="signal-value CLS_COT">COT_NET_STR</div>
    <div class="signal-sub">COT_PCT_STR% OI &middot; as of COT_DATE<br>WoW: COT_CHANGE_STR contracts</div>
    <div class="signal-badge BDG_COT">TXT_COT</div>
  </div>
  <div class="signal-card CLS_CORR">
    <div class="signal-label">&#9315; Cross-Sector Correlation</div>
    <div class="signal-value CLS_CORR">CORR2W_STR</div>
    <div class="signal-sub">2W vs 1M avg: CORR1M_STR &rarr; CORR2W_STR</div>
    <div class="signal-badge BDG_CORR">TXT_CORR</div>
  </div>
</div>
<div class="confirm-counter">
  <div class="confirm-label">Signals confirmed</div>
  <div class="confirm-dots">DOTS_HTML</div>
  <div class="confirm-text"><strong>SIG_COUNT/5</strong> &mdash; <span style="color:CONFIRM_COLOR">CONFIRM_MSG</span></div>
</div>
<div class="charts-grid">
  <div class="chart-card">
    <div class="chart-title">VIX 30-Day History</div>
    <div class="chart-subtitle">Spot VIX &mdash; above 20 = elevated fear regime</div>
    <div id="chart-vix"></div>
  </div>
  <div class="chart-card">
    <div class="chart-title">VIX Term Structure Snapshot</div>
    <div class="chart-subtitle">Upward slope (VIX9D&rarr;VIX&rarr;VIX3M) = contango = panic receding</div>
    <div id="chart-vix-term"></div>
  </div>
  <div class="chart-card">
    <div class="chart-title">NDX Leveraged Money Net (COT)</div>
    <div class="chart-subtitle">CTA proxy &mdash; covering = selling abating</div>
    <div id="chart-cot"></div>
  </div>
  <div class="chart-card">
    <div class="chart-title">Cross-Sector Correlation (Rolling 21D)</div>
    <div class="chart-subtitle">Declining = stocks re-dispersing to fundamentals</div>
    <div id="chart-corr"></div>
  </div>
</div>
<div class="bottom-bar">
  <div class="bottom-item">VIX: <span>CBOE via Yahoo Finance</span></div>
  <div class="bottom-item">Funding: <span>Binance Futures (CoinGecko) + OKX API</span></div>
  <div class="bottom-item">COT: <span>CFTC Disaggregated (&sim;3-day lag)</span></div>
  <div class="bottom-item">Correlation: <span>Sector ETFs XLK&ndash;XLRE</span></div>
  <div class="bottom-item">&#9888; GEX: <span>Requires SpotGamma/SqueezeMetrics</span></div>
</div>
<script>
(function() {
var T = {
  paper_bgcolor:'rgba(0,0,0,0)', plot_bgcolor:'rgba(0,0,0,0)',
  font:{color:'#94a3b8',size:10,family:'-apple-system,sans-serif'},
  xaxis:{gridcolor:'#1e2433',zerolinecolor:'#2d3748',tickfont:{size:9},automargin:true,fixedrange:true},
  yaxis:{gridcolor:'#1e2433',zerolinecolor:'#2d3748',tickfont:{size:9},automargin:true,fixedrange:true},
  margin:{l:40,r:8,t:8,b:40}, showlegend:false, height:190, autosize:true
};
var CFG = {responsive:true, displayModeBar:false};
Plotly.newPlot('chart-vix',[{
  x:J_VIX_DATES, y:J_VIX_VALS,
  type:'scatter', mode:'lines',
  line:{color:'#f59e0b',width:2},
  fill:'tozeroy', fillcolor:'rgba(245,158,11,0.07)'
}], Object.assign({},T,{shapes:[{type:'line',x0:0,x1:1,xref:'paper',y0:20,y1:20,line:{color:'#ef4444',width:1,dash:'dot'}}]}), CFG);
Plotly.newPlot('chart-vix-term',[{
  x:['VIX9D','VIX spot','VIX3M'],
  y:[VIX9D_R, VIX_R, VIX3M_R],
  type:'bar',
  marker:{color:['#ef4444','#f59e0b','#10b981'],line:{width:0}},
  text:[VIX9D_R_STR, VIX_R_STR, VIX3M_R_STR],
  textposition:'outside', textfont:{color:'#e2e8f0',size:12},
  width:[0.5,0.5,0.5]
}],{
  paper_bgcolor:'rgba(0,0,0,0)', plot_bgcolor:'rgba(0,0,0,0)',
  font:{color:'#94a3b8',size:10},
  xaxis:{type:'category',gridcolor:'#1e2433',tickfont:{size:11,color:'#94a3b8'},fixedrange:true},
  yaxis:{gridcolor:'#1e2433',tickfont:{size:9},range:[0,VIX_YMAX],automargin:true,fixedrange:true},
  margin:{l:30,r:8,t:28,b:36}, showlegend:false, height:190, autosize:true
}, CFG);
var cotColors = J_COT_VALS.map(function(v){return v>=0?'#10b981':'#ef4444';});
Plotly.newPlot('chart-cot',[{
  x:J_COT_DATES, y:J_COT_VALS,
  type:'bar', marker:{color:cotColors}
}], Object.assign({},T,{
  shapes:[{type:'line',x0:0,x1:1,xref:'paper',y0:0,y1:0,line:{color:'#475569',width:1}}],
  xaxis:Object.assign({},T.xaxis,{tickangle:-35})
}), CFG);
Plotly.newPlot('chart-corr',[{
  x:J_CORR_DATES, y:J_CORR_HIST,
  type:'scatter', mode:'lines',
  line:{color:'#6366f1',width:2},
  fill:'tozeroy', fillcolor:'rgba(99,102,241,0.07)'
},{
  x:J_CORR_DATES, y:J_CORR_FLAT,
  type:'scatter', mode:'lines',
  line:{color:'#ef4444',width:1,dash:'dash'}
}], Object.assign({},T,{showlegend:false}), CFG);
window.addEventListener('resize',function(){
  ['chart-vix','chart-vix-term','chart-cot','chart-corr'].forEach(function(id){
    Plotly.Plots.resize(document.getElementById(id));
  });
});
})();
</script>
</body>
</html>"""

replacements = {
    "NOWSTR":        now_str,
    "CLS_VIX":       cls_vix,
    "CLS_BTC":       cls_btc,
    "CLS_COT":       cls_cot,
    "CLS_CORR":      cls_corr,
    "CLS_FUNDING":   cls_funding,
    "BDG_VIX":       bdg_vix,
    "BDG_COT":       bdg_cot,
    "BDG_CORR":      bdg_corr,
    "BDG_FUNDING":   bdg_funding,
    "TXT_VIX":       txt_vix,
    "TXT_COT":       txt_cot,
    "TXT_CORR":      txt_corr,
    "TXT_FUNDING":   txt_funding,
    "VIX_DIFF":      vix_diff_str,
    "VIX9D_V":       vix9d_str,
    "VIX_V":         vix_str,
    "VIX3M_V":       vix3m_str,
    "BTC_SRC":       btc_source_lbl,
    "BTC_FR_STR":    btc_fr_str,
    "ETH_FR_STR":    eth_fr_str,
    "OKX_BTC_STR":   okx_btc_str,
    "COT_NET_STR":   cot_net_str,
    "COT_PCT_STR":   cot_pct_str,
    "COT_DATE":      cot_date,
    "COT_CHANGE_STR":cot_change_str,
    "CORR2W_STR":    corr2w_str,
    "CORR1M_STR":    corr1m_str,
    "DOTS_HTML":     dots_html,
    "SIG_COUNT":     str(signals_count),
    "CONFIRM_COLOR": confirm_color,
    "CONFIRM_MSG":   confirm_msg,
    "J_VIX_DATES":   j_vix_dates,
    "J_VIX_VALS":    j_vix_vals,
    "J_COT_DATES":   j_cot_dates,
    "J_COT_VALS":    j_cot_vals,
    "J_CORR_DATES":  j_corr_dates,
    "J_CORR_HIST":   j_corr_hist,
    "J_CORR_FLAT":   j_corr_flat,
    "VIX9D_R_STR":   "'" + vix9d_r + "'",
    "VIX_R_STR":     "'" + vix_r   + "'",
    "VIX3M_R_STR":   "'" + vix3m_r + "'",
    "VIX9D_R":       vix9d_r,
    "VIX_R":         vix_r,
    "VIX3M_R":       vix3m_r,
    "VIX_YMAX":      vix_ymax,
}

for placeholder, value in replacements.items():
    html_out = html_out.replace(placeholder, value)

with open("index.html", "w", encoding="utf-8") as f:
    f.write(html_out)

print(f"Dashboard generated: {len(html_out)} chars, signals={signals_count}/5")
