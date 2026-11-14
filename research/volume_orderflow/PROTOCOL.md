# Volume profile and order flow study: protocol (frozen before any outcome was computed)

Written 2026-11-10 before the first run, from `reports/Volume profile and order flow.md`. No parameter is tuned; every variant below runs once.

## Data
Binance USD-M BTCUSDT perpetual 1m klines with real taker-buy volume, 2023-11-01..2026-10-31, rebuilt from the local zips and the 2026-10-28 REST repair. Historical funding.
Warm-up 2023-11-01..2023-12-31. Development 2024-01-01..2025-06-30. HOLDOUT 2025-07-01..2026-10-31: conclusions. 2026 is not market-virgin.

## Execution
Signals use closed bars; fill at the next 1m open. Stop wins a same-minute stop/target tie. A gap through a stop fills at the worse open. Cost 14 bps round trip, stress 20 bps, plus actual funding. One position at a time per variant. Returns are per 1x notional.

## Profile
Window = 24h from a fixed boundary: 00:00, 08:00 or 13:30 UTC. (The report's "rolling 24h" boundary is replaced by 08:00 because the rules need a defined window open.)
Each 1m bar's volume is spread uniformly over its high-low across bins of 0.05% of the window's opening price. 70% value area expanded outward from the POC one bin at a time. Levels are frozen at window close and used for the next window. Decisions on 30m bars, ATR(14) Wilder at the signal bar.

## Level rules (each at 3 boundaries)
- 80%: window opens outside prior VA; two consecutive 30m closes inside; stop = entry-side edge -/+ 0.25 ATR; target far edge; exit at window end. Variants: all, VA width >= 1% of price.
- VA rejection: opens inside VA; 30m bar pierces an edge by < 0.25 ATR and closes back inside; stop beyond extreme by 0.25 ATR; target POC; exit at window end.
- POC reversion: 30m close further than 1.5 x VA half-width from POC, with a reversal-coloured bar; stop 1 ATR beyond window extreme; target POC; exit at window end.
- Naked POC: POC untouched, aged 1-20 windows; first touch, approached from one side, 30m rejection close back on that side; stop 0.5 ATR beyond; target 1R or 2R; 24h time stop.
- Balance breakout: last 3 windows' VAs mutually overlap; composite = lowest VAL to highest VAH; two 30m closes outside; stop composite edge -/+ 0.25 ATR; target 1 composite width; 24h time stop.

## Event rules
- Quarter-hour flow: (2*takerBuy-volume)/volume of the first minute after :00/:15/:30/:45, z-scored on the trailing 30 days. Long z>=2, short z<=-2. Hold 4/8/12h, no stop. Variant: trailing 60m imbalance beyond its trailing-30-day 10th/90th percentile, same holds.
- Funding fade: settled funding z over trailing 180 settlements beyond 2.5, or |funding| >= 0.05%; fade; hold 8/24h.
- CVD divergence: 15m, 3-bar pivots, two pivots 4-60 bars apart, price higher high with CVD lower high (mirror for lows); fade; exit after 12 bars. Variant: blocked when 50-bar 1m VPIN exceeds its trailing-30-day 90th percentile.

Total: 33 variants. Not run: 1m-vs-aggTrades profile check, HVN/LVN, anchored/composite, spot-vs-perp, cascade proxy, footprint and absorption (no local aggTrades, spot flow or OI metrics, or conditional on a level rule passing).

## Gates (holdout)
Net mean > 0 at 14 bps and at 20 bps; t >= 3.3 (trades do not overlap); at least 100 trades (300 for a full pass); positive in each of 2024, 2025, 2026 (full sample); positive after removing the best 1% of trades; development-period net > 0; quarter-hour flow gross >= 28 bps; above the 95th percentile of placebo runs.

## Placebos (only for variants with holdout net > 0; 300 runs, 1000 if t >= 3.3)
Levels: each window's levels shifted by random sign x U(0.5,1.5) x its VA width. Events: same side and time of day, moved by a random 1-30 days.
