"""1h order-block mitigation strategy: causal, minute-by-minute state machine.

The same ``OB1hStrategy`` object drives live paper trading (``execution.ob1h_engine``) and the
historical replay (``scripts/backtest_ob_mitigation_1h.py``), so there is no separate backtest
logic to drift out of sync.

Rules
  * Bearish order block revisited from below  -> SHORT.  Bullish block revisited from above -> LONG.
  * A block is traded at most once: its first revisit consumes it, whether or not a trade results.
  * Signal on the 1m bar that first reaches the block's near edge from outside; fill at the NEXT 1m
    open (market order), so nothing is filled at a price that was only seen inside the signal bar.
  * Initial stop beyond the far edge (above a bear block / below a bull block) + buffer x ATR(14, 1h).
  * No target. Once a closed 1h candle is >= ``trail_activate_r`` R in profit the stop is trailed on
    every closed 1h candle to the extreme of the last ``trail_lookback`` candles (+ buffer); it only
    ever tightens and applies from the minute the candle closed.

Zones come from ``research.ob_timeframes.detect_zones``, a port of the user's LuxAlgo SMC Pine
script that was checked against the script's own output (CC BY-NC-SA 4.0, © LuxAlgo, non-commercial).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from research.ob_timeframes import Zone, detect_zones
from strategy.luxalgo_internal_ob import wilder_rma

NS_MIN = 60_000_000_000
NS_HOUR = 60 * NS_MIN


@dataclass
class Config:
    symbol: str = "BTCUSDT"
    mitigation: str = "wick"
    stop_buffer_atr: float = 0.25
    min_stop_pct: float = 0.002
    trail_lookback: int = 3
    trail_buffer_atr: float = 0.1
    trail_activate_r: float = 1.0
    start_balance: float = 10_000.0
    risk_pct: float = 0.5
    max_notional_x: float = 3.0
    fee_per_side: float = 0.0005
    slippage_per_side: float = 0.0002


def load_config(path: str | Path = "config/ob_mitigation_1h.yaml") -> Config:
    import yaml

    raw = yaml.safe_load(Path(path).read_text())
    flat = {**raw.get("strategy", {}), **raw.get("account", {})}
    known = {k: v for k, v in flat.items() if k in Config.__dataclass_fields__}
    return Config(**known)


def make_bars(h1: pd.DataFrame) -> pd.DataFrame:
    """1h bars indexed by CLOSE time (UTC), complete candles only, with ATR(14) and gap segments."""
    bars = h1[["open", "high", "low", "close", "volume"]].astype(float).copy()
    bars["segment"] = bars.index.to_series().diff().gt(pd.Timedelta(hours=1)).cumsum().to_numpy()
    bars["atr"] = np.nan
    for _, run in bars.groupby("segment"):
        prev = run["close"].shift()
        tr = pd.concat([run.high - run.low, (run.high - prev).abs(), (run.low - prev).abs()], axis=1).max(axis=1)
        bars.loc[run.index, "atr"] = wilder_rma(tr, 14)
    return bars


def zone_key(z: Zone) -> str:
    return f"{z.side}|{int(z.created.value)}|{z.top:.2f}|{z.bottom:.2f}"


def _iso(ns: int) -> str:
    return pd.Timestamp(int(ns), tz="UTC").isoformat()


class OB1hStrategy:
    def __init__(self, cfg: Config | None = None):
        self.cfg = cfg or Config()
        self.balance = self.cfg.start_balance
        self.consumed: set[str] = set()
        self.position: dict | None = None
        self.pending: dict | None = None
        self.trades: list[dict] = []
        self.events: list[dict] = []
        self.trail_cursor_ns = 0  # close time of the last 1h bar already used for trailing
        self.prev_ts = 0
        self.prev_close = np.nan
        self.zones: list[Zone] = []
        self.visible: list[tuple[int, ...]] = []
        self._set_arrays(pd.DataFrame(columns=["open", "high", "low", "close", "atr"]))

    # ---- zones -------------------------------------------------------------------------

    def _set_arrays(self, bars: pd.DataFrame) -> None:
        self.bars = bars
        self.bar_ns = bars.index.as_unit("ns").asi8 if len(bars) else np.array([], dtype="int64")
        self.bar_high = bars["high"].to_numpy(float)
        self.bar_low = bars["low"].to_numpy(float)
        self.bar_close = bars["close"].to_numpy(float)
        self.bar_atr = bars["atr"].to_numpy(float)

    def load_bars(self, bars: pd.DataFrame) -> None:
        """Recompute zones from 1h bars (index = close time). Safe to call on every new bar."""
        self._set_arrays(bars)
        self.zones, self.visible = detect_zones(bars, self.cfg.mitigation) if len(bars) else ([], [])

    def visible_zones(self, ts_ns: int) -> list[Zone]:
        """The newest-first active blocks as of the last 1h bar that had closed by ``ts_ns``."""
        j = int(np.searchsorted(self.bar_ns, ts_ns, side="right")) - 1
        if j < 0:
            return []
        return [self.zones[i] for i in self.visible[j] if self.zones[i].warmed and self.zones[i].top > self.zones[i].bottom]

    def baseline(self, ts_ns: int) -> None:
        """First start: blocks already revisited on 1h bars before now are not fresh."""
        j = int(np.searchsorted(self.bar_ns, ts_ns, side="right")) - 1
        for z in self.visible_zones(ts_ns):
            first = int(np.searchsorted(self.bar_ns, z.created.value, side="right"))
            if first > j:
                continue
            if z.side == 1 and (self.bar_low[first:j + 1] <= z.top).any():
                self.consumed.add(zone_key(z))
            if z.side == -1 and (self.bar_high[first:j + 1] >= z.bottom).any():
                self.consumed.add(zone_key(z))

    # ---- minute loop -------------------------------------------------------------------

    def on_minute(self, ts_ns: int, o: float, h: float, l: float, c: float, trade: bool = True) -> list[dict]:
        """Process one CLOSED 1m candle (open time ``ts_ns``). Returns events that happened."""
        out: list[dict] = []
        self._advance_trail(ts_ns, out)
        if self.pending is not None and self.position is None:
            if trade:
                self._fill(ts_ns, o, out)
            self.pending = None
        if self.position is not None:
            self._manage(ts_ns, o, h, l, out)
        contiguous = self.prev_ts and ts_ns - self.prev_ts == NS_MIN
        for z in self.visible_zones(ts_ns):
            key = zone_key(z)
            if key in self.consumed:
                continue
            touched = (l <= z.top) if z.side == 1 else (h >= z.bottom)
            if not touched:
                continue
            self.consumed.add(key)
            from_outside = contiguous and ((self.prev_close > z.top) if z.side == 1 else (self.prev_close < z.bottom))
            if trade and from_outside and self.position is None and self.pending is None:
                known = int(np.searchsorted(self.bar_ns, ts_ns, side="right")) - 1
                atr = float(self.bar_atr[known]) if known >= 0 else float("nan")
                if np.isfinite(atr) and atr > 0:
                    self.pending = {"zone": z, "signal_ns": ts_ns, "atr": atr}
                    out.append({"type": "signal", "time": _iso(ts_ns), "side": "long" if z.side == 1 else "short",
                                "zone_top": z.top, "zone_bottom": z.bottom})
        self.prev_ts, self.prev_close = ts_ns, c
        self.events.extend(out)
        del self.events[:-200]
        return out

    def _fill(self, ts_ns: int, open_price: float, out: list[dict]) -> None:
        cfg, p = self.cfg, self.pending
        z, side, atr = p["zone"], p["zone"].side, p["atr"]
        entry = open_price * (1 + side * cfg.slippage_per_side)
        stop = z.bottom - cfg.stop_buffer_atr * atr if side == 1 else z.top + cfg.stop_buffer_atr * atr
        dist = side * (entry - stop)
        if dist <= 0 or dist / entry < cfg.min_stop_pct:
            out.append({"type": "skipped", "time": _iso(ts_ns), "side": "long" if side == 1 else "short",
                        "reason": "entry beyond stop" if dist <= 0 else "stop tighter than minimum"})
            return
        qty = min(self.balance * cfg.risk_pct / 100 / dist, self.balance * cfg.max_notional_x / entry)
        self.position = {
            "side": "long" if side == 1 else "short", "sign": side,
            "zone_top": z.top, "zone_bottom": z.bottom, "zone_created": _iso(z.created.value),
            "signal_time": _iso(p["signal_ns"]), "entry_time": _iso(ts_ns), "entry_ns": ts_ns,
            "entry": entry, "qty": qty, "notional": qty * entry, "risk_usd": qty * dist,
            "initial_stop": stop, "stop": stop, "stop_moves": [], "trailing": False,
            "atr": atr, "fee_entry": qty * entry * cfg.fee_per_side, "best": entry, "worst": entry,
        }
        out.append({"type": "entry", "time": _iso(ts_ns), "side": self.position["side"], "price": entry, "stop": stop})

    def _manage(self, ts_ns: int, o: float, h: float, l: float, out: list[dict]) -> None:
        pos = self.position
        sign = pos["sign"]
        pos["best"] = max(pos["best"], h) if sign == 1 else min(pos["best"], l)
        pos["worst"] = min(pos["worst"], l) if sign == 1 else max(pos["worst"], h)
        stop = pos["stop"]
        if (sign == 1 and l <= stop) or (sign == -1 and h >= stop):  # stop wins same-minute ties
            raw = min(stop, o) if sign == 1 else max(stop, o)  # gap through the stop fills at the worse open
            self._close(ts_ns, raw * (1 - sign * self.cfg.slippage_per_side), out)

    def _close(self, ts_ns: int, exit_price: float, out: list[dict]) -> None:
        pos, cfg = self.position, self.cfg
        gross = pos["qty"] * pos["sign"] * (exit_price - pos["entry"])
        fee_exit = pos["qty"] * exit_price * cfg.fee_per_side
        net = gross - pos["fee_entry"] - fee_exit
        before = self.balance
        self.balance += net
        trade = {k: pos[k] for k in ("side", "zone_top", "zone_bottom", "zone_created", "signal_time", "entry_time",
                                      "entry", "qty", "notional", "risk_usd", "initial_stop", "stop_moves")}
        trade.update(
            exit_time=_iso(ts_ns), exit=exit_price, final_stop=pos["stop"],
            exit_reason="trailing_stop" if pos["stop_moves"] else "initial_stop",
            fees=pos["fee_entry"] + fee_exit, pnl=net, ret_pct=net / before * 100,
            r_net=net / pos["risk_usd"] if pos["risk_usd"] else 0.0,
            hold_hours=(ts_ns - pos["entry_ns"]) / NS_HOUR,
            best_price=pos["best"], worst_price=pos["worst"], balance_after=self.balance,
        )
        self.trades.append(trade)
        self.position = None
        out.append({"type": "exit", "time": _iso(ts_ns), "side": trade["side"], "price": exit_price,
                    "reason": trade["exit_reason"], "pnl": net, "r": trade["r_net"]})

    def _advance_trail(self, ts_ns: int, out: list[dict]) -> None:
        """Apply every 1h bar that closed in (cursor, ts_ns]. Candle data is only used once closed."""
        n = len(self.bar_ns)
        i = int(np.searchsorted(self.bar_ns, self.trail_cursor_ns, side="right"))
        if i >= n or self.bar_ns[i] > ts_ns:
            return
        while i < n and self.bar_ns[i] <= ts_ns:
            pos = self.position
            # Only candles that opened at or after the entry minute: the entry candle mostly holds
            # pre-entry prices, and trailing to its extreme put the stop right next to the fill.
            if pos is not None and self.bar_ns[i] - NS_HOUR >= pos["entry_ns"]:
                self._trail(i, out)
            self.trail_cursor_ns = int(self.bar_ns[i])
            i += 1

    def _trail(self, i: int, out: list[dict]) -> None:
        pos, cfg = self.position, self.cfg
        sign = pos["sign"]
        risk = abs(pos["entry"] - pos["initial_stop"])
        if not pos["trailing"]:
            profit_r = sign * (self.bar_close[i] - pos["entry"]) / risk
            if cfg.trail_activate_r <= 0 or profit_r >= cfg.trail_activate_r:
                pos["trailing"] = True
            else:
                return
        lo = max(0, i - cfg.trail_lookback + 1)
        atr = self.bar_atr[i] if np.isfinite(self.bar_atr[i]) else 0.0
        if sign == 1:
            cand = float(self.bar_low[lo:i + 1].min()) - cfg.trail_buffer_atr * atr
            better = cand > pos["stop"]
        else:
            cand = float(self.bar_high[lo:i + 1].max()) + cfg.trail_buffer_atr * atr
            better = cand < pos["stop"]
        if better:
            pos["stop"] = cand
            move = {"time": _iso(self.bar_ns[i]), "stop": cand}
            pos["stop_moves"].append(move)
            out.append({"type": "trail", "time": move["time"], "side": pos["side"], "stop": cand})

    # ---- views / persistence -----------------------------------------------------------

    def watchlist(self, ts_ns: int, price: float | None) -> list[dict]:
        rows = []
        for z in self.visible_zones(ts_ns):
            key = zone_key(z)
            near = z.bottom if z.side == -1 else z.top
            atr = float(self.bar_atr[max(0, int(np.searchsorted(self.bar_ns, ts_ns, side="right")) - 1)])
            stop = z.top + self.cfg.stop_buffer_atr * atr if z.side == -1 else z.bottom - self.cfg.stop_buffer_atr * atr
            traded = (self.position is not None and self.position["zone_created"] == _iso(z.created.value)
                      and self.position["zone_top"] == z.top)
            traded = traded or any(t["zone_created"] == _iso(z.created.value) and t["zone_top"] == z.top for t in self.trades)
            rows.append({
                "side": "bearish" if z.side == -1 else "bullish",
                "action": "SHORT" if z.side == -1 else "LONG",
                "top": z.top, "bottom": z.bottom, "created": _iso(z.created.value),
                "status": "traded" if traded else "used" if key in self.consumed else "armed",
                "entry_level": near, "planned_stop": stop,
                "distance_pct": (near - price) / price * 100 if price else None,
            })
        return rows

    def unrealized(self, price: float) -> dict | None:
        pos = self.position
        if pos is None:
            return None
        pnl = pos["qty"] * pos["sign"] * (price - pos["entry"]) - pos["fee_entry"]
        return {"pnl": pnl, "pnl_pct": pnl / self.balance * 100,
                "r": pnl / pos["risk_usd"] if pos["risk_usd"] else 0.0}

    def stats(self) -> dict:
        t = pd.DataFrame(self.trades)
        n = len(t)
        wins = int((t.pnl > 0).sum()) if n else 0
        gains = float(t.pnl[t.pnl > 0].sum()) if n else 0.0
        losses = float(-t.pnl[t.pnl < 0].sum()) if n else 0.0
        curve = np.array([self.cfg.start_balance] + [x["balance_after"] for x in self.trades])
        peak = np.maximum.accumulate(curve)
        return {
            "trades": n, "wins": wins, "losses": n - wins,
            "win_rate": wins / n * 100 if n else 0.0,
            "avg_r": float(t.r_net.mean()) if n else 0.0,
            "profit_factor": gains / losses if losses else (None if not gains else float("inf")),
            "fees": float(t.fees.sum()) if n else 0.0,
            "max_drawdown_pct": float(((curve - peak) / peak).min() * 100),
            "avg_hold_hours": float(t.hold_hours.mean()) if n else 0.0,
            "long_trades": int((t.side == "long").sum()) if n else 0,
            "short_trades": int((t.side == "short").sum()) if n else 0,
        }

    def to_state(self) -> dict:
        pos = None
        if self.position:
            pos = dict(self.position)
        return {"balance": self.balance, "consumed": sorted(self.consumed), "position": pos,
                "trades": self.trades, "events": self.events, "trail_cursor_ns": self.trail_cursor_ns,
                "prev_ts": self.prev_ts, "prev_close": None if np.isnan(self.prev_close) else self.prev_close,
                "config": asdict(self.cfg)}

    def from_state(self, s: dict) -> None:
        self.balance = s["balance"]
        self.consumed = set(s["consumed"])
        self.position = s["position"]
        self.trades = s["trades"]
        self.events = s.get("events", [])
        self.trail_cursor_ns = s["trail_cursor_ns"]
        self.prev_ts = s["prev_ts"]
        self.prev_close = np.nan if s["prev_close"] is None else s["prev_close"]
