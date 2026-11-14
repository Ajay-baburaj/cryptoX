"""Firebase Cloud Messaging web push for paper-trade events.

The dashboard registers a device token (``/api/push/register``); when the strategy opens or closes a
paper trade the engine calls ``Notifier.notify`` and every registered browser gets a push. Messages are
data-only; ``frontend/sw.js`` turns them into notifications, so no click-link configuration is needed.
Tokens live in ``data/paper/push_tokens.json`` and are pruned when FCM reports them dead.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from aiohttp import web

from execution.auth import AuthConfig, COOKIE

LOG = logging.getLogger("push")
MAX_EVENT_AGE = 15 * 60  # never notify about something that happened more than 15 minutes ago (restart catch-up)
MAX_TOKENS = 20


class PushStore:
    def __init__(self, path: Path):
        self.path = Path(path)

    def _read(self) -> dict[str, dict]:
        try:
            return json.loads(self.path.read_text())
        except (FileNotFoundError, ValueError):
            return {}

    def _write(self, data: dict[str, dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data))
        os.replace(tmp, self.path)

    def add(self, token: str, email: str) -> None:
        data = self._read()
        data[token] = {"email": email, "created": datetime.now(timezone.utc).isoformat()}
        while len(data) > MAX_TOKENS:  # oldest out
            data.pop(min(data, key=lambda t: data[t]["created"]))
        self._write(data)

    def remove(self, tokens: list[str]) -> None:
        data = self._read()
        for token in tokens:
            data.pop(token, None)
        self._write(data)

    def tokens(self) -> list[str]:
        return list(self._read())

    def count_for(self, email: str) -> int:
        return sum(1 for v in self._read().values() if v.get("email") == email)


def _usd(v: float) -> str:
    return f"{'-' if v < 0 else '+'}${abs(v):,.2f}"


def compose(event: dict) -> dict[str, str] | None:
    """Notification text for a strategy event, or None when it isn't worth a push."""
    side = str(event.get("side", "")).upper()
    strategy = event.get('strategy_name')
    suffix = f" · {strategy}" if strategy else ''
    tag = event.get('strategy_id', 'ob1h')
    if event.get("type") == "entry":
        stop = f"stop-loss ${event['stop']:,.2f}" if event.get('stop') is not None else 'scheduled exit at 23:00 UTC · no stop-loss'
        return {"title": f"{side} opened · {event.get('symbol', 'BTCUSDT')}{suffix}", "tag": f"{tag}-entry", "url": "/#strategies",
                "body": f"Filled at ${event['price']:,.2f} · {stop}"}
    if event.get("type") == "exit":
        reason = {"initial_stop": "Initial stop hit", "trailing_stop": "Trailing stop hit"}.get(event.get("reason"), "Closed")
        r = f" ({event['r']:+.2f}R)" if event.get("r") is not None else ""
        return {"title": f"{side} closed · {_usd(event['pnl'])}{r}{suffix}", "tag": f"{tag}-exit", "url": "/#trades",
                "body": f"{reason} at ${event['price']:,.2f}"}
    return None


@dataclass
class Notifier:
    backend: object
    store: PushStore
    _tasks: set = field(default_factory=set)

    def emit(self, event: dict) -> None:
        """Sync hook for the engine: schedule the push without blocking the trading loop."""
        try:
            task = asyncio.get_running_loop().create_task(self.notify(event))
        except RuntimeError:
            return
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def notify(self, event: dict) -> None:
        message = compose(event)
        if message is None:
            return
        try:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(event["time"])).total_seconds()
        except (KeyError, ValueError):
            age = 0
        if age > MAX_EVENT_AGE:
            return
        await self.send(message)

    async def send(self, message: dict[str, str]) -> dict:
        tokens = self.store.tokens()
        if not tokens:
            return {"sent": 0, "failed": 0, "registered": 0}
        try:
            result = await asyncio.to_thread(self.backend.send_push, tokens, message)
        except Exception:
            LOG.exception("push delivery failed")
            return {"sent": 0, "failed": len(tokens), "registered": len(tokens)}
        if result["dead"]:
            self.store.remove(result["dead"])
        return {"sent": result["sent"], "failed": result["failed"], "registered": len(tokens)}


def add_push_routes(app: web.Application, cfg: AuthConfig, notifier: Notifier) -> None:
    async def who(request: web.Request) -> str:
        return request.get("auth_email") or cfg.session_email(request.cookies.get(COOKIE)) or ""

    async def token_from(request: web.Request) -> str | None:
        if request.content_type != "application/json":
            return None
        try:
            token = (await request.json())["token"]
        except (ValueError, KeyError, TypeError):
            return None
        return token if isinstance(token, str) and 20 <= len(token) <= 4096 else None

    async def register(request: web.Request) -> web.Response:
        token = await token_from(request)
        if token is None:
            return web.json_response({"error": "valid token required"}, status=400)
        notifier.store.add(token, await who(request))
        return web.json_response({"ok": True})

    async def unregister(request: web.Request) -> web.Response:
        token = await token_from(request)
        if token is None:
            return web.json_response({"error": "valid token required"}, status=400)
        notifier.store.remove([token])
        return web.json_response({"ok": True})

    async def test(request: web.Request) -> web.Response:
        result = await notifier.send({"title": "Delta Desk test", "body": "Push notifications are working.",
                                    "tag": "ob1h-test", "url": "/"})
        return web.json_response(result)

    app.router.add_post("/api/push/register", register)
    app.router.add_post("/api/push/unregister", unregister)
    app.router.add_post("/api/push/test", test)
