import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from aiohttp.test_utils import TestClient, TestServer

from execution.auth import AuthConfig, COOKIE, load_secret, make_session, read_session, safe_next, sign_in_allowed
from execution.ob1h_engine import Ob1hEngine
from execution.paper_engine import PaperEngine
from execution.manual_engine import ManualEngine
from execution.push import Notifier, PushStore, compose
from execution.server import build_app

TOKEN = "t" * 40  # push tokens must look plausible (20+ chars)


class FakeBackend:
    """Stands in for Google: verifies the fake ID tokens below and records pushes."""
    password = {"sign_in_provider": "password"}
    tokens = {
        "good": {"email": "Me@Example.com", "firebase": password},
        "stranger": {"email": "stranger@example.com", "firebase": password},
        "google-unverified": {"email": "me@example.com", "email_verified": False, "firebase": {"sign_in_provider": "google.com"}},
        "google-verified": {"email": "me@example.com", "email_verified": True, "firebase": {"sign_in_provider": "google.com"}},
    }

    def __init__(self):
        self.sent, self.dead = [], []

    def verify_id_token(self, token):
        if token not in self.tokens:
            raise ValueError("bad token")
        return self.tokens[token]

    def send_push(self, tokens, data):
        self.sent.append((list(tokens), dict(data)))
        dead = [t for t in tokens if t in self.dead]
        return {"sent": len(tokens) - len(dead), "failed": len(dead), "dead": dead}


SECRET = "s" * 48


def run_app(tmp_path: Path, scenario, backend=None, allowed=("me@example.com",)):
    backend = backend or FakeBackend()
    cfg = AuthConfig(backend, frozenset(allowed), {"apiKey": "k", "authDomain": "d", "projectId": "p", "appId": "a"}, SECRET)
    app = build_app(PaperEngine(trade_log_path=tmp_path / "t.csv"), Ob1hEngine(state_path=tmp_path / "s.json"),
                    auth=cfg, start_engines=False, push_tokens=tmp_path / "push.json",
                    manual=ManualEngine(state_path=tmp_path / 'manual.json'))

    async def go():
        async with TestClient(TestServer(app)) as client:
            return await scenario(client, backend, app, cfg)

    return asyncio.run(go())


async def login(client, token="good"):
    return await client.post("/api/session", json={"idToken": token})


def test_everything_is_locked_until_signed_in(tmp_path):
    async def scenario(client, backend, app, cfg):
        api = await client.get("/api/ob1h")
        assert api.status == 401 and (await api.json())["error"]
        for path in ("/api/summary", "/api/trades", "/api/positions"):
            assert (await client.get(path)).status == 401
        page = await client.get("/", allow_redirects=False)
        assert page.status == 302 and page.headers["Location"].startswith("/login?next=")
        assert (await client.get("/app.js", allow_redirects=False)).status == 302
        assert (await client.post("/api/push/register", json={"token": TOKEN})).status == 401
        assert (await client.post("/api/push/test")).status == 401
        # Only what the login screen itself needs is public.
        for path in ("/login", "/login.js", "/firebase-config", "/sw.js"):
            assert (await client.get(path)).status == 200, path
        assert (await client.get("/firebase-config")).headers["Cache-Control"] == "no-store"

    run_app(tmp_path, scenario)


def test_sign_in_sets_an_httponly_strict_cookie_and_unlocks_the_api(tmp_path):
    async def scenario(client, backend, app, cfg):
        response = await login(client)
        assert response.status == 200 and (await response.json())["email"] == "me@example.com"
        cookie = response.headers["Set-Cookie"].lower()
        assert COOKIE in cookie and "httponly" in cookie and "samesite=strict" in cookie
        api = await client.get("/api/ob1h")
        assert api.status == 200 and "account" in await api.json()
        assert (await client.get("/", allow_redirects=False)).status == 200
        assert (await client.get("/login", allow_redirects=False)).status == 302  # already signed in

    run_app(tmp_path, scenario)


def test_wrong_or_unlisted_accounts_get_no_session(tmp_path):
    async def scenario(client, backend, app, cfg):
        assert (await login(client, "forged")).status == 401
        denied = await login(client, "stranger")  # valid Firebase user, not on the allowlist
        assert denied.status == 403 and "Set-Cookie" not in denied.headers
        assert (await client.get("/api/ob1h")).status == 401
        assert (await client.post("/api/session", data="idToken=good")).status == 415
        assert (await client.post("/api/session", json={})).status == 400

    run_app(tmp_path, scenario)


def test_allowlist_is_rechecked_on_every_session_so_removal_locks_the_user_out(tmp_path):
    async def scenario(client, backend, app, cfg):
        await login(client)
        assert (await client.get("/api/ob1h")).status == 200
        cfg.allowed_emails = frozenset()
        assert (await client.get("/api/ob1h")).status == 401

    run_app(tmp_path, scenario)


def test_forged_and_tampered_cookies_are_rejected(tmp_path):
    async def scenario(client, backend, app, cfg):
        for bad in ("cookie-forged", "garbage", make_session("x" * 48, "me@example.com", 3600),  # wrong signing key
                    make_session(SECRET, "me@example.com", -10),  # expired
                    make_session(SECRET, "stranger@example.com", 3600)):  # validly signed but not allowlisted
            client.session.cookie_jar.update_cookies({COOKIE: bad})
            assert (await client.get("/api/ob1h")).status == 401, bad
        client.session.cookie_jar.update_cookies({COOKIE: make_session(SECRET, "me@example.com", 3600)})
        assert (await client.get("/api/ob1h")).status == 200

    run_app(tmp_path, scenario)


def test_logout_clears_the_session(tmp_path):
    async def scenario(client, backend, app, cfg):
        await login(client)
        out = await client.post("/logout", allow_redirects=False)
        assert out.status == 302 and out.headers["Location"] == "/login"
        client.session.cookie_jar.clear()
        assert (await client.get("/api/ob1h")).status == 401

    run_app(tmp_path, scenario)


def test_repeated_failures_are_rate_limited(tmp_path):
    async def scenario(client, backend, app, cfg):
        codes = [(await login(client, "forged")).status for _ in range(10)]
        assert codes[:8] == [401] * 8 and codes[8:] == [429, 429]
        assert (await login(client, "good")).status == 429  # even a correct login waits it out

    run_app(tmp_path, scenario)


def test_redirect_targets_cannot_leave_the_site():
    assert safe_next("/#trades") == "/#trades"
    for bad in ("//evil.example", "https://evil.example", "/\\evil", None, "", "javascript:alert(1)"):
        assert safe_next(bad) == "/"


def test_security_headers_are_present(tmp_path):
    async def scenario(client, backend, app, cfg):
        for response in (await client.get("/login"), await client.get("/api/ob1h")):
            assert response.headers["X-Frame-Options"] == "DENY"
            assert response.headers["X-Content-Type-Options"] == "nosniff"

    run_app(tmp_path, scenario)


# ---- push ------------------------------------------------------------------------------

def now_iso(seconds_ago=0):
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat()


def test_push_messages_for_entries_and_exits_only():
    entry = compose({"type": "entry", "side": "short", "price": 80794.0, "stop": 81344.5})
    assert entry["title"] == "SHORT opened · BTCUSDT" and "$80,794.00" in entry["body"] and "$81,344.50" in entry["body"]
    win = compose({"type": "exit", "side": "short", "price": 80100.0, "pnl": 21.3, "r": 0.43, "reason": "trailing_stop"})
    assert win["title"] == "SHORT closed · +$21.30 (+0.43R)" and "Trailing stop hit" in win["body"]
    loss = compose({"type": "exit", "side": "long", "price": 79000.0, "pnl": -54.1, "r": -1.08, "reason": "initial_stop"})
    assert loss["title"].startswith("LONG closed · -$54.10") and "Initial stop hit" in loss["body"]
    for noise in ("trail", "signal", "skipped"):
        assert compose({"type": noise, "side": "short"}) is None


def test_devices_register_get_notified_and_dead_tokens_are_pruned(tmp_path):
    async def scenario(client, backend, app, cfg):
        await login(client)
        assert (await client.post("/api/push/register", json={"token": "short"})).status == 400
        assert (await client.post("/api/push/register", json={"token": TOKEN})).status == 200
        dead = "d" * 40
        assert (await client.post("/api/push/register", json={"token": dead})).status == 200
        backend.dead = [dead]
        notifier = app["notifier"]
        await notifier.notify({"type": "entry", "time": now_iso(), "side": "long", "price": 100.0, "stop": 99.0})
        tokens, data = backend.sent[-1]
        assert set(tokens) == {TOKEN, dead} and data["title"] == "LONG opened · BTCUSDT"
        assert notifier.store.tokens() == [TOKEN]  # the dead one was pruned
        # Old events (restart catch-up) and non-trade events never notify.
        before = len(backend.sent)
        await notifier.notify({"type": "exit", "time": now_iso(3600), "side": "long", "price": 1.0, "pnl": 1.0})
        await notifier.notify({"type": "trail", "time": now_iso(), "side": "long", "stop": 1.0})
        assert len(backend.sent) == before
        assert (await client.post("/api/push/unregister", json={"token": TOKEN})).status == 200
        assert notifier.store.tokens() == []
        assert (await client.post("/api/push/test")).status == 200

    run_app(tmp_path, scenario)


def test_engine_events_reach_the_notifier_hook(tmp_path):
    async def scenario(client, backend, app, cfg):
        seen = []
        engine = app["ob1h"]
        engine.on_event = seen.append
        import numpy as np
        import pandas as pd
        bars = pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0, "segment": 0, "atr": 1.0},
                            index=pd.date_range("2026-01-01", periods=3, freq="1h", tz="UTC"))
        engine.strategy.load_bars(bars)
        engine._bar_limit_ns = 2**62
        engine.strategy.on_minute = lambda ts, o, h, l, c, trade=True: [{"type": "entry", "side": "long"}]
        minutes = pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0},
                               index=pd.date_range("2026-01-01", periods=1, freq="1min", tz="UTC"))
        engine._process(minutes, trade=True)
        assert seen == [{"type": "entry", "side": "long"}]
        engine.on_event = lambda e: 1 / 0  # a broken hook must not break trading
        engine._process(minutes, trade=True)

    run_app(tmp_path, scenario)


def test_session_cookie_signature_expiry_and_tamper_detection():
    token = make_session(SECRET, "me@example.com", 3600, now=1000.0)
    assert read_session(SECRET, token, now=1500.0) == "me@example.com"
    assert read_session(SECRET, token, now=1000.0 + 3601) is None  # expired
    assert read_session("other" * 10, token, now=1500.0) is None  # wrong key
    body, sig = token.rsplit(".", 1)
    assert read_session(SECRET, body + "." + sig[:-2] + "AA", now=1500.0) is None  # altered signature
    forged = make_session(SECRET, "attacker@example.com", 3600, now=1000.0).split(".")[0] + "." + sig
    assert read_session(SECRET, forged, now=1500.0) is None  # payload swapped under an old signature
    assert read_session(SECRET, None) is None and read_session(SECRET, "no-dot") is None


def test_sign_in_policy_matches_the_nifty_rules():
    allowed = frozenset({"me@example.com"})
    tokens = FakeBackend.tokens
    assert sign_in_allowed(tokens["good"], allowed) == "me@example.com"  # console-made password account
    assert sign_in_allowed(tokens["stranger"], allowed) is None  # not on the allowlist
    assert sign_in_allowed(tokens["google-unverified"], allowed) is None  # unverified non-password email
    assert sign_in_allowed(tokens["google-verified"], allowed) == "me@example.com"
    assert sign_in_allowed({"firebase": {"sign_in_provider": "password"}}, allowed) is None  # no email at all


def test_unverified_google_login_is_refused(tmp_path):
    async def scenario(client, backend, app, cfg):
        assert (await login(client, "google-unverified")).status == 403
        assert (await login(client, "google-verified")).status == 200

    run_app(tmp_path, scenario)


def test_signing_key_is_generated_once_and_kept_private(tmp_path):
    path = tmp_path / "nested" / "session_secret"
    first = load_secret(path)
    assert len(first) >= 48 and load_secret(path) == first
    assert oct(path.stat().st_mode & 0o777) == "0o600"


def test_hosted_bearer_auth_and_origin_allowlist(tmp_path, monkeypatch):
    monkeypatch.setenv('DASHBOARD_ALLOWED_ORIGINS','https://cryptox-5a848.web.app')
    async def scenario(client, backend, app, cfg):
        origin={'Origin':'https://cryptox-5a848.web.app'}
        pre=await client.options('/api/ob1h',headers=origin)
        assert pre.status==204
        assert pre.headers['Access-Control-Allow-Origin']==origin['Origin']
        assert (await client.options('/api/ob1h',headers={'Origin':'https://evil.example'})).status==403
        denied=await client.get('/api/ob1h',headers=origin)
        assert denied.status==401 and denied.headers['Access-Control-Allow-Origin']==origin['Origin']
        response=await client.get('/api/ob1h',headers={**origin,'Authorization':'Bearer good'})
        assert response.status==200
        assert (await client.get('/api/ob1h',headers={'Authorization':'Bearer stranger'})).status==403
        assert (await client.get('/api/ob1h',headers={'Authorization':'Bearer broken'})).status==401
        registered=await client.post('/api/push/register',headers={'Authorization':'Bearer good'},json={'token':TOKEN})
        assert registered.status==200 and app['notifier'].store.count_for('me@example.com')==1
    run_app(tmp_path,scenario)


def test_strategy_catalog_and_trade_ownership_labels(tmp_path):
    async def scenario(client,backend,app,cfg):
        await login(client)
        manual=app['manual']
        manual.process_quote(100.)
        position=manual.open({'side':'long','quantity':1})
        data=await (await client.get('/api/positions')).json()
        assert data['positions'][0]['strategy_id']=='manual_paper'
        catalog=await (await client.get('/api/strategies')).json()
        assert {s['strategy_id'] for s in catalog['strategies']}=={'ob1h_mitigation','ob15m_mitigation','ob5m_mitigation','manual_paper'}
        manual.close(position['id'])
        engine=app['engine']
        engine.minutes=pd.DataFrame({'open':100.,'high':101.,'low':99.,'close':100.,'volume':1.},
                                     index=pd.date_range('2026-01-01',periods=5,freq='min',tz='UTC'))
        engine.trades=pd.DataFrame([{'side':'long','signal_time':pd.Timestamp('2026-01-01',tz='UTC'),
            'entry_time':pd.Timestamp('2026-01-01',tz='UTC'),'exit_time':pd.Timestamp('2026-01-01 00:03',tz='UTC'),
            'entry':100.,'exit':105.,'stop':95.,'target':110.,'exit_reason':'target','risk_%':5.,
            'ret_net':0.05,'r_net':1.}])
        trades=await (await client.get('/api/trades')).json()
        names={t['strategy_name'] for t in trades['trades']}
        assert 'Manual paper trading' in names and 'OB rejection 1h/4h' in names
        assert (await client.get('/api/trades?limit=invalid')).status==400
    run_app(tmp_path,scenario)


def test_order_block_timeframe_endpoints(tmp_path):
    async def scenario(client, backend, app, cfg):
        await login(client)
        for tf, sid in (("1h", "ob1h_mitigation"), ("15m", "ob15m_mitigation"), ("5m", "ob5m_mitigation")):
            data = await (await client.get(f"/api/ob/{tf}")).json()
            assert data["strategy_id"] == sid and data["timeframe"] == tf
            assert data["config"]["timeframe_minutes"] == {"1h": 60, "15m": 15, "5m": 5}[tf]
        assert (await client.get("/api/ob/4h")).status == 404
    run_app(tmp_path, scenario)
