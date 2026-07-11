# Market Fragility Dashboard

Auto-updating dashboard tracking 5 bottom-confirmation signals from the Chinese analyst's de-leveraging framework.

**Live dashboard:** [https://vincizh.github.io/market-fragility-dashboard/](https://vincizh.github.io/market-fragility-dashboard/) *(or your Netlify URL once connected)*

## Signals Tracked

| # | Signal | Source | Bullish When |
|---|--------|--------|-------------|
| ① | VIX Term Structure | CBOE via Yahoo Finance | VIX3M > VIX (contango) |
| ② | Crypto Funding Rate | Binance Futures (CoinGecko) + OKX | BTC + ETH both positive |
| ③ | CTA Proxy (NDX Lev. Money) | CFTC COT Disaggregated | Week-over-week short covering |
| ④ | Cross-Sector Correlation | Yahoo Finance sector ETFs | Declining (stocks re-dispersing) |

**Rule:** ≥ 3/5 signals = de-lever exhausting. All 5 = re-engage.

## How It Works

- `generate_dashboard.py` fetches live data and writes `index.html`
- GitHub Actions runs it **every hour** automatically
- Netlify (or GitHub Pages) serves the latest `index.html`
- No server needed — fully static after generation

## Setup

### Netlify
1. Connect this repo to Netlify
2. Build command: *(leave blank)*
3. Publish directory: `/` (root)
4. Deploy — Netlify auto-deploys on every push from Actions

### Manual trigger
Go to **Actions → Generate Dashboard → Run workflow** to force an immediate refresh.

## Data Sources
- VIX: CBOE via Yahoo Finance
- Funding rates: Binance Futures proxied via CoinGecko public API + OKX public API
- COT: CFTC Disaggregated Futures (Financial) — ~3-day publication lag
- Correlation: Yahoo Finance (XLK, XLF, XLV, XLE, XLI, XLC, XLY, XLP, XLB, XLU, XLRE)

> ⚠️ Dealer Gamma (GEX) is not included — requires a paid SpotGamma or SqueezeMetrics subscription.
