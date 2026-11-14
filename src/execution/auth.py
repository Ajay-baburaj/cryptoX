"""Firebase Authentication (email + password) for the dashboard and its API.

Same model as the Nifty app: the login page signs in with the Firebase web SDK, the server verifies the
ID token against Google's public keys (no service-account key), and only emails on an allowlist get in.
After a successful check the server sets its own signed session cookie (HttpOnly, SameSite=Strict, Secure
over HTTPS) so pages and API calls need no token plumbing. Every route needs a session except the
login screen's own files: browsers are redirected to ``/login``, API callers get ``401``.

Configuration:
  config/firebase_web.json    the Firebase web-app config (public values; template: firebase_web.example.json)
  DASHBOARD_ALLOWED_EMAILS    comma-separated emails allowed to sign in (``.env`` or environment; required)
  DASHBOARD_SESSION_HOURS     session length, default 12
  data/paper/session_secret   signing key, created automatically on first start

The server will not start until the config and allowlist exist, so it cannot run open by accident.
Accounts made by the owner in the Firebase console (email/password) are not "verified" emails; like Nifty,
the allowlist is the control for those and self sign-up should stay disabled on the project. Removing an
email from the allowlist locks it out immediately; disabling the Firebase user takes effect when its
session expires. Reaching the dashboard from another machine needs HTTPS (or a tunnel).
"""
from __future__ import annotations

import asyncio
import base64
import hmac
import hashlib
import json
import os
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol
from urllib.parse import quote

from aiohttp import web

ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIR = ROOT / "frontend"
COOKIE = "deltadesk_session"
MAX_FAILURES = 8
FAILURE_WINDOW = 300.0
PUBLIC_PATHS = {"/login", "/login.js", "/firebase-config", "/api/session", "/logout", "/sw.js", "/runtime-config.js", "/runtime.js", "/hosted-auth.js"}
REQUIRED_WEB_KEYS = ("apiKey", "authDomain", "projectId", "appId")


class Backend(Protocol):
    def verify_id_token(self, token: str) -> dict: ...
    def send_push(self, tokens: list[str], data: dict[str, str]) -> dict: ...


# ---- sessions --------------------------------------------------------------------------

def _sign(secret: str, payload: str) -> str:
    return base64.urlsafe_b64encode(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest()).decode().rstrip("=")


def make_session(secret: str, email: str, ttl_seconds: float, now: float | None = None) -> str:
    expires = int((now if now is not None else time.time()) + ttl_seconds)
    payload = f"{email}|{expires}|{secrets.token_urlsafe(8)}"
    return f"{base64.urlsafe_b64encode(payload.encode()).decode().rstrip('=')}.{_sign(secret, payload)}"


def read_session(secret: str, token: str | None, now: float | None = None) -> str | None:
    """Email a valid, unexpired cookie belongs to, else None."""
    if not token or "." not in token:
        return None
    body, sig = token.rsplit(".", 1)
    try:
        payload = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)).decode()
        email, expires, _ = payload.rsplit("|", 2)
        if not hmac.compare_digest(sig, _sign(secret, payload)):
            return None
        if int(expires) < (now if now is not None else time.time()):
            return None
    except (ValueError, UnicodeDecodeError):
        return None
    return email


def safe_next(target: str | None) -> str:
    """Only same-site relative redirects after login (no open redirect)."""
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target and "\n" not in target:
        return target
    return "/"


def sign_in_allowed(claims: dict, allowed: frozenset[str]) -> str | None:
    """Email to admit, or None. Verified emails and console-created password accounts count as verified."""
    email = str(claims.get("email", "")).lower()
    provider = (claims.get("firebase") or {}).get("sign_in_provider", "")
    verified = bool(claims.get("email_verified")) or provider == "password"
    return email if email and verified and email in allowed else None


# ---- configuration ---------------------------------------------------------------------

@dataclass
class AuthConfig:
    backend: Backend
    allowed_emails: frozenset[str]
    web_config: dict
    secret: str
    session_hours: float = 12.0
    failures: dict[str, list[float]] = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> "AuthConfig":
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
        problems: list[str] = []
        allowed = frozenset(e.strip().lower() for e in os.environ.get("DASHBOARD_ALLOWED_EMAILS", "").split(",") if e.strip())
        if not allowed:
            problems.append("DASHBOARD_ALLOWED_EMAILS is empty (add DASHBOARD_ALLOWED_EMAILS=you@example.com to .env)")
        web_path = ROOT / "config/firebase_web.json"
        web_config: dict = {}
        if web_path.is_file():
            web_config = json.loads(web_path.read_text())
            missing = [k for k in REQUIRED_WEB_KEYS if not web_config.get(k)]
            if missing:
                problems.append(f"config/firebase_web.json is missing {', '.join(missing)}")
        else:
            problems.append("config/firebase_web.json not found (copy config/firebase_web.example.json and fill it in)")
        if problems:
            raise SystemExit("Dashboard login is not configured:\n  - " + "\n  - ".join(problems)
                             + "\nSee README 'Firebase login and push', then run `make firebase-check`.")
        from execution.firebase_backend import FirebaseBackend

        return cls(FirebaseBackend(web_config["projectId"]), allowed, web_config, load_secret(ROOT / "data/paper/session_secret"),
                   float(os.environ.get("DASHBOARD_SESSION_HOURS", "12")))

    def blocked(self, ip: str, now: float) -> bool:
        recent = [t for t in self.failures.get(ip, []) if now - t < FAILURE_WINDOW]
        self.failures[ip] = recent
        return len(recent) >= MAX_FAILURES

    def record_failure(self, ip: str, now: float) -> None:
        self.failures.setdefault(ip, []).append(now)

    def session_email(self, cookie: str | None) -> str | None:
        """Email of a valid session whose owner is still on the allowlist, else None."""
        email = read_session(self.secret, cookie)
        return email if email and email.lower() in self.allowed_emails else None


def load_secret(path: Path) -> str:
    """The cookie-signing key; generated once and kept (0600) so sessions survive restarts."""
    if path.is_file() and len(path.read_text().strip()) >= 32:
        return path.read_text().strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    secret = secrets.token_urlsafe(48)
    path.write_text(secret)
    os.chmod(path, 0o600)
    return secret


def add_auth(app: web.Application, cfg: AuthConfig) -> None:
    ttl = cfg.session_hours * 3600
    origins = {s.strip() for s in os.environ.get("DASHBOARD_ALLOWED_ORIGINS", "").split(",") if s.strip()}

    @web.middleware
    async def headers_middleware(request: web.Request, handler):
        try:
            if request.method == "OPTIONS" and request.path.startswith("/api/"):
                response = web.Response(status=204 if request.headers.get("Origin") in origins else 403)
            else:
                response = await handler(request)
        except web.HTTPException as exc:
            response = exc
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        if request.headers.get("Origin") in origins and request.path.startswith("/api/"):
            response.headers["Access-Control-Allow-Origin"] = request.headers["Origin"]
            response.headers["Vary"] = "Origin"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
        if request.path.startswith("/api/") or request.path in ("/login", "/firebase-config"):
            response.headers["Cache-Control"] = "no-store"
        if isinstance(response, web.HTTPException):
            raise response
        return response

    @web.middleware
    async def auth_middleware(request: web.Request, handler):
        if request.path.startswith("/api/") and request.headers.get("Authorization"):
            header = request.headers["Authorization"]
            if not header.startswith("Bearer ") or len(header) > 16384:
                return web.json_response({"error": "invalid authorization"}, status=401)
            try:
                claims = await asyncio.to_thread(cfg.backend.verify_id_token, header[7:])
            except Exception:
                return web.json_response({"error": "invalid or expired token"}, status=401)
            email = sign_in_allowed(claims, cfg.allowed_emails)
            if email is None:
                return web.json_response({"error": "account not allowed"}, status=403)
            request["auth_email"] = email
            return await handler(request)
        if request.path in PUBLIC_PATHS:
            return await handler(request)
        if cfg.session_email(request.cookies.get(COOKIE)) is None:
            if request.path.startswith("/api/"):
                return web.json_response({"error": "authentication required"}, status=401)
            target = request.path_qs if request.method == "GET" else "/"
            raise web.HTTPFound(f"/login?next={quote(safe_next(target), safe='')}")
        return await handler(request)

    async def login_page(request: web.Request) -> web.StreamResponse:
        if cfg.session_email(request.cookies.get(COOKIE)):
            raise web.HTTPFound(safe_next(request.query.get("next")))
        return web.FileResponse(FRONTEND_DIR / "login.html")

    async def login_script(request: web.Request) -> web.StreamResponse:
        return web.FileResponse(FRONTEND_DIR / "login.js")

    async def service_worker(request: web.Request) -> web.StreamResponse:
        return web.FileResponse(FRONTEND_DIR / "sw.js", headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"})

    async def firebase_config(request: web.Request) -> web.Response:
        return web.json_response(cfg.web_config)  # web app config values are public by design

    async def create_session(request: web.Request) -> web.Response:
        ip, now = request.remote or "unknown", time.time()
        if cfg.blocked(ip, now):
            return web.json_response({"error": "Too many failed attempts. Try again in a few minutes."}, status=429,
                                     headers={"Retry-After": str(int(FAILURE_WINDOW))})
        if request.content_type != "application/json":  # also keeps this endpoint un-postable from other sites
            return web.json_response({"error": "expected JSON"}, status=415)
        try:
            id_token = str((await request.json())["idToken"])
        except (ValueError, KeyError, TypeError):
            return web.json_response({"error": "idToken required"}, status=400)
        try:
            claims = await asyncio.to_thread(cfg.backend.verify_id_token, id_token)
        except Exception:
            cfg.record_failure(ip, now)
            return web.json_response({"error": "Sign-in could not be verified."}, status=401)
        email = sign_in_allowed(claims, cfg.allowed_emails)
        if email is None:
            cfg.record_failure(ip, now)
            return web.json_response({"error": "This account is not allowed to use this dashboard."}, status=403)
        cfg.failures.pop(ip, None)
        response = web.json_response({"ok": True, "email": email})
        response.set_cookie(COOKIE, make_session(cfg.secret, email, ttl), max_age=int(ttl), httponly=True,
                            samesite="Strict", path="/",
                            secure=request.secure or request.headers.get("X-Forwarded-Proto") == "https")
        return response

    async def logout(request: web.Request) -> web.Response:
        response = web.HTTPFound("/login")
        response.del_cookie(COOKIE, path="/")
        raise response

    app.middlewares.insert(0, headers_middleware)
    app.middlewares.append(auth_middleware)
    app.router.add_get("/login", login_page)
    app.router.add_get("/login.js", login_script)
    app.router.add_get("/sw.js", service_worker)
    app.router.add_get("/firebase-config", firebase_config)
    app.router.add_post("/api/session", create_session)
    app.router.add_post("/logout", logout)
