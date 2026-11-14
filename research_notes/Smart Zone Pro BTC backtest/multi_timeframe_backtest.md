# Smart Zone Pro [Abusuhil] on BTC: multi-timeframe backtest (HTF zones, LTF rejection triggers)

All results are from this study's own code and output files, under `research/smart_zone/mtf/` in the repo. R values are mean net R per trade after base costs unless stated. Links are local paths.

## What data, costs and indicator assumptions does the test rest on?

### Takeaway
The primary data is 3 years of gap-free Binance BTCUSDT perp 1m bars, with Delta BTCUSD 2026 used only as a gappy replication. The zone engine is an independent approximation built from the written description, because the Pine source is unavailable, so results describe this reconstruction and not the exact indicator.

### Cited Findings
- Primary data: Binance USD-M BTCUSDT perp, 1,578,240 1m bars, 2023-11-01 00:00 to 2026-10-31 23:59 UTC, no missing or duplicate minutes, with funding records for the same range — [minutes.parquet](../../data/binance_ob_timeframes/minutes.parquet); [funding.parquet](../../data/binance_ob_timeframes/funding.parquet).
- Replication data: Delta BTCUSD 1m, 2026-01-01 to 2026-10-26, 334,821 bars. Gaps include 2026-06-01 to 06-30 (30 days), 07-27 to 07-31 (5 days), 09-02 to 09-30 (29 days), plus 03-20 and 05-11 (1 day each) and shorter outages — [BTCUSD_1m parquet](../../data/parquet/BTCUSD_1m_20260101_20261026.parquet).
- Splits, frozen in code before any outcome was computed: warmup Nov-Dec 2023, train 2024, validation 2025, test 2026-01-01 to 2026-10-31. The development script truncates data at 2025-12-31, so test bars were not loaded during selection — [config.py](../../research/smart_zone/mtf/config.py); [run_dev.py](../../research/smart_zone/mtf/run_dev.py).
- BTC path by split (first to last close): 2024 42,332 to 93,549; 2025 93,600 to 87,608; 2026 87,615 to 77,523 — [minutes.parquet](../../data/binance_ob_timeframes/minutes.parquet).
- Base costs: 0.05% taker + 0.02% slippage per side, plus historical Binance funding. This matches the repo's `fee_per_side: 0.0005` and `slippage_per_side: 0.0002` — [ob_mitigation_1h.yaml](../../config/ob_mitigation_1h.yaml). Scenarios: with 18% GST on fees (0.079% per side), maker entry (0.02% entry, 0.07% exit), and zero cost — [config.py](../../research/smart_zone/mtf/config.py).
- Assumptions where the description is silent: pivot 5/5; cluster join within 0.5 x min(pivot ATR, zone average ATR) of the cluster mean; recency decay tau 150 HTF bars; 500-bar pivot lookback; flip minimum gap 5 bars; flip bonus 0.5; minimum 2 pivots per zone; touches counted as pivots only; floor width 0.1 ATR; no invalidation on a close through the zone; wick depth 10%-100% of zone width; close margin 0.1 x LTF ATR; stop 0.25 zone ATR beyond the far edge; minimum stop 0.2% of price; 96h time stop; trail activates at +1R and trails 1 HTF ATR — [config.py](../../research/smart_zone/mtf/config.py).
- Strength formula (an assumption): sum of exp(-age/tau) x (0.5 + 0.5 x min(average reaction, 2)) + flip bonus; display = strength x (1 - 0.3 x width / max width) — [engine.py](../../research/smart_zone/mtf/engine.py).
- Lookahead controls: a zone snapshot applies only to LTF bars opening at or after the HTF close, and entry is the next 1m open after the trigger bar closes. Five tests pass: snapshot truncation (1h/4h/1D), signal truncation and availability (4h/15m, 1h/5m, 1D/1h), a future-price-spike invariance test, stop-first tie handling, and flip/Mixed classification — [test_no_lookahead.py](../../research/smart_zone/mtf/test_no_lookahead.py).

### Inferences
- The strength scale is invented, so the star and min-strength cutoffs are not guaranteed to select the same zones the TradingView indicator draws.
- The 2026 test window is unseen for this indicator but is not a virgin market period. The user's earlier studies used the same months.

### Gaps
- The engine was not compared against zones on the user's TradingView chart, because the Pine source and chart zone exports were not available.
- 1D zones have only about 2 months of warmup at the start of 2024, so their 500-bar lookback is only partly filled early in train.
- The maker-entry scenario assumes a fill at the next 1m open at maker fee. Real maker fill rates and adverse selection were not modelled, so it is an upper bound.

## Which zone/trigger combinations have positive expectancy after costs?

### Takeaway
None does in any way that holds up. Unfiltered Balanced results on the 2026 holdout were negative in 39 of 40 combination/exit cells, and gross expectancy is close to zero, so costs produce most of the loss.

### Cited Findings
- 2026 test, Balanced preset, no filter, mean net R by exit — [all_variants_all_periods.csv](../../research/smart_zone/mtf/results/all_variants_all_periods.csv):

| Zone / trigger | Trades (1R exit) | ATR trail | 0.5R | 1R | 2R | Next zone |
|---|---|---|---|---|---|---|
| 1h / 5m | 777 | -0.349 | -0.352 | -0.351 | -0.388 | -0.386 |
| 1h / 15m | 529 | -0.328 | -0.302 | -0.344 | -0.374 | -0.377 |
| 4h / 5m | 243 | -0.236 | -0.169 | -0.170 | -0.197 | -0.274 |
| 4h / 15m | 202 | -0.119 | -0.145 | -0.148 | -0.130 | -0.220 |
| 4h / 1h | 151 | -0.123 | -0.158 | -0.118 | +0.002 | -0.109 |
| 1D / 5m | 46 | -0.237 | -0.190 | -0.184 | -0.236 | -0.231 |
| 1D / 15m | 44 | -0.180 | -0.099 | -0.137 | -0.240 | -0.179 |
| 1D / 1h | 41 | -0.176 | -0.203 | -0.237 | -0.216 | -0.190 |

- At zero cost the same 2026 cells run from about -0.186 to +0.125: 1h/5m -0.022 to -0.062, 1h/15m -0.011 to -0.088, 4h/15m -0.075 to +0.028, 4h/1h -0.037 to +0.125 — [all_variants_all_periods.csv](../../research/smart_zone/mtf/results/all_variants_all_periods.csv).
- Across all variants with at least 15 trades, the share with positive mean R at base cost was 11.9% in train (849 variants), 9.7% in validation (948) and 8.0% in test (922). Medians were -0.193, -0.227 and -0.229. At zero cost the positive shares were 34.3%, 35.7% and 32.2%, with medians near -0.04 — [all_variants_all_periods.csv](../../research/smart_zone/mtf/results/all_variants_all_periods.csv).
- Costs across the seven tested rules: base to maker entry adds about 0.04-0.10 R per trade, and base to zero cost adds about 0.12-0.28 R, largest on the tight 1h/15m rule — [finalists_baselines.csv](../../research/smart_zone/mtf/results/finalists_baselines.csv).

### Inferences
- 1h zones lose the most because their stops are small relative to round-trip cost.
- The single non-negative unfiltered cell (4h/1h 2R, +0.002) is what chance would produce across 40 cells.

### Gaps
- Exit sizing was tested only at the listed R values and trail settings.

## Do the regime and zone-quality filters add out-of-sample value?

### Takeaway
Only the EMA200 trend filter helped consistently, and it mostly made losing cells lose less. First-touch and S/R-flip-only zones did not help, and ADX<=25 alone added nothing out of sample.

### Cited Findings
- Mean change in net R versus the same cell with no filter (paired across combo x preset x exit, cells with at least 15 filtered trades), and the share of cells improved — [filter_marginals.csv](../../research/smart_zone/mtf/results/filter_marginals.csv):

| Filter | Train delta (better) | Val delta (better) | Test delta (better) | Test cells positive |
|---|---|---|---|---|
| EMA200 trend | +0.100 (92%) | +0.046 (60%) | +0.120 (91%) | 17.6% of 68 |
| EMA200 + 4h ADX<=25 | +0.097 (88%) | +0.063 (61%) | +0.170 (94%) | 34.7% of 49 |
| 4h ADX<=25 | +0.019 (60%) | +0.016 (48%) | -0.047 (33%) | 0.0% of 78 |
| 4h ADX>25 | -0.044 (37%) | -0.062 (35%) | +0.026 (61%) | 8.7% of 80 |
| Session 08-20 UTC | -0.035 (34%) | -0.025 (31%) | +0.011 (51%) | 2.5% of 80 |
| Session Asia (<08 UTC) | +0.044 (56%) | -0.048 (34%) | +0.082 (62%) | 26.8% of 71 |
| Vol percentile low | -0.018 (35%) | +0.040 (53%) | -0.019 (38%) | 1.3% of 80 |
| Vol percentile high | +0.002 (54%) | -0.022 (48%) | +0.020 (54%) | 6.3% of 79 |
| Stars >=2 | -0.001 (13%) | -0.009 (15%) | -0.013 (44%) | 2.5% of 80 |
| Stars >=3 | -0.077 (30%) | -0.062 (22%) | +0.041 (60%) | 2.0% of 50 |
| First touch only | -0.065 (30%) | -0.175 (13%) | -0.117 (17%) | 12.8% of 47 |
| S/R flip only | -0.041 (61%) | -0.092 (12%) | -0.011 (50%) | 0.0% of 80 |

- The filter table is reporting, not selection. The filter deltas have no confidence intervals, and cells share trades, so the "better" percentages overstate independence — [run_holdout.py](../../research/smart_zone/mtf/run_holdout.py).
- 4h/15m Balanced with EMA200 + ADX<=25, by exit (train/val/test mean R; test n): 0.5R -0.056/+0.004/-0.083 (61); 1R -0.089/+0.140/-0.012 (53); 2R -0.063/+0.580/+0.156 (44); next zone -0.352/+0.119/+0.140 (32); trail -0.050/+0.429/+0.098 (49) — [all_variants_all_periods.csv](../../research/smart_zone/mtf/results/all_variants_all_periods.csv).

### Inferences
- EMA200 is the only filter that looks like a real effect, consistent in sign across all three periods. It is still not enough: most filtered test cells stay negative.
- The EMA200 + ADX<=25 cells at 2R, next-zone and trail were positive in 2025 and 2026 but all negative in 2024, and none cleared the frozen selection rule. They are a lead for a fresh forward test, not a result.

### Gaps
- Filters were tested singly plus the one EMA200 + ADX combination; broader combinations were deliberately not searched.

## Which exits work?

### Takeaway
No exit rescues the signal. Average net R is negative for all five exits in all three periods, between -0.15 and -0.26.

### Cited Findings
- Mean net R across variants by exit, train / validation / test, with share of variants positive in test: 0.5R -0.150/-0.196/-0.213 (1.6%); 1R -0.191/-0.217/-0.219 (5.4%); 2R -0.201/-0.258/-0.234 (14.1%); next zone -0.244/-0.214/-0.238 (10.1%); ATR trail -0.153/-0.196/-0.217 (9.1%) — [exit_marginals.csv](../../research/smart_zone/mtf/results/exit_marginals.csv).

### Inferences
- The higher positive shares for 2R and next-zone reflect wider outcome dispersion, not higher means.

### Gaps
- Scaling out and break-even stops were not tested.

## Does the result survive train/validation/test, walk-forward and multiple-testing correction?

### Takeaway
No. Across 1,040 variants the development sample shows nothing beyond selection noise (White reality check p=0.98), and all three finalists were negative or flat on the holdout. Walk-forward was positive but statistically indistinguishable from zero.

### Cited Findings
- Variants: 8 combos x 2 presets x 13 filters x 5 exits = 1,040, of which 964 had at least 20 development trades. Another 140 evaluations (20 assumption settings x 7 rules) are reporting only, for 1,180 in total — [dev_summary.json](../../research/smart_zone/mtf/results/dev_summary.json); [sensitivity.csv](../../research/smart_zone/mtf/results/sensitivity.csv).
- Multiple-testing on 2024-25 (weekly net R, 4-week circular block bootstrap, 3,000 resamples): White reality check p=0.978, studentized max-t p=0.799, zero variants with Benjamini-Hochberg q<10% — [dev_summary.json](../../research/smart_zone/mtf/results/dev_summary.json); [dev_multiple_testing.csv](../../research/smart_zone/mtf/results/dev_multiple_testing.csv).
- Selection rule (train n>=40, validation n>=20, mean R>0 in both) passed 7 of 1,040 variants; 3 finalists resulted, all on 4h zones — [finalists.csv](../../research/smart_zone/mtf/results/finalists.csv).
- Holdout results (2026), with week-block 95% bootstrap CI, Holm-adjusted p over the 7 rules, and a random-entry null comparison — [finalists_baselines.csv](../../research/smart_zone/mtf/results/finalists_baselines.csv):

| Rule | Source | Train R (n) | Val R (n) | Test n | Test R [95% CI] | Win rate | PF | Holm p | Null mean R / p |
|---|---|---|---|---|---|---|---|---|---|
| 4h/5m Balanced, ADX<=25, ATR trail | finalist | +0.133 (103) | +0.063 (163) | 133 | -0.159 [-0.436, +0.140] | 34.6% | 0.76 | 1.00 | -0.178 / 0.415 |
| 4h/15m Balanced, Asia session, ATR trail | finalist | +0.028 (80) | +0.067 (98) | 93 | -0.018 [-0.336, +0.331] | 39.8% | 0.97 | 1.00 | -0.176 / 0.098 |
| 4h/1h Strict, ADX<=25, ATR trail | finalist | +0.001 (63) | +0.121 (80) | 66 | -0.241 [-0.538, +0.060] | 34.8% | 0.63 | 1.00 | -0.160 / 0.723 |
| 4h/15m Balanced, EMA200+ADX<=25, 0.5R | baseline | -0.056 (63) | +0.004 (68) | 61 | -0.083 [-0.334, +0.140] | 70.5% | 0.75 | 1.00 | -0.163 / 0.217 |
| 4h/15m Balanced, EMA200+ADX<=25, 1R | baseline | -0.089 (52) | +0.140 (56) | 53 | -0.012 [-0.325, +0.297] | 56.6% | 0.98 | 1.00 | -0.175 / 0.122 |
| 1h/15m Balanced, EMA200+ADX<=25, 0.5R | baseline | -0.067 (125) | -0.369 (173) | 90 | -0.260 [-0.402, -0.124] | 64.4% | 0.37 | 1.00 | -0.288 / 0.362 |
| 4h/1h Balanced, no filter, 1R | baseline | -0.277 (158) | -0.022 (168) | 151 | -0.118 [-0.265, +0.021] | 50.3% | 0.79 | 1.00 | -0.145 / 0.403 |

- Test mean R under other cost cases (base, GST, maker entry, zero), in table order: -0.159/-0.181/-0.098/+0.010; -0.018/-0.038/+0.036/+0.134; -0.241/-0.258/-0.195/-0.115; -0.083/-0.101/-0.033/+0.057; -0.012/-0.031/+0.040/+0.132; -0.260/-0.295/-0.161/+0.017; -0.118/-0.134/-0.074/+0.004 — [finalists_baselines.csv](../../research/smart_zone/mtf/results/finalists_baselines.csv).
- Of the 7 variants passing the dev rule, 6 were negative on the holdout. One, 4h/5m Balanced with EMA200+ADX<=25 and ATR trail, was +0.282 on 55 trades (train +0.059, validation +0.072). It was not a finalist because it ranked below another 4h/5m variant under the frozen rule — [all_variants_all_periods.csv](../../research/smart_zone/mtf/results/all_variants_all_periods.csv).
- Walk-forward (best variant by mean R on a rolling 12 months with n>=30, traded for the next 6): 96 out-of-sample trades, mean +0.067 R [95% CI -0.280, +0.426], one-sided p(mean<=0)=0.36. The four windows returned -0.053 (34 trades), +0.078 (18), +0.306 (21), +0.019 (23) — [walkforward.csv](../../research/smart_zone/mtf/results/walkforward.csv); [walkforward_summary.json](../../research/smart_zone/mtf/results/walkforward_summary.json).
- Assumption sensitivity (reporting only, base cost, dev / test positive counts of 20 settings): 4h/15m ADX-EMA 1R 13/8; 4h/15m Asia trail 12/6; 4h/1h Strict ADX trail 15/0; 4h/5m ADX trail 15/0; 4h/15m ADX-EMA 0.5R 1/0; 1h/15m ADX-EMA 0.5R 0/0; 4h/1h none 1R 0/0 — [sensitivity.csv](../../research/smart_zone/mtf/results/sensitivity.csv). The highest development outlier (+0.399) is `break_inval` with only 4 trades.

### Inferences
- The finalists' development edge did not transfer, which is what the reality check predicted.
- Random-entry nulls show the finalists were about no better than random entries with the same geometry and costs (p between 0.10 and 0.72). The Asia-session finalist came closest at p=0.098, with no Holm adjustment applied to the null p-values.
- The walk-forward result rests on 96 trades and a CI spanning -0.28 to +0.43, so it neither shows an edge nor rules out a small one.

### Gaps
- The random-entry null for the ATR-trail exit uses the risk distance as an ATR proxy, so those null values are approximate.
- Bootstrap p-values are percentile-based and describe sampling noise, not model uncertainty.

## Is the result stable month by month and across long/short, and how does it compare with the earlier studies?

### Takeaway
It is unstable. Positive test months range from 2 to 6 of 10 per rule, short-side results are consistently weak, and the Delta replication is negative for all 7 rules. The earlier 81.6% win-rate study does not reproduce here as an edge.

### Cited Findings
- Positive test months out of 10: 4h/5m ADX trail 3; 4h/15m Asia trail 3; 4h/1h Strict ADX trail 2; 4h/15m EMA-ADX 0.5R 5; 4h/15m EMA-ADX 1R 6; 1h/15m EMA-ADX 0.5R 3; 4h/1h none 1R 5. For the 4h/15m 0.5R baseline, August alone contributed -5.50 R — [monthly.csv](../../research/smart_zone/mtf/results/monthly.csv).
- Long versus short mean R in test: 4h/5m ADX trail +0.091 (55) vs -0.335 (78); 4h/15m Asia trail +0.294 (39) vs -0.244 (54); 4h/1h Strict -0.231 (23) vs -0.247 (43); 4h/15m EMA-ADX 1R +0.102 (16) vs -0.062 (37); 4h/1h none +0.015 (63) vs -0.214 (88) — [sides.csv](../../research/smart_zone/mtf/results/sides.csv).
- Delta BTCUSD 2026 replication, base costs, no funding: mean R -0.197 (75), -0.403 (61), -0.086 (42), -0.321 (38), -0.377 (32), -0.178 (87), -0.192 (101), in the same rule order as the holdout table. Four of the 7 CIs exclude zero on the negative side — [delta_replication.csv](../../research/smart_zone/mtf/results/delta_replication.csv).
- Earlier OB rejection study (Delta 2026): 49 trades, 81.6% wins, +11% at 1x notional, 7/8 months at 60%+ wins, random-entry null at 68% wins from the 0.5R geometry alone, p about 0.02 — [ob-rejection-strategy-study.md](/Users/ajaybaburaj/.claude/projects/-Users-ajaybaburaj-Documents-ajay-crypto/memory/ob-rejection-strategy-study.md).
- This study's closest analogue, 4h/15m Balanced with EMA200+ADX<=25 at 0.5R: 70.5% wins and -0.083 R on Binance 2026 (61 trades); 52.6% wins and -0.321 R on Delta 2026 (38 trades) — [finalists_baselines.csv](../../research/smart_zone/mtf/results/finalists_baselines.csv); [delta_replication.csv](../../research/smart_zone/mtf/results/delta_replication.csv).
- Earlier raw OB retest comparison (Binance, 2026): 4h -2.3%, 1h -32%, 15m -83%, 0/96 variants positive in both 2024 and 2025 — [ob-timeframe-comparison-study.md](/Users/ajaybaburaj/.claude/projects/-Users-ajaybaburaj-Documents-ajay-crypto/memory/ob-timeframe-comparison-study.md).

### Inferences
- Smart Zone rejection behaves like the earlier OB retests: near-zero gross edge, and costs make it negative, with lower timeframes worse.
- The 70.5% win rate at 0.5R is close to the roughly 67% that geometry alone implies before costs, and is not evidence of edge.
- Long-side strength in 2024 and short-side weakness are partly path-dependent. 2024 was a strong uptrend, and the short sides in the finalists were weak in both development and test.

### Gaps
- The comparison with the OB rejection study is not like-for-like: different zone definitions, venue, stops and costs (0.118% round trip there versus 0.14% plus funding here).
- Delta results are affected by long data gaps and by January warmup, and they exclude funding.
