#!/usr/bin/env python3
"""
De-Lever Signal Dashboard Generator
Runs via GitHub Actions on a schedule, writes index.html
Data sources:
  - VIX term structure: Yahoo Finance (CBOE)
  - Crypto funding rates: CoinGecko (Binance Futures) + OKX public API
  - CTA proxy: CFTC COT Disaggregated (NDX Leveraged Money)
  - Cross-sector correlation: Yahoo Finance sector ETFs
"""

import yfinance as yf
import requests
import pandas as pd
import numpy as np
import json
import io
import zipfile
from datetime import datetime, timezone

print("Starting dashboard generation...")

# ============================================================
# METRIC 1: VIX Term Structure
# ============================================================
print("Fetching VIX data...")
vix_spot = yf.download("^VIX", period="30d", auto_adjust=True, progress=False)['Close']
vix3m_hist = yf.download("^VIX3M", period="30d", auto_adjust=True, progress=False)['Close']
vix9d_hist = yf.download("^VIX9D", period="30d", auto_adjust=True, progress=False)['Close']

vix_val = float(vix_spot.iloc[-1].iloc[0])
vix3m_val = float(vix3m_hist.iloc[-1].iloc[0])
vix9d_val = float(vix9d_hist.iloc[-1].iloc[0])

vix_dates = [d.strftime('%Y-%m-%d') for d in vix_spot.index]
vix_vals = [round(float(v), 2) for v in vix_spot.values.flatten()]
vix3m_vals_hist = [round(float(v), 2) for v in vix3m_hist.values.flatten()]

vix_contango = vix3m_val > vix_val
print(f"VIX={vix_val:.2f}, VIX3M={vix3m_val:.2f}, VIX9D={vix9d_val:.2f}, Contango={vix_contango}")

# ============================================================
# METRIC 2: Crypto Funding Rates
# ============================================================
print("Fetching crypto funding rates...")
try:
    cg_resp = requests.get(
        "https://api.coingecko.com/api/v3/derivatives?include_tickers=unexpired",
        timeout=20
    )
    cg_data = cg_resp.json()
    bnb_btc = next((x for x in cg_data if x.get('market') == 'Binance (Futures)' and x.get('symbol') == 'BTCUSDT'), None)
    bnb_eth = next((x for x in cg_data if x.get('market') == 'Binance (Futures)' and x.get('symbol') == 'ETHUSDT'), None)
    bnb_btc_fr = bnb_btc['funding_rate'] * 100 if bnb_btc else None
    bnb_eth_fr = bnb_eth['funding_rate'] * 100 if bnb_eth else None
    bnb_btc_oi = (bnb_btc['open_interest'] or 0) / 1e9 if bnb_btc else None
except Exception as e:
    print(f"CoinGecko error: {e}")
    bnb_btc_fr = bnb_eth_fr = bnb_btc_oi = None

try:
    okx_btc_fr = float(requests.get(
        "https://www.okx.com/api/v5/public/funding-rate?instId=BTC-USDT-SWAP",
        timeout=10
    ).json()['data'][0]['fundingRate']) * 100
    okx_eth_fr = float(requests.get(
        "https://www.okx.com/api/v5/public/funding-rate?instId=ETH-USDT-SWAP",
        timeout=10
    ).json()['data'][0]['fundingRate']) * 100
except Exception as e:
    print(f"OKX error: {e}")
    okx_btc_fr = okx_eth_fr = None

# Fallback: use OKX if CoinGecko fails
btc_fr_display = bnb_btc_fr if bnb_btc_fr is not None else okx_btc_fr
eth_fr_display = bnb_eth_fr if bnb_eth_fr is not None else okx_eth_fr
btc_source = "Binance" if bnb_btc_fr is not None else "OKX"

btc_positive = (btc_fr_display or 0) > 0
eth_positive = (eth_fr_display or 0) > 0
print(f"BTC FR={btc_fr_display:.4f}% ({btc_source}), ETH FR={eth_fr_display:.4f}%")

# ============================================================
# METRIC 3: CFTC COT — NDX Leveraged Money (CTA Proxy)
# ============================================================
print("Fetching CFTC COT data...")

def fetch_cot_year(year):
    url = f"https://www.cftc.gov/files/dea/history/fut_fin_txt_{year}.zip"
    r = requests.get(url, timeout=30)
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        fname = z.namelist()[0]
        with z.open(fname) as f:
            return pd.read_csv(f, low_memory=False)

try:
    current_year = datetime.now().year
    frames = []
    for yr in [current_year - 1, current_year]:
        try:
            frames.append(fetch_cot_year(yr))
        except Exception as e:
            print(f"COT {yr} error: {e}")
    all_cot = pd.concat(frames) if frames else pd.DataFrame()

    ndx_all = all_cot[
        all_cot['Market_and_Exchange_Names'] == 'NASDAQ-100 Consolidated - CHICAGO MERCANTILE EXCHANGE'
    ].copy()
    ndx_all = ndx_all.sort_values('Report_Date_as_YYYY-MM-DD')
    ndx_all['lev_net'] = ndx_all['Lev_Money_Positions_Long_All'] - ndx_all['Lev_Money_Positions_Short_All']
    ndx_all['lev_net_pct_oi'] = ndx_all['lev_net'] / ndx_all['Open_Interest_All'] * 100
    ndx_recent = ndx_all.tail(16)

    latest_cot = ndx_recent.iloc[-1]
    cot_net = int(latest_cot['lev_net'])
    cot_pct = float(latest_cot['lev_net_pct_oi'])
    cot_date = latest_cot['Report_Date_as_YYYY-MM-DD']
    cot_change = cot_net - int(ndx_recent.iloc[-2]['lev_net'])
    cot_chart_dates = ndx_recent['Report_Date_as_YYYY-MM-DD'].tolist()
    cot_chart_vals = [int(x) for x in ndx_recent['lev_net'].tolist()]
    cta_covering = cot_change > 0
except Exception as e:
    print(f"COT processing error: {e}")
    cot_net = cot_pct = cot_change = 0
    cot_date = "N/A"
    cot_chart_dates = cot_chart_vals = []
    cta_covering = False

print(f"COT net={cot_net:,}, pct={cot_pct:.1f}%, change={cot_change:+,}")

# ============================================================
# METRIC 4: Cross-Sector Correlation
# ============================================================
print("Fetching sector correlation data...")
tickers = ['XLK','XLF','XLV','XLE','XLI','XLC','XLY','XLP','XLB','XLU','XLRE']
n = len(tickers)
sector_data = yf.download(tickers, period="2mo", auto_adjust=True, progress=False)['Close']
returns_full = sector_data.pct_change().dropna()

corr_1m = returns_full.tail(21).corr()
avg_corr_1m = (corr_1m.values.sum() - n) / (n*(n-1))
corr_2w = returns_full.tail(10).corr()
avg_corr_2w = (corr_2w.values.sum() - n) / (n*(n-1))

corr_history = []
dates_hist = []
for i in range(21, len(returns_full)+1):
    window = returns_full.iloc[i-21:i]
    cm = window.corr().values
    ac = (cm.sum() - n) / (n*(n-1))
    corr_history.append(round(ac, 4))
    dates_hist.append(returns_full.index[i-1].strftime('%Y-%m-%d'))

corr_declining = avg_corr_2w < avg_corr_1m
print(f"Corr 1M={avg_corr_1m:.3f}, 2W={avg_corr_2w:.3f}, declining={corr_declining}")

# ============================================================
# COMPUTE SIGNALS
# ============================================================
signals_count = sum([vix_contango, btc_positive, eth_positive, cta_covering, corr_declining])
now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

vix_class = "green" if vix_contango else "red"
btc_class = "green" if btc_positive else "red"
eth_class = "green" if eth_positive else "red"
cot_class = "green" if cta_covering else "red"
corr_class = "green" if corr_declining else "yellow"
funding_card = "green" if btc_positive and eth_positive else "yellow" if btc_positive or eth_positive else "red"
funding_badge = "badge-green" if btc_positive and eth_positive else "badge-yellow" if btc_positive or eth_positive else "badge-red"
funding_summary = ("BOTH POSITIVE \u2705 \u2014 Risk appetite returning" if btc_positive and eth_positive
                   else "MIXED \u26a0\ufe0f \u2014 Partial recovery" if btc_positive or eth_positive
                   else "BOTH NEGATIVE \u26a0\ufe0f \u2014 Still de-risking")

if signals_count <= 1:
    confirm_msg, confirm_color = "No signals confirmed \u2014 stay out, liquidity vacuum still active", "#ef4444"
elif signals_count == 2:
    confirm_msg, confirm_color = "Watch closely \u2014 de-lever may be abating", "#f59e0b"
elif signals_count == 3:
    confirm_msg, confirm_color = "Threshold reached: mechanical selling likely exhausting", "#10b981"
elif signals_count == 4:
    confirm_msg, confirm_color = "Strong confirmation \u2014 consider re-entry on core names", "#10b981"
else:
    confirm_msg, confirm_color = "All signals confirmed \u2014 de-lever complete, re-engage", "#10b981"

signal_labels = [
    ("VIX Contango", vix_contango),
    ("BTC FR+", btc_positive),
    ("ETH FR+", eth_positive),
    ("CTA Covering", cta_covering),
    ("Corr Declining", corr_declining),
]
dots_html = "".join(
    f'<div class="dot {"filled" if ok else "empty"}" title="{label}"></div>'
    for label, ok in signal_labels
)

# ============================================================
# RENDER HTML
# ============================================================
html_out = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
<title>De-Lever Signal Dashboard</title>
<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ background: #0d0f14; color: #e2e8f0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }}
.header {{ background: #141720; border-bottom: 1px solid #2d3748; padding: 14px 20px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; }}
.header-left h1 {{ font-size: 16px; font-weight: 700; color: #e2e8f0; }}
.header-left h1 span {{ color: #6366f1; }}
.header-left p {{ font-size: 11px; color: #475569; margin-top: 2px; }}
.header-right {{ display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }}
.timestamp {{ font-size: 11px; color: #64748b; }}
.signal-bar {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; padding: 16px 20px; }}
@media (max-width: 900px) {{ .signal-bar {{ grid-template-columns: repeat(2, 1fr); }} }}
@media (max-width: 480px) {{ .signal-bar {{ grid-template-columns: 1fr; }} }}
.signal-card {{ background: #141720; border: 1px solid #2d3748; border-radius: 10px; padding: 14px 16px; }}
.signal-card.green {{ border-left: 3px solid #10b981; }}
.signal-card.red {{ border-left: 3px solid #ef4444; }}
.signal-card.yellow {{ border-left: 3px solid #f59e0b; }}
.signal-label {{ font-size: 10px; color: #64748b; text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 5px; }}
.signal-value {{ font-size: 20px; font-weight: 700; margin-bottom: 3px; line-height: 1.2; }}
.signal-value.green {{ color: #10b981; }}
.signal-value.red {{ color: #ef4444; }}
.signal-value.yellow {{ color: #f59e0b; }}
.signal-sub {{ font-size: 11px; color: #64748b; line-height: 1.4; }}
.signal-badge {{ display: inline-block; font-size: 10px; font-weight: 600; padding: 3px 8px; border-radius: 4px; margin-top: 7px; line-height: 1.4; }}
.badge-green {{ background: rgba(16,185,129,0.15); color: #10b981; }}
.badge-red {{ background: rgba(239,68,68,0.15); color: #ef4444; }}
.badge-yellow {{ background: rgba(245,158,11,0.15); color: #f59e0b; }}
.confirm-counter {{ background: #141720; border: 1px solid #2d3748; border-radius: 8px; margin: 0 20px 16px 20px; padding: 12px 16px; display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }}
.confirm-label {{ font-size: 11px; color: #64748b; text-transform: uppercase; letter-spacing: 0.06em; white-space: nowrap; }}
.confirm-dots {{ display: flex; gap: 6px; flex-shrink: 0; }}
.dot {{ width: 11px; height: 11px; border-radius: 50%; cursor: default; }}
.dot.filled {{ background: #10b981; }}
.dot.empty {{ background: #2d3748; }}
.confirm-text {{ font-size: 12px; color: #94a3b8; }}
.confirm-text strong {{ color: #e2e8f0; }}
.charts-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; padding: 0 20px 16px 20px; }}
@media (max-width: 700px) {{ .charts-grid {{ grid-template-columns: 1fr; }} }}
.chart-card {{ background: #141720; border: 1px solid #2d3748; border-radius: 10px; padding: 14px; min-width: 0; }}
.chart-title {{ font-size: 12px; font-weight: 600; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.05em; }}
.chart-subtitle {{ font-size: 10px; color: #475569; margin: 3px 0 10px 0; line-height: 1.4; }}
.bottom-bar {{ background: #0a0c10; border-top: 1px solid #1e2433; padding: 10px 20px; display: flex; flex-wrap: wrap; gap: 16px; }}
.bottom-item {{ font-size: 10px; color: #475569; }}
.bottom-item span {{ color: #64748b; }}
</style>
</head>
<body>
<div class="header">
  <div class="header-left">
    <h1>De-Lever Signal Dashboard <span>/ NDX</span></h1>
    <p>5 bottom confirmation signals &middot; auto-updated every hour</p>
  </div>
  <div class="header-right">
    <div class="timestamp">Last updated: {now_str}</div>
  </div>
</div>
<div class="signal-bar">
  <div class="signal-card {vix_class}">
    <div class="signal-label">&#9312; VIX Term Structure</div>
    <div class="signal-value {vix_class}">{vix3m_val - vix_val:+.2f} pts</div>
    <div class="signal-sub">VIX9D {vix9d_val:.1f} &rarr; VIX {vix_val:.1f} &rarr; VIX3M {vix3m_val:.1f}</div>
    <div class="signal-badge {'badge-green' if vix_contango else 'badge-red'}">{'CONTANGO \u2705' if vix_contango else 'BACKWARDATION \u26a0\ufe0f'}</div>
  </div>
  <div class="signal-card {funding_card}">
    <div class="signal-label">&#9313; Crypto Funding ({btc_source})</div>
    <div class="signal-value {btc_class}">BTC {btc_fr_display:+.4f}%</div>
    <div class="signal-sub">ETH {eth_fr_display:+.4f}% &middot; OKX BTC {okx_btc_fr:+.4f}%</div>
    <div class="signal-badge {funding_badge}">{funding_summary}</div>
  </div>
  <div class="signal-card {cot_class}">
    <div class="signal-label">&#9314; CTA Proxy (CFTC COT)</div>
    <div class="signal-value {cot_class}">{cot_net:,}</div>
    <div class="signal-sub">{cot_pct:.1f}% OI &middot; as of {cot_date}<br>WoW: {cot_change:+,} contracts</div>
    <div class="signal-badge {'badge-green' if cta_covering else 'badge-red'}">{'SHORT COVERING \u2705' if cta_covering else 'ADDING SHORTS \u26a0\ufe0f'}</div>
  </div>
  <div class="signal-card {corr_class}">
    <div class="signal-label">&#9315; Cross-Sector Correlation</div>
    <div class="signal-value {corr_class}">{avg_corr_2w:.3f}</div>
    <div class="signal-sub">2W vs 1M avg: {avg_corr_1m:.3f} &rarr; {avg_corr_2w:.3f}</div>
    <div class="signal-badge {'badge-green' if corr_declining else 'badge-yellow'}">{'DECLINING \u2705' if corr_declining else 'ELEVATED \u26a0\ufe0f'}</div>
  </div>
</div>
<div class="confirm-counter">
  <div class="confirm-label">Signals confirmed</div>
  <div class="confirm-dots">{dots_html}</div>
  <div class="confirm-text"><strong>{signals_count}/5</strong> &mdash; <span style="color:{confirm_color}">{confirm_msg}</span></div>
</div>
<div class="charts-grid">
  <div class="chart-card">
    <div class="chart-title">VIX 30-Day History</div>
    <div class="chart-subtitle">Spot VIX &mdash; above 20 = elevated fear regime</div>
    <div id="chart-vix"></div>
  </div>
  <div class="chart-card">
    <div class="chart-title">VIX Term Structure Snapshot</div>
    <div class="chart-subtitle">Upward slope = contango = panic receding</div>
    <div id="chart-vix-term"></div>
  </div>
  <div class="chart-card">
    <div class="chart-title">NDX Leveraged Money Net (COT)</div>
    <div class="chart-subtitle">CTA proxy &mdash; net short = crowded; covering = selling abating</div>
    <div id="chart-cot"></div>
  </div>
  <div class="chart-card">
    <div class="chart-title">Cross-Sector Correlation (Rolling 21D)</div>
    <div class="chart-subtitle">High = panic-driven; declining = fundamentals returning</div>
    <div id="chart-corr"></div>
  </div>
</div>
<div class="bottom-bar">
  <div class="bottom-item">VIX: <span>CBOE via Yahoo Finance</span></div>
  <div class="bottom-item">Funding: <span>Binance Futures (CoinGecko) + OKX API</span></div>
  <div class="bottom-item">COT: <span>CFTC Disaggregated (&sim;3-day lag)</span></div>
  <div class="bottom-item">Correlation: <span>Sector ETFs XLK&ndash;XLRE</span></div>
  <div class="bottom-item">&nbsp;&#9888; GEX: <span>Requires SpotGamma/SqueezeMetrics</span></div>
</div>
<script>
(function() {{
var THEME = {{
  paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)',
  font: {{ color: '#94a3b8', size: 10, family: '-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif' }},
  xaxis: {{ gridcolor: '#1e2433', zerolinecolor: '#2d3748', tickfont: {{ size: 9 }}, automargin: true, fixedrange: true }},
  yaxis: {{ gridcolor: '#1e2433', zerolinecolor: '#2d3748', tickfont: {{ size: 9 }}, automargin: true, fixedrange: true }},
  margin: {{ l: 40, r: 8, t: 8, b: 40 }},
  showlegend: false, height: 190, autosize: true
}};
Plotly.newPlot('chart-vix', [{{
  x: {json.dumps(vix_dates)}, y: {json.dumps(vix_vals)},
  type: 'scatter', mode: 'lines',
  line: {{ color: '#f59e0b', width: 2 }},
  fill: 'tozeroy', fillcolor: 'rgba(245,158,11,0.07)'
}}], Object.assign({{}}, THEME, {{
  shapes: [{{ type:'line', x0:0, x1:1, xref:'paper', y0:20, y1:20, line:{{ color:'#ef4444', width:1, dash:'dot' }} }}]
}}), {{ responsive: true, displayModeBar: false }});
Plotly.newPlot('chart-vix-term', [{{
  x: ['VIX9D', 'VIX spot', 'VIX3M'],
  y: [{round(vix9d_val,2)}, {round(vix_val,2)}, {round(vix3m_val,2)}],
  type: 'bar',
  marker: {{ color: ['#ef4444','#f59e0b','#10b981'], line: {{ width: 0 }} }},
  text: ['{round(vix9d_val,2)}', '{round(vix_val,2)}', '{round(vix3m_val,2)}'],
  textposition: 'outside', textfont: {{ color: '#e2e8f0', size: 12 }},
  width: [0.5, 0.5, 0.5]
}}], {{
  paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)',
  font: {{ color: '#94a3b8', size: 10 }},
  xaxis: {{ type: 'category', gridcolor: '#1e2433', tickfont: {{ size: 11, color: '#94a3b8' }}, fixedrange: true }},
  yaxis: {{ gridcolor: '#1e2433', zerolinecolor: '#2d3748', tickfont: {{ size: 9 }}, range: [0, {max(vix9d_val, vix_val, vix3m_val) * 1.25:.2f}], automargin: true, fixedrange: true }},
  margin: {{ l: 30, r: 8, t: 28, b: 36 }},
  showlegend: false, height: 190, autosize: true
}}, {{ responsive: true, displayModeBar: false }});
var cotColors = {json.dumps(cot_chart_vals)}.map(function(v){{ return v >= 0 ? '#10b981' : '#ef4444'; }});
Plotly.newPlot('chart-cot', [{{
  x: {json.dumps(cot_chart_dates)}, y: {json.dumps(cot_chart_vals)},
  type: 'bar', marker: {{ color: cotColors }}
}}], Object.assign({{}}, THEME, {{
  shapes: [{{ type:'line', x0:0, x1:1, xref:'paper', y0:0, y1:0, line:{{ color:'#475569', width:1 }} }}],
  xaxis: Object.assign({{}}, THEME.xaxis, {{ tickangle: -35 }})
}}), {{ responsive: true, displayModeBar: false }});
Plotly.newPlot('chart-corr', [{{
  x: {json.dumps(dates_hist)}, y: {json.dumps(corr_history)},
  type: 'scatter', mode: 'lines',
  line: {{ color: '#6366f1', width: 2 }},
  fill: 'tozeroy', fillcolor: 'rgba(99,102,241,0.07)'
}}, {{
  x: {json.dumps(dates_hist)}, y: {json.dumps([0.5]*len(dates_hist))},
  type: 'scatter', mode: 'lines',
  line: {{ color: '#ef4444', width: 1, dash: 'dash' }}
}}], Object.assign({{}}, THEME, {{ showlegend: false }}), {{ responsive: true, displayModeBar: false }});
window.addEventListener('resize', function() {{
  ['chart-vix','chart-vix-term','chart-cot','chart-corr'].forEach(function(id){{
    Plotly.Plots.resize(document.getElementById(id));
  }});
}});
}})();
</script>
</body>
</html>"""

with open("index.html", "w", encoding="utf-8") as f:
    f.write(html_out)

print(f"Dashboard generated successfully: {len(html_out)} chars")
print(f"Signals: {signals_count}/5")
