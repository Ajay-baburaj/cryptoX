# CryptoX deployment — 5 November 2026 (IST)

- Dashboard: https://cryptox-5a848.web.app
- API: https://cryptox.34-93-128-49.sslip.io
- GCP/Firebase project: `cryptox-5a848`
- Dedicated VM: `cryptox-bot`, `asia-south1-a`, e2-medium
- Reserved IP: `34.93.128.49`
- Retained persistent disk: 20 GB balanced
- Service: `cryptox.service`, `/opt/cryptox`, unprivileged `cryptox` user
- Service identity: `cryptox-engine@cryptox-5a848.iam.gserviceaccount.com`, FCM API Admin in CryptoX only
- Admin allowlist: `admin@cryptox.com`
- Hosting version: `1257a7a3613e89d6`

CryptoX uses its own VM, network, disk, IP and service identity. Nifty infrastructure was not modified. Both projects use the existing billing account; CryptoX incurs separate ongoing usage charges.

## Validation

- 68 Python tests and 9 chart tests passed.
- Mock-browser hosted login, bearer API request and logout passed.
- Real hosted page loads Firebase SDK/config and redirects an unauthenticated visitor to login, without page errors.
- Public API HTTPS certificate validates; unauthenticated API returns 401.
- Hosted-origin CORS preflight succeeds; untrusted origin preflight is rejected.
- On-VM internal authenticated smoke test reports engine `ok` and fresh Binance data. This uses an internal test session, not a real Firebase user login.
- FCM validation-only request returned HTTP 200 using the VM identity. No notification was sent.
- Controlled service restart passed: paper start time/state preserved, processed-minute cursor did not regress, and fresh market data resumed.
- Service enabled at boot and configured to restart on failure; live state stored on the retained disk.

## User acceptance test

Sign in at the dashboard with `admin@cryptox.com` and the password created in Firebase. Confirm the paper strategy data is updating. Enable notifications on that hosted origin, allow browser/OS permission, and use Send test notification. Confirm actual receipt; FCM acceptance alone is not proof of device delivery.

Cloud deployment starts a fresh, independent paper account. Local paper history/session cookies/notification registrations were not migrated. This remains paper trading only, with no real exchange orders.

See [maintenance and redeployment instructions](README.md). Automated off-VM backups and external uptime alerts are not configured yet.

## Strategy catalog update — 5 November 2026

Published Hosting version `7aba3cf389408593` with a Strategies tab, independent account summaries, strategy-labeled open positions and combined/filterable trade history. Added Delta BTCUSD session-long paper engine (21:00–23:00 UTC), persisted in `data/paper/seasonality_state.json`. Existing OB account state is preserved; pre-update code/state backup is `/var/backups/cryptox/pre-seasonality-20261105.tgz` on the VM.

Validation: 79 Python tests, 9 chart tests, mocked-browser catalog/position/history/filter/login checks, a real Delta data tick, and deployed API/feed checks. Complete-session CSV replay was checked against a synthetic complete/incomplete pair. No performance result is claimed for the session strategy; the user's historical CSV was not supplied.

## Manual paper trading update — 5 November 2026

Published Hosting version `c2eb8561d7a85304` and installed the manual paper engine on the existing CryptoX VM. The Manual trading sidebar opens BTCUSDT market Buy/Long and Sell/Short controls, optional SL/TP/percentage trail, protection editing, and manual close. The independent account starts at 10,000 USDT; its state is stored in `data/paper/manual_state.json`. Manual positions and trades join the shared catalog and history. No broker orders are sent.

Existing environment and paper-account state were preserved. Pre-update code/state backup: `/var/backups/cryptox/pre-manual-20261105T172624Z.tgz`. Backend service is active; internal authenticated checks verified all three account feeds healthy, the manual quote fresh, stale position references rejected, and existing account start times/history preserved. Verification placed no paper trades. Public HTTPS checks confirmed authentication remains required and the published frontend assets match the local build. The real hosted page redirects to login and loads the correct project/API configuration without browser errors.

Before deployment, 102 Python tests and 9 chart tests passed; mocked-browser checks covered Buy, Sell, protection edits, disabling the trail, close, unified history, polling during edits, and mobile rendering. Actual signed-in order placement remains for user acceptance testing. SL/TP/trail checks use sampled quotes every 2 seconds while the backend runs; gaps and downtime fill at the next observed quote.

## Multiple manual positions update — 10 November 2026

Removed the session-long strategy from paper trading, allowed several manual positions at once, and added green/red position cards and a recent-orders table. Code-only update on the existing VM: `.env` and paper state were left in place, and `install_vm.sh` was not run because there are no new dependencies. Pre-update code/state backup is in `/var/backups/cryptox/` as `pre-multimanual-*.tgz`. `seasonality_state.json` remains on disk but is no longer used. No session-long position was open at deployment.

Before deployment, 104 Python tests and 9 chart tests passed. Service restarted cleanly with no errors; signed-in order placement remains for user acceptance testing.

## 1H order-block trailing fix — 14 November 2026

Live trades were being stopped by the trail within the first hour and then moving 1.3R-9R in their favour. Cause: the trail started on the first closed 1h candle even while the trade was losing, and that candle could be the entry candle (mostly pre-entry prices). Fix: the entry candle is never used for trailing, and the stop only trails once a closed 1h candle is at least 1.5R in profit (lookback 2). Settings re-chosen on 2024-2025 only; backtest still loses money (2026 test -7.1% vs -31.2% before). Backup: `/var/backups/cryptox/pre-trailfix-*.tgz`. Frontend unchanged.
