# BTCUSDT perpetual order-block timeframe comparison — protocol

Written before running the new comparison, 2026-11-04 (Asia/Kolkata).

Question: Do 15m, 1h, or 4h internal order-block retests produce better executable results on Binance USD-M BTCUSDT perpetual futures?

## Data and separation

- Binance public monthly 1m futures candles and funding records, 2023-11 through 2026-10. Nov–Dec 2023 is warmup only.
- Development: calendar 2024; validation: calendar 2025; final evaluation: Jan–Oct 2026. Never choose exits using final-evaluation returns.
- Freeze these rules before outcomes. Report a fixed common baseline, all prespecified variants, and the rule selected on development/validation separately.
- 2026 market history was used in older Delta studies in this repo; do not describe this as a completely virgin market holdout or forward test.
- Verify SHA256 archives, timestamps, missing/duplicate minutes, OHLC invariants and funding coverage. No centered-median cleaning, no fabricated candles. Reset structure after missing minutes; evaluate only complete timeframe bars. Only bars whose close has passed may affect decisions.

## Indicator and entries

- Use the user's latest LuxAlgo SMC Pine indicator (frontend/indicators/luxalgo-smc.pine), internal length 5, swing length 50, ATR(200) high-volatility parsing, newest five active internal blocks. Both long and short. A block exists only after the confirming bar closes.
- Baseline invalidation: source-timeframe high/low mitigation at bar close, as the supplied script. Prespecified sensitivity: close mitigation.
- First actual revisit of the near edge after creation, while visible, consumes the opportunity. No 0.25% near-entry buffer. Blocks revisited while invisible are also considered no longer fresh; there is no later retry after a filtered/skipped first retest.
- Touch: signal when the 1m bar first reaches the block from outside; fill at next 1m open (market response to confirmed touch). This avoids treating a candle's pre-entry high as post-entry profit. Entry must remain outside the initial stop and occur in the next contiguous minute.
- Rejection: on that first retest's 15m candle, require a close back outside the near edge and no break of the far edge; enter at the next 1m open after the 15m candle closes. Same 15m confirmation timeframe for every OB timeframe.
- One position at a time per independently simulated variant; newest block wins simultaneous entry conflicts. No pyramiding. Prior touch consumes a block even if another position prevents execution.
- Equal start date and 200 source-bar warmup for every timeframe. Zone detection uses all available warmup history.

## Fixed exits, risk, costs

- Stop beyond far edge + 0.25 ATR(14) of the OB source timeframe, known at touch; frozen at entry. Sensitivity: 0.5 ATR buffer. Minimum initial stop distance 0.2% of fill.
- Prespecified exits: fixed 0.5R, 1R (primary), 2R, and trail activated at +1R then 1 source ATR behind the favorable extreme. Max hold 96 hours for all.
- Walk exits on 1m bars; stop wins same-minute stop/target ties; newly tightened trailing stop applies next minute; gap stops fill at worse open. End positions at data/split boundaries and report those exits.
- Risk 0.5% of current equity per trade, cap position notional at 3x equity. Report net R, profit factor, win rate, compounded risk-sized return, and minute-close mark-to-market drawdown. No claim of liquidation/exchange-perfect execution.
- Baseline fee assumption 0.05% per side, independent of unknown personal fee tier. Adverse slippage 0.02% per side. Fee on actual entry and exit notionals. Historical funding charged/credited when position spans a funding settlement. Prefer archived/API settlement mark price; otherwise explicitly label 1m futures open proxy.
- Cost sensitivity: zero costs/gross diagnostic, fee-only + funding, baseline, and 0.05% slippage per side + fees/funding. Optional low-fee case is an assumption, not claimed account pricing.

## Comparisons and uncertainty

- Grid: 3 OB timeframes × 2 entry styles × 2 mitigation rules × 2 stop buffers × 4 exits = 96 variants. No added indicator filters selected after seeing results.
- Primary comparison: touch, high/low mitigation, 0.25 ATR stop, 1R target for all three timeframes.
- Choose one rule per timeframe using only 2024+2025: minimum 40 development trades and 20 validation trades, positive mean net R in BOTH periods, then highest lower of the two period mean Rs. If none passes, say so; do not promote a failing rule based on the test period.
- Show long/short, monthly, and yearly results. No inference from win rate alone. Include sample size and fee/funding burden.
- Week-block bootstrap confidence intervals for expectancy and pairwise daily portfolio return differences; preserve calendar weeks, including inactive weeks. Use at least 2,000 resamples. These quantify sampling uncertainty, not model uncertainty.
- Null benchmark: random entries matched to entry month, side, time-of-day bucket and stop-distance distribution, with identical exit/cost rules; sequential exposure constraint and time bounds. At least 200 random portfolios per timeframe for the fixed baseline. Report one-sided empirical p-values as exploratory and adjust three baseline comparisons with Holm; do not search for a favorable null.
- A timeframe is a candidate only if the prespecified test evidence supports positive expectancy, practical drawdown and reasonable trade counts. If all lose or results are inconclusive, report that directly.

## Reproducibility and bounds

Save downloader, simulation source, tests, data manifest, all-variant CSVs, baseline trade logs/equity, summary tables and a readable report. The historical study does not modify the paper engine or submit orders. Indicator chart itself remains spot BTCUSDT; this study uses the futures contract requested by the user.
