# No Order-Flow Edge Survives Verification Yet

No volume profile or order flow strategy has verified, independent, out-of-sample evidence of beating about 0.14% round-trip on intraday BTC, so every rule below is a test specification rather than a proven system. The 80% rule, POC reversion, LVN/HVN, naked POC, anchored profiles, CVD divergence, absorption and stacked imbalance rest on vendor definitions and unaudited numbers. OFI, VPIN and fast book signals are statistically real, but they either describe the move as it happens, predict volatility instead of direction, or operate at horizons of seconds where taker fees destroy them. The single best-supported directional lead is slow taker imbalance measured at quarter-hour boundaries and held 4 to 12 hours, and even that is a gross, uncosted working-paper result of roughly 5 to 17 bps. Cost arithmetic points the same way: at realistic hit rates a 14 bps taker needs holding periods of about one hour to half a day, which rules out the scalping setups these tools are usually sold for. I recommend building one shared test harness and running, in order: quarter-hour flow, a placebo-controlled battery led by the 80% rule and naked POC, then funding fade and spot-versus-perp flow as small add-ons. VPIN should enter only as a filter on something that already passes. Prior studies in this project found no edge in level-based BTC systems, so the expected result for the level battery is null, and nothing should reach the paper-trading dashboard before clearing the gates set out below.

## Fees decide the horizon before any signal is chosen

The cost hurdle eliminates more candidates than the literature does. For a symmetric directional bet the requirement is `(2p - 1) * E|r| >= 14 bps`. Binance perpetuals show mean absolute 1-minute returns of about **5.4 to 10.9 bps** across six assets ([Quarter-Hour Effect](https://arxiv.org/html/2607.09426v2)), so even perfect 1-minute direction fails to cover the cost on average. Scaling by the square root of time, which is an approximation, a 60% hit rate needs about 41 to 168 minutes of holding and a 55% hit rate needs about 2.75 to 11 hours.

Level trades face the same arithmetic through their breakeven win rate, `(S + c) / (T + S)`:

| Target / stop | Breakeven before cost | Breakeven after 0.14% |
|---|---|---|
| 0.3% / 0.3% | 50.0% | **73.3%** |
| 0.5% / 0.5% | 50.0% | 64.0% |
| 1.0% / 1.0% | 50.0% | 57.0% |
| 1.0% / 0.5% | 33.3% | 42.7% |

The fast literature confirms the arithmetic. Across 14 BTC markets at 500 ms, book and trade features explain 10% to 37% of return variation and earn about +11,000 bps gross over two days, yet **every market loses at default fees, averaging -18,899 bps** ([Albers et al.](https://arxiv.org/pdf/2108.09750)). In a 2022-2025 walk-forward at a 3-second horizon, BTC taker returned 0.13 a year against 0.83 for buy-and-hold, with p = 0.75 ([Bieganowski and Ślepaczuk](https://arxiv.org/html/2602.00776)). The strongest-looking quarter-hour microstructure result has BTC out-of-sample AUC of 0.6035 and accuracy of 57.30%, but it is worth only about **0.5 bps per boundary** ([Quarter-Hour Effect](https://arxiv.org/html/2607.09426v2)).

Costs in the repo match the brief: `config/ob_mitigation_1h.yaml` charges 0.05% fee plus 0.02% slippage per side, which is 0.14% round-trip. `config/ema_vwap.yaml` models Delta India taker at 0.059% per side including GST, or 0.118% before slippage. The research notes did not independently verify Delta's fees or measure Binance-to-Delta basis, so a signal built on Binance data and traded on Delta needs that gap measured.

## Volume profile rules are conventions, and only placebos can test them

Only the 80% rule has a reasonably standard definition: open outside the prior value area, accept back inside for two consecutive 30-minute periods, and target the opposite edge. Even so, its source gives no stop offset and states that the figure "is a rule-of-thumb label rather than a rigorously audited statistic" ([LuxAlgo](https://www.luxalgo.com/library/concept/80-percent-rule/)). The other unaudited figures, all seen only in search snippets, are a forum backtest near **62%** ([NexusFi](https://nexusfi.com/showthread.php?t=30847&page=2)) and a social-media claim of just over **40%** on ES ([X post](https://x.com/Am_Shai/status/1680924992421396481)). All are touch rates, which ignore whether the stop was hit first. No BTC test of the rule was found.

Naked POC evidence is weaker still. A closed-source script claims 87% retest in 7 days and 95% in 90 days across 281 BTC daily POCs, with no published method (snippet only, [RVOL NPOCs](https://es.tradingview.com/script/XW2oToNA-RVOL-NPOCs)), and a vendor concedes there are "no rigorous public statistics" ([LuxAlgo](https://www.luxalgo.com/library/concept/naked-poc/)). A high retest rate is expected anyway, because recent POCs sit close to price and any near level gets revisited. HVN and LVN cut-offs vary inside a single source, from the 80th to the 90th percentile to mean plus 2 SD ([Papers With Backtest](https://paperswithbacktest.com/course/volume-profile-indicator-trading-strategies)). I found no sourced numeric rule at all for value area rejection, anchored profiles or balance breakouts.

The one academic anchor is a warning. Osler's FX work reports strong evidence that published support and resistance levels help predict intraday trend interruptions ([FRBNY](https://www.newyorkfed.org/research/epr/00v06n2/0007osle)), but rates bounced off **arbitrary levels 56.2% of the time** (snippet only, [FRBNY PDF](https://resources.newyorkfed.org/medialibrary/media/research/epr/00v06n2/0007osle.pdf)). The right benchmark for a level is therefore a random level, not 50%. Kavajecz and Odders-White tie support and resistance to resting book depth (abstract only, [RFS](https://ideas.repec.org/a/oup/rfinst/v17y2004i4p1043-1071.html)), whereas volume profile measures executed volume. I found no peer-reviewed test showing that high traded-volume levels attract or repel price. One preprint uses prior-day VAH, VAL and POC on SOL perpetuals with a current-day POC target, but its results could not be read ([Perera, SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6932998)) and it deserves a manual read.

These specifications come from the research notes rather than published rules. Common settings are a profile built from 1m bars, levels frozen at window close, 0.05%-of-price bins, a 70% value area expanded outward from the POC, and 30m confirmation bars. Fixed-dollar bins and code that accumulates volume by sorted price are both wrong for this purpose; the Papers With Backtest example does the latter.

| Strategy | Setup | Entry | Stop | Target | Assessment |
|---|---|---|---|---|---|
| **80% rule** | Window opens outside prior VA | Close of 2nd consecutive 30m close inside VA | Entry-side VA edge + 0.25 x 30m ATR | Opposite VA edge; variant 50% off at POC | Test first: largest target in the family |
| **Naked POC first touch** | POC untouched, aged 1-20 windows | Limit at level, or rejection close (both) | 0.5 x 30m ATR beyond | Fixed 1R and 2R | Test second: cleanest placebo design |
| **VA rejection** | Open inside VA; excursion beyond edge under 0.25 x ATR | 30m close back inside | Beyond extreme + buffer | POC | Low prior: small target |
| **POC reversion** | Price over 1.5 x VA half-width from prior POC; no trend trigger | 30m reversal close | 1 x 30m ATR beyond extreme | Prior POC | Low prior: fades trends |
| **HVN fade / LVN pass-through** | HVN = local peak above P80; LVN = trough below P20 of smoothed profile | HVN: rejection close at first touch. LVN: 30m close through | HVN: beyond node. LVN: back across | HVN: next LVN or POC. LVN: next HVN | Low prior: extra smoothing parameters |
| **Anchored / composite** | Anchor at swing extreme or event; composite of last 5 or 20 windows | As HVN fade at composite POC/VA edges | Same | Same | Run only if a daily-profile rule passes |
| **Balance breakout** | At least 3 windows with overlapping VAs | Two 30m closes outside composite VA | Back inside VA | 1 x composite VA width, or next NPOC | Worth a slot: the only continuation rule |

The 80% rule's geometry explains its priority. With entry 0.1W inside the value area, stop 0.1W outside and target at the far edge, where W is value area width, risk is 0.2W and reward 0.9W. Breakeven is 18% before cost, about **31% at W = 1%** and about **44% at W = 0.5%**. The result should therefore be reported by W, with a pre-set minimum width, since narrow days are where cost does the damage.

No study compares session boundaries, bin sizes or value area percentages for crypto. Test 00:00 UTC, 13:30 UTC and rolling 24h, and require the result to hold across all three, because an edge at only one boundary is probably noise.

## Order flow divides into real but untradable, and tradable but unproven

| Signal | Statistically real? | Tradable at 14 bps with 1m decisions? | Data |
|---|---|---|---|
| OFI, contemporaneous trade imbalance | Yes | No: describes the current move | Book events for OFI; klines for imbalance |
| Book and trade features under 3 s | Yes | No: latency and fees | Book and trades |
| Quarter-hour opening return, 10 s | Yes, out of sample | No: about 0.5 bps gross | aggTrades |
| **Quarter-hour imbalance, 4-12 h** | Reported in one working paper | **Unknown; best candidate** | aggTrades, or klines as a proxy |
| VPIN to volatility change | Yes, contested as mechanical | Filter only | Klines |
| CVD divergence, stacked imbalance, absorption | No evidence found | Unknown, low prior | Klines or aggTrades |

OFI has an exact definition built from best-quote updates, with an average contemporaneous R² of 65% on US stocks ([Cont et al.](https://arxiv.org/abs/1011.6402)). On BitMEX, trade flow imbalance explained contemporaneous moves better than OFI (abstract only, [Silantyev](https://link.springer.com/doi/10.1007/s42521-019-00007-w)). That is explanation of a move in progress, so it should be excluded here, particularly because true OFI requires a book-event history.

VPIN on 1m bars averages `|V_sell - V_buy| / V` over a rolling window. On BTC and four other coins it predicts the sign of changes in realized volatility with accuracy of 0.56 to 0.58 and has no power on skewness ([Easley et al.](https://stoye.economics.cornell.edu/docs/Easley_ssrn-4814346.pdf)). Andersen and Bondarenko argue its power is mechanical, stemming from trading intensity ([Finance Markets abstract](https://econpapers.repec.org/RePEc:eee:finmar:v:17:y:2014:i:c:p:47-52)), and from bulk-classification error ([Review of Finance abstract](https://econpapers.repec.org/RePEc:oup:revfin:v:19:y:2015:i:1:p:1-54.)). Binance's real taker flag sidesteps the classification critique, though I found no paper testing that on crypto. The intensity critique remains, so VPIN must beat plain realized volatility and plain volume to earn a place.

CVD divergence has a usable vendor definition: two swing highs 4 to 60 bars apart, with a higher price high and a lower CVD high, scored 12 bars later, and the vendor itself advises against trading it alone ([CoinGlass](https://www.coinglass.com/cvd/BTC)). Stacked imbalance is a convention of about 3:1 across three or more levels ([LuxAlgo](https://www.luxalgo.com/library/concept/bid-ask-imbalance/)). The leading description of absorption requires near-zero delta in one passage and "clear dominance by one side" in another, and says it "is not a forecast" ([ATAS](https://learn.atas.net/volume-basics/volume-analysis/footprint-patterns)). Any absorption test therefore rests on a definition the tester invents.

The quarter-hour paper is the exception worth pursuing. On Binance perpetuals from 2021 to October 2024, imbalance in 10-second windows at quarter-hour openings forecasts returns most strongly at 4 to 12 hours, significant at 95% in four of six contracts. A lagged-flow component is stable at **5 to 6 bps**, and a public-signal component reaches **9.8 bps at 8h and 16.9 bps at 12h** ([Quarter-Hour Effect](https://arxiv.org/html/2607.09426v2)). Three cautions apply. The effects are gross decomposition terms and may not add up. No net strategy was tested. And BTC's cumulative effect appears only in a figure, so BTC may not be one of the four significant contracts. The published magnitudes also fall short of the entry gate proposed below, so a pass requires that extreme imbalance deciles earn materially more than the average effect, which is exactly what the test should determine.

## Funding and liquidations add mechanism but almost no tradable sample

Funding is the one area where carry can materially change a contrarian trade. At the recently observed 1 bp per 8h, it barely matters. At 10 bp per 8h, a fade that receives funding would collect about 10 bps per settlement. Backtests that ignore funding therefore misstate precisely the trades that this family selects. The best open backtest I found, a student project shorting a funding z-score above 2.5 and longing below -2.5 with an 8h hold, shows Sharpe 0.771 but Calmar 0.111, 125 trades over 2020-2024 and year-by-year Calmar flipping from -0.587 in 2021 to +0.634 in 2024; it does not say whether funding is included ([Strategy-project](https://github.com/Adeline117/Strategy-project)). Its implied return of about 1.5% a year would be erased by moving from 8 to 14 bps round-trip on about 25 trades a year.

Liquidation research describes mechanism but publishes no trading results. A study of seven BTC cascades finds no event-invariant warning signal, with price precursors absent in tariff-news shocks (snippet only, [arXiv 2607.27070](https://arxiv.org/abs/2607.27070)), and two targeted searches found no event study of post-liquidation returns over minutes to hours. Binance's archive directory for USDT-M liquidation snapshots lists no symbols, and the live stream pushes at most the latest liquidation per symbol each second, so it undercounts ([Binance docs](https://developers.binance.com/docs/derivatives/usds-margined-futures/websocket-market-streams/All-Market-Liquidation-Order-Streams)). Historical tests must use open-interest drop plus range expansion as a proxy, from 5-minute metrics files available since September 2020 ([archive listing](https://s3-ap-northeast-1.amazonaws.com/data.binance.vision?delimiter=/&prefix=data/futures/um/daily/)). Open-interest research found concerns volatility rather than direction, and spot-versus-perp CVD divergence has no published test.

Combining these with levels should wait. A rule requiring a funding or cascade trigger within 0.25 ATR of a POC or value area edge shrinks an already rare sample, and it is useful only as a filter on a base signal that has already passed.

## Build one harness and run five experiments in a fixed order

The repo is close to ready. `data/binance_ob_timeframes/raw/` holds 36 months of BTCUSDT perpetual 1m kline zips and funding from November 2023 to October 2026, and those zips contain `taker_buy_volume`. However, `minutes.parquet` retains only OHLCV, so the first change is to rebuild it with taker-buy volume. No Binance aggTrades are stored locally, and no volume profile or POC code exists yet. `research/smart_zone/placebo/` already provides a frozen-protocol and placebo pattern to copy. For a strategy that passes, `src/strategy/ob_mitigation_1h.py` and `src/execution/ob1h_engine.py` show the minute-driven `on_minute` shape for wiring into `make paper`.

| Order | Experiment | Rule (specification, not evidence) | Data | Why here |
|---|---|---|---|---|
| 0 | Profile accuracy check | Build 3-6 months of daily profiles from aggTrades and from 1m OHLCV spread uniformly over high-low; compare POC, VAH and VAL error. Use 1m if median error is well below 0.05% | aggTrades, 1m | Fixes the data choice for all level tests |
| 1 | **Quarter-hour flow** | At boundary T, `OI = (buy - sell) / (buy + sell)` over [T, T+10 s), with sell when `isBuyerMaker`. Z-score over trailing 30 days. Long at Z >= +2, short at Z <= -2. Enter at next 1m open, one position at a time, exit at fixed 4h, 8h or 12h, no stop. Variants: first-minute klines `(2 * takerBuy - volume) / volume`; last-hour cumulated imbalance in top or bottom decile | aggTrades, funding | Only directional lead near the cost level; up to about 3 non-overlapping trades a day at 8h, so sample is adequate |
| 2 | **Level battery** | The seven rules above, three session boundaries, 21 base variants | 1m klines | Rich trade count and the placebo design is ready |
| 3 | Funding fade | Settled funding z over 60 days beyond 2.5, or absolute funding of at least 0.05% per 8h. Fade next bar. Exit at 8h or 24h. Charge actual funding | Funding, already local | Trivial to run, but about 25 trades a year cannot reach significance on BTC alone; replicate on ETH and SOL |
| 4 | Spot-versus-perp flow | 4h change in normalized spot delta minus perp delta beyond 2 z, with flat price. Follow spot. Exit 4h or 8h | Spot and perp klines | Plausible mechanism, no published test, cheap once taker volume exists |
| 5 | CVD divergence, VPIN filter, cascade proxy | CVD on 15m with 3-bar pivots, exit after 12 bars. VPIN over 50 or 200 1m bars, block mean-reversion entries at its trailing-30-day P90. Cascade: 5m OI drop in top 1% of trailing 90 days, range above 3x ATR, OI down at least 1%; fade after a 5m close back inside, else follow if no close inside in 15m; exit 1h or 4h; add 10 bps per side stress | Klines, metrics | Placebo-only or conditional; expect failure |

Footprint and absorption should not be built yet. They need aggTrades processed at price level and they have no verification. If the aggTrades pipeline exists after experiment 1, one fixed test is cheap: on 15m footprints with a 3:1 same-price ratio across three or more 0.05% bins, follow the stack and exit after 4h. Treat that as a late, low-prior slot, because the comparison direction (diagonal or same-price) is a platform setting with no authoritative answer. OFI and deep-learning book models should be dropped for this execution profile.

### The acceptance gates must be written down before the first run

The gates below are a recommended judgment. The published anchors are the t > 3 hurdle ([Harvey, Liu and Zhu](https://nber.org/papers/w20592)) and PBO as a method ([Bailey et al.](https://papers.ssrn.com/abstract=2326253)). The sources disagree on a PBO cutoff.

| Gate | Threshold |
|---|---|
| Net edge | Mean net trade above 0 at 14 bps plus actual funding, and still above 0 at 20 bps |
| Quarter-hour flow entry bar | Gross of at least 28 bps per trade before paper trading |
| Significance | Net t of at least 3.0 with block-bootstrap or HAC errors; Bonferroni about 3.5 for 100 variants, 3.8 for 378 |
| Selection | DSR of at least 0.95 at true trial count; PBO below 0.25 preferred, reject at or above 0.50 |
| Sample | At least 300 non-overlapping trades; 100 is "tentative" only |
| Stability | Positive in at least 70% of walk-forward folds and in each of 2023, 2024, 2025 and 2026 year-to-date |
| Fragility | Positive after removing the best 1% of trades; neighboring parameters also positive |
| Placebo | Above the 95th percentile of at least 1,000 placebo runs |
| Forward | At least 3 months or 50 paper trades, with slippage inside the assumption |

For levels, placebos should be matched on distance from price and age, and should include a shifted-profile version using another day's profile. For event signals, use random entries matched on hour, volatility and side. All signals must use closed bars and next-bar-open fills, and same-minute stop-and-target conflicts should count as failures, as in the Smart Zone protocol. The experiments above come to about 40 to 50 pre-registered variants, which implies a Bonferroni hurdle near t = 3.3 by my calculation. Volatility, trend and session filters multiply that count, and no source showed out-of-sample benefit from them on order flow or volume levels, so apply them only to base signals that pass.

Period design needs one correction to the notes. Local data starts in November 2023, so a 2021-2023 development period requires downloading more. The quarter-hour paper's sample ends in October 2024, so **November 2024 to October 2026 is genuinely unseen by those authors** and forms the most valuable test here. Use 2021-2023 for fitting, 2024 for validation, 2025 through early 2026 as a further check, and touch the final 6 to 12 months once. For the level battery, reuse the Smart Zone split of 2024-01 to 2025-06 for development and 2025-07 to 2026-10 for holdout, with the caveat from its protocol that 2026 is not market-virgin ([PROTOCOL](/Users/ajaybaburaj/Documents/ajay/crypto/research/smart_zone/placebo/PROTOCOL.md)).

Live feed access needs a direct check. Public Binance futures endpoints returned HTTP 200 from an Indian IP on 2026-11-10, but users reported HTTP 451 from GCP in 2022 ([Binance forum](https://dev.binance.vision/t/google-cloud-and-ip-restriction-451-on-fapi-binance/13820)), and asia-south1 was not tested. Run `curl -i https://fapi.binance.com/fapi/v1/time` from the VM before planning any perp-fed job there. Do not engineer around a block, since IP workarounds can conflict with Binance's terms. Also note the existing OB1h paper engine reads spot data, whereas the quarter-hour evidence comes from perpetuals.

## Conclusion

The useful shift is from asking which volume tool works to asking what a 14 bps taker can afford. That constraint leaves slow flow signals held for hours, and level trades with wide targets; it excludes nearly everything footprint and scalping education is built around. Since this project has already rejected order-block, S/R-zone and trend-flip families, a null on the level battery would add little new information, whereas a quarter-hour flow test on two post-sample years is an original result either way.

Fee regime may matter more than any signal in this report: fee tier was decisive in Albers et al., and Bieganowski's best BTC result was maker-side (annual return 2.93, not significant at p = 0.11). Limit-order execution is the most promising follow-up, but it needs adverse selection simulated, which bar data cannot do. The important unknowns are specific and answerable: the unread [Perera](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6932998) and [Vafin](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6938742) SSRN papers, BTC's own panel in the quarter-hour figure, and the OHLCV-versus-trades profile error measured in step 0. All thresholds here remain untested starting choices, and my literature search was limited, so the missing evidence is not proof that no edge exists.
