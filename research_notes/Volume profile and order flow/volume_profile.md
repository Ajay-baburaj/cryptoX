# Volume Profile / Market Profile Strategies for Intraday BTC and Crypto

Source-quality labels: [ACADEMIC] peer-reviewed or central-bank research. [PREPRINT] arXiv/SSRN. [TRADE] trade-magazine. [VENDOR] vendor, course, indicator seller or prop-firm content (low quality). [FORUM] forum or social post (low quality).

Access limits: several key pages could not be opened (403/404 or unreadable). Where a figure comes only from a search-result summary and the page itself was not read, it is marked [SNIPPET ONLY]. Those figures should be checked before being quoted as fact.

## What are the exact rules for each strategy?

### Takeaway
Only the 80% rule has a reasonably standard published definition, and even that lacks stop offsets. All the others are described qualitatively in the sources found, so the numeric rules below are my own specifications for testing, not established rules.

### Cited Findings
- **80% rule (value-area rule).** Map the prior session's VAH, VAL and POC. Today must open outside the prior value area. Wait for re-entry and acceptance, classically two consecutive 30-minute periods inside. Target the opposite value-area boundary, with the prior POC as a common scale-out. Stop goes back outside the entry-side boundary, with no offset given. A quick re-exit on the entry side invalidates the setup. [VENDOR] — [LuxAlgo, 80% Rule](https://www.luxalgo.com/library/concept/80-percent-rule/)
- Practitioners typically restrict the 80% rule to regular-trading-hours value areas, and thin overnight sessions produce more false re-entries. BTC has neither an RTH session nor a true overnight. [VENDOR] — [LuxAlgo, 80% Rule](https://www.luxalgo.com/library/concept/80-percent-rule/)
- **Naked (virgin) POC.** A prior session's POC that price has not traded back through since that session ended. The first return is watched for a bounce or fade. The stop goes just beyond the level, with no fixed distance given. Open NPOCs in the direction of a breakout from balance serve as targets or scale-outs. Straight acceptance through the level with no reaction means it is no longer special. [VENDOR] — [LuxAlgo, Naked POC](https://www.luxalgo.com/library/concept/naked-poc/)
- **HVN/LVN thresholds vary by example** within a single source: above the 90th percentile of per-level volume; above mean + 2 SD (day trading); above the 80th percentile for HVN and below the 20th for LVN (swing). Entries are qualitative, such as entering when price revisits an HVN after a breakout, or when price approaches the POC on rising volume. [VENDOR] — [Papers With Backtest course](https://paperswithbacktest.com/course/volume-profile-indicator-trading-strategies)
- **POC reversion.** Described as POC acting as a magnet, with mean-reversion trades looking for exhaustion in low-volume areas away from it. The article's headline 162% to 223% return claim could not be assessed (asset, period and fees not seen). [VENDOR] [SNIPPET ONLY] — [Medium/Codex](https://medium.com/codex/the-institutional-edge-how-we-boosted-a-strategys-return-from-162-to-223-with-one-indicator-eef74cadae91)
- **Prior-day level mean reversion in crypto perps.** One paper uses previous-day VAH, VAL and POC as entry context, the current day's POC as profit target, and a "Tape Speed" confirmation indicator. [PREPRINT] [SNIPPET ONLY] — [Perera, SSRN 6932998](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6932998)
- A value area is taken as the range holding 70% of volume. — [Papers With Backtest course](https://paperswithbacktest.com/course/volume-profile-indicator-trading-strategies). That source's code accumulates volume over rows sorted by price rather than expanding outward from the POC, so it should not be reused for value-area levels.

### Inferences
These are my proposed test specifications. None is sourced as an established rule. Common definitions: profile built from 1m bars, levels frozen at window close (no lookahead), bin = 0.05% of price, VA = 70% expanded outward from POC, cost 0.14% round trip, 30m bars for confirmation.

| Strategy | Setup | Entry | Stop | Target |
|---|---|---|---|---|
| 80% rule | Window open outside prior VA | Close of 2nd consecutive 30m bar closing inside VA | Entry-side VA boundary plus 0.25 x 30m ATR | Opposite VA boundary (variant: 50% off at POC) |
| VA rejection | Open inside VA; price trades beyond VAH/VAL by under 0.25 x ATR | 30m close back inside VA | Beyond the excursion extreme plus buffer | POC |
| POC reversion | Price more than 1.5 x VA half-width from prior POC, with no trend filter triggered | 30m reversal bar close | 1 x 30m ATR beyond extreme | Prior POC |
| HVN fade / LVN pass-through | HVN = local peak above 80th percentile; LVN = local trough below 20th, from smoothed profile | HVN: rejection close at first touch. LVN: 30m close through it | HVN: beyond node. LVN: back across it | HVN: next LVN or POC. LVN: next HVN |
| Naked POC first touch | POC untouched, aged 1-20 windows, older ones dropped | Limit at level or rejection close (test both) | 0.5 x 30m ATR beyond | 1R and 2R fixed |
| Anchored / composite | Anchor at swing extreme or major event; composite = last 5, 20 windows | Same as HVN fade at composite POC/VA edges | Same | Same |
| Balance-to-imbalance | At least 3 windows with overlapping VAs | Two consecutive 30m closes outside the composite VA (acceptance) | Back inside VA | 1 x composite VA width, or next NPOC |

Breakeven win rate for a trade with target T, stop S and cost c is (S+c)/(T+S). With c = 0.14%:

| Target / stop | Breakeven before cost | Breakeven after 0.14% |
|---|---|---|
| 0.3% / 0.3% | 50.0% | 73.3% |
| 0.5% / 0.5% | 50.0% | 64.0% |
| 1.0% / 1.0% | 50.0% | 57.0% |
| 1.0% / 0.5% | 33.3% | 42.7% |

So the rule-of-thumb targets (POC from the VA edge, often a fraction of one day's range) are the ones cost hurts most.

### Gaps
- No sourced numeric rules were found for VA rejection, LVN/HVN entries, anchored or composite profiles, or balance-to-imbalance breakout. Dalton's and Steidlmayer's books were not consulted directly, and they are the likely primary source for the structural definitions.
- No source specified a stop buffer for the 80% rule.

## What parameters are used (window, session boundary, VA %, bins, confirmation)?

### Takeaway
70% value area and 30-minute acceptance are the conventions. There is no evidence-based answer for the session boundary on 24/7 crypto, or for bin size.

### Cited Findings
- Value area is commonly 70% of activity. — [Papers With Backtest course](https://paperswithbacktest.com/course/volume-profile-indicator-trading-strategies). Some implementations use about 68%, tied to one standard deviation. [FORUM] [SNIPPET ONLY] — [NexusFi thread](https://nexusfi.com/showthread.php?t=30847&page=2)
- Acceptance is classically two consecutive 30-minute periods; some traders judge it by time and volume built instead. [VENDOR] — [LuxAlgo, 80% Rule](https://www.luxalgo.com/library/concept/80-percent-rule/)
- One published example uses a fixed `price_interval=1.0` bin and recommends no bin size for any setup; lookback is left to optimisation. [VENDOR] — [Papers With Backtest course](https://paperswithbacktest.com/course/volume-profile-indicator-trading-strategies)
- NPOCs are commonly down-weighted or dropped after a few months, and levels from high-volume sessions are weighted most. [VENDOR] [SNIPPET ONLY] — [LuxAlgo, Naked POC As Level](https://www.luxalgo.com/library/concept/naked-poc-as-level/)

### Inferences
- The 00:00 UTC boundary is the natural default because daily candles and many crypto tools use it, but this is my reasoning. Treat the boundary as a parameter (00:00 UTC, 13:30 UTC US cash open, rolling 24h) and require the result to hold across all of them. An edge that exists at only one boundary is probably noise.
- Percentage-based bins suit BTC better than fixed-dollar bins, because BTC's price has changed by multiples across a multi-year sample.

### Gaps
- I found no study comparing session boundaries, bin sizes or VA percentages for crypto.
- A search summary noted that crypto volume is spread across venues, so one exchange's profile shows only part of the market. It is plausible, but I could not tie it to a specific page, and I found no measurement of how much profiles differ between venues.

## What evidence exists after costs?

### Takeaway
I found no independent, out-of-sample, cost-inclusive test of any volume-profile strategy on BTC. The count of strategies shown to survive 0.14% round trip is zero, and that reflects missing evidence rather than a demonstrated failure: the evidence cannot say.

### Cited Findings
| Source | Quality | Market / period | Sample | Costs | Net / win rate | OOS |
|---|---|---|---|---|---|---|
| [Perera, SSRN 6932998](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6932998) | [PREPRINT] [SNIPPET ONLY] | SOL/USDT perp, Binance, 5 years | Not seen | Keywords mention transaction cost analysis | Not seen (page returned 403) | Not seen; keywords mention Monte Carlo |
| [Drinka, Ptasienski & Humes, S&C V.6:12](https://store.traders.com/-v06-c12-mktprof-pdf.html) | [TRADE] [SNIPPET ONLY] | 12 futures markets, three-month window | Day-structure tabulation | None; not a trading test | Some markets, notably CBOT corn, agreed with Steidlmayer's observations | No |
| [Medium/Codex](https://medium.com/codex/the-institutional-edge-how-we-boosted-a-strategys-return-from-162-to-223-with-one-indicator-eef74cadae91) | [VENDOR] [SNIPPET ONLY] | Not seen | Not seen | Not seen | 162% to 223% headline | Not seen |

- The Papers With Backtest volume-profile course reports no volume-profile backtest at all, and no costs for the other strategies it mentions. — [Papers With Backtest course](https://paperswithbacktest.com/course/volume-profile-indicator-trading-strategies)
- A 2026 preprint finds short-horizon crypto mean reversion averaging AUC 0.531, with 98% of pairs above 0.5 on 15-minute out-of-sample tests. It is not POC-specific, and an AUC this small says nothing about clearing 0.14%. [PREPRINT] [SNIPPET ONLY] — [arXiv 2608.21888](https://arxiv.org/pdf/2608.21888)
- Published claims that could not be traced to any study: a 2020 *Journal of Futures Markets* result that imbalanced profiles preceded continuation 63% of the time, and a Dalton attribution that price returns to the prior day's POC about 80% of the time. Both came from search summaries of vendor guides, and I could not verify either exists as described.

### Inferences
- A revisit or touch statistic is not a trade result. It ignores whether the stop was hit first and ignores cost.
- Prior work here (no edge in order-block or S/R-zone variants) raises the bar: the prior for a discretionary level-based intraday rule clearing 0.14% is low until a local test shows otherwise.

### Gaps
- Perera's actual results are unknown; the SSRN page was blocked and a follow-up search found no other copy. It should be read manually, and it covers SOL rather than BTC.
- No failed replications with published code were found for BTC. The absence probably reflects few rigorous tests being published, but I cannot rule out sources my searches missed (about 20 queries; journal databases not directly searched).

## Do high-volume price levels act as support/resistance or attract price (academic evidence)?

### Takeaway
There is real but modest academic evidence that some support/resistance levels matter intraday, mostly in FX. I found no peer-reviewed test that high traded-volume levels specifically act as S/R or attract price.

### Cited Findings
- Osler (FRBNY, 2000) tested levels published by six FX firms and reports "strong evidence" they help predict intraday trend interruptions. [ACADEMIC] — [FRBNY EPR](https://www.newyorkfed.org/research/epr/00v06n2/0007osle)
- From summaries of that paper: 1996-98 minute quotes; rates bounced off arbitrary levels 56.2% of the time on average, with published levels doing better; predictive power lasted at least five business days; firms did not agree much with each other. [ACADEMIC] [SNIPPET ONLY] — [FRBNY PDF](https://resources.newyorkfed.org/medialibrary/media/research/epr/00v06n2/0007osle.pdf)
- Kavajecz & Odders-White (RFS 2004): support and resistance levels coincide with peaks in limit-order-book depth, and the relationship stems from technical rules locating depth already on the book. [ACADEMIC] [SNIPPET ONLY, abstract] — [RFS 17(4)](https://ideas.repec.org/a/oup/rfinst/v17y2004i4p1043-1071.html)
- Osler (JF 2003) offers a microstructure explanation for S/R predictive power and for unusually rapid trends after levels are crossed, drawing on order clustering at round numbers. [ACADEMIC] [SNIPPET ONLY] — [JF 58(5)](https://ideas.repec.org/a/bla/jfinan/v58y2003i5p1791-1819.html)
- Chung & Bellotti (2021): an algorithm's intraday S/R levels reverse trends at a statistically significant rate, prior bounces raise bounce probability, the probability decays over time, and AR(1) processes do not explain the levels. The abstract does not address volume or trading profit. [PREPRINT] — [arXiv 2101.07410](https://arxiv.org/abs/2101.07410)
- A summary page describes the S/R evidence as sparse, mixed and weak, says small effects do not survive costs and fade out of sample, and notes that with many candidate levels some overlap price by chance. It reports no data of its own and its Osler citation looks wrong, so treat it as low quality. [VENDOR] — [Prop Ledger](https://prop-ledger.org/learn/paper/support-and-resistance-is-there-statistical-evidence-that-prior-levels-change-pr)
- Steidlmayer-derived Auction Market Theory is described as empirical rather than derived from theory. [SNIPPET ONLY] — [Scribd, Auction Market Theory](https://www.scribd.com/doc/55884921/Auction-Market-Theory)

### Inferences
- Osler's 56.2% bounce rate at arbitrary levels is the key lesson: a level-based result must beat random levels, not 50%. The project's placebo framework is the right test.
- Kavajecz & Odders-White tie S/R to resting depth. Volume profile measures executed volume, which is a different quantity. Whether past traded volume predicts future resting depth is untested in anything I found.

### Gaps
- A search summary said high-volume S/R zones "exhibit significantly longer lifetimes", but its attribution was unclear and I could not locate the paper. Do not use it.
- A stock-market paper, "Use of the volume profile in making investment decisions on the stock market", exists on [ResearchGate](https://www.researchgate.net/publication/398683237_Use_of_the_volume_profile_in_making_investment_decisions_on_the_stock_market), but it returned 403, so results are unknown.
- Chung & Bellotti's full text could not be parsed, so instruments, sample and effect sizes are unreported here.

## Is the 80% rule's claimed hit rate independently verified?

### Takeaway
No. I found no verified, reproducible study. Unaudited figures range from about 40% to 80%, and even a vendor that sells the concept calls 80% a rule-of-thumb label.

### Cited Findings
- "The figure is a rule-of-thumb label rather than a rigorously audited statistic", and "Backtests on modern electronic sessions often find lower completion rates." [VENDOR] — [LuxAlgo, 80% Rule](https://www.luxalgo.com/library/concept/80-percent-rule/)
- A forum user reported a TradeStation backtest with completion closer to 62%. [FORUM] [SNIPPET ONLY; page returned 403] — [NexusFi thread](https://nexusfi.com/showthread.php?t=30847&page=2)
- A 2023 social post claimed the ES figure was slightly above 40%, with no methodology. [FORUM] [SNIPPET ONLY] — [X post](https://x.com/Am_Shai/status/1680924992421396481)
- A forum post suggests the "80%" label may relate more to the value-area framework than to tested win rates. [FORUM] [SNIPPET ONLY] — [NexusFi thread](https://nexusfi.com/showthread.php?t=30847&page=2)

### Inferences
- The rule's completion rate is touch-based, so it overstates a tradeable win rate. A stop near the entry-side boundary can be hit before the far side is reached.
- Worked example (illustrative): entry 0.1W inside the VA, stop 0.1W outside, target the far edge (W = VA width). Risk is 0.2W and reward 0.9W, so breakeven is 18% before cost. At 0.14% cost it is about 31% for W = 1% and about 44% for W = 0.5%. The tight stop would lower the real win rate well below the touch rate, so these thresholds are not as easy as they look.

### Gaps
- Two further figures appeared in search summaries without a linked source: "67% accuracy in independent testing" and "72% revisit probability for ES 2018-2024". Neither has a published method, and I could not attribute them to a page.
- No BTC-specific test of the 80% rule was found.

## Naked POC retest statistics

### Takeaway
The only number found is unaudited marketing copy, and a high revisit rate is expected even without any effect.

### Cited Findings
- A closed-source TradingView script claims 95% retest within 90 days and 87% within 7 days, from 281 POCs on BTC daily, 2018-2024. No method published. [VENDOR] [SNIPPET ONLY; page returned 404 on fetch] — [RVOL NPOCs](https://es.tradingview.com/script/XW2oToNA-RVOL-NPOCs)
- "No rigorous public statistics on fill rates or reaction quality", and public claims rest on "anecdote and cherry-picked examples." Many NPOCs never trade again, especially after strong one-directional trends. [VENDOR] — [LuxAlgo, Naked POC](https://www.luxalgo.com/library/concept/naked-poc/)

### Inferences
- Prior-day POCs lie near current price, so a random walk would revisit most of them within days. The relevant test compares NPOC revisit and reaction rates against placebo levels at the same distance and age.

### Gaps
- No independent NPOC reaction or trade-outcome statistics were found.

## Can profiles from 1m OHLCV approximate those from trades?

### Takeaway
Probably well enough for POC at the bin widths proposed here, based on one unaudited ES study. No crypto-specific error estimate exists, so it should be measured directly from aggTrades.

### Cited Findings
- An E-mini S&P 500 comparison over 1,088 trading days found no VPOC difference between tick and 1-minute data on about 30% of days, and a difference of two ticks or less on 68.2% of days. The authors concluded minute-based profiles seem accurate enough. Disagreement arises when two volume peaks are of similar height. [VENDOR] [SNIPPET ONLY; two direct fetches of the page did not show this text] — [ABC Trading Group](https://www.abctradinggroup.com/services/research/)
- A NinjaTrader user reported matching VPOCs on ES, YM and NQ but a large mismatch on RTY, so results vary by instrument. [FORUM] [SNIPPET ONLY] — [NinjaTrader forum](https://forum.ninjatrader.com/forum/ninjatrader-8/platform-technical-support-aa/1186369-orderflowvolumeprofile-minute-tick)
- Historical and live profiles can differ in POC and value area because of how data loads. [FORUM] [SNIPPET ONLY] — [NinjaTrader forum](https://forum.ninjatrader.com/forum/ninjatrader-8/platform-technical-support-aa/1288975-inconsistent-loading-of-historic-volume-profile)
- Lower-timeframe bars let volume be spread only across the prices each bar touched. Buy/sell splits from OHLCV remain estimates. [VENDOR] [SNIPPET ONLY] — [TradingView, Intrabar Volume Profile](https://id.tradingview.com/script/lx7yTFiR-Intrabar-Volume-Profile-Order-Flow/)

### Inferences
- ES has a 0.25-point tick, so two ticks is 0.5 points, which is small relative to a daily range. The 32% of days with larger differences likely include bimodal days where the POC jumps between peaks, and those are the days when a single POC level is least meaningful.
- Value-area edges depend on cumulative volume, so they should be less sensitive than the POC to single-bin noise. This is untested in my sources.
- A cheap local check: for 3-6 months of BTCUSDT, build the daily profile from aggTrades and from 1m OHLCV (uniform across high-low), then report the distribution of POC, VAH and VAL error as a percentage of price and of the 0.14% cost. If median error is well below 0.05%, 1m is adequate for long tests.

### Gaps
- No quantified OHLCV-versus-trades error for BTC or any crypto was found.

## What distinguishes volume-profile levels from the order-block and S/R zones already rejected here?

### Takeaway
The input data differs, since volume profile uses executed volume at price rather than swing or candle patterns. There is no evidence that this difference produces an edge, so it remains a hypothesis to test with the same placebo design.

### Cited Findings
- The project's Smart Zone Pro study found no out-of-sample edge on BTC (Binance BTCUSDT perp 2023-11 to 2026-10) across 5,600+ variants, with zones no better than width-matched placebo levels. Its Pine source is protected, so it tested reconstructions from the description. — Local project memory, `smart-zone-pro-study.md`; report at `reports/Smart Zone Pro BTC backtest.md`
- A repository search of `research/` and `src/` found no existing volume-profile or point-of-control code, so these levels have not been tested in this project. — Local search of the project, 2026-11-10
- Kavajecz & Odders-White link S/R to peaks in book depth, not to traded volume. [ACADEMIC] [SNIPPET ONLY] — [RFS 17(4)](https://ideas.repec.org/a/oup/rfinst/v17y2004i4p1043-1071.html)

### Inferences
Possible real differences:
- Levels are computed from a mechanical, parameter-light rule (fewer degrees of freedom than zone heuristics, though bins, windows and VA % still add some).
- The levels carry a positioning rationale: heavy trading at a price implies many participants with entries there. This is a plausible story, not a finding.
- The levels update on a fixed schedule, which makes a clean placebo design straightforward.

Reasons to expect the same null result:
- Same structural trade as the failed studies: intraday fade at a level with a small target against 0.14% cost.
- The POC sits inside the recent range and close to price, so a touch happens often by construction.
- Touch-based hit rates are the same statistic that misled in earlier level studies.

Recommended test design, reusing the Smart Zone placebo approach:
1. Placebo levels matched on distance from price and on age, plus a shifted-profile placebo (prior profile from a different day, rescaled to the same distance).
2. Pre-register a small grid: three session boundaries, one bin size, 70% VA, and the seven rules above.
3. Split development and validation by period; correct for multiple testing; evaluate at 0.14% round trip.

### Gaps
- Whether Smart Zone Pro's reconstructions used volume at all was not checked here. If they weighted zones by volume, the distinction narrows.
