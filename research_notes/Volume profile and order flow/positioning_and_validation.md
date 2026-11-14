# Derivatives positioning signals for BTC perpetuals: evidence, costs, validation, data

Research date: 2026-11-10. Cost hurdle: 0.14% (14 bp) round-trip taker.

Evidence labels: **[A]** peer-reviewed. **[B]** preprint or working paper. **[C]** open code or student project. **[D]** vendor, exchange blog or influencer (low quality). **[Own test]** direct check of public endpoints on 2026-11-10 from this machine (India IP).

Reading limits: the two arXiv papers on quarter-hour effects and perp fundamentals were read through a page-extraction tool, in large part. Other papers are known only from search snippets or abstracts. These are marked "snippet only".

## What are the exact rules and evidence for fading or following liquidation cascades, funding-rate extremes, open-interest plus price/CVD regimes, and spot-versus-perp CVD divergence?

### Takeaway
No credible peer-reviewed or preprint source found gives net-of-cost directional rules for BTC on any of these four signals. Published work explains the mechanisms (price impact, cascade microstructure, perp-spot convergence). The rules below are therefore test specifications, not evidence-backed strategies.

### Cited Findings

**Liquidation cascades**
- [B] A study of seven BTC perp cascades (2022-2025) found no event-invariant early-warning variable. Price showed critical slowing down in five of seven events, and none in the two sudden tariff-news shocks (snippet only) — [Garcia Seuma, arXiv 2607.27070](https://arxiv.org/abs/2607.27070)
- [B] A companion paper on October 2025 describes an abrupt transition, with the in-cascade signal in liquidity: price impact spiked while open interest cleared by 25-70% (snippet only) — [arXiv 2608.03616](https://arxiv.org/abs/2608.03616)
- [B] On 10 October 2025, the mark price used to trigger liquidations undershot both spot and futures, producing reflexive feedback. The paper covers the crash, not post-event returns (snippet only) — [Lim, SSRN 6579278](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6579278)
- [B] A BitMEX paper measures liquidation as a share of open interest but tests no trading strategy (snippet only) — [arXiv 2102.04591](https://arxiv.org/pdf/2102.04591)
- [D] Open interest nets entries against exits, so a fall in OI cannot be read as a liquidation count. Forced closes likely amplified a move if selling began before liquidations surged. No test is given — [Publish0x commentary](https://www.publish0x.com/things-i-think-about/what-falling-bitcoin-open-interest-means-after-liquidations-xzrelyj)
- Two targeted searches found no event study of returns over minutes to hours after liquidations.

**Funding-rate extremes**
- [C] Best open backtest found: short when the funding z-score is above +threshold, long when below -threshold; enter next open; exit after a fixed hold. Optional 0.5% stop and an OI-change filter. "Optimal" setting: threshold 2.5, 60-day lookback, 8h hold — [Adeline117/Strategy-project](https://github.com/Adeline117/Strategy-project)
- [C] Same project, 2020-2024: Sharpe 0.771, Calmar 0.111, max drawdown 13.77%, win rate 54.4%, 125 trades, 1x leverage, 0.04% taker per side, no slippage mentioned. It does not say whether funding is in P&L, and it has a synthetic GBM fallback without saying which data produced the results — [same source](https://github.com/Adeline117/Strategy-project)
- [C] Its walk-forward Calmar by year: 2021 -0.587 (23 trades), 2022 -0.249 (25), 2023 +0.567 (28), 2024 +0.634 (23). The sign flip between periods points to instability — [same source](https://github.com/Adeline117/Strategy-project)
- [B] Funding rates themselves are forecastable out of sample on Binance and Bybit with double-autoregressive models. This predicts funding, not price (snippet only) — [Inan, SSRN 5576424](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5576424)
- [B] A 2019 BitMEX paper examines funding and price with Granger causality; single venue and old (snippet only) — [arXiv 1912.03270](https://www.arxiv.org/pdf/1912.03270)
- [D] A vendor tear-sheet shows Sharpe 2.09 over 90 days: too short to use — [algotick.dev](https://algotick.dev/backtests/funding-rate/bitcoin)
- [B, adjacent] Delta-neutral funding carry is the best-documented funding use, and it is a different trade from a contrarian signal. SSRN paper reports 16.0% annual return and Sharpe 6.1 (snippet only, not independently verified) — [Chan, SSRN 5292305](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5292305)

**Open interest plus price/CVD regimes**
- [A] The academic OI work found relates to volatility, not direction: Bitcoin volatility covaries negatively with unexpected futures OI in the long run (snippet only) — [ScienceDirect S1057521923000133](https://www.sciencedirect.com/science/article/abs/pii/S1057521923000133)
- [A] Normal and jump volatility covary positively with unexpected futures OI in the short run and negatively in the mid run, at daily-type horizons (snippet only) — [ScienceDirect S1544612322000903](https://www.sciencedirect.com/science/article/abs/pii/S1544612322000903)
- [D] The familiar four-quadrant reading and "high OI plus high funding means reversal risk" appear only in untested guides — [Gate guide](https://web3.gate.com/crypto-wiki/article/how-do-futures-open-interest-funding-rates-and-liquidation-data-predict-crypto-derivatives-market-signals-in-2026-20260111)

**Order flow and spot-versus-perp**
- [B] Binance perps, 2020-01-08 to 2024-03-11 for BTC and ETH. Hourly taker imbalance leans against the futures-spot deviation: coefficient -0.0106 on lagged annualized deviation, t = -13.30, pooled panel of 176,940 observations. This does not test whether flow predicts returns — [Fundamentals of Perpetual Futures, arXiv 2212.06888](https://arxiv.org/html/2212.06888v7)
- [B] Taker-flow price impact is larger in the high-deviation tercile (high minus low 0.062 bp, significant at 1%), and it "rises sharply only in the upper tail" — [same paper](https://arxiv.org/html/2212.06888v7)
- [B] Quarter-hour effect, six Binance perps including BTC, January 2021 to October 2024. Imbalance in 10-second windows at quarter-hour openings forecasts returns; strongest around 4-12h, significant at 95% in four of six contracts. No net-of-cost strategy is evaluated, and BTC-specific cumulative effects appear only in a figure — [arXiv 2607.09426](https://arxiv.org/html/2607.09426v2)
- [A] Bitcoin order-flow imbalance has explanatory power for returns, but largely contemporaneous (snippet only) — [Fragmentation, Price Formation and Cross-Impact](https://www.tandfonline.com/doi/full/10.1080/1350486X.2022.2080083)
- Price-discovery results conflict, and are sensitive to sample and sampling frequency: one set of studies has perps and futures on unregulated venues (Huobi, OKEx, BitMEX) leading, per a search summary whose exact paper was not opened ([Southampton eprint, closest listing](https://eprints.soton.ac.uk/426715); attribution unconfirmed), while [Frijns et al.](https://acfr.aut.ac.nz/__data/assets/pdf_file/0009/296424/B-Frijns-Bitcoin_Paper.pdf) find futures lead on average for Dec 2017 to Mar 2019 (snippets only).
- Two searches found no published study testing a spot-versus-perp CVD divergence rule.

### Inferences

These are test specifications to pre-register. None has demonstrated edge. Use bar-close signals, next-bar-open fills, and 14 bp plus actual funding.

Shared definitions from 1-minute klines: `delta = 2 * taker_buy_volume - volume`; `CVD` is the cumulative sum of delta. Compute separately for perp and spot.

| ID | Signal | Entry | Exit | Prior belief |
|---|---|---|---|---|
| F1 Funding fade | Settled funding z-score over 60 days above +2.5 or below -2.5 (also test absolute funding of at least 0.05% per 8h) | Opposite side of the crowded leg, next bar after settlement | Fixed 8h and 24h variants; no optimizing | Low to moderate: rare events; sample about 25 trades a year |
| L1 Cascade fade | Liquidation notional or 5m OI drop in top 1% of trailing 90 days, 5m range above 3x ATR, and OI down at least 1% | Wait for a 5m close back inside the shock bar; fade | Fixed 1h and 4h, stop beyond shock extreme | Unknown: no published returns; needs forward-collected data |
| L2 Cascade follow | Same trigger, but no close back inside within 15m | Follow direction | Fixed 1h and 4h | Unknown |
| O1 OI regime | 1h OI change and 1h return in the same direction, with both above their 80th percentile | Follow | Fixed 4h | Low: only commentary supports it |
| O2 Crowded fade | Funding z above 2 and OI at 90-day high, with a perp CVD/price divergence over 1h | Fade after 15m reversal close | Fixed 4h and 8h | Low |
| S1 Spot-perp CVD | 4h change in normalized spot delta minus normalized perp delta beyond 2 z, and price flat | Follow spot | Fixed 4h and 8h | Low to moderate: mechanism plausible, no published test |
| Q1 Quarter-hour flow | Signed imbalance in the first minute after each quarter-hour, cumulated over the last hour, top or bottom decile | Follow | 4h, 8h, 12h | Best-supported direction, but the paper used 10-second windows, which 1-minute polling cannot reproduce exactly |
| V1 Level combo | Any of F1, L1 or O2 firing within 0.25 ATR of prior-session POC, VAH or VAL | Same as the base signal | Same as the base signal | Test only as a filter on a base signal that passes; must beat placebo levels |

L1 and L2 need caution: the two cascade types above (endogenous buildup versus exogenous shock) suggest one rule may not fit both, but with only seven studied events that split cannot be calibrated from the literature.

The user's earlier BTC work found no edge after costs in level-based and trend-flip systems, including results no better than placebo levels — [project memory: Smart Zone Pro study](/Users/ajaybaburaj/.claude/projects/-Users-ajaybaburaj-Documents-ajay-crypto/memory/smart-zone-pro-study.md). So V1 should be presumed null.

### Gaps
- No credible post-liquidation return event study was located. Absence from about four searches does not prove none exists.
- No BTC-specific, net-of-cost academic test of funding extremes, OI regimes or CVD divergence was found.
- The full text of the 2026 cascade papers and the Lim paper was not read.

## What horizon and net magnitude are documented, and do they beat about 0.14% round-trip costs, including funding payments?

### Takeaway
No directional positioning signal has a documented net edge above 14 bp for BTC at retail taker cost. The strongest figures are either gross and unexecuted, or come from two-leg perp-spot convergence at maker fees, which is not the target trade.

### Cited Findings
- [B] Quarter-hour opening model: BTC out-of-sample R² 3.82%, AUC 0.6035, accuracy 57.30%, on a 10-second target. The average sign-weighted realized forecast is about 0.5 bp per boundary, against fees of 5 bp taker and 2 bp maker — [arXiv 2607.09426](https://arxiv.org/html/2607.09426v2)
- [B] Same paper, order-flow decomposition across contracts: lagged-flow component stable at 5-6 bp; public-signal component 9.8 bp at 8h and 16.9 bp at 12h. These are gross decomposition effects, not strategy returns, and market impact and queue priority are not modeled — [arXiv 2607.09426](https://arxiv.org/html/2607.09426v2)
- [B] Perp-spot convergence, BTC, 2020-2024: Sharpe 3.35 with high-tier maker fees, 3.27 after effective spreads; 11.65 with no fees. Zero-cost annualized return 52.55%, of which 37.61 points came from convergence and 14.94 from funding — [arXiv 2212.06888](https://arxiv.org/html/2212.06888v7)
- [B] That strategy needs deviations beyond about ±179.4% a year at its high fee tier, and fee tiers assume maker execution (VIP 1, 5, 8; no retail taker tier) — [arXiv 2212.06888](https://arxiv.org/html/2212.06888v7)
- Funding settles every 8 hours at 00:00, 08:00 and 16:00 GMT, and approximates the weighted average premium of the prior 8 hours — [arXiv 2212.06888](https://arxiv.org/html/2212.06888v7)
- [Own test] The latest BTCUSDT settled funding rate fetched was 0.0001 (1 bp per 8h) — [Binance fundingRate endpoint](https://fapi.binance.com/fapi/v1/fundingRate?symbol=BTCUSDT&limit=1)

### Inferences
- The break-even gross edge is 14 bp per trade on notional, before funding. Q1's 5-6 bp component would not clear it. The 16.9 bp 12h figure would clear only barely, and it is not an executed return.
- Funding arithmetic: at 1 bp per 8h, an 8h hold crossing one settlement changes P&L by about ±1 bp, and a 24h hold by about ±3 bp. At an extreme 10 bp per 8h, a fade that receives funding gains about 10 bp per settlement, which would be material. A 24h hold would receive about 30 bp if funding stayed that high.
- That makes crowded-side fades the only family where funding can materially help. It also means any backtest omitting funding misstates exactly the trades it selects. Model funding at actual settlement timestamps, on the venue actually traded.
- The student backtest's Calmar 0.111 and drawdown 13.77% imply about 1.5% a year (assuming Calmar is annual return over max drawdown). Moving from its 8 bp to 14 bp round-trip adds 6 bp on about 25 trades a year, or about 1.5% a year. That would erase the return.
- Size sets no constraint at retail scale: the deviation paper puts BTC effective spreads near 0.1 bp, so fees dominate. Shocks are the exception, because liquidity deteriorates during cascades, so L1 and L2 need extra slippage (start at 10 bp each way as a stress assumption; this is a judgment, not a measured figure).
- Maker execution is the largest available lever, but it brings adverse-selection and non-fill problems that bar-based backtests cannot show.

### Gaps
- No published net-of-cost figure for any of F1, L1, L2, O1, O2 or S1 on BTC.
- Delta Exchange fees and funding were not researched here. A signal from Binance data executed on Delta also has basis and funding differences that need measuring.

## Which regime filters (volatility, trend, time of day/session) improve order-flow or volume-level signals with out-of-sample support?

### Takeaway
Out-of-sample support exists for price-based intraday effects conditioned on volatility and session, though unstable over time. No source found shows out-of-sample improvement from these filters on order-flow or volume-profile signals.

### Cited Findings
- [A] Bitcoin intraday time-series momentum holds in and out of sample, with the first half of the day predicting the final half hour, and predictability strongest on high-volatility days (snippet only) — [University of Reading accepted version](https://centaur.reading.ac.uk/100181/3/21Sep2021Bitcoin%20Intraday%20Time-Series%20Momentum.R2.pdf)
- [A] 5-minute data, 2013-2020: both intraday momentum and reversal exist in and out of sample, and patterns change with large jumps, FOMC releases, liquidity and COVID (snippet only) — [Intraday return predictability](https://www.sciencedirect.com/science/article/abs/pii/S1062940822000833)
- [A] Training and holdout results disagree for session rules: Bitcoin's full-sample best is a conditional Reversal/Reversal at 08:00, while the training-period best is Momentum/Long at 11:00 UTC. The nighttime reversal contrast is not significant in 2016-2020 but significant in 2021-2025 (snippet only) — [JRFM 2026](https://doi.org/10.3390/jrfm19090692)
- [B] Volatility and liquidity have strong day-of-week, hour-of-day and within-hour periodicity, and periodicity improves models in and out of sample. This is volatility and liquidity forecasting, not direction (snippet only) — [arXiv 2109.12142](https://arxiv.org/pdf/2109.12142)
- [C/D] A secondary blog summary of a paper defines intraday as 15:00-21:00 UTC with a 21:00-23:00 UTC window standing out; not verified against the original — [Paperswithbacktest](https://paperswithbacktest.com/blog/bitcoin-never-sleeps-exploiting-seasonality)
- [B] Cascades split between endogenous and exogenous shocks, with price precursors absent in news-shock events — [arXiv 2607.27070](https://arxiv.org/abs/2607.27070)

### Inferences
- Use volatility filters to choose whether to trade and how to size. That use has the firmest support, because volatility periodicity is robust while direction is not.
- Pre-specify a small set: 24h realized-vol tercile, one trend state (price vs 200-period EMA or 4h ADX threshold), and one session split (15:00-21:00 UTC vs other). The user's 4h ADX and EMA200 filter on the order-block study is a reasonable precedent to reuse rather than re-optimize.
- Exclude or separately tag scheduled macro windows (FOMC at minimum), since one study finds patterns change there.
- Count each filter state as extra trials in the multiple-testing correction below.

### Gaps
- No out-of-sample filter result was found specifically for CVD, liquidations, funding or volume-profile levels.
- A search summary mentioned a seven-exchange study finding time-specific return anomalies without persistence, but no source link could be tied to it, so it is not relied on.

## Which validation methods fit this research, and what acceptance thresholds should a retail researcher testing many variants on BTC use?

### Takeaway
Use a pre-registered variant list, walk-forward as the main test, purged cross-validation for any fitted model, placebo controls for level-based signals, and DSR plus PBO for selection. The published anchors are t above 3 and PBO; the rest of the threshold table is a recommended judgment.

### Cited Findings
- A t-ratio above 3.0 is the proposed hurdle for a newly discovered factor given extensive data mining (abstract and summaries) — [Harvey, Liu, Zhu, NBER w20592](https://nber.org/papers/w20592)
- Commentary argues 3.0 may be too lenient because the sample covers only top journals (low-quality study guide) — [Brainscape](https://www.brainscape.com/flashcards/12886732/packs/21266483)
- CSCV is a model-free, nonparametric way to estimate the probability of backtest overfitting — [Bailey, Borwein, Lopez de Prado, Zhu, SSRN 2326253](https://papers.ssrn.com/abstract=2326253)
- PBO can be computed as the share of in-sample/out-of-sample splits where the in-sample winner ranks at or below the out-of-sample median — [fynance implementation](https://fynance.readthedocs.io/en/master/_modules/fynance/research/overfit.html)
- Sources disagree on any PBO cutoff: [one says no universal threshold exists](https://www.luxalgo.com/library/concept/probability-of-backtest-overfitting/), while a [low-authority page uses 0.50](https://skillselion.com/skills/agiprolabs/claude-trading-skills/walk-forward-validation).
- DSR deflates the Sharpe for selection bias and non-normality using a higher benchmark — [teaching lab summary](https://quinfer.github.io/financial-data-science/labs/lab10_backtesting.html). A DSR below 0.95 as a warning is a low-authority rule of thumb; the original paper's page was inaccessible (HTTP 403) — [skill page](https://skillselion.com/skills/agiprolabs/claude-trading-skills/walk-forward-validation)
- Purging removes training observations sharing data with the test set, embargo adds a buffer after it, and CPCV yields multiple out-of-sample paths rather than a single walk-forward path — [fynance CPCV docs](https://fynance.readthedocs.io/en/latest/generated/fynance.data.combinatorial_purged_cv.html)
- Project precedent: the MTF Supertrend study had 0/378 variants pass 2024 and 2025 after costs — [project memory](/Users/ajaybaburaj/.claude/projects/-Users-ajaybaburaj-Documents-ajay-crypto/memory/mtf-supertrend-study.md)

### Inferences

**Method by signal type**

| Method | Use for | Notes |
|---|---|---|
| Pre-registration | Everything | Freeze variants and the hold-out before looking |
| Walk-forward | All fixed rules | Primary test; report every fold |
| Purged CV with embargo | Any fitted model (regression, LASSO, ML) | Embargo at least the maximum hold plus feature lookback overlap |
| CSCV/PBO | Grids of 20 or more variants | Needs the full variant return matrix |
| DSR | Selected best variant | Use the true number of trials tried, including abandoned ones |
| Placebo levels | Volume profile or any level signal | Shift levels by random offsets matched for distance from price; repeat at least 1,000 times |
| Placebo timing | Event signals (L1, F1) | Random entries matched for hour, volatility and side |
| Benjamini-Hochberg FDR | Screening many variants | Screening step only, followed by holdout |

**Recommended acceptance gates (judgment, all required)**

| Gate | Threshold |
|---|---|
| Net of 14 bp plus actual funding | Mean net trade above 0 at 14 bp; still above 0 at 20 bp |
| Statistical | Net t-stat at least 3.0, using block bootstrap or HAC errors for overlap |
| Multiple testing | Bonferroni-adjusted two-sided: about t 3.5 for 100 variants, 3.8 for 378, 4.1 for 1,000 |
| DSR | At least 0.95 using true trial count |
| PBO | Below 0.25 preferred; reject at 0.50 or above |
| Sample | At least 300 non-overlapping trades, or 100 with an explicit "tentative" label |
| Stability | Positive net in at least 70% of walk-forward folds and in each of 2023, 2024, 2025 and 2026 year-to-date |
| Concentration | Removing the best 1% of trades leaves net P&L positive |
| Parameter robustness | Neighboring parameter settings also positive net |
| Placebo | Real signal above the 95th percentile of placebo results |
| Final holdout | Last 6-12 months touched once; net positive at t at least 2 |
| Paper or forward | At least 3 months or 50 trades, with realized slippage within the backtest assumption |

The required sample grows quickly. Trades needed for t = 3 are roughly `(3 * sigma / mu)^2`. Under an illustrative 100 bp per-trade standard deviation and 10 bp net edge, that is about 900 independent trades. Rare-event signals such as F1 (about 25 a year) cannot reach that on BTC alone. They need cross-asset replication on ETH and SOL, or should be treated as unproven.

Hold ETH and SOL out as an independent check rather than pooling them into the search.

### Gaps
- The original DSR paper could not be fetched (HTTP 403), so its formula and cutoffs here were not confirmed against the source.
- Osler's work using artificial support and resistance levels is the likely origin of level placebos. The search did not surface it, so it is uncited here and should be checked before being quoted.

## Which free historical datasets exist, what date coverage do they have, are they usable live from public endpoints, and are there regional restrictions from India or GCP asia-south1?

### Takeaway
Binance's public archive covers almost everything needed from 2020, except USDT-M liquidations, which must be collected forward and are incomplete by design. Public futures endpoints returned data from this India IP on 2026-11-10; GCP asia-south1 is untested, and historic reports of GCP being blocked make a direct check from the VM essential.

### Cited Findings

**Archive coverage for BTCUSDT [Own test: S3 listing of data.binance.vision, 2026-11-10]**

| Dataset | Path | First file | Latest confirmed |
|---|---|---|---|
| Perp aggTrades | um/monthly | 2020-01 | At least 2026-09 |
| Perp 1m klines, including taker buy volume | um/monthly | 2020-01 | Daily file for 2026-11-01 downloaded |
| Funding | um/monthly | 2020-01 | At least 2026-09 |
| Metrics (5m OI, OI value, top-trader and account ratios, taker ratio) | um/daily | 2020-09-01 | 2026-11-01 downloaded |
| Book depth | um/daily | 2023-01-01 | At least 2026-10-31 |
| Spot aggTrades | spot/monthly | 2017-08 | Not checked |

- Source for the table: [data.binance.vision S3 listing](https://s3-ap-northeast-1.amazonaws.com/data.binance.vision?delimiter=/&prefix=data/futures/um/daily/)
- [Own test] USDT-M directories contain aggTrades, bookDepth, bookTicker, indexPriceKlines, klines, markPriceKlines, metrics, premiumIndexKlines and trades (daily); fundingRate is in monthly only. The `um/daily/liquidationSnapshot/` prefix lists no symbols, while the COIN-M prefix does list contracts such as `AAVEUSD_PERP` — [S3 listing](https://s3-ap-northeast-1.amazonaws.com/data.binance.vision?delimiter=/&prefix=data/futures/um/daily/liquidationSnapshot/)
- [Own test] Metrics columns: `create_time, symbol, sum_open_interest, sum_open_interest_value, count_toptrader_long_short_ratio, sum_toptrader_long_short_ratio, count_long_short_ratio, sum_taker_long_short_vol_ratio`. Data quality: the 2020-09-01 file has 577 lines with duplicated rows (about double the 289 expected), and the 2026-11-01 file is not time-sorted, so dedupe and sort — [sample file](https://data.binance.vision/data/futures/um/daily/metrics/BTCUSDT/BTCUSDT-metrics-2026-11-01.zip)
- [Own test] Funding from REST reaches back to 2019-09-10 08:00 UTC — [fundingRate endpoint](https://fapi.binance.com/fapi/v1/fundingRate?symbol=BTCUSDT&startTime=1567296000000&limit=1)
- Daily archive data appears the next day and monthly data on the first Monday of the month — [binance-public-data README](https://github.com/binance/binance-public-data)

**Live endpoints**
- `openInterestHist` has 5m to longer periods but only the latest month, at 1000 requests per 5 minutes per IP; the basis endpoint has the latest 30 days — [Binance docs](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Open-Interest-Statistics)
- `!forceOrder@arr` pushes at most the latest liquidation per symbol in each 1000 ms, so it undercounts — [Binance docs](https://developers.binance.com/docs/derivatives/usds-margined-futures/websocket-market-streams/All-Market-Liquidation-Order-Streams)
- [Own test, India IP] HTTP 200 without a key for `fapi/v1/time`, `futures/data/openInterestHist`, `fapi/v1/fundingRate` and `futures/data/takerlongshortRatio`. `fapi/v1/allForceOrders` returned 404, and `fapi/v1/forceOrders` returned 401 "API-key format invalid", so there is no keyless REST liquidation history.

**Regional restrictions**
- HTTP 451 is returned when a service is unavailable from the requesting location, and developers reported it on GCP from about December 2022 — [Binance dev forum: Google Cloud and 451](https://dev.binance.vision/t/google-cloud-and-ip-restriction-451-on-fapi-binance/13820)
- In those reports GCP IPs were said to resolve as US-based regardless of region, and moving to asia-northeast1 did not fix fapi; one user reported success with Cloud NAT through a European static IP — [same thread](https://dev.binance.vision/t/google-cloud-and-ip-restriction-451-on-fapi-binance/13820). These are user reports, mostly from 2022, with no official Binance confirmation found.
- Binance terms list the US, Malaysia and Ontario among Restricted Locations, as quoted in developer discussion; seen in a search summary, and the specific thread was not opened — [Binance dev forum, closest listing](https://dev.binance.vision/t/service-unavailable-from-a-restricted-location/13813)
- Binance was blocked in India in January 2024, paid a penalty of 188.2 million rupees in June 2024, and resumed after FIU registration around August 2024 — [Cointelegraph](https://cointelegraph.com/news/binance-india-relaunch-fiu-registration). One source gives May 2024 for the registration date.
- Whether Indian accounts may trade Binance derivatives is contested: [one low-quality comparison says not available](https://bestcryptoindia.com/fiu-registered-crypto-exchanges-india), and a sponsored [Business Today feature](https://www.businesstoday.in/impact-feature/story/how-binances-247-trading-hub-is-revolutionizing-crypto-stocks-gold-for-indian-investors-526422-2026-04-20) describes TradFi perps as usable by Indian investors.

### Inferences
- Taker flow and CVD can be fully backtested from 1m klines for perp and spot, without trade-level files. Use aggTrades only when a sub-minute feature such as Q1 demands it.
- OI signals are limited to 5-minute resolution (metrics, from 2020-09), which suits the 1-minute-or-slower constraint.
- Liquidation-trigger strategies cannot be backtested from the free Binance USDT-M archive. Use OI drop plus range expansion as a proxy historically (the L1 trigger), and start collecting `!forceOrder@arr` now to validate the proxy, recognizing its undercount.
- For live use, check the VM first with `curl -i https://fapi.binance.com/fapi/v1/time`. A 451 means the GCP egress is blocked. The project's OB1h engine already reads spot data from `data-api.binance.vision`, but that does not establish futures access. Do not assume masking egress is acceptable: IP workarounds can conflict with Binance's terms. Trading on Delta while reading public data is a separate question from holding a Binance derivatives account.
- A safe fallback is to run the collector or signal job wherever a direct check succeeds, or use the daily archive for research, which needs no fapi access.

### Gaps
- `asia-south1` was not tested. The VM is IAP-only and was out of scope for this note. No current report specific to that region was found.
- No official Binance statement was found on Indian users' derivatives eligibility or on GCP IP geolocation.
- Exact end dates for archive files were not fully enumerated, because listings were sampled from a late marker.
- Free liquidation history from other venues, and third-party data sources such as Coinalyze or Tardis free tiers, were not researched in this pass.
