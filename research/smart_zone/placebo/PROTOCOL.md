# Smart-zone placebo study: pre-registered protocol (frozen before any outcome was computed)

Written 2026-11-08 before the first run. The Pine source is not available; everything below is an independent
re-implementation of the textual spec, so results describe THIS implementation.

## Data
Primary: Binance USD-M BTCUSDT perpetual 1m candles, data/binance_ob_timeframes/minutes.parquet (a BTCUSD proxy).
Cross-check (exploratory, not in the test families): Delta BTCUSD 1m, 2026 only, with gaps; complete bars only.
Timeframes 5m, 15m, 1h, 4h, built from 1m; only complete bars.

## Splits (fixed now)
Warm-up 2023-11-01..2023-12-31 (no events counted). Development 2024-01-01..2025-06-30 (pipeline checks only).
HOLDOUT 2025-07-01..2026-10-31: all conclusions. No parameter is tuned on either split; every parameter below is fixed a priori.
2026 price history was used in earlier studies in this repo, for other indicators; holdout is not market-virgin.

## Assumptions for the zone engine (Balanced primary; Strict = 0.6 ATR secondary)
Pivot left=right=5, strict extreme in window; confirmed at i+5; ATR(14) Wilder stored at pivot bar i. Lookback 500 bars.
Pivot reaction = adverse excursion over the right bars / ATR_i. Sort by price; add to the cluster if price - cluster top <=
0.5*min(pivot ATR, cluster mean ATR). Weight = reaction * exp(-age/250). If width > max width*mean ATR, trim to centre +- max/2
around the weighted centre, and members outside are dropped. Minimum width 0.1 mean ATR (single pivots would otherwise be lines).
Flip = pivot types change chronologically and latest type differs from the earliest. Strength =
(sum of recency) * clip(mean reaction, 0, 3) * (1.25 if flip). Stars: >=1.5, >=3, >=5. Primary population: stars >= 1.
Zones rebuilt at bars where a pivot is confirmed; a zone used at bar t was built from data through bar t-1.

## Events
Touch: prior close outside the zone and bar reaches the near edge. Role = support if approached from above, resistance if from below.
Lock: after a touch, overlapping zones cannot fire until a close is >=0.5 ATR outside the locked interval.
Reaction, 1m path from the minute after first touch, ATR at t-1: support target = top + X*ATR, failure = bottom - X*ATR (mirrored for
resistance). X = 0.5, 1, 2. Same-minute double hit = failure. Horizon 300 TF bars; unresolved excluded and reported.
Rejection signal (flag on a touch): depth into zone >= 0.1*width, <= width, close beyond near edge by >= 0.05 ATR.
Trade: next TF open; stop far edge +-0.25 ATR; target 1R; time stop 48 bars; stop wins ties; gaps fill at worse open.
Costs: 0.14% round trip baseline (0.05% taker + 0.02% slippage per side), 0.12% low case; plus historical Binance funding.

## Arms
Random offset: on a zone lineage's birth, centre = close + random sign*|real distance|*U(0.7,1.3), avoiding overlap with live real zones (10 tries), kept for the
lineage's life, width = real zone's current width. 20 replicates. Inherits stars etc. from parent.
Shuffled-time: ATR-normalised offset and width from a real zone born >=30 days away, re-anchored at the birth close, kept for the lineage. 20 replicates.
Hindsight (exploratory only): same zones with confirmation lag removed (pivot visible at its own bar).

## Tests (holdout, two-sided, alpha 5%)
F1: real minus random offset and real minus shuffled reaction rate, 4 TF x 3 X x 2 = 24.
F2: OLS slope of reaction on level (stars, touch bucket, reaction quartile from dev cut-offs, flip), raw and excess over random-offset slope:
4 x 4 x 3 x 2 = 96.
F3: rejection signals vs random entries (same month, side, stop/target %, time stop), 500 replicates, one-sided, net R, 4 TF = 4.
Holm within each family and across all 124. Week-block bootstrap (5000) plus 4-week blocks; SE = larger of the two; p from z on SE; CI = +-1.96 SE.
Stability by year and by ATR%-tercile (dev cut-offs) is descriptive, not counted. Secondary profiles and hindsight are separately labelled.

## Amendment 1 (2026-11-08, before any event/outcome computation; only the no-lookahead check had run)
From the public TradingView description of the script (no source available): star mapping is 1 star < 1.5, 2 stars 1.5-3, 3 stars 3-5, 4 stars > 5
(the 0..3 level in code = 1..4 stars). Display filter: Balanced shows max 5 zones, strength >= 1.25; Strict max 3 zones, strength >= 1.75.
Types: Support (all pivot lows), Resistance (all highs), S->R, R->S, Mixed (hidden by default, rejections blocked). A flip requires one
phase to end before the other starts with a minimum gap (default unpublished; assumed 5 bars). A width penalty on display score is unpublished and not modelled.
Rejection direction: support-type zones (S, R->S) long only, resistance-type (R, S->R) short only, mixed blocked. Placebo arms skip the type filter.
PRIMARY F1 population becomes "displayed": non-mixed, strength >= 1.25 (1.75 strict), top 5 (3) by strength in each rebuild (flag inherited by placebos).
F2 uses all events (mixed excluded for the flip feature). F3 uses displayed real signals. Test counts unchanged.

## Amendment 2 (2026-11-08, after the development run, before the holdout run)
Dev diagnostics showed the shuffled-time arm is confounded: donor widths average ~0.23 ATR vs ~0.58 ATR for real displayed zones (the failure barrier sits
closer for narrower zones, so the arm's reaction rate is mechanically lower). Added arm 4 "shuffled_time_widthmatched": donor offset as before, width = the recipient real
zone's current width. The original arm 2 stays reported, flagged as confounded. F1 grows to 36 tests (4 TF x 3 X x 3 nulls); global family to 136.
Disclosure: the dev run printed the by-year table across all years, so X=1 real-vs-random rates for 2025H2 and 2026 (holdout-overlapping) were seen before the holdout run. No parameter, population or
threshold was changed as a result; arm 4 is the only change and it was motivated by the width diagnostic on dev data.
