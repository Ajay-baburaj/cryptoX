# Smart Zone Pro [Abusuhil] rejection signals on the same timeframe as the zones: BTC backtest

Local sources below are paths under `/Users/ajaybaburaj/Documents/ajay/crypto/`. R is per-trade risk; "base" cost = taker 0.05% + slippage 0.02% per side plus historical funding. All numbers come from this study's runs unless a web link is given.

## Bottom line: is there an out-of-sample edge after costs?

### Takeaway
No. The fixed baseline loses on every timeframe and preset in every period at base cost, and neither rule selected on 2024-2025 was profitable on the 2026 holdout. Gross expectancy is about zero, so costs turn a flat signal into a loss rather than eating a real edge.

### Cited Findings
- 4,440 variants were evaluated (4,200 primary grid + 240 sensitivity), each across 6 cost scenarios. No variant passed BH-FDR or Bonferroni on pooled dev+val at base cost; the smallest one-sided p across the 3,157 variants with at least 30 trades was 0.113 — [analyze.log](research/smart_zone/same_tf/results/analyze.log)
- At base cost, 0 of 2,383 primary variants with at least 30 trades in each split were positive in dev, val and test — [analysis run](research/smart_zone/same_tf/analyze.py)
- Holdout (2026), base cost, frozen selected rules: 30m Strict/Res/3-star/time-30-bars/0.25 ATR: 44 trades, win 18.2%, -0.155R, PF 0.86, MDD 11.7%, return -3.2%, 95% CI [-0.99, +1.24]. 240m Strict/flip/all stars/time-30-bars/0.1 ATR: 33 trades, win 6.1%, -0.477R, PF 0.56, MDD 12.3%, return -8.0%, CI [-1.15, +1.04] — [baseline_selected_ci.csv](research/smart_zone/same_tf/results/baseline_selected_ci.csv)
- 5m, 15m and 60m had no rule pass the selection filter on dev+val — [selection_frozen.json](research/smart_zone/same_tf/results/selection_frozen.json)

### Inferences
- The result is robust to the choice of test: the baseline, the selected rules, walk-forward and the Delta replication all agree.

### Gaps
- The indicator is a reconstruction from a description. The conclusion applies to this reconstruction, not provably to the closed-source script.

## What data, indicator assumptions and protocol were used?

### Takeaway
Primary data is 3 years of gap-free Binance BTCUSDT perpetual 1m bars, used as a BTCUSD proxy because the repo's Delta BTCUSD series covers only 2026 and has large holes. The holdout was fixed before any outcome was computed.

### Cited Findings
- Binance USD-M BTCUSDT perp 1m: 2023-11-01 to 2026-10-31, 1,578,240 rows, no gaps or duplicates; funding has 3,288 records — [minutes.parquet](data/binance_ob_timeframes/minutes.parquet)
- Delta BTCUSD 1m: 2026-01-01 to 2026-10-26, 334,821 rows, 17 gaps totalling about 95,739 missing minutes (22% of the span), including holes of 30 days ending 2026-07-01 and 29 days ending 2026-10-01 — [replicate.log](research/smart_zone/same_tf/results/replicate.log)
- All timeframes (5m, 15m, 30m, 1h, 4h) were resampled from 1m — [common.py](research/smart_zone/same_tf/common.py)
- Split: warmup Nov-Dec 2023, dev 2024, val 2025, test Jan-Oct 2026. Stage 1 ran with minutes physically cut at 2026-01-01 and wrote the selection. Stage 2 reproduced dev/val exactly (max |avgR diff| 0.0 over 53,280 rows) — [protocol.py](research/smart_zone/same_tf/protocol.py), [analyze.log](research/smart_zone/same_tf/results/analyze.log)
- 2026 BTC prices were used by older studies in this repo (other strategies), so the holdout is new for this strategy but not a virgin market period — [ob_timeframe_protocol.md](research/ob_timeframe_protocol.md)
- No public page or Pine source for "Smart Zone Pro" by Abusuhil was found; a search surfaced only other scripts, such as ["abusuhil zonewatch"](https://it.tradingview.com/script/OWiyahIp-abusuhil-zonewatch) and [The Machine - Smart Zones PRO](https://in.tradingview.com/script/84iwgQFM-The-Machine-Smart-Zones-PRO).
- Assumptions, all in `Params` — [smart_zone.py](research/smart_zone/same_tf/smart_zone.py):
  - Pivots: left = right = 5; high/low strict on the right side; ATR is Wilder 14 at the pivot bar; reaction = |close at confirmation - pivot| / ATR.
  - Clustering: merge distance = 0.5 x max width x min(pivot ATR, zone average ATR). Zone = pivot span +/- 0.1 ATR. Trimming drops the pivot farthest from the reaction x recency weighted center.
  - Flip gap: 10 bars.
  - Strength = touches x (0.5 + 0.5 x reaction) x mean(0.5^(age/200 bars)) + 1.0 flip bonus. Display = strength - 0.3 x width in ATR. Filter, ranking and stars use display.
  - Rejection: depth >= 0.1 ATR; wick no more than 0.25 ATR past the far edge; close >= 0.05 ATR beyond the near edge. Zones as of the prior bar (self-confirmation excluded). Entry at next bar open.
  - Exits were walked on 1m bars, stop first on ties, capped at split end; 100-bar max hold for R targets.
  - Sizing for return/MDD: 0.5% equity risk, leverage capped at 3x.
- Scale check before any trade outcome (2024 zones only): 1h Balanced median strength 3.31, touches 3.0, reaction 1.91, median width 0.52 ATR, versus the chart label "Str:3.7 Tch:3 Rct:1.51"; the excursion-based reaction scored further away (2.64) — [calibrate.py](research/smart_zone/same_tf/calibrate.py)
- No-lookahead test: truncating the series, and separately corrupting all later bars with noise, left every earlier signal unchanged on 12 cut-point runs over four timeframe/preset combinations (8,531 signals compared); a stop-first tie test also passes — [tests_no_lookahead.py](research/smart_zone/same_tf/tests_no_lookahead.py)

### Inferences
- Strength sits on a plausible scale, but one chart label cannot validate the formula.

### Gaps
- Funding on Delta differs from Binance; the Binance rates are a proxy and Delta's own funding was not modelled in the replication.
- The exact Pine scoring, trimming and rejection logic could not be confirmed.

## Results by timeframe, preset, zone type and star level

### Takeaway
No timeframe/preset/zone/star cell shows a positive test expectancy with at least 30 trades at the 1R/0.25 ATR baseline exit, 0 of 121 cells. Losses shrink with higher timeframes because costs are a smaller fraction of a wider stop.

### Cited Findings
- Baseline (all zones, all stars, 1R, 0.25 ATR stop buffer), base cost, 2026 test — [baseline_selected_ci.csv](research/smart_zone/same_tf/results/baseline_selected_ci.csv):

| TF | Preset | Trades | Win | Avg R | PF | MDD | Return | 95% CI |
|---|---|---|---|---|---|---|---|---|
| 5m | Balanced | 4,408 | 32.2% | -1.006 | 0.11 | 100% | -100% | [-1.12, -0.91] |
| 5m | Strict | 2,906 | 26.8% | -1.160 | 0.07 | 100% | -100% | [-1.29, -1.05] |
| 15m | Balanced | 1,356 | 46.0% | -0.519 | 0.33 | 96.4% | -96.4% | [-0.59, -0.45] |
| 15m | Strict | 909 | 46.3% | -0.563 | 0.30 | 90.1% | -90.1% | [-0.66, -0.47] |
| 30m | Balanced | 703 | 46.1% | -0.387 | 0.45 | 74.6% | -74.5% | [-0.47, -0.31] |
| 30m | Strict | 471 | 50.1% | -0.363 | 0.47 | 57.2% | -57.2% | [-0.46, -0.26] |
| 1h | Balanced | 323 | 43.0% | -0.351 | 0.49 | 44.0% | -43.5% | [-0.46, -0.23] |
| 1h | Strict | 231 | 45.9% | -0.330 | 0.51 | 33.0% | -31.8% | [-0.45, -0.21] |
| 4h | Balanced | 96 | 49.0% | -0.114 | 0.80 | 7.2% | -5.4% | [-0.30, +0.07] |
| 4h | Strict | 72 | 47.2% | -0.164 | 0.72 | 8.7% | -5.8% | [-0.45, +0.08] |

- Dev and val are negative in every one of these rows as well (for example 4h Balanced -0.214 and -0.131; 1h Balanced -0.246 and -0.245) — [baseline_splits.csv](research/smart_zone/same_tf/results/baseline_splits.csv)
- Full cube by zone type and star at 1R/0.25 ATR: 200 test cells, 121 with at least 30 trades, 0 positive — [cube_R1_b025.csv](research/smart_zone/same_tf/results/cube_R1_b025.csv)
- Median test avg R across cells with at least 30 trades: flip -0.477, Sup -0.507, Res -0.557. By star: 1 star -1.189, 2 stars -0.548, 3 stars -0.420, 4 stars -0.536 — same file
- 4h Strict Res was +0.018R on 25 test trades, and 4h Balanced 2-star was -0.044R on 47 trades; these are noise-sized and neither was a pre-selected rule — same file
- Median stop distance on the test set: 5m 0.18%, 15m 0.33%, 30m 0.50%, 1h 0.68%, 4h 1.60%, so a 0.14% round trip costs 0.80R, 0.42R, 0.28R, 0.20R and 0.09R respectively — [analysis run](research/smart_zone/same_tf/analyze.py)

### Inferences
- Higher star ratings do not produce a monotone improvement. 3-star is the least bad but still clearly negative.
- Low-timeframe results are dominated by mechanical cost: the 5m baseline pays about 0.8R of cost per trade on a gross near-zero signal.

### Gaps
- 4h cells are small (tens of trades), so individual cells cannot be distinguished from zero.

## Which exits work?

### Takeaway
None work across periods. Exit choice changes the size of the loss, and no exit is reliably positive after costs. Wider stop buffers lose less for the same cost reason.

### Cited Findings
- Mean baseline-grid avg R by exit across dev/val/test, base cost: 0.5R -0.388/-0.453/-0.494; 1R -0.399/-0.455/-0.493; 1.5R -0.385/-0.455/-0.502; 2R -0.366/-0.454/-0.506; opposite zone -0.441/-0.485/-0.573; 10-bar time stop -0.404/-0.454/-0.500; 30-bar time stop -0.351/-0.486/-0.476 — [exits_all.csv](research/smart_zone/same_tf/results/exits_all.csv)
- Stop buffer (0.1/0.25/0.5 ATR), test mean avg R: -0.595/-0.508/-0.416 — same file
- Best-looking test-period results (not selected in advance): 1h Strict flip 3-star time-30 at 0.1 ATR, +0.386R on 92 trades, PF 1.40; 4h Balanced all time-30 at 0.5 ATR, +0.259R on 60 trades. Both lost in 2024 and 2025 (1h rule -0.266R dev, -0.428R val; 4h rule -0.282R dev, -0.236R val), so they failed the selection filter, and picking them from the test set would be data-mining — [stage2_metrics.csv](research/smart_zone/same_tf/results/stage2_metrics.csv)

### Inferences
- Time-based exits show the largest period-to-period variance because they let R run far from the tight stop, which suits a selection rule's noise rather than proving edge.
- Same-timeframe bar walking gives nearly identical results to the 1m walk (for example 1h Balanced test -0.351 in both), so bar-level tie handling is not driving the conclusion — [tf_walk.csv](research/smart_zone/same_tf/results/tf_walk.csv)

### Gaps
- Trailing stops were outside the requested exit list and were not tested.

## Does anything survive costs, and how much do costs matter?

### Takeaway
Nothing survives base cost out of sample. Maker entry reduces losses but the baseline stays negative everywhere, and even at zero cost the baseline is flat.

### Cited Findings
- Base-cost and maker assumptions: the base taker 0.05% and slippage range come from the study brief; the 0.02% maker rate and the 18% GST scenario are unverified assumptions (see Gaps). The repo's previous study used 0.05% fee + 0.02% slippage per side and funding — [ob_timeframe_protocol.md](research/ob_timeframe_protocol.md). The repo paper config is harsher: 0.1% fee + 0.05% slippage — [config.yaml](config/config.yaml)
- Baseline test avg R by cost scenario — [baseline_costs.csv](research/smart_zone/same_tf/results/baseline_costs.csv):

| TF/Preset | Zero | Maker entry | Taker + 0.01% | Base | Base + GST | Repo config |
|---|---|---|---|---|---|---|
| 5m Balanced | -0.023 | -0.655 | -0.866 | -1.006 | -1.132 | -2.130 |
| 15m Balanced | -0.035 | -0.346 | -0.450 | -0.519 | -0.581 | -1.072 |
| 30m Balanced | -0.077 | -0.276 | -0.343 | -0.387 | -0.427 | -0.740 |
| 1h Balanced | -0.136 | -0.274 | -0.320 | -0.351 | -0.379 | -0.597 |
| 4h Balanced | -0.021 | -0.081 | -0.101 | -0.114 | -0.126 | -0.219 |
| 4h Strict | -0.056 | -0.125 | -0.149 | -0.164 | -0.178 | -0.290 |

- Across the primary grid, the share of 2,649 variants (at least 30 trades in a split) with positive test avg R was 32.4% at zero cost, 2.4% with maker entry, and 1.4% at base cost — [analyze.log](research/smart_zone/same_tf/results/analyze.log)
- Three of 2,383 variants were positive in all three splits under maker-entry: all 30m Strict Res 3-star (opposite zone 0.1 ATR; time-30 0.1 ATR; time-30 0.5 ATR), with test avg R of +0.249, +0.154 and +0.022. These are the same variant family as the frozen selected rule — [analysis run](research/smart_zone/same_tf/analyze.py)

### Inferences
- Those three maker-entry survivors should not be treated as an edge. They are 3 of 2,383 tries, near-duplicates of one family, they do not hold at base cost, and the maker assumption gives a guaranteed fill at the next open with no adverse selection, which is optimistic.
- A search summary mentioned a Delta offer waiving the closing fee on BTC futures positions closed within 30 minutes (page returned 404, so unverified). Even if active it would leave entry fee and slippage, and 5m zero-cost expectancy is already slightly below zero.

### Gaps
- Real maker fill rates were not modelled, and the maker scenario pays no slippage on entry.
- Delta's fee schedule could not be verified: a web search summary reported 0.05% taker, 0.02% maker and 18% GST on fees, but the two Delta support pages it pointed to returned HTTP 404 when opened. Confirm against the in-app rate card.

## Train/validation/test, walk-forward and multiple-testing

### Takeaway
The selection process found rules that looked positive on 2024-2025 and failed on 2026. Walk-forward produced no credibly positive result, and no variant is significant after correction.

### Cited Findings
- Selection: only 2 of 4,200 primary variants at 30m and 6 at 4h passed the filters (dev >= 30 trades, val >= 20 trades, mean net R > 0 in both); 5m, 15m, 1h had none — [selection_frozen.json](research/smart_zone/same_tf/results/selection_frozen.json)
- Selected rules, dev / val / test avg R: 30m +0.184 / +0.488 / -0.155; 4h +0.495 / +0.325 / -0.477 — [baseline_selected_ci.csv](research/smart_zone/same_tf/results/baseline_selected_ci.csv)
- Walk-forward (quarterly re-selection on trailing 12 months, best positive variant with at least 30 trades, 2025-Q1 to Oct 2026), base cost: 5m no qualifying rule in any fold (0 trades); 15m 167 trades -0.138R [-0.44, +0.24]; 30m 97 trades +0.011R [-0.55, +0.74]; 1h 125 trades -0.468R [-0.77, -0.13]; 4h 85 trades -0.323R [-0.61, +0.01]; best across all timeframes 91 trades -0.162R [-0.63, +0.46] — [walkforward.csv](research/smart_zone/same_tf/results/walkforward.csv), [walkforward_folds.csv](research/smart_zone/same_tf/results/walkforward_folds.csv)
- Multiple testing, pooled dev+val, 3,157 variants with n >= 30: 0 with raw p < 0.05, 0 BH-FDR, 0 Bonferroni (threshold 1.13e-5, smallest p 0.113) — [analyze.log](research/smart_zone/same_tf/results/analyze.log)
- Deflated Sharpe on selected rules: per-trade SR 0.104 (30m) and 0.129 (4h) against SR* 0.89 for N = 4,440 trials, DSR probability about 0 — [baseline_selected_ci.csv](research/smart_zone/same_tf/results/baseline_selected_ci.csv)
- Holm on the 12 test hypotheses (10 baselines + 2 selected): every adjusted p = 1.0 — [test_holm.csv](research/smart_zone/same_tf/results/test_holm.csv)
- Rank correlation of variant avg R across periods: dev-val 0.80, val-test 0.82 — [analyze.log](research/smart_zone/same_tf/results/analyze.log)

### Inferences
- The high rank correlation reflects mainly the persistent ordering of cost burden by timeframe and stop width, not persistent alpha, since nearly all variants are negative.
- SR* of 0.89 is inflated: the trial Sharpe variance includes small-sample noise and N counts correlated variants. A milder correction would not change the outcome, as the best raw p (0.113) already fails at N = 1.

### Gaps
- Effective number of independent trials was not estimated.

## Do results hold long and short, and by year or regime?

### Takeaway
Long and short are about equally negative, and every year and regime is negative for the baseline. No side or regime rescues the signal.

### Cited Findings
- Baseline, all periods, long / short avg R, base cost: 5m Balanced -0.913 / -0.928; 15m Balanced -0.453 / -0.470; 30m Balanced -0.305 / -0.308; 1h Balanced -0.264 / -0.287; 4h Balanced -0.143 [CI -0.30, +0.03] / -0.159 [-0.31, -0.01]; 4h Strict -0.102 [-0.30, +0.10] / -0.132 [-0.31, +0.06] — [slices.csv](research/smart_zone/same_tf/results/slices.csv)
- Year (2024 / 2025 / 2026): 1h Balanced -0.25 / -0.24 / -0.35; 4h Balanced -0.21 / -0.13 / -0.11; 15m Balanced -0.39 / -0.49 / -0.52 — same file
- Regime (causal: prior-day close vs 200-day SMA; 20-day realised vol vs trailing 180-day median), baseline avg R: all negative in all timeframe/preset rows; 4h Balanced bull -0.26, bear -0.04, high vol -0.07, low vol -0.20; 1h Balanced bull -0.27, bear -0.29 — same file
- Selected 30m rule is short-only by construction (Res zones). The selected 4h rule was long +0.557R [-0.41, +1.83] on 46 trades and short -0.084R on 75 trades, across all splits — same file

### Inferences
- The 4h baseline's narrow bear-regime loss (-0.04R) is within noise and not evidence of a tradable regime filter; adding one would be another fitted variant.

### Gaps
- Regime results for the small 4h samples have wide confidence intervals.

## Replication and assumption sensitivity

### Takeaway
Delta BTCUSD 2026 data and all 24 single-assumption changes give the same negative result, so the conclusion does not hinge on one default.

### Cited Findings
- Delta BTCUSD 2026 (frozen rules, no funding), base cost, baseline: 5m Balanced 3,052 trades -1.009R; 15m Balanced 995 trades -0.544R; 30m Balanced 470 trades -0.429R; 1h Balanced 204 trades -0.258R. Zero-cost: -0.009R, -0.050R, -0.103R, -0.034R respectively. 15m Strict is the single zero-cost positive at +0.052R. The frozen 30m selected rule on Delta was -0.413R on 29 trades at base cost — [delta_replication.csv](research/smart_zone/same_tf/results/delta_replication.csv)
- Sensitivity on 24 single-parameter changes (pivot lengths, merge distance, padding, recency, flip gap and bonus, depth, penetration, margin, reaction definition, filter basis, prior-close requirement, zone invalidation, stored pivots), base cost, at 1R/0.25 ATR across the 10 timeframe/preset pairs: mean test avg R ranged -0.417 to -0.555, and only 1 of 240 test cells was positive (merge 0.8) — [sensitivity.csv](research/smart_zone/same_tf/results/sensitivity.csv)

### Inferences
- The assumptions most likely to be wrong relative to the original script (scoring and padding) move the loss only modestly and do not change its sign.

### Gaps
- Delta 4h could not be replicated: after splitting at gaps longer than 60 minutes, no segment had the required 300 4h bars, so it produced 0 trades. The Delta set overlaps only the 2026 test window.
- No random-entry null benchmark was run; zero-cost baselines near 0R serve as the informal check.
