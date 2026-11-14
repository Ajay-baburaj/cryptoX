"""Frontend + paper-trading API in one process: `make paper` serves both on one port.

No API key is used anywhere here and no real orders are placed — this only reads public market
data and simulates trades. Every page and API route sits behind a Firebase email/password login
(auth.py) and the server will not start until Firebase is configured (`make firebase-check`).
Paper-trade entries/exits are pushed to registered browsers via FCM (push.py). It listens on
127.0.0.1 by default; set DASHBOARD_HOST=0.0.0.0 (with HTTPS or a tunnel in front) for other machines.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path

from aiohttp import web

from execution.auth import AuthConfig, add_auth
from execution.ob1h_engine import Ob1hEngine
from execution.paper_engine import PaperEngine
from execution.manual_engine import ManualEngine
from execution.push import Notifier, PushStore, add_push_routes


ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIR = ROOT / "frontend"


async def handle_summary(request: web.Request) -> web.Response:
    engine: PaperEngine = request.app["engine"]
    return web.json_response(engine.summary())


async def handle_positions(request: web.Request) -> web.Response:
    strategies = strategy_snapshots(request.app)
    return web.json_response({"positions": [p for s in strategies for p in s["positions"]]}, dumps=lambda o: json.dumps(o, default=float))


def strategy_snapshots(app):
    ob = app['ob1h'].snapshot(trade_limit=len(app['ob1h'].strategy.trades))
    ob['validation'] = 'Research found no edge after costs · paper observation only'
    ob['rules'] = 'First revisit of a 1h order block; long or short. Stop beyond block + 0.25 ATR; trails every closed 1h candle. Risk 0.5% of equity, max 3× notional. Fee 0.05% and slippage 0.02% per side.'
    ob['positions'] = [ob['position']] if ob['position'] else []
    return [ob, app['manual'].snapshot()]


async def handle_manual(request: web.Request) -> web.Response:
    engine = request.app['manual']
    if request.method == 'GET':
        return web.json_response(engine.snapshot())
    if request.content_type != 'application/json':
        return web.json_response({'error': 'Expected JSON'}, status=415)
    try:
        data = await request.json()
        if not isinstance(data, dict):
            raise ValueError('Expected a JSON object')
        async with engine._lock:
            action = request.match_info['action']
            if action == 'open':
                engine.open(data)
            elif action == 'update':
                engine.update(data.get('position_id'), data)
            else:
                engine.close(data.get('position_id'))
        return web.json_response(engine.snapshot())
    except ValueError as exc:
        return web.json_response({'error': str(exc)}, status=400)


async def handle_strategies(request):
    return web.json_response({'strategies': strategy_snapshots(request.app)}, dumps=lambda o: json.dumps(o, default=float))


async def handle_ob1h(request: web.Request) -> web.Response:
    engine: Ob1hEngine = request.app["ob1h"]
    return web.json_response(engine.snapshot(), dumps=lambda o: json.dumps(o, default=float))


async def handle_index(request: web.Request) -> web.FileResponse:
    return web.FileResponse(FRONTEND_DIR / "index.html")


async def handle_trades(request: web.Request) -> web.Response:
    try:
        limit = max(1, min(1000, int(request.query.get('limit', '200'))))
    except ValueError:
        raise web.HTTPBadRequest(text='Invalid limit')
    trades = [t for s in strategy_snapshots(request.app) for t in s['trades']]
    trades.sort(key=lambda t: t['exit_time'], reverse=True)
    return web.json_response({'trades': trades[:limit]}, dumps=lambda o: json.dumps(o, default=float))


async def start_engine(app: web.Application) -> None:
    engine: PaperEngine = app["engine"]
    app["engine_task"] = asyncio.create_task(engine.run())
    app["ob1h_task"] = asyncio.create_task(app["ob1h"].run())
    app['manual_task'] = asyncio.create_task(app['manual'].run())


async def stop_engine(app: web.Application) -> None:
    tasks = []
    for name in ("engine_task", "ob1h_task", "manual_task"):
        task: asyncio.Task | None = app.get(name)
        if task is not None:
            task.cancel()
            tasks.append(task)
    await asyncio.gather(*tasks, return_exceptions=True)


def build_app(engine: PaperEngine | None = None, ob1h: Ob1hEngine | None = None,
              auth: AuthConfig | None = None, start_engines: bool = True,
              push_tokens: Path | None = None, manual: ManualEngine | None = None) -> web.Application:
    app = web.Application()
    auth = auth or AuthConfig.from_env()  # fails closed when login isn't configured
    add_auth(app, auth)
    app["engine"] = engine or PaperEngine()
    app["ob1h"] = ob1h or Ob1hEngine()
    app['manual'] = manual or ManualEngine()
    notifier = Notifier(auth.backend, PushStore(push_tokens or ROOT / "data/paper/push_tokens.json"))
    app["notifier"] = notifier
    app["ob1h"].on_event = lambda event: notifier.emit({**event, 'strategy_id': 'ob1h_mitigation', 'strategy_name': '1H order-block mitigation', 'symbol': 'BTCUSDT'})
    add_push_routes(app, auth, notifier)
    app.router.add_get("/api/summary", handle_summary)
    app.router.add_get("/api/positions", handle_positions)
    app.router.add_get("/api/trades", handle_trades)
    app.router.add_get("/api/ob1h", handle_ob1h)
    app.router.add_get("/api/strategies", handle_strategies)
    app.router.add_get('/api/manual', handle_manual)
    app.router.add_post('/api/manual/{action:open|update|close}', handle_manual)
    app.router.add_get("/", handle_index)
    app.router.add_static("/", FRONTEND_DIR, show_index=False)
    if start_engines:
        app.on_startup.append(start_engine)
        app.on_cleanup.append(stop_engine)
    return app


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app = build_app()
    web.run_app(app, host=os.environ.get("DASHBOARD_HOST", "127.0.0.1"), port=int(os.environ.get("DASHBOARD_PORT", "8000")))


if __name__ == "__main__":
    main()
