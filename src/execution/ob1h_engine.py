"""Live paper-trading engine for the order-block mitigation strategy (1h, 15m or 5m blocks).

One engine per block timeframe; each keeps its own paper account and state file.

Reads Binance spot BTCUSDT candles from the public ``data-api.binance.vision`` endpoint, the same
feed as the dashboard chart (no API key; nothing is ever sent to an exchange). Every poll it
processes each newly CLOSED 1m candle through ``strategy.ob_mitigation_1h.OB1hStrategy``, the same
state machine the backtest uses. State (balance, open position, trades, consumed blocks) is saved
to ``data/paper/ob1h_state.json`` after every batch, so a restart resumes where it left off.

On the very first start it trades forward only: blocks already revisited are marked used and no
past trade is invented.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass, field, asdict
from pathlib import Path

import aiohttp
import numpy as np
import pandas as pd

from strategy.ob_mitigation_1h import Config, OB1hStrategy, NS_MIN, load_config, make_bars

LOG = logging.getLogger("ob1h_engine")
REST = "https://data-api.binance.vision"
MAX_CATCHUP = pd.Timedelta(days=3)


def _klines_frame(rows: list, close_index: bool) -> pd.DataFrame:
    frame = pd.DataFrame(rows).iloc[:, :6]
    frame.columns = ["t", "open", "high", "low", "close", "volume"]
    frame[["open", "high", "low", "close", "volume"]] = frame[["open", "high", "low", "close", "volume"]].astype(float)
    frame["t"] = pd.to_datetime(frame["t"], unit="ms", utc=True)
    return frame.set_index("t")


@dataclass
class Ob1hEngine:
    cfg: Config = field(default_factory=load_config)
    state_path: Path = field(default_factory=lambda: Path("data/paper/ob1h_state.json"))
    poll_seconds: int = 15
    on_event: Callable[[dict], None] | None = None  # e.g. push notifications on entry / exit
    strategy_id: str = "ob1h_mitigation"
    strategy_name: str = "1H order-block mitigation"

    strategy: OB1hStrategy = field(init=False)
    mark_price: float | None = field(default=None, init=False)
    last_update: pd.Timestamp | None = field(default=None, init=False)
    started_at: str | None = field(default=None, init=False)
    status: str = field(default="starting", init=False)
    last_minute_ns: int = field(default=0, init=False)
    _bar_limit_ns: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        self.strategy = OB1hStrategy(self.cfg)
        self.tf_minutes = int(self.cfg.timeframe_minutes)
        self.tf_ns = self.tf_minutes * NS_MIN
        self.interval = "1h" if self.tf_minutes == 60 else f"{self.tf_minutes}m"

    # ---- data --------------------------------------------------------------------------

    async def _get(self, session: aiohttp.ClientSession, params: dict) -> list:
        async with session.get(f"{REST}/api/v3/klines", params={"symbol": self.cfg.symbol, **params},
                               timeout=aiohttp.ClientTimeout(total=20)) as resp:
            body = await resp.json()
        if not isinstance(body, list):
            raise RuntimeError(f"Binance klines failed: {body}")
        return body

    async def _refresh_bars(self, session: aiohttp.ClientSession) -> None:
        rows = await self._get(session, {"interval": self.interval, "limit": 1000})
        frame = _klines_frame(rows, True)
        now = pd.Timestamp.now(tz="UTC")
        step = pd.Timedelta(minutes=self.tf_minutes)
        frame = frame[frame.index + step <= now]  # closed candles only
        frame.index = frame.index + step          # label by close time
        self.strategy.load_bars(make_bars(frame, self.tf_minutes))
        self._bar_limit_ns = int(self.strategy.bar_ns[-1]) + self.tf_ns

    async def _minutes_since(self, session: aiohttp.ClientSession, start_ns: int) -> pd.DataFrame:
        """Closed 1m candles with open time >= start_ns; also refreshes the mark price."""
        out = []
        cursor = start_ns
        while True:
            rows = await self._get(session, {"interval": "1m", "limit": 1000, "startTime": cursor // 1_000_000})
            if not rows:
                break
            out.append(_klines_frame(rows, False))
            if len(rows) < 1000:
                break
            cursor = int(out[-1].index[-1].value) + NS_MIN
        frame = pd.concat(out) if out else pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        if len(frame):
            self.mark_price = float(frame["close"].iloc[-1])  # includes the still-forming candle
        now = pd.Timestamp.now(tz="UTC")
        return frame[frame.index + pd.Timedelta(minutes=1) <= now]

    # ---- processing --------------------------------------------------------------------

    def _process(self, minutes: pd.DataFrame, trade: bool) -> None:
        s = self.strategy
        for ts, row in zip(minutes.index.as_unit("ns").asi8, minutes[["open", "high", "low", "close"]].to_numpy()):
            if int(ts) >= self._bar_limit_ns:
                break  # wait for the bar that closed to be published before using later minutes
            for event in s.on_minute(int(ts), *row, trade=trade):
                LOG.info("%s %s", self.strategy_id, event)
                if self.on_event is not None:
                    try:
                        self.on_event(event)
                    except Exception:  # a notification problem must never stop the trading loop
                        LOG.exception("on_event hook failed")
            self.last_minute_ns = int(ts)

    async def _start(self, session: aiohttp.ClientSession) -> None:
        await self._refresh_bars(session)
        s = self.strategy
        if self.state_path.exists():
            saved = json.loads(self.state_path.read_text())
            s.from_state(saved["strategy"])
            self.last_minute_ns = saved["last_minute_ns"]
            self.started_at = saved["started_at"]
            gap = pd.Timestamp.now(tz="UTC") - pd.Timestamp(self.last_minute_ns, tz="UTC")
            if gap > MAX_CATCHUP:  # too stale to replay: re-baseline instead of inventing old trades
                LOG.warning("saved state is %s old; re-baselining blocks and skipping the gap", gap)
                s.baseline(int(s.bar_ns[-1]))
                self.last_minute_ns = int(s.bar_ns[-1]) - NS_MIN
                s.prev_ts = 0
        else:
            self.started_at = pd.Timestamp.now(tz="UTC").isoformat()
            last_close = int(s.bar_ns[-1])
            s.baseline(last_close)
            s.trail_cursor_ns = last_close
            self.last_minute_ns = last_close - NS_MIN
        minutes = await self._minutes_since(session, self.last_minute_ns + NS_MIN)
        first_run = not self.state_path.exists()
        self._process(minutes, trade=not first_run)  # first run: only learn which blocks the last partial hour used
        if first_run:
            s.pending = None
        self._save()
        self.status = "ok"
        self.last_update = pd.Timestamp.now(tz="UTC")

    async def _tick(self, session: aiohttp.ClientSession) -> None:
        if pd.Timestamp.now(tz="UTC").value >= self._bar_limit_ns:
            await self._refresh_bars(session)
        minutes = await self._minutes_since(session, self.last_minute_ns + NS_MIN)
        self._process(minutes, trade=True)
        if len(minutes):
            self._save()
        self.status = "ok"
        self.last_update = pd.Timestamp.now(tz="UTC")

    def _save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"strategy": self.strategy.to_state(), "last_minute_ns": self.last_minute_ns,
                   "started_at": self.started_at}
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, default=float))
        os.replace(tmp, self.state_path)

    async def run(self) -> None:
        started = False
        async with aiohttp.ClientSession() as session:
            while True:
                try:
                    if not started:
                        await self._start(session)
                        started = True
                    else:
                        await self._tick(session)
                except Exception:
                    LOG.exception("%s engine tick failed; retrying shortly", self.strategy_id)
                    self.status = "degraded"
                    await asyncio.sleep(5)
                    continue
                await asyncio.sleep(self.poll_seconds)

    # ---- read-only view for the API ----------------------------------------------------

    def snapshot(self, trade_limit: int = 200) -> dict:
        s = self.strategy
        price = self.mark_price
        now_ns = max(s.prev_ts, self.last_minute_ns) or (int(s.bar_ns[-1]) if len(s.bar_ns) else 0)
        position = None
        if s.position is not None:
            p = dict(s.position)
            u = s.unrealized(price) if price else None
            p.pop("entry_ns", None)
            p["mark_price"] = price
            p["unrealized_pnl"] = u["pnl"] if u else None
            p["unrealized_pct"] = u["pnl_pct"] if u else None
            p["unrealized_r"] = u["r"] if u else None
            p["risk_to_stop_pct"] = abs(price - p["stop"]) / price * 100 if price else None
            position = p
        equity = s.balance + ((position or {}).get("unrealized_pnl") or 0.0)
        curve = [{"time": self.started_at, "balance": s.cfg.start_balance}]
        curve += [{"time": t["exit_time"], "balance": t["balance_after"]} for t in s.trades]
        st = s.stats()
        if st["profit_factor"] == float("inf"):
            st["profit_factor"] = None
        identity = {"strategy_id": self.strategy_id, "strategy_name": self.strategy_name,
                    "symbol": self.cfg.symbol, "venue": "Binance Spot", "currency": "USDT",
                    "timeframe": self.interval}
        if position:
            position.update(identity)
        return {
            **identity,
            "status": self.status,
            "last_update": self.last_update.isoformat() if self.last_update is not None else None,
            "started_at": self.started_at,
            "symbol": s.cfg.symbol,
            "mark_price": price,
            "config": asdict(s.cfg),
            "account": {"start_balance": s.cfg.start_balance, "balance": s.balance, "equity": equity,
                        "pnl": equity - s.cfg.start_balance, "pnl_pct": (equity / s.cfg.start_balance - 1) * 100},
            "stats": st,
            "position": position,
            "watchlist": s.watchlist(now_ns, price) if now_ns else [],
            "trades": [{**t, **identity} for t in list(reversed(s.trades))[:trade_limit]],
            "events": list(reversed(s.events))[:30],
            "equity_curve": curve,
        }
