# Market Fragility Dashboard

A public-data dashboard for **market fragility, not market direction**. The page is organised as a four-layer risk stack, read top to bottom:

1. **Fragility** — the Liquidity Pressure Index (LPI) and its conditional tail table.
2. **Conditions** — funding and plumbing (SOFR, repo, reserves, TGA, standing facilities), the Fed balance sheet and reserve-management purchases, credit spreads, and rates and term premium.
3. **Crowding** — S&P 500 concentration, AI leadership, CFTC positioning and the basis-trade proxy.
4. **Amplifiers and triggers** — the de-leveraging bottom signals (VIX curve, crypto funding, CTA short covering, correlation) and dealer gamma.

An overview scorecard, a what-changed panel and the key takeaway sit above the layers. A data-health chip in the header links to a table of every source with its last observation date and status.

**Live dashboard:** <https://vincizh.github.io/market-fragility-dashboard/>

The dashboard is deterministic and refreshes hourly through GitHub Actions. A missing upstream source degrades only that module; stale or date-misaligned data is shown in gray and is never rendered as a current value.

## Current modules

| Layer | Module | Formula / display | Source and cadence |
|---|---|---|---|
| L1 | Liquidity Pressure Index | Causal weekly percentiles of short rate, coupon supply, net liquidity and VIX | FRED, FiscalData, Cboe/Yahoo market history; weekly / daily inputs |
| 1 | LPI conditional tail table | Forward S&P 500 outcomes by LPI band; folded by default | Yahoo ^GSPC weekly |
| 2 | Reserves / GDP | `WRESBAL / (GDP × 1,000)` with a rolling 156-week percentile; warning/elevated requires two weekly observations | [FRED WRESBAL](https://fred.stlouisfed.org/graph/fredgraph.csv?id=WRESBAL), [FRED GDP](https://fred.stlouisfed.org/graph/fredgraph.csv?id=GDP) |
| 2 | NY Fed repo accepted | Daily accepted amount and trailing 7-calendar-day sum; persistence / own-history percentile, not a dollar threshold | [NY Fed Markets API](https://markets.newyorkfed.org/api/rp/repo/all/results/last/40.json) |
| 2 | Dollar Funding Pressure (SOFR − IORB · reserves · TGA) | Three-leg strategy overlay combined into a 0/3–3/3 resonance state | [NY Fed SOFR](https://markets.newyorkfed.org/api/rates/secured/sofr/last/15.json), [FRB PRATES IORB](https://www.federalreserve.gov/datadownload/Choose.aspx?rel=PRATES), [Federal Reserve H.4.1](https://www.federalreserve.gov/releases/h41/current/h41.htm), [Treasury DTS](https://fiscaldata.treasury.gov/datasets/daily-treasury-statement/operating-cash-balance) |
| 2 | Funding extras and backstops | SOFR distribution, TGCR, SOFR volume; standing repo, swap lines, FIMA repo and discount window usage against their own history | FRED series listed in the data dictionary in [METHODOLOGY.md](METHODOLOGY.md) |
| 2 | Fed balance sheet and RMP | Treasury bills and short coupons held, reserve-management-purchase pace, foreign official RRP pool | FRED H.4.1 series; programme background in the [NY Fed RMP statement](https://www.newyorkfed.org/markets/opolicy/operating_policy_251210a) and the [Federal Reserve press release](https://www.federalreserve.gov/newsevents/pressreleases/monetary20251210a1.htm) |
| 2 | Credit | ICE BofA OAS by rating bucket, CCC minus BB, NFCI, ANFCI, St. Louis stress index, EM corporate OAS | FRED |
| 2 | Rates and term premium | 2Y, 10Y, 30Y, real 10Y, breakeven, 10Y term premium, 10Y-2Y | FRED |
| 3 | CFTC positioning and basis proxy | Leveraged-fund / managed-money net positions, percentiles, and a 2y/5y/10y basis-trade proxy | [CFTC public reporting API](https://publicreporting.cftc.gov/) · weekly |
| 3 | S&P 500 concentration | Sum of the largest 10 and 5 weights in SPY's official holdings file; local daily snapshots begin the history | [SSGA SPY holdings](https://www.ssga.com/us/en/intermediary/library-content/products/fund-data/etfs/us/holdings-daily-us-en-spy.xlsx) |
| 3 | AI breadth and relative strength | Fixed 19-security basket above 50d/200d MAs; SMH/SPY and SOXX/SPY ratio trends | Yahoo Finance adjusted daily closes |
| 4 | VIX term structure | Official Cboe VIX and VIX3M closes (VIX9D optional); the curve uses the latest date on which VIX and VIX3M are both available, with FRED VIXCLS/VXVCLS as fallback | [Cboe VIX3M history](https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX3M_History.csv) |
| 4 | Dealer gamma | Homebrew Black–Scholes gamma aggregation from SPY/QQQ option chains; a reading is rejected when the chain has fewer than 200 usable contracts or 3 expiries, and the last accepted snapshot is shown labelled as cached | Yahoo option chains |
| 4 | Crypto funding, CTA and correlation | Crypto funding rate (unit-checked), NDX COT short-covering proxy, cross-sector correlation | CoinGecko/OKX, CFTC, Yahoo Finance |
| – | Liquidity calendar | Rolling 120 days: announced Treasury coupon settlements, FOMC decision days, tax dates, month and quarter ends, estimated refunding dates; weekly event count, no severity percentiles | [FiscalData upcoming auctions](https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/od/upcoming_auctions), [Fed FOMC calendar](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm) |

The new FRED indicators (funding extras, backstops, Fed balance sheet, credit, rates) are descriptive. They do not enter the LPI, the de-leveraging tally or any composite.

### Code layout

| File | Role |
|---|---|
| `generate_dashboard.py` | Orchestration: fetches non-FRED sources, computes LPI, COT, signals, assembles the page |
| `fast_metrics.py` | Freshness rules, FRED fetch with archive fallback, VIX alignment, funding unit checks, weekly issuance grid |
| `fred_catalog.py` | Declarative list of FRED series with units, cadence, maximum age |
| `fred_monitor.py` | Concurrent catalog fetch, spreads, percentiles, z-scores, descriptive states |
| `fred_modules.py` / `fred_render.py` | Section builders and renderers for funding, Fed balance sheet, credit, rates; what-changed helpers |
| `layout_render.py` | Navigation, scorecard, collapsible sections, COT heat strip, tabs, data-health table |
| `dash_state.py` | Embedded 45-day snapshot used by the what-changed panel |
| `stress_calendar.py` | Rolling 120-day liquidity calendar |
| `index_gex.py` | Pure homebrew-GEX functions (no network) |
| `health.py` | Source registry written to `data/health.json` and the Actions step summary |


## Critical data-quality rules

### VIX term structure

The dashboard **does not use Yahoo `^VIX3M`**. It uses Cboe's official daily-history CSVs for VIX and VIX3M, with VIX9D as an optional third point, and falls back to FRED VIXCLS and VXVCLS if Cboe is unavailable. The curve is built on the latest date on which VIX and VIX3M both exist, and VIX9D is shown only if it carries that same date. The spot VIX history is independent of the curve. A curve older than the freshness limit is marked stale.

### Reserves are relative, not fixed dollar thresholds

The **normalized structural metric** is unchanged: reserves/GDP with a causal 3-year (156-week) percentile — below the 20th percentile for two weekly observations is a warning, below the 10th for two is elevated. The `$2.90T` / `$2.80T` dollar levels appear only inside the Dollar Funding Pressure section, where they are labeled as the operator's strategy overlay rather than an empirical law, and they do not feed the reserves/GDP percentile logic.

### Dollar Funding Pressure: one section, three legs

`SOFR − IORB`, **bank reserve balances** and the **Treasury General Account** are consolidated into a single Layer 1 section (`#funding-pressure`) with three aligned small-multiple charts on one shared x-axis and one shared 3M/6M/1Y/3Y range control. There is no separate SOFR-IORB panel any more, and no dual/triple-axis overlay.

The absolute trigger levels below are an explicit **user-defined strategy overlay**, not a universal empirical law, and the dashboard says so on the page. The three-leg state is a *fragility confirmation*, never a deterministic market-top prediction.

| Leg | Card | Active (counts toward resonance) | Elevated |
|---|---|---|---|
| A. Funding price | `SOFR − IORB` in bp | filtered non-calendar 5-observation median ≥ `+3bp` **and** the last 3 non-calendar observations all ≥ `+3bp` | filtered median ≥ `+5bp` |
| B. Liquidity buffer | reserve balances, `$T` | level ≤ `$2.90T` **and** 4-week change ≤ `−$50B` | level ≤ `$2.85T` or 4-week change ≤ `−$100B` |
| C. Fiscal drain | TGA, `$T` | level ≥ `$0.90T` **and** 4-week change ≥ `+$50B` | level ≥ `$1.00T` or 4-week change ≥ `+$100B` |

Only one of the two conditions met shows as **approaching** and does *not* count. Resonance: `0/3` no resonance · `1/3` watch (the named leg only) · `2/3` yellow warning, funding pressure building · `3/3` structural-top risk signal. A stale, unavailable, or 4-week-incomplete leg can never count as triggered; the header then shows an incomplete-data state.

Causality is stated on the page as a three-node path: a rebuilding TGA drains bank reserves one-for-one, and a thinner reserve buffer makes secured overnight funding price above IORB.

### SOFR − IORB is calendar-filtered

Month-end, quarter-end, major US corporate estimated-tax dates (April/June/September/December 15, adjusted to business days), and large Treasury settlement dates derived from [Treasury auction issue dates](https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/od/auctions_query) are labeled as calendar noise. A “large” settlement is an official auction issue date with at least `$30B` offered. They are displayed as hollow markers but cannot trigger a structural alert or the strategy leg.

* **Strategy threshold (visually primary):** `+3bp`, with the 3-observation persistence rule above.
* **Analytical reference bands (kept, muted):** structural watch at three consecutive non-calendar observations ≥ `+2bp`; elevated ≥ `+5bp`. These are this dashboard's own persistence-based bands and are intentionally stricter/different from the operator's `+3bp` line.
* The emphasized series is a five-observation median of non-calendar readings.

Positive SOFR − IORB means secured overnight funding trades above the Fed's administered reserve rate. It is a stress confirmation signal — especially with repo use and SOFR-tail widening — not a stand-alone market-top predictor.

### Reserves and TGA are fetched from official releases, spliced, never interpolated

Both series are read first from the [Federal Reserve H.4.1 release](https://www.federalreserve.gov/releases/h41/current/h41.htm) (Table 1, *Reserve balances with Federal Reserve Banks* and *U.S. Treasury, General Account*, weekly average of daily figures for the week ended Wednesday — the same definition FRED publishes as `WRESBAL` / `WTREGEN`), then from FRED, then from the local versioned cache; the live/preferred tail wins on overlap and nothing is interpolated or forward-filled. `data/fred-cache/H41_WEEKLY.csv` accumulates each parsed release so a fredgraph outage from CI cannot blank the legs. The Daily Treasury Statement operating-cash endpoint is an official daily fallback tail for the TGA only. Each source is fetched in its own isolated try/except, so one failure cannot blank the other two legs.

Reserves/GDP with its rolling 156-week percentile remains a **separate** normalized structural metric; the strategy overlay's dollar levels do not replace it.

### LPI: spliced official sources, one common as-of week, freshness gate

FRED can time out from GitHub Actions, which previously froze every LPI factor on the last cached week. Each LPI input now splices a second official source after FRED's last observation: SOFR from the [NY Fed reference-rate API](https://markets.newyorkfed.org/), WALCL (Wednesday total assets) and WTREGEN (weekly-average TGA) from the [Federal Reserve H.4.1 release archive](https://www.federalreserve.gov/releases/h41/), and overnight RRP take-up from the [NY Fed reverse-repo results API](https://markets.newyorkfed.org/api/rp/reverserepo/all/results/last/500.json). The pre-2018 short-rate history uses DFF, now committed to `data/fred-cache/DFF.csv` so CI and local runs use the same history.

* Net-liquidity inputs are carried forward only across a single interior gap (holiday shift), never past a series' last print.
* Treasury auctions dated after today are excluded from the 4-week duration-supply sum.
* The headline, factor cards, sparklines and decomposition all read the same week: the latest week on which every available factor has an observation. The gauge shows that common as-of date plus each factor's own last observation and source.
* If the common week is more than 12 days old, the LPI is shown gray as a last-known value and no regime action language or sizing stance is issued.
* LPI bands: below 40 low, 40-60 neutral, 60-80 elevated, 80+ extreme. The regime level still splits High/Low at 60.

### De-lever conditions are counted over evaluable signals only

The amplifier count is `confirmed / evaluable`. A signal whose source failed (VIX curve stale or date-mismatched, a crypto funding rate missing, COT unavailable) is marked unavailable and removed from the denominator instead of counting as a failed condition. BTC and ETH funding are two separate votes. Dealer gamma is context and is not part of the count.

### Freshness and fallback

Every Phase A/B card shows both the **observation date** and the **pipeline fetch time**, plus its expected cadence. Daily business-day data becomes stale after four calendar days and weekly reserve data after ten; stale data is gray. FRED requests use retry plus a versioned archive of official FRED CSV responses as a graceful fallback; the archive only grows (new observations are merged in, history is never shortened) and a cached row is labelled cached in the data-health table. FRED requests are sent without a custom User-Agent because the fredgraph endpoint stalls on custom or browser agents. Stale data is never forward-filled. The displayed observation date, not the page refresh time, governs freshness.

### S&P 500 concentration history

SSGA publishes the current SPY holdings file, not an index history. The pipeline appends the observed Top-5/Top-10 result to `data/spy-concentration-history.json` once per day. Until 60 snapshots exist, it explicitly reports **insufficient history** and does not fabricate percentile alerts.

### AI basket and survivorship caveat

The fixed basket is: `NVDA, MU, MSFT, GOOGL, AMZN, META, AVGO, ORCL, VRT, ETN, PWR, CEG, TSM, ANET, DELL, SMCI, KLAC, AMAT, LRCX`. It is a documented, subjective supply-chain basket, not an index or recommendation; it has survivorship and selection bias. `SMH` is used only as an ETF benchmark, alongside `SOXX`, for relative-strength ratios.

### DIX boundary

DIX is **not an automated signal or score** in this repository. FINRA ATS or Reg SHO data must never be silently presented as equivalent to DIX because neither provides its directional dark-pool-buying construct. Any future DIX display must be explicitly manual, proprietary/unverified, and excluded from automated scoring.

## Running locally

```bash
pip install yfinance requests pandas numpy openpyxl
python -m unittest test_fast_metrics test_fred_monitor test_dash_state test_stress_calendar test_index_gex
python generate_dashboard.py          # writes index.html
npm install --no-save playwright@1.55.0 && npx playwright install chromium
node test_dashboard_browser.mjs index.html
node test_dashboard_degraded.mjs index.html
# FRED outage scenario (page built only from the archived CSVs)
MFD_FORCE_FRED_CACHE=1 MFD_OUTPUT=index-degraded.html python generate_dashboard.py
node test_dashboard_fred_cache.mjs index-degraded.html
```

GitHub Actions runs hourly with a 20-minute timeout. It runs the unit tests, the FRED-cache scenario, the main generation and the browser checks, then commits `index.html`, the daily SPY concentration snapshots, the FRED archive and `data/health.json` when data changes. `index-degraded.html` is never committed. Do not commit a locally generated `index.html`: it carries the embedded GEX and dashboard-state history that the hosted page accumulates.

## Methodology

See [METHODOLOGY.md](METHODOLOGY.md) for definitions, status logic, sources, cadence, limitations, and what is intentionally excluded.

## Disclaimer

This dashboard is research infrastructure, not investment advice. It measures fragility and confirmation conditions; it does not predict market direction or provide a trading recommendation.
