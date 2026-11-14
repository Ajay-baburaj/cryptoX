# Order flow trading signals for intraday BTC and crypto (spot and perpetuals)

Evidence labels used below: **[PEER]** peer-reviewed; **[WP]** working paper or arXiv preprint; **[VENDOR]** vendor, influencer or educational page (low quality). "Read" means the full text was read; "abstract/snippet only" means it was not.

Execution constraint assumed throughout: taker market orders on BTCUSDT, about 14 bps round trip, polling at 1 minute or slower.

## What are the definitions and exact rules for CVD divergence, taker imbalance, absorption, footprint stacked imbalance, OFI and VPIN?

### Takeaway
OFI and VPIN have exact published formulas. Taker imbalance is simple arithmetic on an exchange flag. CVD divergence, absorption and stacked imbalance are vendor conventions, and their thresholds have no empirical basis that I could find.

### Cited Findings
- **OFI (Cont, Kukanov, Stoikov).** For consecutive best-quote updates n-1 and n, with bid price P^B, bid size q^B, ask price P^A, ask size q^A: `e_n = 1{P^B_n >= P^B_n-1} q^B_n - 1{P^B_n <= P^B_n-1} q^B_n-1 - 1{P^A_n <= P^A_n-1} q^A_n + 1{P^A_n >= P^A_n-1} q^A_n-1`. `OFI_k` is the sum of `e_n` over interval k. — [Cont et al., read](https://arxiv.org/abs/1011.6402)
- OFI treats a market sell and a cancelled buy of equal size as equivalent, because both shrink the bid queue. The model is `dP_k = beta * OFI_k + error`. — [Cont et al., read](https://arxiv.org/abs/1011.6402)
- **VPIN, 1-minute bar form (Easley, O'Hara, Yang, Zhang).** `VPIN_t = (1/W) * sum over i=t-W+1..t of |V^S_i - V^B_i| / V_i`, where `V^B_i = V_i * Z(dp_i / sigma_dp_i)` (bulk volume classification, Z is the standard normal CDF) and `V^S_i = V_i - V^B_i`. — [Easley et al. 2024, read in part](https://stoye.economics.cornell.edu/docs/Easley_ssrn-4814346.pdf)
- The original VPIN uses equal-volume buckets instead of time bars. — [Practitioner description of bucket construction](https://themicrostructurelab.substack.com/p/toxic-flow-segmentation-measuring)
- **Trade (taker) imbalance.** Order imbalance is signed order flow divided by total volume, bounded in [-1, 1]; direction comes from the `isBuyerMaker` flag in Binance aggTrades. — [Quarter-Hour Effect, read](https://arxiv.org/html/2607.09426v2)
- **CVD divergence [VENDOR].** Bearish: two consecutive swing highs 4 to 60 bars apart, where price makes a higher high and CVD makes a lower high. CoinGlass scores it by price move 12 bars after confirmation and advises against trading it alone. — [CoinGlass CVD](https://www.coinglass.com/cvd/BTC)
- **Stacked imbalance [VENDOR].** Ratio commonly about 300% (3:1), with three or more consecutive same-direction price levels; described as convention. — [LuxAlgo](https://www.luxalgo.com/library/concept/bid-ask-imbalance/); [ATAS](https://learn.atas.net/volume-basics/volume-analysis/footprint-patterns)
- **Absorption [VENDOR].** ATAS: unusually high volume at one level, with price staying put or barely moving. It gives no numeric threshold, requires near-zero delta in one passage and "clear dominance by one side" in another, and says absorption "is not a forecast". — [ATAS](https://learn.atas.net/volume-basics/volume-analysis/footprint-patterns)

### Inferences
- Absorption has no single testable definition, because the leading vendor description contradicts itself. Any test has to fix its own definition in advance.
- On Binance, VPIN can use the real taker flag rather than bulk classification. That should remove the classification error at the centre of the VPIN critique (see the academic section), though I found no paper testing this on crypto.

### Gaps
- I found no authoritative source for the footprint comparison direction (diagonal versus same-price bid/ask). This is a platform setting and must be fixed before testing.

## What horizon does predictability last in crypto, and how large is it in bps versus about 14 bps round trip?

### Takeaway
Strong predictability is sub-second to a few seconds and is smaller than taker costs even at those speeds. The only order-flow result I found near your cost level is at 4 to 12 hours, and it has not been tested net of costs.

### Cited Findings
- At 500 ms, linear book-and-trade features explain 10% to 37% of future return variation across 14 BTC markets (February 2021). — [Albers et al., read in part](https://arxiv.org/pdf/2108.09750)
- Binance perpetuals, 2021-2024, six assets: mean absolute 10-second returns are about 1.9 to 3.9 bps, and 1-minute returns about 5.4 to 10.9 bps. — [Quarter-Hour Effect](https://arxiv.org/html/2607.09426v2)
- The predictable component of the first 10 seconds after each quarter hour is about 0.5 bps per boundary (out-of-sample direction AUC 0.60, accuracy 57.12%), which the authors put at about one-tenth of a single 5 bps taker fee. — [Quarter-Hour Effect](https://arxiv.org/html/2607.09426v2)
- In the same paper, quarter-hour order imbalance predicts returns mainly over 4 to 12 hours, with small or negative coefficients at short horizons. The reported public-signal component is under 1 bp at 4 hours, about 9.8 bps at 8 hours and 16.9 bps at 12 hours; a lagged-flow component is a stable 5 to 6 bps. The paper does not test this effect net of costs. — [Quarter-Hour Effect](https://arxiv.org/html/2607.09426v2)

### Inferences
- **Break-even arithmetic (mine).** For a symmetric directional bet, `(2p - 1) * E|r| >= 14 bps`. At 1 minute, E|r| is at most about 10.9 bps, so even perfect direction (p = 1) cannot cover 14 bps on average with the reported range.
- Assuming E|r| scales with the square root of time from the 1-minute range of 5.4 to 10.9 bps (an approximation), p = 0.60 needs E|r| = 70 bps, about 41 to 168 minutes of holding. p = 0.55 needs E|r| = 140 bps, about 2.75 to 11 hours.
- So at 14 bps, realistic hit rates imply holding from roughly one hour to half a day. This matches the only horizon where order flow approaches cost.
- The 9.8 and 16.9 bps figures come from a machine-extracted summary of a decomposition, and they may not be additive with the 5 to 6 bps component. Treat them as hypotheses, not as expected trade returns.

### Gaps
- BTC-specific figures in the Quarter-Hour paper were not separated out in what I extracted; the 5.4 to 10.9 bps range is cross-asset.
- I found no peer-reviewed BTC study mapping order-flow predictability continuously across 1-minute to 1-day horizons in bps net of costs.

## What do academic studies find specifically on BTC and crypto?

### Takeaway
Statistical predictability is well documented, but no study I could verify shows a BTC taker strategy that survives retail fees at 1-minute latency. The clearest test, Albers et al., loses money on every market at default fees.

### Cited Findings

| Study | Sample and period | Target and horizon | Out-of-sample result | Costs included? |
|---|---|---|---|---|
| [Albers, Cucuringu, Howison, Shestopaloff 2021](https://arxiv.org/pdf/2108.09750) [PEER, read in part] | 14 BTC spot and perpetual markets; train Feb 22-27 2021, test Feb 28-Mar 1 2021 | Return, 500 ms | R² 10-37%. Gross PnL about +11,000 bps over 2 days | Yes. **Default fees: every market negative, average -18,899 bps.** Lowest VIP fees: average -9,621 bps |
| [Bieganowski, Ślepaczuk 2026](https://arxiv.org/html/2602.00776) [WP, read] | Binance perpetuals, BTC, LTC, ETC, ENJ, ROSE; 1-second data; Jan 2022-Oct 2025 | Mid return, 3 s | Walk-forward. **BTC taker annual return 0.13 versus buy-and-hold 0.83, p = 0.75.** ETC, ENJ, ROSE taker returns 4.06-7.00, significant at 5% | Taker fee stated but rate not given; latency not modelled |
| [Quarter-Hour Effect 2026](https://arxiv.org/html/2607.09426v2) [WP, read] | Binance perpetuals, 6 assets, 2021-Oct 2024; out-of-sample from Jul 2021 | 10 s after quarter hour; imbalance to 12 h | R² 3.37%, AUC 0.60; about 0.5 bps gross | Compared only to fees; 4-12 h effect not costed |
| [Easley, O'Hara, Yang, Zhang 2024](https://stoye.economics.cornell.edu/docs/Easley_ssrn-4814346.pdf) [WP, read in part] | BTC, ETH, ADA, SOL, XRP; 1-minute bars; Jan 2021-Jul 2023 | Sign of change in realized volatility, autocorrelation, kurtosis and similar. **Not return direction** | Accuracy 0.56-0.58 for realized volatility; skewness 0.50 (none). Roll and VPIN most important | No |
| [TLOB 2025](https://arxiv.org/html/2502.15757v3) [WP, read] | Binance BTCUSDT perpetual, Jan 9-20 2023, 250 ms; final single day is the test | Trend, 1-10 s | F1 74.7% at 1 s falling to 41.5% at 10 s | No BTC profitability test. Authors say the methods are "not sufficiently mature" for live trading |
| [Bybit LOB benchmark 2025](https://arxiv.org/html/2506.05764v2) [WP, read] | BTCUSDT, one day (2025-01-30), 100 ms | 100-1000 ms | Binary accuracy 0.53-0.73 with smoothed labels | No trading simulation |
| [Silantyev 2019](https://link.springer.com/doi/10.1007/s42521-019-00007-w) [PEER, abstract/snippet only] | BitMEX XBTUSD | Contemporaneous price change | Trade flow imbalance explains contemporaneous moves better than OFI, contrary to its hypothesis | Not a trading study |
| [Cont et al. 2014](https://arxiv.org/abs/1011.6402) [PEER, read in part; equities benchmark] | 50 US stocks | Contemporaneous mid change | Average R² 65% | Not a trading study |
| [Raffaelli et al. 2026](https://link.springer.com/article/10.1007/s10203-026-00570-z) [PEER, abstract only] | BTC/USD limit order book events | Return sign, high frequency | Hybrid Hawkes model beats pure Hawkes in accuracy and simulated profit | Not verified |
| [Kitvanitphasu et al. 2026](https://www.sciencedirect.com/science/article/pii/S0275531925004192) [PEER, snippet only] | Bitcoin VPIN and price jumps | Volatility and jumps | Search summary: toxicity leads volatility | Not verified |

- Albers et al.'s only strongly positive result was on Huobi spot using Binance perpetual features at VIP fees (+11,426 bps), and they note top-of-book size there may support only "a single digit USD amount". — [Albers et al.](https://arxiv.org/pdf/2108.09750)
- Andersen and Bondarenko find VPIN a poor volatility predictor, with predictive content stemming from a mechanical relation with trading intensity; Easley et al. dispute this. — [Andersen and Bondarenko abstract](https://econpapers.repec.org/RePEc:eee:finmar:v:17:y:2014:i:c:p:47-52); [rejoinder](https://opus.cloud1.lib.uts.edu.au/handle/10453/118180)
- A later Andersen and Bondarenko paper attributes VPIN's prediction to volatility-induced classification errors in bulk classification. — [Review of Finance abstract](https://econpapers.repec.org/RePEc:oup:revfin:v:19:y:2015:i:1:p:1-54.)

### Inferences
- High R² in OFI and trade-imbalance papers is mostly **contemporaneous**: it explains the move as it happens. That cannot be traded.
- Bieganowski's strong alt results rely on holding periods of seconds with no latency modelled, so they do not transfer to 1-minute polling. BTC, the relevant asset, shows no significant taker edge even there.
- VPIN's best-supported use in crypto is forecasting volatility change, not direction.
- Deep-learning LOB papers on BTC use test windows as short as one day, at horizons under about 10 seconds. They are irrelevant to this execution setup.

### Gaps
- [Vafin's SSRN paper on order-flow imbalance and short-horizon crypto predictability](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6938742) could not be accessed (HTTP 403). It reportedly addresses costs and data snooping, so it is worth reading manually.
- The ScienceDirect, Springer and PMC full texts were inaccessible. That includes [Nowcasting bitcoin's crash risk with order imbalance](https://pmc.ncbi.nlm.nih.gov/articles/PMC10040314/), whose results are unverified here.
- An earlier temporal-CNN paper reports 71% walk-forward accuracy at 2 seconds on Coinbase, seen in a snippet only, with cost treatment unverified. — [arXiv 2010.01241](https://arxiv.org/abs/2010.01241)

## Which signals can be computed from Binance 1m candles with taker-buy volume, which need aggTrades, and which need order-book history? What are the free data sources and limits?

### Takeaway
Taker imbalance, CVD, CVD divergence and VPIN work from free 1-minute klines. Footprint and price-level absorption need aggTrades. True OFI needs a book event stream, which is not freely available as long history for spot.

### Cited Findings
- Binance klines (spot and USD-M) include column 10 "Taker buy base asset volume" and column 11 "Taker buy quote asset volume". — [binance-public-data](https://github.com/binance/binance-public-data/)
- Files cover aggTrades, klines and trades for spot, USD-M and COIN-M, with CHECKSUM verification; aggTrades include price, quantity, timestamp and "was the buyer the maker". — [binance-public-data](https://github.com/binance/binance-public-data/)
- Spot timestamps are in microseconds from January 1, 2025 onward. — [binance-public-data](https://github.com/binance/binance-public-data/)
- A third-party downloader lists bookDepth, bookTicker, liquidationSnapshot and metrics for USD-M and COIN-M, and none for spot. The official README page I read did not mention them. — [binance-bulk-downloader](https://github.com/aoki-h-jp/binance-bulk-downloader)
- Taker-buy-based CVD history is available from 2017 for spot and 2020 for perpetuals according to one chart provider. — [BGeometrics](https://charts.bgeometrics.com/orderflow.html)
- Tardis offers tick-level incremental L2 CSVs, with the first day of each month downloadable without an API key. — [Tardis docs](https://docs.tardis.dev/downloadable-csv-files/overview.md)

| Signal | 1m klines | aggTrades | Book history |
|---|---|---|---|
| Taker imbalance, CVD | Yes | Yes (any bar) | No |
| CVD divergence | Yes | Optional | No |
| VPIN | Yes (taker flag or bulk classification) | Yes, for true volume buckets | No |
| Footprint stacked imbalance | No | **Required** | No |
| Absorption, volume-at-price proxy | No | **Required** | No |
| Absorption, true passive refill | No | Partial | **Required** |
| OFI (Cont) | No | No | **Required** (best quote updates) |
| Book imbalance, deep-learning LOB | No | No | **Required** |

### Inferences
- Trades in the footprint are classified by the exchange flag, which is better than the bid/ask inference used in many equity datasets.
- Klines are single-venue: Binance flow only, with no intrabar ordering.
- The practical free route to book data is to record the websocket yourself going forward. Backtests on it are limited to the recording period.

### Gaps
- I could not confirm from Binance's own documentation the start date, cadence or current availability of bookDepth and bookTicker files.
- I could not confirm that Binance spot or USD-M L2 is in Tardis's free first-of-month tier.

## Is a volume-bar or dollar-bar construction better than time bars?

### Takeaway
Statistical benefits are real but modest and depend on the measure. There is no clean evidence that switching bars by itself adds net profit, so it is a low-priority refinement.

### Cited Findings
- Library documentation states that tick, volume and dollar bars look closer to normal than time bars, and suggests dollar bars of about 1/50 of average daily dollar value. — [mlfinpy docs](https://mlfinpy.readthedocs.io/en/latest/_sources/FinancialDataStructure.rst.txt)
- BTCUSDT perpetual, 2020-2025: time-bar baselines are "a competitive reference set"; Ljung-Box serial independence is rejected for nearly all series; normality results are mixed and regime dependent. For dollar bars, a 60-minute time-bar baseline had slightly lower variance-ratio deviation at short horizons. — [Fayyaz et al. 2026, first half read](https://arxiv.org/html/2608.26158)
- In the same study, bars built from 1-minute data had lower excess kurtosis than bars built from ticks (dollar bars 23.7 versus 50.4), while tick pipelines showed better random-walk conformance. — [Fayyaz et al. 2026](https://arxiv.org/html/2608.26158)
- BTC and ETH, tick data, January 2018-June 2023: CUSUM filtering plus triple-barrier labelling beat time bars with next-bar prediction, staying positive after transaction costs. — [Grądzki, Wójcik, Lessmann 2025, abstract only](https://link.springer.com/article/10.1186/s40854-025-00866-w)
- Statistical advantages of dollar bars do not automatically translate to strategy efficacy. — [MQL5 article, VENDOR](https://www.mql5.com/en/articles/23310)

### Inferences
- The Grądzki result combines sampling and labelling, so it does not isolate the bar type. Its fee assumption is unverified.
- Dollar bars built from 1-minute klines are feasible with your data, but polling limits decisions to the next minute boundary.

### Gaps
- I did not read the machine-learning downstream section of Fayyaz et al., so its predictive comparison is not reported here.

## Do retail footprint and absorption setups have any independent verification?

### Takeaway
No. I found no independent, out-of-sample, cost-inclusive study of stacked imbalance, absorption or CVD divergence. This is absence of evidence from a limited search, not proof of no edge.

### Cited Findings
- LuxAlgo states that an imbalance describes what happened rather than what must happen next, and that imbalances pressed into a larger opposing level are routinely absorbed. [VENDOR] — [LuxAlgo](https://www.luxalgo.com/library/concept/bid-ask-imbalance/)
- ATAS provides no backtests, win rates or sample sizes for footprint patterns. [VENDOR] — [ATAS](https://learn.atas.net/volume-basics/volume-analysis/footprint-patterns)
- FootprintKit detects stacks and absorption and makes no performance claims. — [TradingView script](https://id.tradingview.com/script/c7gwEeFB-FootprintKit/)
- A paywalled January-February 2026 practitioner study covers 53,080 "toxic burst" VPIN events on Binance, Gate.io and OKX; its returns and costs were not visible. [Low quality until read] — [The Microstructure Lab](https://themicrostructurelab.substack.com/p/toxic-flow-segmentation-measuring)
- A search for fee-inclusive CVD divergence backtests found only vendor chart and definition pages. — [CoinGlass](https://www.coinglass.com/cvd/BTC); [CryptoQuant](https://cryptoquant.com/asset/btc/chart/market-indicator/futures-taker-cvdcumulative-volume-delta-90-day)

### Inferences
- These setups are typically short-horizon reads. Given the break-even arithmetic above, they are unlikely to clear 14 bps unless a large move follows, so they carry a high prior of failure at this cost level.

### Gaps
- I did not find open-source footprint backtests with code and costs. A wider GitHub search could change this.

## Which signals are statistically real versus tradable, and what are the precise rules for the best candidates?

### Takeaway
No order-flow signal here is demonstrated tradable under 14 bps taker costs and 1-minute polling. The rules below are **untested pre-registration specs written by me**, in priority order; none has a verified edge.

### Cited Findings

| Signal | Statistically real? | Tradable at 14 bps, 1-minute polling? | Basis |
|---|---|---|---|
| OFI, trade imbalance (contemporaneous) | Yes | No, describes the current move | [Cont](https://arxiv.org/abs/1011.6402); [Silantyev](https://link.springer.com/doi/10.1007/s42521-019-00007-w) |
| Book and trade features, under 3 s | Yes | No, latency and fees | [Albers](https://arxiv.org/pdf/2108.09750); [Bieganowski](https://arxiv.org/html/2602.00776) |
| Quarter-hour opening return, 10 s | Yes, out of sample | No, about 0.5 bps gross | [Quarter-Hour](https://arxiv.org/html/2607.09426v2) |
| Quarter-hour imbalance, 4-12 h | Reported, working paper | **Unknown; best candidate to test** | [Quarter-Hour](https://arxiv.org/html/2607.09426v2) |
| VPIN to volatility change | Yes, contested as mechanical | Only indirectly, as a filter | [Easley](https://stoye.economics.cornell.edu/docs/Easley_ssrn-4814346.pdf); [Andersen](https://econpapers.repec.org/RePEc:eee:finmar:v:17:y:2014:i:c:p:47-52) |
| CVD divergence, stacked imbalance, absorption | No evidence found | Unknown, low prior | Sections above |

### Inferences

**Common test rules (all candidates).** Signals use only closed bars. Enter at the next 1-minute open after the signal. Charge 14 bps per round trip plus a slippage stress at 20 bps. Fit on 2021-2023, validate on 2024, and hold out 2025 onward. Compare against a matched-time and matched-volatility random-entry placebo. Count every parameter variant tried. Require mean net return above zero at 20 bps in both validation and holdout.

**Rule 1: Slow taker imbalance, 8-hour hold (data: aggTrades, with a klines variant).**
1. At each quarter-hour boundary T, compute `OI_T = (buy qty - sell qty) / (buy qty + sell qty)` from aggTrades in [T, T+10 s), where a trade is a sell when `isBuyerMaker` is true. The window should be checked against the paper before use.
2. Klines variant: `OI_T = (2 * takerBuyBase - volume) / volume` over the 1-minute bar starting at T.
3. Standardise: `Z_T = (OI_T - trailing 30-day mean) / trailing 30-day std`, using the same quarter-hour-of-day sample only if results justify the extra parameter.
4. Long if `Z_T >= +2`; short if `Z_T <= -2`. Enter at the first 1-minute open after the window. One position at a time; ignore signals while in a position.
5. Exit by time at T + 8 hours (test 4, 8 and 12 hours, fixed in advance). No target or stop in the base test.
6. Gate: mean gross return per trade must be at least 28 bps before it merits live paper trading, which is twice the assumed round-trip cost.

**Rule 2: VPIN as a volatility regime filter (data: 1-minute klines). Not a directional signal.**
1. Each minute: `imb_i = |2 * takerBuyBase_i - volume_i| / volume_i`, and `VPIN_t = mean(imb_i)` over the last W = 50 bars (test 50 and 200, fixed in advance).
2. Percentile `P_t` = rank of `VPIN_t` in the trailing 30 days.
3. If `P_t >= 0.90`, block new mean-reversion entries in existing strategies, or halve size.
4. Compare with a baseline replacing VPIN by trailing realized volatility and by volume. Keep VPIN only if it improves net results over both, since the critique says its power may be mechanical.

**Rule 3: CVD divergence, placebo test only (data: 15-minute bars from 1-minute klines).**
1. `CVD_t = cumulative sum of (2 * takerBuyBase - volume)`.
2. Pivot high at bar k: high is the maximum of bars k-3..k+3, confirmed at k+3 (no lookahead).
3. Bearish: two consecutive pivot highs 4 to 60 bars apart, with price high2 > high1 and CVD at pivot 2 < CVD at pivot 1. Bullish is the mirror on pivot lows.
4. Enter at the open after confirmation in the divergence direction. Exit after 12 bars, matching the CoinGlass scoring window.
5. Discard unless it beats placebo entries after costs. Expect failure, consistent with earlier studies in this project that found no edge in unverified retail setups.

**Do not build for this execution profile:** OFI from book data, deep-learning LOB, and footprint or absorption scalps. OFI and LOB work at horizons you cannot reach. Footprint and absorption have no verification and need heavier data.

**Lower-cost change that matters more than any signal here.** Costs dominate these results. Albers et al. found fee regime decisive, and the literature's most positive BTC result in Bieganowski was on the maker side (annual return 2.93, though not statistically significant, p = 0.11). Testing limit-order entries may be worth more than another taker signal, but adverse selection must be simulated.

### Gaps
- All thresholds in these rules (Z of 2, W of 50, percentile of 0.90) are my starting choices, not published values.
- I have not run these backtests. This note covers literature only; the required data is available for free on Binance.
</content>
