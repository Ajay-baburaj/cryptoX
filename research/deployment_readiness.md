# CryptoX deployment readiness — 5 November 2026

**Historical pre-deployment audit.** The gaps below were identified before deployment. The dedicated CryptoX deployment now supersedes this status; see [deployment record](../deploy/DEPLOYED.md). Real user sign-in and notification receipt still need user confirmation.

## Verified

- Firebase project `cryptox-5a848` has Authentication initialized.
- Local allowlist contains `admin@cryptox.com`.
- Unauthenticated `/` redirects to login; private APIs return 401.
- Local Google default credentials are discoverable. This does not prove FCM send permission on the deployment server.
- Zero notification browsers were registered at the audit check; no real delivery test was possible.
- Paper strategy state and push registrations use atomic JSON replacement. They require a persistent writable disk.
- This application is paper trading only. No exchange orders are submitted.

## Fixes during review

- Push tests now count only HTTP 200 FCM responses as accepted. Missing credentials, HTTP errors, and network failures cannot report successful sends.
- Only an explicit FCM `UNREGISTERED` error removes a device; generic 404 responses do not.
- Firebase token validation explicitly checks the project issuer and a valid subject in addition to the library's signature, audience and time checks.
- Browser registration waits for an active service worker and supports a project public `vapidKey` in `config/firebase_web.json`.

FCM acceptance is not proof of a displayed notification. Sign in at `http://localhost:8000`, enable notifications, permit them in the browser/OS, then use the test button and confirm actual receipt. Use localhost rather than `0.0.0.0`. Test the deployed HTTPS origin separately because it has a separate browser registration.

## Match Nifty's architecture

Inspected `../Nifty/firebase.json`, `../Nifty/scripts/deploy_server.sh`, and `../Nifty/frontend/src/api.ts`.

Nifty's frontend is on Firebase Hosting. Its engine runs on GCP VM `nifty-bot` in project `optionx-512609`, zone `asia-south1-a`, managed by `nifty-engine`. The hosted frontend uses `VITE_API_BASE` and Firebase bearer tokens to reach the separate API.

CryptoX currently has neither a Firebase Hosting build/config nor a separate-backend API/auth connection. Simply uploading `frontend/` will not run Python or provide `/firebase-config`, `/api/session`, or `/api/ob1h`.

Before deploying with the same architecture:

1. Prepare a hosted frontend build with CryptoX public Firebase configuration, a backend HTTPS URL, Firebase token refresh, and bearer-authenticated API requests. Preserve local development support.
2. Add backend bearer verification, a strict hosted-origin CORS allowlist, and appropriate login-expiry handling. The current SameSite=Strict cookie design assumes the same origin.
3. Select the backend VM and install CryptoX as its own user/service, port, directory and persistent data location. Do not overwrite Nifty's engine or state. Verify VM capacity before sharing it.
4. Configure HTTPS/API routing, process restart on boot, logs, monitoring of stale market data, and backups of `data/paper/` (session secret, strategy state, trade history and browser tokens). Run one engine instance; JSON state does not support multiple replicas.
5. Provision the deployment service identity with FCM permission for CryptoX. Mac CLI login does not provision server credentials. Verify public market-data access from the chosen deployment region.
6. Configure Firebase authorized domains and verify the manual-admin account/sign-up policy. Generate/configure a project Web Push public key if required by the browser/provider; no private key belongs in the frontend.
7. Verify real login/logout, unauthorized API rejection, foreground/background notification receipt, restart state recovery, market-feed freshness, and no duplicate engine instances on the deployment environment.

Deployment is not performed by this audit. VM reuse, public hostname and infrastructure changes remain to be decided.

## Sources

- [Firebase web messaging setup](https://firebase.google.com/docs/cloud-messaging/web/get-started)
- [FCM error semantics](https://firebase.google.com/docs/cloud-messaging/error-codes)
- [Firebase ID token validation requirements](https://firebase.google.com/docs/auth/admin/verify-id-tokens)
- [Firebase Hosting cookie handling](https://firebase.google.com/docs/hosting/manage-cache): if choosing a Cloud Run/Functions rewrite instead, Hosting generally strips cookies except `__session`; the current `deltadesk_session` cookie would need adaptation. A request-driven backend also needs a separate design for the continuous trading loop and durable state.
