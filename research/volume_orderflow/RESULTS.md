# Volume profile and order flow study: results

Run once on 2026-11-10 under the frozen [protocol](PROTOCOL.md). Reproduce with `make volume-orderflow`. Per-variant numbers: `output/results.csv`.

**0 of 33 variants passed. None had positive net return in the holdout (2025-07-01 to 2026-10-31) at 14 bps round trip plus funding.** No placebo ran, because placebos were reserved for variants with positive holdout net.

| Family | Variants | Holdout trades (range) | Holdout gross bps (range) | Holdout net bps (range) |
|---|---|---|---|---|
| 80% rule | 6 | 68-110 | -7.7 to +2.0 | -21.7 to -12.0 |
| Value area rejection | 3 | 204-211 | -5.6 to +4.8 | -19.6 to -9.2 |
| POC reversion | 3 | 364-380 | -3.9 to +3.8 | -17.9 to -10.2 |
| Naked POC | 6 | 231-245 | -1.0 to +6.9 | -15.0 to -7.1 |
| Balance breakout | 3 | 118-123 | +1.8 to +12.0 | -12.2 to -2.0 |
| Quarter-hour flow | 6 | 464-1964 | -6.7 to +0.9 | -20.7 to -13.1 |
| Funding fade | 4 | 0-29 | about -21 | about -35 |
| CVD divergence | 2 | 1641-1807 | about -0.7 | about -14.7 |

The best variant, balance breakout at the 13:30 boundary, made -2.0 bps net (t = -0.2, 118 trades), and its 2025 and 2026 calendar-year results were negative.

Limits: quarter-hour flow uses the first 1m kline as a proxy for the paper's 10-second aggTrades window. Profiles use 1m bars spread over high-low, not trades. Not tested: HVN/LVN, anchored profiles, spot-versus-perp flow, cascade proxy, footprint, absorption. These results describe this implementation on BTCUSDT over these 3 years only.
