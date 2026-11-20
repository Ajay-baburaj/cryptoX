# BTCUSD multi-timeframe agents

Run these commands from the project root with the existing Python environment. The agents use their own entry point and write by default under `data/btc_agents/`.

## Run the backtest

```sh
.venv/bin/python -m btc_agents backtest --venue binance --start 2024-01-01 --end 2026-11-01 --walk-forward --ablations
```

This reads the existing Binance USDT perpetual 1m ZIPs and settlement rates. Dates are UTC and the end is exclusive. The default model charges 5.9 bps of trading fees and 4.1 bps of modeled spread and slippage per side, using the standard Delta fee assumption for comparison. Supply venue-appropriate costs with `--fee-bps` and `--friction-bps`. For a 14 bps round-trip scenario use `--friction-bps 1.1`. Funding is applied separately at settlement. [Delta futures fees](https://www.delta.exchange/support/solutions?articleId=80001177864&categoryId=80000464973&folderId=80000726071)

Use public Delta candles, funding and open interest for a venue-native replay. The optional local trade archive adds signed volume where its OHLCV matches the candle feed.

```sh
.venv/bin/python -m btc_agents import-archives --venue delta --directory data/raw --output data/btc_agents/delta_trades.parquet
.venv/bin/python -m btc_agents delta-candles --start 2026-01-01 --end 2026-10-27
.venv/bin/python -m btc_agents delta-funding --start 2026-01-01 --end 2026-10-27
.venv/bin/python -m btc_agents delta-oi --start 2026-01-01 --end 2026-10-27
.venv/bin/python -m btc_agents backtest --venue delta --minutes data/btc_agents/delta_minutes.parquet \
  --flow-minutes data/btc_agents/delta_trades.parquet --funding data/btc_agents/delta_funding.csv \
  --context data/btc_agents/delta_oi.csv --output data/btc_agents/delta_replay --walk-forward --ablations
```

`delta-candles --start <UTC-date> --end <UTC-date>` downloads or updates the new local Delta minute cache. The official candle endpoint provides OHLCV. The trade archive importer also reconstructs taker buy volume from buyer role. Settlement collection samples the verified 00:00, 08:00, and 16:00 UTC boundaries, converts Delta's percent units to decimal fractions, and reports unexpected timestamps, rates that change between those boundaries, or missing settlement rows. Supply a verified settlement file directly with `--funding` for other schedules. [Delta candle API](https://docs.delta.exchange/#get-historical-ohlc-candles) · [Delta funding methodology](https://www.delta.exchange/support/solutions?articleId=80001199725&categoryId=80000464979&folderId=80000729988)

For a Binance-signal and Delta-execution replay, use `--venue binance --execution-venue delta --execution-minutes data/btc_agents/delta_minutes.parquet --execution-funding data/btc_agents/delta_funding.csv`. Risk levels translate by the two venues' last observable price difference at the decision. Fills and settlement P&L use the execution venue. Use separate output folders for different runs.

The report directory contains `run.json` for the data range and settings, `features.parquet` for each 5m decision snapshot, `decisions.jsonl` for master and agent results on breakout candidates, `execution_audit.csv` for fill and risk outcomes, a trade ledger for each arm, and overall and regime scorecards. `forecasts.csv` reports gross forward direction and returns at 1h, 4h, and 12h independently of risk exits and position limits. The four-hour trade arms measure incremental higher-timeframe alignment on a shared data-availability window and compare available hourly flow with flow aligned to the breakout. The optional walk-forward report uses rolling six-month training and two-month test windows. It picks among three score thresholds only when training has at least 20 closed trades, otherwise it uses 0.60. The ablations remove one agent's gate or score. The trigger ablation keeps the breakout event and removes its volume gate. The structure ablation keeps levels for risk so its comparison measures removal of the structure gate and score.

Sharpe and drawdown in the scorecards are based on daily realized equity and gap marks. Intraday mark-to-market drawdown can differ. Trades interrupted by missing data are labeled unresolved and valued at the last observable price for the mark-inclusive result. The closed-only columns show the sensitivity to that treatment. Each walk-forward fold starts from the same equity. Summing its percentages gives the sum of independent fold results.

## Collect free headlines and positioning data

```sh
.venv/bin/python -m btc_agents news --every 300
.venv/bin/python -m btc_agents derivatives --every 300
```

The news command polls keyless CoinDesk, Cointelegraph Bitcoin, Federal Reserve monetary policy, and BLS inflation and jobs RSS feeds. Add `gdelt` to `--sources coindesk,cointelegraph_btc,fed,bls_cpi,bls_jobs,gdelt` for GDELT's public JSON search. GDELT can rate-limit requests. The collector reports errors per source and continues with the others. It stores headline, URL, source, topic, publication time when supplied, and first-seen time in SQLite. The archive deduplicates canonical URLs and uses the later of publication and first receipt for replay. RSS gives recent items and the archive accumulates forward as it polls. [Fed RSS](https://www.federalreserve.gov/feeds/feeds.htm) · [BLS RSS](https://www.bls.gov/feed/) · [GDELT API](https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/)

Headlines provide event context. A recent BTC security headline halves the planned risk in the first experimental ruleset. Other headline topics are recorded for review. The agent also accepts a separately sourced Fear & Greed observation as a contrarian score at extremes.

The derivatives command records public Delta funding, open interest and mark snapshots plus Binance futures premium, one-hour open-interest change, global and top-account ratios, and taker ratio. Pass its output as `--context data/btc_agents/derivatives.csv`. The same format accepts manually supplied or provider-exported observations such as ETF net flows and macro returns with their rolling BTC correlations. Use a verified availability timestamp for each row. Returns and rates use decimal fractions, and ETF flows use signed USD.

```csv
available_at,metric,value,source
2026-01-05T20:30:00Z,etf_net_flow_usd,250000000,example_provider
```

For CPI, jobs releases, or FOMC blackouts, pass `--events` with the announcement time and when that schedule was known. The 30-minute windows use UTC and apply only once the schedule was available. [BLS releases](https://www.bls.gov/schedule/) · [FOMC calendar](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm)

```csv
event_at,available_at
2026-01-05T13:30:00Z,2026-01-02T17:00:00Z
```

## Preview a signal

Run `.venv/bin/python -m btc_agents signal --venue delta --live` to refresh public candles and see the latest completed 5m decision with the four market-state readings.

```sh
.venv/bin/python -m btc_agents signal --venue delta --minutes data/btc_agents/delta_minutes.parquet --funding data/btc_agents/delta_funding.csv --as-of 2026-10-26T18:00:00Z
```

Omit `--as-of` for a current signal against an up-to-date minute file. The command returns JSON with the master decision and agent reasons. A qualified signal also needs a cost-adjusted 2:1 risk plan. The preview estimates it from the latest close and checks freshness against the latest UTC 5m boundary. Replay evaluates risk from the modeled entry price and fills conservatively from 1m bars. Signals are research output.

## Initial rules and scope

The 4H bias uses EMA50 with two-close confirmation and an ADX threshold of 20. The 1H agent checks momentum and proximity to confirmed range levels. The 15m agent evaluates trend and pullbacks. The 5m entry requires a close beyond the previous 20 bars with above-average or equal relative volume. Signal JSON reports trend from ADX and directional indicators, plus ATR as a percentage of price. Volatility is low or high below the 25th or above the 75th percentile of the preceding 100 bars on that timeframe. Deterministically computed features include EMA, ATR, ADX, RSI, MACD, relative volume, session VWAP, Bollinger bandwidth, and taker imbalance and CVD when the input supplies them. Missing required data blocks the applicable gate.

This is the deterministic phase of the PDF design. External ETF, on-chain and macro features use supplied point-in-time observations. LLM interpretation, reflection fed into prompts, exchange testnet orders and Telegram alerts are subsequent phases. The historical benchmark is development evidence for the rules and cost assumptions tested.
