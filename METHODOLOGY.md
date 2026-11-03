# Methodology & Data Dictionary

## Design principle

The dashboard measures **fragility**: the possibility that funding pressure, crowding, or market structure could amplify a move. It does not predict direction and does not combine slow/low-frequency inputs into the fast-variable summary score.

All Phase A/B metrics use a visible observation date, fetch time, cadence, and stale state. Sources below are linked directly to their public endpoints.

## Page structure

Four layers: fragility (LPI), conditions (funding, Fed balance sheet, credit, rates), crowding, amplifiers and triggers. Each indicator state uses the same five labels: normal, watch, elevated, stress, and context (plotted, no state). States are percentile-based against the series' own trailing history. Fixed levels, where shown, are labelled operator reference lines and do not drive a state. The overview replaces the old six-tile scorecard with the fragility chain described below. Section badges use breadth: one indicator at watch or worse caps the badge at watch, two cap it at elevated, and three or more allow the worst state.

## L1 · Funding & Liquidity

| Metric | Definition | Status logic | Official source | Cadence / limitations |
|---|---|---|---|---|
| Reserves / GDP | `WRESBAL / (GDP × 1,000) × 100` | Rolling 156-week percentile. Warning below 20th percentile for two weekly observations; elevated below 10th for two. | [WRESBAL](https://fred.stlouisfed.org/graph/fredgraph.csv?id=WRESBAL), [GDP](https://fred.stlouisfed.org/graph/fredgraph.csv?id=GDP) | WRESBAL weekly; GDP quarterly and carried forward. Raw reserves are displayed only as context. |
| NY Fed repo accepted | Sum of `totalAmtAccepted` per operation day; show daily and 7-day sum | Watch uses non-zero persistence or a high percentile of the operation's own trailing distribution, not a magic dollar level. | [NY Fed repo results](https://markets.newyorkfed.org/api/rp/repo/all/results/last/40.json) | Daily. Operational usage is confirmation, not a top signal. |
| SOFR p99 − median | `percentPercentile99 − percentRate` | Display/confirmation only; no hard-coded alert score. | [NY Fed SOFR API](https://markets.newyorkfed.org/api/rates/secured/sofr/last/15.json) | Daily. A wider tail can indicate funding stress before the median moves. |
| SOFR − IORB (funding-price leg) | `(SOFR − IORB) × 100` basis points | Calendar days cannot alert. **Strategy leg active** = filtered non-calendar 5-observation median ≥ +3bp *and* last 3 non-calendar observations all ≥ +3bp; elevated ≥ +5bp. Reference bands retained: watch = 3 consecutive non-calendar ≥ +2bp, elevated ≥ +5bp. | [NY Fed SOFR](https://markets.newyorkfed.org/api/rates/secured/sofr/last/15.json), [FRB PRATES IORB](https://www.federalreserve.gov/datadownload/Choose.aspx?rel=PRATES), [Treasury auction data](https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/od/auctions_query) | Daily; featured line is a median of the latest 5 non-calendar observations. Month/quarter ends, corporate estimated-tax dates, and Treasury auction issue dates with at least `$30B` offered are labeled and excluded from the rule. |
| Bank reserve balances (liquidity-buffer leg) | Level in `$T`; `Δ1w = current − as-of(t−7d)`, `Δ4w = current − as-of(t−28d)` in `$B`; speed = `Δ4w ÷ 4` | **Active** = level ≤ `$2.90T` *and* `Δ4w` ≤ `−$50B`; **elevated** = level ≤ `$2.85T` or `Δ4w` ≤ `−$100B`; one condition only = *approaching* (does not count); missing 4-week observation = *incomplete* (never counts). | [H.4.1 Table 1](https://www.federalreserve.gov/releases/h41/current/h41.htm), [FRED WRESBAL](https://fred.stlouisfed.org/series/WRESBAL) | Weekly average of daily figures, week ended Wednesday, released Thursday; stale after 10 days. As-of deltas use real observation dates — no interpolation or forward-fill. Separate from the reserves/GDP percentile metric. |
| Treasury General Account (fiscal-drain leg) | Level in `$T`; same `Δ1w` / `Δ4w` / speed formulas | **Active** = level ≥ `$0.90T` *and* `Δ4w` ≥ `+$50B`; **elevated** = level ≥ `$1.00T` or `Δ4w` ≥ `+$100B`; one condition only = *approaching*; missing 4-week observation = *incomplete*. | [H.4.1 Table 1](https://www.federalreserve.gov/releases/h41/current/h41.htm), [FRED WTREGEN](https://fred.stlouisfed.org/series/WTREGEN), [Treasury DTS operating cash](https://fiscaldata.treasury.gov/datasets/daily-treasury-statement/operating-cash-balance) | Weekly (DTS daily closing balance only as an official fallback tail, flagged as mixed cadence). Bill-settlement timing makes the balance lumpy. |
| Dollar funding resonance | Count of active legs out of three | `0/3` no resonance · `1/3` watch (leg named) · `2/3` yellow warning, pressure building · `3/3` structural-top risk signal = fragility **confirmation**, explicitly not a deterministic market-top prediction. Stale, unavailable, or incomplete legs never count and raise an incomplete-data state. | Same sources as the three legs | The absolute thresholds are a documented **user-defined strategy overlay**, not an estimated statistical law, and are regime-dependent. |
| LPI | Equal-weight causal percentile composite of short rate, duration supply, inverted net liquidity, and VIX | Separate LPI regime logic; not a directional forecast. | [FRED](https://fred.stlouisfed.org/), [FiscalData](https://fiscaldata.treasury.gov/), [Cboe](https://www.cboe.com/) | Weekly composite; inputs have mixed cadences. |

## L2 · Crowding

| Metric | Definition | Status logic | Source | Cadence / limitations |
|---|---|---|---|---|
| COT positioning | Leveraged-fund or managed-money net contracts, own-history percentile and z-score | Observational crowding context and basis-trade proxy. | [CFTC public reporting](https://publicreporting.cftc.gov/) | Weekly, published with lag. |
| Basis-trade proxy | Mean across 2y/5y/10y of asset-manager long and leveraged-fund short percentiles | Percentile proxy, not a measured cash-futures basis position. | [CFTC public reporting](https://publicreporting.cftc.gov/) | Weekly; positioning proxy only. |
| SPY Top-10 / Top-5 | Sum of top 10 / top 5 official SPY holding weights | No percentile status until at least 60 locally collected daily snapshots exist. | [SSGA SPY holdings](https://www.ssga.com/us/en/intermediary/library-content/products/fund-data/etfs/us/holdings-daily-us-en-spy.xlsx) | Daily business day. SPY is a proxy for S&P 500; issuer history is not supplied. |

## L3 · Transmission & Amplifiers

| Metric | Definition | How to read | Source | Cadence / limitations |
|---|---|---|---|---|
| VIX term structure | Cboe VIX, VIX3M and optional VIX9D daily close (FRED VIXCLS / VXVCLS fallback) | The curve uses the latest date on which VIX and VIX3M are both available (VIX9D optional, shown only on the same date); contango is VIX3M above VIX. | [VIX](https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv), [VIX9D](https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX9D_History.csv), [VIX3M](https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX3M_History.csv) | Daily business day. Curve shape is not a directional forecast. |
| HY / IG / BBB OAS | ICE BofA option-adjusted spread and 60-day change | Credit-spread widening can confirm transmission beyond equities. | [HY](https://fred.stlouisfed.org/graph/fredgraph.csv?id=BAMLH0A0HYM2), [IG](https://fred.stlouisfed.org/graph/fredgraph.csv?id=BAMLC0A0CM), [BBB](https://fred.stlouisfed.org/graph/fredgraph.csv?id=BAMLC0A4CBBB) | Daily. Index spreads do not isolate AI issuers. |
| AI breadth | Fixed basket percentage above 50d / 200d moving average | A breadth/leadership measure, not a scoring input. | [Yahoo Finance](https://finance.yahoo.com/) adjusted-close data | Daily. Fixed basket has selection/survivorship bias. |
| SMH/SPY and SOXX/SPY | ETF adjusted-close ratio, with 50d/200d averages and 60-day change | Semiconductor leadership versus broad market. | [Yahoo Finance](https://finance.yahoo.com/) | Daily. ETF rebalances can cause structural breaks. |
| Homebrew GEX | Black–Scholes gamma aggregation by strike from SPY/QQQ option chains | Positive estimate can dampen, negative can amplify; it is model-based. | [Yahoo Finance options](https://finance.yahoo.com/) | Intraday/daily chain availability and model assumptions limit precision. |

## Intentionally excluded or manual-only

* **DIX:** no durable public endpoint is used. It is excluded from automated scoring. FINRA ATS/Reg SHO is not treated as equivalent.
* **AI CapEx cycle:** deliberately out of scope for this fast-variable implementation; slow quarterly data is not added as a fourth layer or folded into fast confirmation.
* **Forward P/E, issuer CDS, detailed DRAM/NAND contract prices and management guidance:** require paid or manual processes and are not represented as automatic current data.

## LPI data lineage and freshness

| Factor | Primary | Splice after the primary's last observation | Notes |
|---|---|---|---|
| Short rate | FRED SOFR (DFF before 2018) | NY Fed SOFR median | Weekly W-WED last value |
| Net liquidity | FRED WALCL − WTREGEN − RRPONTSYD | H.4.1 total assets and weekly-average TGA; NY Fed overnight RRP | One interior gap may be carried; no carry past the last print |
| Duration supply | Treasury auctions query (13-week sum of nominal and TIPS Notes and Bonds of 1.5 years or more, reopenings included, FRN excluded, `$B`) | TreasuryDirect auctioned-securities API for auctions not yet in FiscalData | Auctions dated after today are excluded; no weekly row past the last date a source covers |
| Vol amplifier | Yahoo ^VIX | none | Weekly close |

The composite is read on the common as-of week (minimum of each factor's last valid week). A common week older than 12 days is labelled stale; the page then shows the last-known value in gray and suppresses action language. Conditional tail statistics use the full weekly S&P 500 path for forward outcomes, and the columns report the frequency of a maximum drawdown larger than 5% or 10% within the horizon. COT chart percentiles are expanding (each week ranked only against data available that week); the z-score uses a trailing 156-week window.

## Freshness

A daily business-day series is gray after four calendar days; the weekly reserves series is gray after ten calendar days. Every new card reports both the underlying observation date and the pipeline fetch time. FRED live reads retry, then use a committed cache of official FRED CSV responses only when necessary; freshness remains based on the observation date.

## Fragility chain (v4)

The chain asks whether pressure is moving in the usual order: thin backdrop, then repo strain, then reserve scarcity, then transmission to credit, rates and the dollar, then price amplification. An indicator is on, off or unavailable; unavailable indicators are excluded from the count, and a stale series is unavailable.

| Stage | Indicators and on rule |
|---|---|
| 0 Backdrop | LPI ≥ 60 (weekly; unavailable when stale); basis-trade proxy ≥ 80; reserves leg active or elevated; reserves/GDP at warning or elevated |
| 1 Repo strain | SOFR − IORB 5-day calendar-filtered median ≥ +3 bp; TGCR − IORB and BGCR − IORB 5-day medians ≥ +3 bp; SOFR 99th − median at watch or worse; 3m T-bill − SOFR at or above its 90th percentile |
| 2 Reserve scarcity | EFFR − IORB ≥ −1 bp or a 20-day rise of 2 bp or more; standing repo facility in use (7-day sum ≥ $1B); discount window at or above its own 3-year 95th percentile with a positive 4-week change |
| 3 Transmission | 20-day change z ≥ 1.5 for HY OAS, HY − IG and CCC − BB; 10Y realized volatility at or above its 5-year 80th percentile; broad dollar 20-day change z ≥ 1.5; financial CP − T-bill at or above its 90th percentile |
| 4 Amplification | dealer gamma negative; VIX curve in backwardation; 2-week sector correlation ≥ 0.6 and above the 1-month value; SPY volume ≥ 1.5× its 20-day average on a down day |

A stage is confirmed when two or more indicators are on, partial when one is on, quiet when none is on. Stage 2 has hard triggers that confirm it alone: EFFR at or above IORB, or standing repo usage above $1B and at or above its 3-year 95th percentile.

Chain level: stage 1 confirmed gives watch; stage 2, 3 or 4 confirmed gives elevated; two or more of stages 2 to 4 confirmed gives stress. A confirmed backdrop raises the level by one step only while the level is below elevated. The stance sentence in the key takeaway comes from the chain level. The weekly LPI is shown as backdrop and no longer sets the stance.

Every production run compares the chain with the last stored run in `data/chain-state.json` and appends an event when the chain level, a stage status or the FSI band changes. An unavailable reading never creates an event and does not overwrite the last known value, so a data outage is not shown as relief.

## Funding Stress Index (v4)

Three daily spreads, each in basis points: repo = SOFR − IORB (5-observation median); interbank = EFFR − IORB; tail = SOFR 99th percentile − SOFR (5-observation median). IOER is the anchor before IORB began on 2021-07-29. Each spread is converted to a percentile of its trailing 1,260 observations (at least 250), using only past and current data, with ties at their mid-rank. The FSI is the mean of the available percentiles; at least two are required. Bands: below 60 normal, 60 to 80 watch, 80 to 95 elevated, 95 or more stress. The index is shown on the overview beside stages 1 and 2 and does not enter the chain level, the LPI or the de-leveraging tally.

Backtest from 2019: September 2019 peak 100, March 2020 peak 97, October to November 2025 peak 90, March 2023 peak 37 (the bank failures were a deposit run, not a funding-price event), April 2025 peak 60. About 6% of days were at 80 or higher.

## Descriptive FRED indicators (v2)

These series feed the Conditions layer only. They do not enter the LPI, the de-leveraging tally, the Key Takeaway stance or any composite. Rules:

* Credit spreads: stress = level percentile >= 95 and 20-day change z >= 2; elevated = percentile >= 90 and z >= 1; watch = percentile >= 80 or z >= 2; otherwise normal. Rates: elevated = level percentile >= 80 and change z >= 1 (high and rising); watch = percentile >= 80; otherwise normal. Both need at least one year of history. NFCI, ANFCI and the St. Louis stress index use 0 (their historical average) as the watch line and 1.0, an operator-set heuristic, as the elevated line. Percentiles and z-scores compare the latest value, or its change, with the series' own trailing three-year distribution.
* Backstop usage (standing repo, swap lines, FIMA repo) is "quiet" below a $1B floor and above that is compared with its own 95th percentile; swaps use a $5B floor; the discount window is compared with its own 95th percentile. Backstops in use are counted over standing repo, swap lines and FIMA repo; the discount window carries its own state.
* The foreign official reverse repo pool is context only.
* Weekly series are stale after their cadence plus a grace period (see `max_age_days` below). A stale series shows no state and is never forward-filled.
* ICE BofA OAS series on FRED carry roughly three years of history, so percentiles for them use that window.
* The What-changed panel rebuilds each indicator's state as of seven days earlier from the same series and lists differences, then adds the largest standardized one-week moves (z of the 5-observation change for daily series, 1-observation for weekly series, threshold |z| >= 1.5). Chain stages are additionally compared with an embedded daily snapshot that is 5 to 10 days old; until one exists the panel says it is building history.
* Reserve-management purchases: the Federal Reserve announced the programme on 2025-12-10; see the [NY Fed operating policy statement](https://www.newyorkfed.org/markets/opolicy/operating_policy_251210a) and the [Federal Reserve press release](https://www.federalreserve.gov/newsevents/pressreleases/monetary20251210a1.htm). The dashboard shows the observed change in Treasury bills held (WSHOBL) and compares it with the average since the programme began.

### Liquidity calendar

Rolling window from seven days ago to 120 days ahead. Status labels: announced (Treasury upcoming-auctions feed), scheduled (Fed FOMC calendar, tax dates, month and quarter ends), estimated (quarterly refunding announcement on the first Wednesday of February, May, August and November; settlement on the 15th rolled to the next business day; holidays are not modelled). The weekly bar is a count of events with quarter-end and refunding settlement counted twice. No severity percentile is claimed. A unit test fails when the built-in FOMC list ends before the end of the window.

### Data health

Every source registers a name, provider, last observation date, cadence and status (current, cached, stale, failed) in `health.py`. The header chip summarises the counts, the Methods section lists every row, and `data/health.json` plus the Actions step summary carry the same information.

### Embedded state

`hgex-state` stores up to 400 daily SPY/QQQ gamma snapshots; `dash-state` stores 45 daily snapshots of the chain level, each stage status and the FSI band. `data/chain-state.json` stores the latest run and up to 200 stage-change events; the production run writes it, the degraded test run does not. Both live inside `index.html` because the workflow commits only generated files. A locally generated `index.html` must not be committed over the hosted one.

### Secured repo versus interbank funding (v3)

Two overnight markets are compared with IORB, the rate the Fed pays on reserve balances.

* Secured repo: SOFR (all Treasury repo), BGCR (tri-party plus GCF) and TGCR (tri-party only). Cash is lent against Treasury collateral. These rates rise when dealers need cash to finance Treasury inventory or settlement, or when cash leaves money funds for the TGA. They measure collateral and dealer balance-sheet pressure.
* Unsecured interbank: EFFR (fed funds, about $0.1T, mostly FHLB lending) and OBFR (fed funds plus Eurodollar, about $0.2T). These rates rise toward IORB when banks bid for reserves. They measure reserve scarcity directly.

Classification (`fred_monitor.funding_locus`), using the SOFR - IORB 5-observation non-calendar median and EFFR - IORB:

| Secured median >= +3 bp | EFFR - IORB >= 0 bp, or 20-observation rise >= +2 bp | Locus |
|---|---|---|
| yes | yes | broad (repo and interbank both tight; the pattern of scarce reserves) |
| yes | no | secured (collateral and dealer pressure; reserves not scarce) |
| no | yes | unsecured (unusual; check bank-specific funding) |
| no | no | calm |

EFFR - IORB state is an exception to the percentile rule (D2): EFFR - IORB moved from about -7 bp (2023 to August 2025) to about -2 bp by November 2025 and has stayed there, so a 3-year percentile reads near the top without any new change. The state uses the IORB anchor instead: watch at or above -1 bp or on a 20-observation rise of +2 bp or more; elevated at or above 0 bp. The thresholds are operator references. The locus and these states are descriptive and do not enter the LPI, a composite or the de-lever tally (D6).

### Net liquidity decomposition (v3)

Net liquidity = Fed total assets (WALCL) - TGA (WTREGEN) - ON RRP (RRPONTSYD), in $ billions, on H.4.1 Wednesdays where all three exist. ON RRP is daily; the Wednesday value is used, or the latest print within three days before it. Rows stop at the last common Wednesday; no series is forward-filled. Weekly contributions: +change in assets, -change in TGA, -change in ON RRP; they sum to the change in net liquidity.

The result depends on the window and the end date. H.4.1 uses Wednesday levels, while the Daily Treasury Statement gives daily TGA balances, so a 5-business-day sum built from DTS data will differ from the 1-week H.4.1 change. A single week near tax dates, month-end or coupon settlement can reverse the sign. The card shows 1w and 4w changes; the chart shows every weekly contribution so the reader can see which leg moved.

### Market tape (v3)

Daily adjusted closes from Yahoo Finance: RSP/SPY, IWM/SPY and QQQ/SPY ratios (20-day percent change and its 3-year percentile, 50-day average), SPY volume divided by the average of the prior 20 sessions (today excluded), and GLD and USO 1, 5 and 20-day returns. These are context. A falling RSP/SPY ratio means fewer stocks carry the index; a volume ratio near 2x on a down day signals forced or hedging flow. None enters the LPI, a composite or the de-lever tally.

### Other v3 cards

* HY - IG OAS (BAMLH0A0HYM2 - BAMLC0A0CM), bp: the extra spread paid for high-yield risk over investment grade.
* 2-year Treasury yield (DGS2) and 10Y/2Y realized volatility: standard deviation of daily yield changes over 20 sessions, times the square root of 252, in bp.
* 3-month T-bill minus SOFR (DTB3 - SOFR), bp. DTB3 is quoted on a discount basis, so the level carries a small negative bias; changes are more informative than the level.

### Data dictionary (FRED and NY Fed series)

All series are fetched from fredgraph.csv except BGCR and BGCRVOL, which come from the [NY Fed Markets reference-rates API](https://markets.newyorkfed.org/api/rates/secured/bgcr/search.json) because FRED does not carry BGCR. NY Fed series use the same merge-only cache (`data/fred-cache/NYFED_<id>.csv`).

| Series | Label | Section | Raw unit | Display | Cadence | Max age (days) | Role |
|---|---|---|---|---|---|---|---|
| [SOFR](https://fred.stlouisfed.org/series/SOFR) | SOFR | funding | percent | pct | daily business day | 5 | context |
| [IORB](https://fred.stlouisfed.org/series/IORB) | IORB | funding | percent | pct | daily business day | 10 | context |
| [TGCRRATE](https://fred.stlouisfed.org/series/TGCRRATE) | Tri-party general collateral rate | funding | percent | pct | daily business day | 5 | state |
| [EFFR](https://fred.stlouisfed.org/series/EFFR) | Effective federal funds rate | funding | percent | pct | daily business day | 5 | state |
| [OBFR](https://fred.stlouisfed.org/series/OBFR) | Overnight bank funding rate | funding | percent | pct | daily business day | 5 | context |
| [EFFRVOL](https://fred.stlouisfed.org/series/EFFRVOL) | Effective federal funds volume | funding | billions | $B | daily business day | 5 | context |
| [OBFRVOL](https://fred.stlouisfed.org/series/OBFRVOL) | Overnight bank funding volume | funding | billions | $B | daily business day | 5 | context |
| [TGCRVOLUME](https://fred.stlouisfed.org/series/TGCRVOLUME) | Tri-party general collateral rate volume | funding | billions | $B | daily business day | 5 | context |
| [BGCR](https://www.newyorkfed.org/markets/reference-rates/bgcr) | Broad general collateral rate (NY Fed) (NY Fed) | funding | percent | pct | daily business day | 5 | context |
| [BGCRVOL](https://www.newyorkfed.org/markets/reference-rates/bgcr) | Broad general collateral rate volume (NY Fed) (NY Fed) | funding | billions | $B | daily business day | 5 | context |
| [SOFR1](https://fred.stlouisfed.org/series/SOFR1) | SOFR 1st percentile | funding | percent | pct | daily business day | 5 | context |
| [SOFR25](https://fred.stlouisfed.org/series/SOFR25) | SOFR 25th percentile | funding | percent | pct | daily business day | 5 | context |
| [SOFR75](https://fred.stlouisfed.org/series/SOFR75) | SOFR 75th percentile | funding | percent | pct | daily business day | 5 | context |
| [SOFR99](https://fred.stlouisfed.org/series/SOFR99) | SOFR 99th percentile | funding | percent | pct | daily business day | 5 | context |
| [SOFRVOL](https://fred.stlouisfed.org/series/SOFRVOL) | SOFR transaction volume | funding | billions | $B | daily business day | 5 | context |
| [RPONTSYD](https://fred.stlouisfed.org/series/RPONTSYD) | Standing repo / overnight repo (Treasury) | backstop | billions | $B | daily business day | 5 | state |
| [WLCFLPCL](https://fred.stlouisfed.org/series/WLCFLPCL) | Discount window primary credit | backstop | millions | $B | weekly (H.4.1, Wednesday level, Thursday release) | 12 | state |
| [SWPT](https://fred.stlouisfed.org/series/SWPT) | Central bank liquidity swaps | backstop | millions | $B | weekly (H.4.1, Wednesday level, Thursday release) | 12 | state |
| [H41RESPPALGTRFNWW](https://fred.stlouisfed.org/series/H41RESPPALGTRFNWW) | FIMA repo facility (actual usage) | backstop | millions | $B | weekly (H.4.1, Wednesday level, Thursday release) | 12 | state |
| [WLRRAFOIAL](https://fred.stlouisfed.org/series/WLRRAFOIAL) | Foreign official reverse repo pool (liability) | backstop | millions | $B | weekly (H.4.1, Wednesday level, Thursday release) | 12 | context |
| [WSHOBL](https://fred.stlouisfed.org/series/WSHOBL) | SOMA Treasury bills | fedbs | millions | $B | weekly (H.4.1, Wednesday level, Thursday release) | 12 | context |
| [WSHOSHO](https://fred.stlouisfed.org/series/WSHOSHO) | SOMA securities held outright | fedbs | millions | $T | weekly (H.4.1, Wednesday level, Thursday release) | 12 | context |
| [WSHONBNL](https://fred.stlouisfed.org/series/WSHONBNL) | SOMA Treasury notes and bonds (nominal) | fedbs | millions | $B | weekly (H.4.1, Wednesday level, Thursday release) | 12 | context |
| [WSHOMCB](https://fred.stlouisfed.org/series/WSHOMCB) | SOMA mortgage-backed securities | fedbs | millions | $B | weekly (H.4.1, Wednesday level, Thursday release) | 12 | context |
| [WSEFINTL1](https://fred.stlouisfed.org/series/WSEFINTL1) | Securities held in custody for foreign official accounts | fedbs | millions | $T | weekly (H.4.1, Wednesday level, Thursday release) | 12 | context |
| [RRPONTSYD](https://fred.stlouisfed.org/series/RRPONTSYD) | Overnight reverse repo (ON RRP) take-up | fedbs | billions | $B | daily business day | 5 | context |
| [WALCL](https://fred.stlouisfed.org/series/WALCL) | Fed total assets | fedbs | millions | $T | weekly (H.4.1, Wednesday level, Thursday release) | 12 | context |
| [WRESBAL](https://fred.stlouisfed.org/series/WRESBAL) | Reserve balances at Federal Reserve Banks | fedbs | millions | $T | weekly (H.4.1, Wednesday level, Thursday release) | 12 | context |
| [WTREGEN](https://fred.stlouisfed.org/series/WTREGEN) | Treasury General Account | fedbs | millions | $T | weekly (H.4.1, Wednesday level, Thursday release) | 12 | context |
| [BAMLH0A0HYM2](https://fred.stlouisfed.org/series/BAMLH0A0HYM2) | US high yield OAS | credit | percent | bp | daily business day | 5 | state |
| [BAMLC0A0CM](https://fred.stlouisfed.org/series/BAMLC0A0CM) | US investment grade OAS | credit | percent | bp | daily business day | 5 | state |
| [BAMLC0A4CBBB](https://fred.stlouisfed.org/series/BAMLC0A4CBBB) | US BBB OAS | credit | percent | bp | daily business day | 5 | state |
| [BAMLH0A1HYBB](https://fred.stlouisfed.org/series/BAMLH0A1HYBB) | BB OAS | credit | percent | bp | daily business day | 5 | state |
| [BAMLH0A2HYB](https://fred.stlouisfed.org/series/BAMLH0A2HYB) | Single-B OAS | credit | percent | bp | daily business day | 5 | state |
| [BAMLH0A3HYC](https://fred.stlouisfed.org/series/BAMLH0A3HYC) | CCC and lower OAS | credit | percent | bp | daily business day | 5 | state |
| [BAMLEMCBPIOAS](https://fred.stlouisfed.org/series/BAMLEMCBPIOAS) | Emerging markets corporate plus OAS | credit | percent | bp | daily business day | 5 | context |
| [NFCI](https://fred.stlouisfed.org/series/NFCI) | Chicago Fed National Financial Conditions Index | credit | index | index | weekly (Friday) | 14 | context |
| [ANFCI](https://fred.stlouisfed.org/series/ANFCI) | Adjusted NFCI | credit | index | index | weekly (Friday) | 14 | context |
| [STLFSI4](https://fred.stlouisfed.org/series/STLFSI4) | St. Louis Fed Financial Stress Index | credit | index | index | weekly (Friday) | 14 | context |
| [DCPF3M](https://fred.stlouisfed.org/series/DCPF3M) | 3-month AA financial commercial paper rate | credit | percent | pct | daily business day | 7 | context |
| [DTB3](https://fred.stlouisfed.org/series/DTB3) | 3-month Treasury bill secondary market rate | credit | percent | pct | daily business day | 7 | context |
| [DGS2](https://fred.stlouisfed.org/series/DGS2) | 2-year Treasury yield | rates | percent | pct | daily business day | 5 | context |
| [DGS5](https://fred.stlouisfed.org/series/DGS5) | 5-year Treasury yield | rates | percent | pct | daily business day | 5 | context |
| [DGS10](https://fred.stlouisfed.org/series/DGS10) | 10-year Treasury yield | rates | percent | pct | daily business day | 5 | context |
| [DGS30](https://fred.stlouisfed.org/series/DGS30) | 30-year Treasury yield | rates | percent | pct | daily business day | 5 | state |
| [T10Y2Y](https://fred.stlouisfed.org/series/T10Y2Y) | 10-year minus 2-year Treasury spread | rates | percent | bp | daily business day | 5 | context |
| [T10Y3M](https://fred.stlouisfed.org/series/T10Y3M) | 10-year minus 3-month Treasury spread | rates | percent | bp | daily business day | 5 | context |
| [DFII10](https://fred.stlouisfed.org/series/DFII10) | 10-year TIPS real yield | rates | percent | pct | daily business day | 5 | state |
| [T10YIE](https://fred.stlouisfed.org/series/T10YIE) | 10-year breakeven inflation | rates | percent | pct | daily business day | 5 | context |
| [THREEFYTP10](https://fred.stlouisfed.org/series/THREEFYTP10) | Kim-Wright 10-year term premium (model estimate) | rates | percent | pct | daily business day | 7 | state |
| [TASACBW027SBOG](https://fred.stlouisfed.org/series/TASACBW027SBOG) | Commercial banks: Treasury and agency securities | rates | billions | $B | weekly (H.8) | 14 | context |
| [DTWEXBGS](https://fred.stlouisfed.org/series/DTWEXBGS) | Nominal broad US dollar index | rates | index | index | daily business day | 8 | context |
| [VIXCLS](https://fred.stlouisfed.org/series/VIXCLS) | CBOE Volatility Index close | vol | index | index | daily business day | 5 | context |
| [VXVCLS](https://fred.stlouisfed.org/series/VXVCLS) | CBOE 3-month Volatility Index close | vol | index | index | daily business day | 5 | context |
