# Smart Zone Pro [Abusuhil]-style zones on BTC: placebo tests and external evidence

Local results are cited by file path under `/Users/ajaybaburaj/Documents/ajay/crypto/`. The code, frozen protocol and all result tables are in `research/smart_zone/placebo/`. The main tables are in `research/smart_zone/placebo/output/binance_balanced_p5/results_holdout/`. Unless stated otherwise, the numbers below are holdout results (2025-07-01 to 2026-10-31) for the Balanced profile with pivot length 5.

The Pine source is protected, so these are results for an independent re-implementation of the published description and the assignment spec. They are not results for the actual script.

## When price touches a zone, does it react more often than at placebo levels of the same width?

### Takeaway
No. Against width-matched placebos, real zones have no measurable reaction advantage on 5m, 15m, 1h or 4h at X = 0.5, 1 or 2 ATR. All 24 valid holdout comparisons are either null or negative, and none shows a positive edge after correction. The one that survives within-family Holm is negative (1h, X = 0.5, real 4.1pp below placebo).

### Cited Findings

**Data used**
- Primary: Binance USD-M BTCUSDT perpetual, 1m, 2023-11-01 to 2026-10-31, 1,578,240 rows, 0 missing minutes after one day (2026-10-28) was repaired from the REST API. This is a BTCUSD proxy, not Delta's contract. — `data/binance_ob_timeframes/audit.json`; `data/binance_ob_timeframes/minutes.parquet`
- Exploratory cross-check: Delta BTCUSD 1m, 2026-01-01 to 2026-10-26, 334,821 rows out of about 430k possible minutes (large gaps; no June raw archive is present). Only complete bars were used, and events started 2026-03-01. — `data/parquet/BTCUSD_1m_20260101_20261026.parquet`; `data/raw/`
- Timeframes 5m/15m/1h/4h were built from 1m. Barriers and touch timing were resolved on the 1m path. — `research/smart_zone/placebo/engine.py`

**No lookahead**
- A truncation and poison check passed 24 of 24 cut points across all four timeframes. Every zone rebuild made before bar T was identical when future bars were removed and when they were replaced with random garbage. Pivot confirmation lag was exactly 5 bars. The check ran on the first 12,000 bars of each timeframe and covers the primary configuration. — `research/smart_zone/placebo/truncation_check.py`

**Holdout reaction rates (real minus placebo, with 95% CI)**

Displayed zones only. Null A is random offset at matched distance and identical width (20 replicates). Null B is shuffled-time geometry, width-matched (20 replicates). Unresolved events are excluded (at most 0.8%).

| TF | X | n real | Real rate | Null A rate | Real − A (CI) | p | Null B rate | Real − B (CI) | p |
|---|---|---|---|---|---|---|---|---|---|
| 5m | 0.5 | 18,067 | 60.2% | 60.8% | −0.64pp (−1.23, −0.06) | 0.032 | 60.6% | −0.44pp (−1.19, 0.30) | 0.24 |
| 5m | 1 | 18,067 | 57.1% | 57.3% | −0.20pp (−0.79, 0.40) | 0.52 | 57.3% | −0.20pp (−0.88, 0.48) | 0.56 |
| 5m | 2 | 18,047 | 54.7% | 54.3% | +0.41pp (−0.30, 1.13) | 0.26 | 54.4% | +0.32pp (−0.43, 1.06) | 0.40 |
| 15m | 0.5 | 5,961 | 64.2% | 64.2% | +0.08pp (−1.08, 1.24) | 0.90 | 64.4% | −0.19pp (−1.45, 1.07) | 0.77 |
| 15m | 1 | 5,961 | 59.5% | 59.6% | −0.12pp (−1.11, 0.86) | 0.81 | 59.8% | −0.33pp (−1.27, 0.62) | 0.50 |
| 15m | 2 | 5,960 | 56.4% | 56.3% | +0.20pp (−1.24, 1.64) | 0.79 | 55.9% | +0.54pp (−0.69, 1.77) | 0.39 |
| 1h | 0.5 | 1,306 | 63.3% | 67.4% | −4.06pp (−6.58, −1.54) | 0.0016 | 66.4% | −3.03pp (−5.82, −0.24) | 0.033 |
| 1h | 1 | 1,306 | 59.0% | 61.4% | −2.39pp (−5.32, 0.54) | 0.11 | 60.3% | −1.36pp (−4.61, 1.89) | 0.41 |
| 1h | 2 | 1,305 | 53.4% | 57.5% | −4.08pp (−7.11, −1.04) | 0.0084 | 56.3% | −2.85pp (−7.03, 1.33) | 0.18 |
| 4h | 0.5 | 373 | 63.3% | 64.0% | −0.70pp (−5.23, 3.84) | 0.76 | 64.1% | −0.78pp (−5.28, 3.73) | 0.74 |
| 4h | 1 | 373 | 56.3% | 57.6% | −1.26pp (−7.09, 4.58) | 0.67 | 57.2% | −0.86pp (−6.21, 4.48) | 0.75 |
| 4h | 2 | 371 | 56.3% | 55.2% | +1.19pp (−4.11, 6.49) | 0.66 | 53.4% | +2.95pp (−2.08, 7.99) | 0.25 |

Source: `research/smart_zone/placebo/output/binance_balanced_p5/results_holdout/f1.csv`

- Multiple testing: 136 tests in total across the F1 reaction tests (36), the F2 score tests (96) and the F3 signal tests (4); the F3 p-values are empirical from 500 random portfolios. Family F1 has 36 tests, because it includes the 12 confounded-arm tests. Against the two valid nulls, Holm leaves only the 1h X = 0.5 real-vs-random comparison significant (real below placebo, Holm p = 0.045), and it does not survive Holm across all 136 (0.17). Against the valid nulls, no difference is positive and significant. — `research/smart_zone/placebo/output/binance_balanced_p5/results_holdout/f1.csv`; `research/smart_zone/placebo/output/binance_balanced_p5/holdout_log.txt`
- Confidence intervals are precise enough at 5m and 15m to rule out effects larger than roughly +1 to +2pp. At 4h the intervals are wide (about ±5pp) and cannot rule out an effect the size Osler reports (see the external-evidence section). — `results_holdout/f1.csv`
- Inference used a week-block bootstrap (5000 resamples) with 4-week-block sensitivity. The standard error is the larger of the two, the CI is ±1.96 SE, and p-values are z-based. — `research/smart_zone/placebo/analyze.py`
- Reaction base rates are far above 50% for everyone because the failure barrier is further away than the success barrier (zone width sits on the failure side). Real zones and placebos are geometrically the same, so a "60% reaction rate" by itself carries no information. — `results_holdout/f1.csv`

**A confounded null, reported honestly**
- The originally pre-registered shuffled-time arm was confounded: donor widths averaged about 0.23 ATR against about 0.58 ATR for real displayed zones. Narrower zones have a nearer failure barrier, so the arm's reaction rate is mechanically lower. It reports real zones "beating" it by +1 to +9pp, significant in many cells, which is an artifact. I kept it, labelled `shuffled_time_CONFOUNDED`. — `research/smart_zone/placebo/output/binance_balanced_p5/results_holdout/f1.csv`; `research/smart_zone/placebo/PROTOCOL.md` Amendment 2
- Protocol discipline: the protocol was frozen before any outcome (Amendment 1 from the public script description, before any events). Amendment 2 added the width-matched arm after seeing dev results (2024-01-01 to 2025-06-30) and before the holdout was run. Disclosure: the dev analysis printed the by-year table for all years, so X = 1 real-vs-random-offset rates for 2025H2 and 2026 were seen before the holdout run. No parameter or population changed; only the arm addition did. — `research/smart_zone/placebo/PROTOCOL.md`
- Hindsight arm (exploratory; confirmation lag removed): real rates rise by at most 1.25pp over causal zones (about 0.4 to 1.25pp in 11 of 12 cells, and −0.06pp at 4h X = 2) (e.g. 5m X = 1 57.7% vs 57.1%). — `results_holdout/hindsight.csv`

**Robustness (holdout, random-offset null, descriptive)**
- Strict profile (max width 0.6 ATR, top 3 zones, min strength 1.75) on 15m/1h/4h: all nine differences are negative or insignificant (range −6.1pp to +2.2pp), none Holm-significant. — `research/smart_zone/placebo/output/binance_strict_p5/results_holdout/f1.csv`
- Pivot length 10 on 15m/1h/4h: all nine are negative or insignificant, none Holm-significant (4h X = 1 is −6.2pp, unadjusted p 0.012, Holm 0.15). — `research/smart_zone/placebo/output/binance_balanced_p10/results_holdout/f1.csv`
- Delta BTCUSD (March–October 2026 window, exploratory, 10 replicates): no positive Holm-significant difference. The largest is 5m X = 2, +1.56pp (unadjusted p 0.019, Holm 0.32). 4h is negative (−5.5 to −9.1pp), on small n (146–152 events). — `research/smart_zone/placebo/output/delta_balanced_p5/results_holdout/f1.csv`

### Inferences
- Under this implementation, BTC does not react to these zones any more than to arbitrary levels of the same width at the same distance. Null B confirms that the Null A result is not an artifact of how the random offsets were generated.
- A negative difference at 1h does not mean zones are "anti-predictive" in any tradeable sense; it is inconsistent across X and nulls and does not survive global correction.
- Reaction rates quoted without a placebo benchmark are misleading for this construct, since 60%+ arises from geometry alone.

### Gaps
- The Pine source is unavailable, so every parameter not on the public page is my assumption: pivot length (5 and 10 tested; the indicator default is unpublished), lookback, merge multiplier 0.5 of ATR, decay, flip minimum gap, strength formula scale, minimum width. The zones may differ materially from the script's.
- At 4h the sample is too small (n of about 370) to exclude an effect of Osler's size.
- I did not test with Delta-specific fills or an order book.

## Do reaction rates rise with stars, touch count, reaction score and flip status?

### Takeaway
Reaction rates do rise with stars, touches and flip status, but placebo zones given the same parent attributes rise equally. The scoring is capturing zone width (geometry), not information about future price behaviour. None of the 48 excess-slope tests survives Holm, and the reaction score carries no signal even in raw form.

### Cited Findings
- Raw slope of reaction rate on level (X = 1): stars +3.4pp per level at 5m, +3.6pp at 15m, +2.8pp at 1h, +2.5pp at 4h (not significant at 4h). Touches +3.9pp, +4.0pp, +3.0pp, +3.9pp. Flip +5.7pp (5m), +5.9pp (15m), not significant at 1h or 4h. — `results_holdout/f2.csv`
- 22 of the 96 tests pass Holm within family, and all 22 are raw-slope tests (22 of 48 raw): stars, touches or flip on 5m and 15m, stars or touches on 1h, and one touches test at 4h. Reaction-quality never passes. — `results_holdout/f2.csv`
- Excess slopes (real minus random-offset placebos with the same inherited attribute): 0 of 48 pass Holm; 5m stars excess +0.05pp, touches +0.22pp, flip +0.84pp, all inside the CI around zero. Some 1h excess slopes are negative at unadjusted p below 0.05 but not after Holm. — `results_holdout/f2.csv`
- Level table example, 5m, X = 1: 1-star 50.9% real vs 51.2% placebo; 4-star 60.3% real vs 60.7% placebo. The placebo rises by the same amount. — `results_holdout/levels.csv`
- Under the secondary profiles, 0 excess-slope tests pass Holm (Strict 0, pivot 10 0; raw tests 9 and 8 respectively). — `research/smart_zone/placebo/output/binance_strict_p5/results_holdout/f2.csv`; `research/smart_zone/placebo/output/binance_balanced_p10/results_holdout/f2.csv`

### Inferences
- Mean zone width on holdout real events rises from about 0.13 ATR at 1 star to about 0.85 ATR at 4 stars, from about 0.11 ATR at 1 touch to about 0.93 ATR at 4+ touches, and from about 0.27 to about 0.65 ATR for flips (computed from `events_*.parquet`, consistent across timeframes). Wider zones have mechanically further failure barriers, so the score's apparent information is width, which any level of the same width also has.
- A star-based filter is unlikely to improve a trading rule beyond width alone.

### Gaps
- The script's "display score" width penalty is unpublished and not modelled; it could weaken this geometric channel in the real script.
- Reaction-score quartile cut-offs come from dev data, so the quartile scale is arbitrary.

## Are the rejection signals better than a random-entry benchmark, net of costs?

### Takeaway
No. On the holdout, rejection signals lose money net of costs on every timeframe and match or underperform random entries with identical side, stop distance, target and time limit. None of the four tests is significant.

### Cited Findings

| TF | Signals | Win rate | Mean net R | Random mean R (5–95%) | Real − random R (CI) | p (one-sided) | Gross % per trade | Net % per trade |
|---|---|---|---|---|---|---|---|---|
| 5m | 2,656 | 31.6% | −1.003 | −1.001 (−1.030, −0.969) | −0.002 (−0.058, 0.054) | 0.515 | −0.003 | −0.143 |
| 15m | 1,007 | 43.0% | −0.569 | −0.515 (−0.566, −0.468) | −0.054 (−0.114, 0.006) | 0.964 | −0.017 | −0.157 |
| 1h | 235 | 48.9% | −0.225 | −0.213 (−0.323, −0.112) | −0.012 (−0.141, 0.118) | 0.595 | −0.022 | −0.162 |
| 4h | 68 | 45.6% | −0.182 | −0.136 (−0.332, 0.051) | −0.046 (−0.289, 0.197) | 0.645 | −0.039 | −0.179 |

Source: `research/smart_zone/placebo/output/binance_balanced_p5/results_holdout/f3.csv`

- Trade design: entry at next bar open; stop at far zone edge ±0.25 ATR; 1R target; 48-bar time stop; 0.14% round-trip costs; Binance funding included; stop wins ties. Random benchmark matches month, side, stop %, target and time stop, with 500 replicates. — `research/smart_zone/placebo/bench.py`; `research/smart_zone/placebo/PROTOCOL.md`
- Mean stop distance is 0.21% at 5m and 0.38% at 15m, so a round-trip cost of 0.14% consumes 67% and 37% of 1R. — `results_holdout/f3.csv`
- Dev-period signals were also negative net (−0.84R to −0.08R); none passed Holm. Dev 1h mean net R was −0.084 at 280 trades, which did not hold up in the holdout. — `research/smart_zone/placebo/output/binance_balanced_p5/results_dev/f3.csv`

### Inferences
- Rejection candles at these zones are not better than random entries with the same stop, target and side. The bulk of the net loss is the cost-to-stop ratio, not a directional loss.

### Gaps
- Signals in this study fire only on the first touch of each lock episode, because that is how the touch events were defined. The script's diamond logic could differ. Reported numbers apply to the assumed rule.
- There is no one-position-at-a-time constraint; results are per-signal expectancy. A sequential portfolio simulation was not run.

## Is any effect large enough to pay costs?

### Takeaway
No. Gross expected per-trade returns are near zero or negative everywhere (the best cell is +0.066% at 4h X = 2 in a fade-at-the-edge model), against Delta-style costs of 0.12–0.14% round trip. Breakeven cost is zero for most cells, since gross returns are negative.

### Cited Findings
- Cost assumption: Delta-style taker 0.05% per side plus 0.01–0.02% slippage per side, i.e. 0.12–0.14% round trip (assignment-supplied; not independently verified against Delta's current fee schedule).
- Fade-at-the-touched-edge model (gross, X barriers, holdout): 5m, 15m and 1h are negative or tiny at all X except 15m X = 2 (+0.0115% gross). 4h X = 2 is +0.066%, 4h X = 0.5 and X = 1 are negative (−0.035%, −0.083%). Excess over random-offset placebo is within noise (5m −0.15bp to +0.09bp in % terms: −0.0015% to +0.0009%; 1h X = 2 −0.13%, SE 0.05%). — `results_holdout/breakeven.csv`
- Rejection-signal gross per trade is negative on every timeframe (−0.003% to −0.039%), so breakeven cost per round trip is 0. Net per trade is −0.143% to −0.179%. — `results_holdout/f3.csv`
- Required edge to pay 0.14% round trip in the fade model at X = 1 (Δp × (2X + W) × ATR% = 0.14%, using mean ATR% and W from `breakeven.csv`): about 35pp at 5m, 19pp at 15m, 9pp at 1h, 4.4pp at 4h. Observed differences are about zero. Only at 4h is the required edge inside the confidence interval, and there the point estimate is −1.3pp. — `results_holdout/breakeven.csv`; `results_holdout/f1.csv`
- Taker costs sit against a target of about 1 ATR (0.16% at 5m, 0.28% at 15m, 0.59% at 1h, 1.2% at 4h average ATR%). Short timeframes cannot pay costs under any plausible reaction edge. — `results_holdout/breakeven.csv`

### Inferences
- Edge-fill assumptions are optimistic (limit orders at the zone edge ignore queue position and adverse selection), so the fade model flatters the case. It still fails.
- Even a genuine effect of the size in Osler's FX study (about 4–5pp) would only just reach the 4h breakeven. It would not pay at 5m, 15m or 1h.

### Gaps
- Maker-fee execution and order-book fills were not modelled; this is outside the taker cost case the assignment specified.

## Is the effect stable across years and volatility regimes?

### Takeaway
There is no effect to be stable. Real-minus-placebo differences at X = 1 sit around zero or below in every year (2024, 2025, 2026) and every volatility tercile, with no sign pattern to exploit.

### Cited Findings
- Year (X = 1, real minus random offset): 5m −0.66pp, −0.50pp, −0.25pp; 15m −0.45pp, +0.61pp, −0.20pp; 1h −2.12pp, −2.36pp, −3.21pp; 4h −1.72pp, +3.08pp, −5.43pp (2024, 2025, 2026; no 95% CI in this table excludes zero). Note that 2024 and part of 2025 are dev period. — `results_holdout/year.csv`
- Volatility tercile within holdout (ATR% cut-offs from dev; X = 1): 5m −0.38pp, +0.37pp, −0.55pp; 15m +0.15pp, −0.35pp, −0.87pp; 1h −1.17pp, −3.70pp, −6.26pp (high volatility worst, n = 157); 4h −1.15pp, −3.76pp, with too few events in the high tercile to report. All of these CIs include zero. — `results_holdout/vol.csv`
- These breakdowns are descriptive and uncounted in the test families, per protocol. — `research/smart_zone/placebo/PROTOCOL.md`

### Inferences
- The 1h negative sign is consistent across years, but small and not significant after correction; I would not interpret it as a reliable anti-signal.

### Gaps
- The 2.5-year usable window covers few distinct volatility regimes for a strategy-grade claim.

## What does published evidence say, and what is known about the script?

### Takeaway
The best-known S/R study (Osler 2000, FX) found published levels beat arbitrary levels by about 4–5pp over a 15-minute horizon, and explicitly left profitability untested. Wider technical-rule studies, once corrected for data snooping, mostly lose significance out of sample, including on Bitcoin. I found no direct academic test of S/R zones on BTC, and no independent test of this script. The script page makes no performance claims and no statement on repainting.

### Cited Findings

**Osler and S/R levels**
- Osler (FRBNY Economic Policy Review, July 2000) tests support and resistance levels published by six FX firms against 10,000 sets of arbitrary levels: rates bounced off arbitrary levels 56.2% of the time and off published levels 60.8%, with average advantages of 4.2pp (mark), 5.6pp (yen) and 4.0pp (pound). — [Osler 2000](https://resources.newyorkfed.org/medialibrary/media/research/epr/00v06n2/0007osle.pdf)
- A "bounce" there means the rate is on the expected side of the level 15 minutes later (30 minutes as an alternative), a much weaker criterion than the barrier-race outcome used here. — [Osler 2000](https://resources.newyorkfed.org/medialibrary/media/research/epr/00v06n2/0007osle.pdf)
- Osler explicitly leaves profitability open, saying that whether traders could profit from these bounces would be "an appropriate subject for future research." — [Osler 2000](https://resources.newyorkfed.org/medialibrary/media/research/epr/00v06n2/0007osle.pdf)
- The arbitrary-benchmark design used by Osler is the same in spirit as the placebo design here. — [Osler 2000](https://resources.newyorkfed.org/medialibrary/media/research/epr/00v06n2/0007osle.pdf)

**Trading-rule tests and data snooping**
- Brock, Lakonishok and LeBaron (1992) tested moving-average and trading-range-break rules (a support/resistance form) on DJIA data and, as summarised by Sullivan et al., found the 26 rules significantly outperformed the benchmark. — [Sullivan, Timmermann, White 1999](https://bashtage.github.io/kevinsheppard.com/files/teaching/mfe/advanced-econometrics/Sullivan_Timmermann_White.pdf)
- Sullivan, Timmermann and White (1999, Journal of Finance) applied the Reality Check bootstrap: some rules held up in the 1897–1986 period after snooping adjustment, but out of sample (1987–1996) "there is scant evidence that technical trading rules were of any economic value." — [Sullivan, Timmermann, White 1999](https://bashtage.github.io/kevinsheppard.com/files/teaching/mfe/advanced-econometrics/Sullivan_Timmermann_White.pdf)

**Crypto**
- Hudson and Urquhart (Annals of Operations Research, 2021) tested about 15,000 technical rules on cryptocurrencies, found predictability in-sample, but report "no predictability for Bitcoin in the out-of-sample period." I read the abstract only. — [Hudson & Urquhart abstract](https://centaur.reading.ac.uk/85715)
- An Erasmus thesis (5-minute BTC/USD, January 2013 to July 2017, 3,312 intraday rules) found rules significantly profitable after snooping and cost adjustments, with profitability unstable and declining over time. This covers an early, less efficient market period and is a thesis, not peer-reviewed. — [Erasmus thesis](https://thesis.eur.nl/pub/41546/)
- A 2023 Journal of Accounting and Finance study of four strategies on BTC/USDT and ETH/USDT during 2022–2023 reported a lack of profitable technical strategies after data-snooping adjustment. I saw only a search summary of this one, not the full text. — [JAF 2023](https://articlegateway.com/index.php/JAF/article/download/6453/6095)
- Algorithmic S/R on price data: Chung and Bellotti (arXiv 2101.07410) report levels reverse trends at a statistically significant rate, with more prior bounces predicting more future bounces and decay over time; I read the abstract only and did not verify the assets. Garzarelli et al. (arXiv 1110.5197) report prices "more likely re-bounce than cross these values." — [Chung & Bellotti](https://arxiv.org/abs/2101.07410); [Garzarelli et al.](https://arxiv.org/abs/1110.5197)

**The script itself**
- Smart Zone Pro [Abusuhil] is a Pine v6 protected-source script (source not viewable) in TradingView's educational category, listed "Mar 15" with no year shown on the page. — [TradingView script page](https://www.tradingview.com/script/oK06JCrx-Smart-Zone-Pro-Abusuhil/)
- Published mechanics: confirmed pivots, ATR(14) stored at formation, clustering with the more conservative of pivot ATR and zone average, trimming toward a centre weighted by reaction quality times recency, strength from touches, recency decay, average reaction and flip bonus, with a separate width penalty on the display score. Stars: 1 star below 1.5, 2 stars 1.5–3, 3 stars 3–5, 4 stars above 5. Balanced shows up to 5 zones, min strength 1.25, 1.0 ATR max width; Strict shows up to 3, 1.75, 0.6 ATR. Mixed zones are hidden and block rejections. — [TradingView script page](https://www.tradingview.com/script/oK06JCrx-Smart-Zone-Pro-Abusuhil/)
- Author claims: the page makes no backtest, win-rate or profitability claims. It says the tool is analytical, does not predict price, and generates no buy or sell signals. — [TradingView script page](https://www.tradingview.com/script/oK06JCrx-Smart-Zone-Pro-Abusuhil/)
- The page says nothing about repainting or redrawing. — [TradingView script page](https://www.tradingview.com/script/oK06JCrx-Smart-Zone-Pro-Abusuhil/)
- I found no independent test or peer review of this script; searches returned the script page and similarly named but different scripts, such as — [The Machine – Smart Zones PRO](https://www.tradingview.com/script/jpD8T1hB-The-Machine-Smart-Zones-PRO/) (invite-only)

**Repainting mechanics**
- TradingView's Pine docs define repainting as behaviour differing between historical and realtime bars. The docs specifically warn that pivot scripts often plot on the actual pivot bar though the pivot is detected bars later, and recommend plotting without an offset by default. — [Pine repainting docs](https://tradingview.com/pine-script-docs/concepts/repainting)
- The docs add that a chart refresh rebuilds elapsed realtime bars from historical data and that a change to the first bar can change later calculations. — [Pine repainting docs](https://tradingview.com/pine-script-docs/concepts/repainting)
- TradingView's help article describes plotting on past bars with a negative offset as one of the behaviours commonly called repainting, and says the historical-vs-realtime effect is "not a bug." — [TradingView support](https://www.tradingview.com/support/solutions/43000478429-script-or-strategy-gives-different-results-after-refreshing-the-page-repainting)

### Inferences
- Confirmed pivots do not themselves imply zones are stable on the chart. Zones in a recompute-each-bar engine with age decay, trimming and a top-N display will change: past zones are dropped or re-centred and strength shifts. The chart shows the current zone set, so past price reactions at drawn zones reflect selection after the fact (inference; the script's code cannot be read).
- My hindsight test removed only the pivot confirmation lag and produced a small uplift (at most about 1.25pp), so plotting lag is not the main source of flattering chart appearance in this implementation. The more likely source is the current set of zones being drawn on bars that already happened.
- Findings from FX and DJIA are not automatically transferable to BTC. Osler's 4–5pp used human-published levels with a 15-minute horizon and no costs.

### Gaps
- Full text of Hudson & Urquhart, Chung & Bellotti and the 2023 JAF study was not read; only abstracts or search summaries were available.
- I found no peer-reviewed test of pivot-cluster S/R zones on BTC specifically.
- I could not observe the script's actual behaviour on a live chart or read its code, so whether zones redraw historically is unconfirmed.
- The script's popularity counters (346 and 4,492) are unlabeled on the page and are not interpreted here.
