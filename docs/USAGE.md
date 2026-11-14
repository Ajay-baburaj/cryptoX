# Usage and operations reference

Detailed setup, command and behaviour reference. Start with the [README](../README.md) and [architecture](ARCHITECTURE.md).

Local Python trading bot scaffold using Delta Exchange public market data. It does not submit real orders. Historical candles use Delta's public `/v2/history/candles` API and live data uses its public WebSocket channels. The future execution adapter is only a stub; setting `LIVE_TRADING=true` does not enable order placement.

The main dashboard chart displays Binance Spot BTCUSDT using public REST candles and a live WebSocket feed, with prices in USDT and timestamps in IST. The paper account panels use the Delta BTCUSD strategy.

The chart includes a JavaScript adaptation of the supplied **Smart Money Concepts [LuxAlgo]** indicator. Internal/swing BOS and CHoCH, the latest five internal order blocks, equal highs/lows, and strong/weak swing levels are enabled by default. **Indicator settings** controls swing blocks, pivot labels, candle coloring, fair value gaps, premium/discount zones, previous day/week/month levels, structure filters, mitigation, and display mode. Preferences are saved in the browser. **Fullscreen** expands the chart with its controls; use the exit button or Esc to return.

The adaptation is in `frontend/indicators/smc.js`; the original supplied Pine script is preserved in `frontend/indicators/luxalgo-smc.pine`. It runs on the 1,000 loaded Binance candles and recalculates on live updates, including rollback of unconfirmed signals. Fair value gaps use the chart timeframe; the Pine script's independent FVG timeframe and TradingView alert delivery are not implemented. This is a JavaScript port, not a Pine runtime or a claim of exact TradingView parity. History length, feeds, and an unfinished candle can change the drawings. Both the supplied source and adaptation carry LuxAlgo attribution and CC BY-NC-SA 4.0 terms.

## Setup

Requires Python 3.11+. `make setup` creates `.venv` and installs dependencies. Copy `config/.env.example` to `.env` for local configuration. No API key is needed for public market data.

## Firebase login and push notifications

Same setup as the Nifty app. The dashboard and every `/api/*` route sit behind **Firebase Authentication (email + password)**; the server verifies the Firebase ID token against Google's public keys (no service-account key file) and only emails in `DASHBOARD_ALLOWED_EMAILS` get in. Paper-trade entries and exits are pushed to your browser through **Firebase Cloud Messaging**. `make paper` refuses to start until login is configured, so it can never run open by accident. The Firebase project is `cryptox-5a848` and its web config is already in `config/firebase_web.json`.

One-time steps:

1. [Authentication](https://console.firebase.google.com/project/cryptox-5a848/authentication) → **Get started** → **Sign-in method** → enable *Email/Password*. **Users → Add user** with your email and a strong password. **Settings → User actions →** untick *Enable create (sign-up)* so nobody can register themselves.
2. In `.env` add `DASHBOARD_ALLOWED_EMAILS=you@example.com` (comma-separated; only these may sign in).
3. `make firebase-check`, then `make paper`, then open **http://localhost:8000** (not `0.0.0.0`: browsers only allow service workers on localhost or HTTPS).
4. Click **Enable notifications** in the sidebar and allow the browser prompt; **Send test notification** reports Firebase acceptance or failure; confirm actual receipt in your browser. For a project Web Push certificate, add its public key as `vapidKey` in `config/firebase_web.json` (never a private key).

Push *sending* uses the machine's default Google credentials, like Nifty: on a VM, attach a service account with the **Firebase Cloud Messaging Admin** role; on a laptop run `gcloud auth application-default login`. Without credentials the dashboard works and sending is skipped with one log line (`make firebase-check` reports which).

Notes: sessions last 12 hours (`DASHBOARD_SESSION_HOURS`) and are signed with a key created in `data/paper/session_secret`; removing an email from the allowlist locks it out immediately. The server listens on `127.0.0.1` (set `DASHBOARD_HOST=0.0.0.0` only behind HTTPS or a tunnel, and add the domain under Authentication → Settings → Authorized domains). Notifications fire on trade entry and exit only (not on every stop trail); events older than 15 minutes (restart catch-up) are never pushed. `data/paper/push_tokens.json` holds the registered browsers.

## Commands

- `make test` — run pytest
- `make test-frontend` — run indicator calculation tests (Node.js 18+; no npm install needed)
- `make data` — download configured market history
- `make backtest` — run a backtest
- `make strategy-backtest` — run the EMA200 + RSI50 + Engulfing strategy on local Delta BTCUSD trade archives
- `make strategy-optimize` — coarse chronological parameter search; keeps Aug–Oct 2026 as holdout data
- `make daily-strategy-backtest` — test the daily SMA50/EMA7/RSI2/ADX2 rules against buy-and-hold
- `make ob-rejection-backtest` — researched strategy: 1h/4h LuxAlgo internal order blocks, 15m wick rejection, trade with the 15m EMA200 only while 4h ADX ≤ 25, stop 0.5 ATR beyond the zone, 0.5R target (Jan–Oct 2026: 49 trades, 81.6% wins, 7/8 months ≥ 60%)
- `make ob-rejection-research` — grid search behind it: train Jan–May / test Jul–Oct, robustness by family, random-entry null test
- `make ob-rejection-baseline` — original version: 4h OBs, 15m rejection, 2R-activated trailing stop (−14%, 24% wins)
- `make ob-touch-backtest` — the 15m order blocks drawn by the TradingView script in `order_block_new.txt` (ported exactly, `pine_internal_blocks`: close mitigation, latest 5 drawn), entering on a touch or near-touch (within 0.25%) with an ATR trailing stop and no fixed target, config in `config/ob_touch_15m.yaml`. Research found no edge: Jan–Oct 2026 682 trades, 48% wins, −60%, 0/9 months ≥ 60%, and the no-stop directional null test is ~50% at every buffer width. Documented negative result, not wired into `make paper`
- `make ob-touch-research` — grid search behind it: near-touch buffer (touch-only / ATR / % of price) x trailing-stop params, train Jan–May / test Jul–Oct (0 of 63 settings robust), plus the directional-edge null test per buffer size
- `make ob15-diagnosis` — why the 15m order-block touch strategy loses: entry beats random by 0.2 points (no edge), gross R is ~0 under all 27 exits and 13 stop placements, and fees (~0.21R per trade at ~0.6% risk) account for ~95% of the loss; none of 10 pre-written filters passed the train gate. Tables in `data/reports/ob15_diagnosis_*.csv`
- `make mytradesetup-backtest` — signals from `order_block_new.txt` (a TradingView indicator with no exits): Hull/Kalman Buy/Sell crosses and pivot-gated reversal candles, alone and gated by a touched 15m order block, entered after the signal bar closes with an assumed 1.5 ATR stop + ATR trail. Jan–Oct 2026: every variant loses (win rates 46–49%, PF 0.5–0.6) and the no-stop null test is ~50%. No edge; documented negative result
- `make ob1h-backtest` / `make ob1h-grid` — replay the **1h order-block mitigation paper strategy** (`src/strategy/ob_mitigation_1h.py`, config `config/ob_mitigation_1h.yaml`) on Binance BTCUSDT 1m history, using the same state machine as live paper trading. Bearish 1h block revisited → short, bullish → long; stop beyond the far edge of the block (above a bearish block) + 0.25 ATR; no target. The stop stays at the block until a closed 1h candle (never the entry candle) is ≥ 1.5R in profit, then trails to the extreme of the last 2 closed candles and only tightens. Results 2024 / 2025 / Jan–Oct 2026: −22% / −18% / −7%, mean −0.15 / −0.13 / −0.05 R: no edge after costs, consistent with `research/ob_timeframe_report.md`. Built for paper observation, not validated. Trail settings were chosen on 2024+2025 only (`data/reports/ob1h_grid.csv`)
- `make ema-vwap-backtest` — EMA(9/20) + session VWAP intraday trend filter, config in `config/ema_vwap.yaml`. Research found no directional edge on BTCUSD (47–53% forward hit rate at every horizon); kept as a documented, non-live baseline — see the config file's header
- `make ema-vwap-research` — the grid search and directional-edge test behind that finding
- `make volume-orderflow` — pre-registered volume profile and order-flow study (80% rule, value area rejection, POC reversion, naked POC, balance breakout, quarter-hour taker flow, funding fade, CVD divergence) on Binance BTCUSDT 1m klines with taker-buy volume. 0 of 33 variants net-positive in the 2025-07..2026-10 holdout; see `research/volume_orderflow/RESULTS.md`
- `make paper` — frontend and backend together (also runs the live 1h order-block mitigation paper bot on Binance BTCUSDT, state in `data/paper/ob1h_state.json`, shown in the dashboard's **1H order-block mitigation** section and at `/api/ob1h`); at `http://localhost:8000`: serves the dashboard and runs a live paper-trading engine for the order-block strategy (`src/execution/paper_engine.py`) on Delta's public 1m candles. Simulated trades, balance, win rate and the open position are real (reruns the exact backtest entry/exit logic on live data, no API key, no real orders); the trade log persists to `data/paper/trades.csv`
- `make frontend` — serve just the static dashboard at `http://localhost:8000` (BTCUSDT spot chart only, live from Binance; the other panels stay blank without the backend — use `make paper` for those)

`make paper` and `make frontend` use the same port, so run one or the other, not both.

The Python adaptation in `src/strategy/luxalgo_internal_ob.py` is derived from LuxAlgo's supplied SMC Pine script and carries its CC BY-NC-SA 4.0 attribution and share-alike terms. It is for non-commercial use.

All timestamps are stored in UTC and displayed in Asia/Kolkata.

## Deployment readiness

See [the deployment audit](research/deployment_readiness.md). Matching Nifty requires Firebase Hosting for the frontend plus an always-on Python backend, persistent storage, and a hosted API/auth integration. The hosted build now supports Firebase Hosting plus the dedicated CryptoX VM. See [deployment instructions](deploy/README.md).

## Paper strategies and manual trading

The Strategies sidebar tab lists independent forward-paper accounts: **1H order-block mitigation** (Binance Spot BTCUSDT, 10,000 USDT) and **Manual paper trading** (BTCUSDT, 10,000 USDT). Overview open positions and unified trade history show account names, market and quote currency; history can be filtered by account. The legacy Delta research replay remains separate from this forward-paper catalog.

Use **Manual trading** in the sidebar to Buy/Long or Sell/Short at the current public BTCUSDT quote. Enter quantity in BTC and optional stop-loss, take-profit prices and trailing distance in percent. Several positions can be open at once, in either direction, each with its own protection; their combined notional plus entry fee must fit within the account (1×). Use **Edit SL / TP / Trail** on a position to change its protection (blank disables it), or **Close position** for a market exit. Trades appear in the shared history under Manual paper trading. No orders are sent to a broker.

Manual simulation charges 0.05% fees and 0.02% adverse slippage per side; funding and liquidation are excluded. The trailing stop follows the best observed price from entry, only tightens, and resets when its percentage is changed. Public prices are checked every 2 seconds while the backend runs. Triggered stops and targets fill at the observed quote plus slippage, so gaps can fill beyond the requested level. Offline price paths are not replayed: on recovery, the next fresh quote checks the saved protection. New orders, edits and manual exits require a quote less than 15 seconds old. Account state is saved atomically in `data/paper/manual_state.json`; restarting resumes the account. All allowed dashboard users share this manual account, like the strategy accounts. API: `GET /api/manual`, `POST /api/manual/open` (`side`, `quantity`, optional `stop`, `target`, `trail_pct`), `POST /api/manual/update` (`position_id` plus protection fields), `POST /api/manual/close` (`position_id`). Each position has its own ID, so a stale browser cannot edit or close the wrong trade.

The 21:00–23:00 UTC session-long strategy has been removed from paper trading. Its engine (`src/execution/seasonality_engine.py`) remains only for the backtest below. Its cost model: buy at `open * 1.0001`, sell at `open * 0.9999`, subtract `2 * 0.0005 * 1.18` from the price return.

To run the supplied historical CSV model:

```sh
.venv/bin/python scripts/backtest_seasonality.py BTCUSD_15m.csv
```

The CSV needs UTC-compatible `timestamp` and positive `open` columns, with unique 15-minute candle-open timestamps. Output: `data/reports/seasonality_backtest.csv`. No historical seasonality result is claimed without supplying and testing the dataset.
