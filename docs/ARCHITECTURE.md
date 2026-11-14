# Architecture

This document describes how CryptoX is put together and how data moves through it. Diagrams use Mermaid and render on GitHub.

## 1. System context

```mermaid
flowchart TB
    user(["Trader (allowlisted email)"])
    subgraph cloud["Production"]
        hosting["Firebase Hosting<br/>cryptox-5a848.web.app"]
        vm["GCP VM cryptox-bot<br/>Caddy (HTTPS) → Python :8000"]
        fauth["Firebase Authentication"]
        fcm["Firebase Cloud Messaging"]
    end
    binance["Binance public market data<br/>REST + WebSocket"]
    delta["Delta Exchange India<br/>public REST"]

    user -- "loads dashboard" --> hosting
    user -- "signs in" --> fauth
    user -- "API calls with Firebase ID token" --> vm
    user -- "chart data, direct" --> binance
    vm -- "klines, tickers" --> binance
    vm -- "1m candles (legacy replay)" --> delta
    vm -- "verifies tokens with Google public keys" --> fauth
    vm -- "trade alerts" --> fcm -- "web push" --> user
```

The browser fetches chart candles straight from Binance, so the chart works even when the backend is offline. Everything account-related goes through the backend.

## 2. Backend components

One Python process (`make paper`, or `cryptox.service` on the VM) runs an aiohttp web app and several long-lived asyncio tasks.

```mermaid
flowchart LR
    subgraph proc["Python process · src/execution"]
        direction TB
        server["server.py<br/>build_app() · routes · snapshot merge"]
        auth["auth.py<br/>Firebase ID token / signed session cookie<br/>email allowlist · CORS"]
        push["push.py<br/>Notifier · PushStore"]
        subgraph tasks["asyncio tasks"]
            ob["Ob1hEngine<br/>poll every 15 s"]
            man["ManualEngine<br/>quote every 2 s"]
            pe["PaperEngine<br/>poll every 60 s"]
        end
        strat["strategy/ob_mitigation_1h.py<br/>OB1hStrategy state machine"]
        lux["strategy/luxalgo_internal_ob.py<br/>order-block detection"]
    end

    files[("data/paper/<br/>ob1h_state.json · manual_state.json<br/>trades.csv · push_tokens.json · session_secret")]

    auth --> server
    server --> ob & man & pe
    ob --> strat --> lux
    ob -- "on_event" --> push
    ob & man & pe --> files
    push --> files
    auth --> files
```

| Component | Responsibility | State file |
|---|---|---|
| `server.py` | Routes, static files, merges engine snapshots for `/api/strategies`, `/api/positions`, `/api/trades` | none |
| `auth.py` | Login page, `/api/session`, bearer token and cookie checks, allowlist re-checked on every request, CORS for Hosting origins | `session_secret` |
| `ob1h_engine.py` + `OB1hStrategy` | 1h order-block mitigation bot: detect blocks on closed 1h candles, enter on first revisit, manage stop and trail per 1m candle | `ob1h_state.json` |
| `manual_engine.py` | Multiple manual paper positions with SL, TP and trail, checked on each quote | `manual_state.json` |
| `paper_engine.py` | Legacy Delta OB-rejection replay (backs `/api/summary`) | `trades.csv` |
| `push.py` | Registers browser FCM tokens and sends entry and exit alerts (never stop-trail updates, never events older than 15 min) | `push_tokens.json` |
| `seasonality_engine.py` | Retired session-long strategy, used only by `scripts/backtest_seasonality.py` | none |

All state is written atomically (write to `.tmp`, then `os.replace`), so a crash never leaves a half-written file, and a restart resumes positions.

## 3. Data flow: 1H order-block paper bot

```mermaid
sequenceDiagram
    autonumber
    participant B as Binance REST
    participant E as Ob1hEngine
    participant S as OB1hStrategy
    participant F as ob1h_state.json
    participant N as Notifier → FCM

    E->>B: GET klines 1h (limit 1000)
    B-->>E: candles
    E->>S: load_bars(closed 1h candles only)
    Note over S: LuxAlgo internal order blocks<br/>(newest 5 active)
    loop every 15 s
        E->>B: GET klines 1m since last processed minute
        B-->>E: 1m candles (+ forming candle → mark price)
        loop each CLOSED 1m candle
            E->>S: on_minute(ts, o, h, l, c)
            S->>S: trail stop on each newly closed 1h candle<br/>(skip entry candle, only after ≥1.5R profit)
            S->>S: stop hit? (stop wins ties, gaps fill at worse open)
            S->>S: first revisit of a block → entry at next 1m open
            S-->>E: events (signal, entry, trail, exit)
            E->>N: entry / exit events
        end
        E->>F: save state atomically
    end
```

Rules that keep the bot honest:

- **Closed data only:** 1h candles are labelled by close time and used only after they close, and later minutes wait for the next 1h candle to be published.
- **Forward only:** on the first start, already-revisited blocks are marked used and no past trade is invented. After a gap of more than 3 days, blocks are re-baselined instead of replayed.
- **Costs:** 0.05% fee and 0.02% slippage per side. Risk is 0.5% of equity per trade, with a 3× notional cap.

## 4. Data flow: manual paper order

```mermaid
sequenceDiagram
    autonumber
    actor U as Trader
    participant UI as manual.js
    participant A as auth.py
    participant API as server.py
    participant M as ManualEngine
    participant B as Binance ticker
    participant F as manual_state.json

    loop every 2 s (background task)
        M->>B: GET /api/v3/ticker/24hr BTCUSDT
        B-->>M: last price (rejected if older than 15 s)
        M->>M: per position: stop / trailing stop → close<br/>target → close, else tighten trail
        M->>F: save
    end
    U->>UI: Buy / Sell (qty, SL, TP, trail %)
    UI->>A: POST /api/manual/open (token or cookie)
    A->>API: allowed email
    API->>M: open(data) under engine lock
    M->>M: fresh quote? levels valid?<br/>total notional + fee ≤ balance?
    M->>F: save
    API-->>UI: snapshot (positions, trades, account)
    UI->>UI: green / red cards, recent orders table
```

Each position has its own `id`. Update and close requests must name it, so a stale browser tab cannot change the wrong trade. Version 1 state files, which held a single position, are migrated on load.

## 5. Authentication flow

```mermaid
sequenceDiagram
    autonumber
    actor U as User
    participant L as Login page
    participant FA as Firebase Auth
    participant API as Backend (auth.py)

    U->>L: email + password
    L->>FA: signInWithEmailAndPassword
    FA-->>L: ID token (short-lived)
    alt Local dashboard (same origin)
        L->>API: POST /api/session {idToken}
        API->>API: verify signature with Google keys,<br/>project, expiry, email in allowlist
        API-->>L: signed HttpOnly session cookie (12 h)
    else Hosted dashboard (Firebase Hosting)
        L->>API: /api/* with Authorization: Bearer <ID token>
        API->>API: same verification on every request, CORS allows Hosting origins only
    end
```

No service-account key file is used. Token verification uses Google's public certificates, and FCM sending uses the VM's attached service account through application default credentials.

## 6. Research pipeline

```mermaid
flowchart LR
    arch["data.binance.vision<br/>monthly 1m kline + funding zips"] --> dl["scripts/download_binance_ob_research.py"]
    dl --> raw[("data/binance_ob_timeframes/raw")]
    raw --> mins[("minutes.parquet")]
    proto["PROTOCOL.md<br/>frozen before first run"] --> run
    mins --> run["scripts/research_*.py<br/>backtest_*.py"]
    raw --> run
    run --> gates{"Gates: net > 0 at 14 and 20 bps,<br/>t ≥ 3.3, each year positive,<br/>placebo > 95th pct"}
    gates -- pass --> paper["Wire into paper engine"]
    gates -- fail --> doc["Documented negative result<br/>research/*/RESULTS.md"]
```

Backtests reuse the live state machines where one exists (`OB1hStrategy` is shared by `make ob1h-backtest` and the live bot), so paper results and backtests follow identical rules. Periods are split into development, validation and test or holdout. Parameters are chosen without looking at the final period.

## 7. Deployment topology

```mermaid
flowchart LR
    dev["Developer machine"] -- "scripts/build_hosted.py<br/>firebase deploy --only hosting" --> host["Firebase Hosting"]
    dev -- "code-only tarball via IAP SSH<br/>(.env and data/ never shipped)" --> vm
    subgraph vm["GCP VM cryptox-bot · asia-south1-a"]
        caddy["Caddy :443<br/>TLS, security headers"] --> py["cryptox.service<br/>user cryptox · 127.0.0.1:8000"]
        py --> disk[("/opt/cryptox/data/paper<br/>retained persistent disk")]
        envf[".env (600)"] --> py
    end
    browser["Browser"] --> host
    browser -- HTTPS --> caddy
```

Updates back up `/opt/cryptox` to `/var/backups/cryptox/` before the code is swapped, then restart the service and check it. SSH is only through IAP, and only ports 80 and 443 are public.
