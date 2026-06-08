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
parts.append('<div class="bottom-item">GEX: <span>Requires SpotGamma/SqueezeMetrics</span></div>')
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
parts.append('window.addEventListener("resize",function(){')
parts.append('  ["chart-vix","chart-vix-term","chart-cot","chart-corr"].forEach(function(id){Plotly.Plots.resize(document.getElementById(id));});')
parts.append('});')
parts.append('})();')
parts.append('</script></body></html>')

out = "\n".join(parts)

with open("index.html", "w", encoding="utf-8") as f:
    f.write(out)

print("Done. chars={} signals={}/5".format(len(out), sig_count))
