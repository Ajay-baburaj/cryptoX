"""Live paper-trading engine for the 1h/4h order-block rejection strategy.

Polls Delta's public REST API for 1-minute BTCUSD candles (no API key needed, nothing is
traded for real) and reruns the exact backtest pipeline from ``strategy.ob_rejection``
(``strategy_events`` + ``simulate``) over a rolling window on every tick. A trade whose exit
lands on the newest available minute, with reason ``data_gap``, is still open in the real
backtest sense (no further data to resolve it) — live, that is exactly "still running", so it
is reported as the open position with the live price marking it to market. Reusing the
backtest functions directly means live results use identical entry/exit mechanics and fees,
so there is nothing separate to drift out of sync with the validated backtest.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path

import aiohttp
import pandas as pd

from strategy.ob_rejection import MinutePath, StrategyConfig, clean_minutes, monthly, simulate, strategy_events


LOG = logging.getLogger("paper_engine")
REST_BASE = "https://api.india.delta.exchange"
MAX_CANDLES_PER_REQUEST = 4000  # Delta's REST cap, independent of the requested range


@dataclass
class PaperEngine:
    symbol: str = "BTCUSD"
    strategy_config: StrategyConfig = field(default_factory=StrategyConfig)
    starting_balance: float = 1_000_000.0  # INR, matches the dashboard's original preview figure
    warmup_days: int = 45  # >= the 4h EMA200 lookback (~33 days) plus margin
    rolling_window_days: int = 60
    poll_seconds: int = 60
    trade_log_path: Path = field(default_factory=lambda: Path("data/paper/trades.csv"))

    minutes: pd.DataFrame = field(default_factory=pd.DataFrame, init=False)
    trades: pd.DataFrame = field(default_factory=pd.DataFrame, init=False)
    mark_price: float | None = field(default=None, init=False)
    last_update: pd.Timestamp | None = field(default=None, init=False)
    status: str = field(default="starting", init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    async def _fetch_candles(self, session: aiohttp.ClientSession, start: int, end: int) -> list[dict]:
        url = f"{REST_BASE}/v2/history/candles"
        out: list[dict] = []
        s = start
        while s < end:
            e = min(s + MAX_CANDLES_PER_REQUEST * 60, end)
            params = {"resolution": "1m", "symbol": self.symbol, "start": str(s), "end": str(e)}
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                body = await resp.json()
            if not body.get("success"):
                raise RuntimeError(f"Delta candle fetch failed: {body.get('error')}")
            out.extend(body["result"])
            s = e
        return out

    async def _fetch_ticker(self, session: aiohttp.ClientSession) -> float | None:
        try:
            async with session.get(f"{REST_BASE}/v2/tickers/{self.symbol}",
                                    timeout=aiohttp.ClientTimeout(total=10)) as resp:
                body = await resp.json()
            return float(body["result"]["close"])
        except Exception:  # network hiccup; keep the last known mark price
            return self.mark_price

    def _to_frame(self, raw: list[dict]) -> pd.DataFrame:
        frame = pd.DataFrame(raw)
        if frame.empty:
            return frame
        frame["minute"] = pd.to_datetime(frame["time"], unit="s", utc=True)
        frame = frame.set_index("minute")[["open", "high", "low", "close", "volume"]].astype(float)
        return frame.sort_index()

    async def seed(self, session: aiohttp.ClientSession) -> None:
        """Fetch enough history to warm up every indicator before the first signal check."""
        now = pd.Timestamp.utcnow()
        start = int((now - pd.Timedelta(days=self.warmup_days)).timestamp())
        end = int(now.timestamp())
        raw = await self._fetch_candles(session, start, end)
        self.minutes = self._to_frame(raw)
        LOG.info("seeded %d one-minute candles (%s to %s)", len(self.minutes),
                  self.minutes.index.min(), self.minutes.index.max())
        self.mark_price = await self._fetch_ticker(session)
        self._load_trade_log()
        await self._recompute()

    def _load_trade_log(self) -> None:
        if self.trade_log_path.exists():
            self.trades = pd.read_csv(self.trade_log_path, parse_dates=["signal_time", "entry_time", "exit_time"])
            for col in ("signal_time", "entry_time", "exit_time"):
                self.trades[col] = pd.to_datetime(self.trades[col], utc=True)

    def _persist_new_trades(self, computed: pd.DataFrame) -> None:
        """Append trades that are genuinely closed (not the live open position) to the log."""
        if computed.empty:
            return
        last_minute = self.minutes.index[-1]
        closed = computed[(computed["exit_reason"] != "data_gap") | (computed["exit_time"] < last_minute)]
        known = set(self.trades["signal_time"]) if not self.trades.empty else set()
        new_rows = closed[~closed["signal_time"].isin(known)]
        if new_rows.empty:
            return
        self.trade_log_path.parent.mkdir(parents=True, exist_ok=True)
        new_rows.to_csv(self.trade_log_path, mode="a", header=not self.trade_log_path.exists(), index=False)
        self.trades = pd.concat([self.trades, new_rows], ignore_index=True) if not self.trades.empty else new_rows

    async def _recompute(self) -> None:
        async with self._lock:
            cleaned = clean_minutes(self.minutes)
            events = strategy_events(cleaned, self.strategy_config)
            path = MinutePath(cleaned)
            computed = simulate(events, path, self.strategy_config.exit)
            self._persist_new_trades(computed)
            self.last_update = pd.Timestamp.utcnow()
            self.status = "ok"

    async def _poll_once(self, session: aiohttp.ClientSession) -> None:
        last_known = self.minutes.index[-1] if not self.minutes.empty else None
        now = pd.Timestamp.utcnow()
        start = int(last_known.timestamp()) if last_known is not None else int((now - pd.Timedelta(days=1)).timestamp())
        raw = await self._fetch_candles(session, start, int(now.timestamp()))
        fresh = self._to_frame(raw)
        if not fresh.empty:
            self.minutes = pd.concat([self.minutes, fresh])
            self.minutes = self.minutes[~self.minutes.index.duplicated(keep="last")].sort_index()
            cutoff = self.minutes.index[-1] - pd.Timedelta(days=self.rolling_window_days)
            self.minutes = self.minutes[self.minutes.index >= cutoff]
        self.mark_price = await self._fetch_ticker(session)
        await self._recompute()

    async def run(self) -> None:
        async with aiohttp.ClientSession() as session:
            while True:
                try:
                    if self.minutes.empty:
                        await self.seed(session)
                    else:
                        await self._poll_once(session)
                except Exception:
                    LOG.exception("paper engine tick failed; retrying after a short delay")
                    self.status = "degraded"
                    await asyncio.sleep(5)
                    continue
                await asyncio.sleep(self.poll_seconds)

    # --- read-only views for the API layer ---

    def open_position(self) -> dict | None:
        """The currently-open simulated trade, mark-to-market against the latest price."""
        if self.trades.empty or self.minutes.empty:
            return None
        last_minute = self.minutes.index[-1]
        last = self.trades.iloc[-1]
        if not (last["exit_reason"] == "data_gap" and last["exit_time"] >= last_minute):
            return None
        price = self.mark_price or float(self.minutes["close"].iloc[-1])
        side = 1 if last["side"] == "long" else -1
        unrealized_pct = side * (price - last["entry"]) / last["entry"] * 100
        return {
            "side": last["side"],
            "entry": float(last["entry"]),
            "entry_time": last["entry_time"].isoformat(),
            "stop": float(last["stop"]),
            "target": float(last["target"]),
            "mark_price": price,
            "unrealized_%": round(unrealized_pct, 3),
            "risk_%": round(float(last["risk_%"]), 3),
        }

    def closed_trades(self) -> pd.DataFrame:
        if self.trades.empty:
            return self.trades
        last_minute = self.minutes.index[-1] if not self.minutes.empty else None
        if last_minute is None:
            return self.trades
        return self.trades[~((self.trades["exit_reason"] == "data_gap") & (self.trades["exit_time"] >= last_minute))]

    def summary(self) -> dict:
        closed = self.closed_trades()
        equity = (1 + closed["ret_net"]).prod() if not closed.empty else 1.0
        open_pos = self.open_position()
        if open_pos:
            equity *= 1 + open_pos["unrealized_%"] / 100
        wins = int((closed["ret_net"] > 0).sum()) if not closed.empty else 0
        return {
            "status": self.status,
            "last_update": self.last_update.isoformat() if self.last_update is not None else None,
            "symbol": self.symbol,
            "starting_balance": self.starting_balance,
            "balance": round(self.starting_balance * equity, 2),
            "total_pnl_%": round((equity - 1) * 100, 3),
            "trades": len(closed),
            "wins": wins,
            "win_rate_%": round(wins / len(closed) * 100, 2) if len(closed) else 0.0,
            "open_positions": 1 if open_pos else 0,
            "mark_price": self.mark_price,
        }
