# BTCUSDT perpetual: which order-block timeframe (15m / 1h / 4h) works best?

Protocol: [ob_timeframe_protocol.md](ob_timeframe_protocol.md), written before the runs. Outputs: `data/reports/ob_timeframes/`. Reproduce with `python scripts/research_ob_timeframes.py` (needs `PYTHONPATH=src`).

## Answer

**None of the three timeframes has a tradable edge after costs. 4h is the least bad, and it is only "least bad", not profitable.**

| 2026 test (Jan–Oct), 1R target, 0.5% risk, fees 0.05% + slippage 0.02% per side, funding | 15m | 1h | 4h |
|---|---|---|---|
| Trades | 988 | 320 | 71 |
| Win rate | 48.1% | 47.2% | 50.7% |
| Mean net R / trade | **−0.36** | **−0.24** | **−0.06** |
| 95% CI of mean R (week bootstrap) | −0.42 … −0.30 | −0.34 … −0.13 | −0.31 … +0.19 |
| Portfolio return | −83.5% | −32.1% | −2.3% |
| Max drawdown | −83.5% | −32.7% | −7.1% |

- 15m and 1h are clearly negative: their CIs exclude zero, and the result is the same in development (2024) and validation (2025).
- 4h is statistically indistinguishable from zero (CI −0.31…+0.19, only 71 trades). Do not read it as "4h works".
- Paired daily-return difference (2026): 4h beats 1h by ~12 bps/day (CI 6–18) and 15m by ~58 bps/day. That ranking is real, but it is a ranking of losers.

## Where the loss comes from: costs, not the signal

Gross (no fees, no slippage, no funding), 2026:

| | 15m | 1h | 4h |
|---|---|---|---|
| Gross mean R | +0.018 | −0.025 | +0.041 |
| Fees + funding only | −0.258 | −0.182 | −0.023 |
| Baseline (fees + slippage + funding) | −0.361 | −0.240 | −0.063 |
| Stress (0.05% slippage) | −0.522 | −0.311 | −0.080 |
| Assumed low-fee (0.02% fee) | −0.200 | −0.148 | −0.025 |

Gross expectancy is about zero at every timeframe: the order block gives no directional information. Tighter stops on 15m mean fees eat a larger share of each R (0.27R per trade on 15m vs 0.06R on 4h), so shorter timeframes are punished most. Even with an assumed 0.02% fee, all three are still negative.

## Random-entry check

Random entries matched on month, side, 4h clock bucket and risk, with the same exits and costs (250 portfolios each, 2026):

| | Observed R | Random mean R | Random 95th pct | Holm p |
|---|---|---|---|---|
| 15m | −0.361 | −0.386 | −0.334 | 0.69 |
| 1h | −0.240 | −0.209 | −0.121 | 0.71 |
| 4h | −0.063 | −0.107 | +0.105 | 0.71 |

The OB retest is **not better than random entries** at any timeframe. On 1h it is slightly worse than random (not significant).

## Prespecified selection (development 2024 + validation 2025 only)

96 variants were tested (timeframe × touch/rejection × wick/close mitigation × 0.25/0.5 ATR stop × 0.5R/1R/2R/trail).

- **0 of 96 had positive mean R in both 2024 and 2025.** Per the protocol, no rule is promoted for any timeframe (`selected.json` is all null).
- 4h variants looked positive in 2024 (e.g. rejection, 0.5 ATR, 1R: +0.18R on ~53 trades), then flipped negative in 2025 (−0.45R). That is the typical pattern of noise on small samples.
- 14 variants were positive in 2026 (all of them 4h; every 15m and 1h variant was negative), but they failed the validation filter, and choosing them now would be selecting on the test period. Not a finding.
- Rejection entries beat touch entries on 15m, but both are strongly negative. On 1h, touch beats rejection in 2026; in 2025 rejection had a few positive variants (2R/trail). None survived both periods.

## Compared with the earlier Delta study in this repo

The earlier 1h/4h-OB + 15m-rejection + EMA200 + ADX filter result (81.6% win rate at 0.5R, thin edge) is a different strategy with extra filters and a different venue and data. This study used no filters, so the two do not contradict each other, but this study gives no support for the unfiltered OB retest. The prior result remains the only lead, and it still needs an out-of-sample test with the same cost model.

## Data and checks

- Binance USD-M BTCUSDT 1m candles + funding, Nov 2023 – Oct 2026 (first two months warmup), 0 missing minutes after repair. One missing archive day (2026-10-28) was repaired from the REST API (sha256 recorded in `audit.json`).
- Indicator logic matches the Pine script on prefixes of 1000 bars and the full history at all timeframes and both mitigation rules (`indicator_parity.json`, 18/18).
- Execution tests pass (`tests/test_ob_timeframes.py`, 11 tests): confirmation timing, same-minute stop/target, trailing, funding, data gaps.

## Caveats

- 2026 data was seen in earlier repo studies, so the test period is not a virgin holdout.
- One symbol, one indicator parameter set (as supplied), one 0.5% risk level. The bootstrap CIs quantify sampling noise only, not model uncertainty.
- The simulation assumes market fills at the next 1m open and does not model order-book depth or liquidation.
- The 4h sample (71 trades) is too small to rule out a modest edge; it is only enough to say there is no evidence of one.

## Suggested next step

Stop trying to trade the raw OB retest on any timeframe. If you want to keep exploring, test the filtered 1h/4h-OB + 15m-rejection strategy on this same Binance data with these costs and the protocol's split, so the comparison is like-for-like.
