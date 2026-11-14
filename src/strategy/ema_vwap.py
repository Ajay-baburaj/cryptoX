"""EMA 9/20 + session VWAP intraday trend filter, made into a complete, testable rule set.

The source idea only says: long when price > VWAP and EMA9 > EMA20, short on the mirror image.
Everything it leaves out is a config choice here: the entry trigger, stop, exit, session/time
filters, chop filter and sizing. Signals use closed bars only; entries fill at the next bar's
open; stops and targets are walked on one-minute candles (a minute touching both = stop).

Crypto trades 24/7, so the VWAP "session" resets at ``session_reset_utc_hour`` (default 00:00
UTC = 05:30 IST, the TradingView default).
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from strategy.ob_rejection import (
    FEE_PER_SIDE,
    MinutePath,
    adx,
    aggregate,
    ema,
    segment_ids,
    true_range,
    walk_exit,
)
from strategy.luxalgo_internal_ob import wilder_rma


@dataclass(frozen=True)
class EmaVwapConfig:
    # chart
    timeframe_minutes: int = 5
    fast_ema: int = 9
    slow_ema: int = 20
    session_reset_utc_hour: int = 0
    # entry trigger: cross (9/20 cross while price is on the VWAP side), vwap_reclaim (close
    # crosses VWAP while EMAs agree), align (first bar both conditions hold), pullback (bar
    # tags EMA9 and closes back on the trend side while both conditions hold)
    trigger: str = "cross"
    # filters
    skip_open_minutes: int = 0          # no entries this long after the VWAP reset
    min_adx: float = 0.0                # chop filter on the trading timeframe (0 = off)
    htf_filter: str = "none"            # none | h1_ema50 | h4_ema50: trade only with that trend
    min_ema_gap_atr: float = 0.0        # |EMA9 - EMA20| must exceed this many ATRs
    sides: str = "both"                 # both | long | short
    # stop: atr (k x ATR from entry), swing (beyond last N-bar extreme), vwap, slow_ema
    stop: str = "atr"
    stop_atr: float = 1.5               # ATR multiple (atr) or ATR buffer (swing/vwap/slow_ema)
    swing_lookback: int = 10
    min_stop_pct: float = 0.002         # skip trades whose stop is tighter than this (fees)
    # exit: fixed R target and/or a signal exit; whichever comes first
    target_r: float | None = 1.0        # None = no fixed target
    exit_on: str = "none"               # none | opposite (EMA9/20 flip) | vwap (close through VWAP)
    flat_at_session_end: bool = True
    max_hours: int = 24
    # costs and sizing (sizing is applied by the backtest, not the signal logic)
    fee_per_side: float = FEE_PER_SIDE
    risk_per_trade_pct: float = 1.0
    max_leverage: float = 10.0

    @classmethod
    def from_dict(cls, values: dict) -> "EmaVwapConfig":
        known = {f.name for f in fields(cls)}
        unknown = set(values) - known
        if unknown:
            raise ValueError(f"Unknown EMA/VWAP config keys: {sorted(unknown)}")
        return cls(**values)

    @classmethod
    def load(cls, path: str | Path) -> "EmaVwapConfig":
        """Load the ``strategy:`` block of a YAML config file (see config/ema_vwap.yaml).

        ``symbol`` is informational only (which instrument the config was tuned for) and is
        not a simulation parameter, so it is dropped before building the dataclass.
        """
        raw = dict(yaml.safe_load(Path(path).read_text())["strategy"])
        raw.pop("symbol", None)
        return cls.from_dict(raw)


def session_vwap(bars: pd.DataFrame, reset_utc_hour: int) -> tuple[pd.Series, pd.Series]:
    """Volume-weighted typical price, reset daily; also returns each bar's session start."""
    starts = bars.index - pd.Timedelta(minutes=1)  # bars are labelled by close; use their open
    session = (starts - pd.Timedelta(hours=reset_utc_hour)).floor("D") + pd.Timedelta(hours=reset_utc_hour)
    typical = (bars["high"] + bars["low"] + bars["close"]) / 3
    pv = (typical * bars["volume"]).groupby(session).cumsum()
    vol = bars["volume"].groupby(session).cumsum()
    return (pv / vol.replace(0, np.nan)).ffill(), pd.Series(session, index=bars.index)


def prepare_bars(minutes: pd.DataFrame, config: EmaVwapConfig) -> pd.DataFrame:
    """Trading-timeframe bars with every indicator the rules and filters need."""
    tf = config.timeframe_minutes
    bars = aggregate(minutes, tf)
    out = bars[["open", "high", "low", "close", "volume"]].copy()
    out["ema_fast"] = ema(out["close"], config.fast_ema)
    out["ema_slow"] = ema(out["close"], config.slow_ema)
    out["vwap"], out["session"] = session_vwap(bars, config.session_reset_utc_hour)
    out["atr"] = wilder_rma(true_range(bars).fillna(bars["high"] - bars["low"]), 14)
    out["adx"] = adx(bars, 14)
    out["minutes_in_session"] = (out.index - out["session"]).dt.total_seconds() / 60
    for label, minutes_per_bar in (("h1", 60), ("h4", 240)):
        htf = aggregate(minutes, minutes_per_bar)
        direction = np.sign(htf["close"] - ema(htf["close"], 50))
        out[f"{label}_ema50_dir"] = direction.reindex(out.index, method="ffill")
    out["seg"] = segment_ids(out.index, pd.Timedelta(minutes=tf)).to_numpy()
    return out


def _next_true(cond: np.ndarray) -> np.ndarray:
    """next_true[i] = first j >= i where cond[j], else len(cond)."""
    idx = np.where(cond, np.arange(len(cond)), len(cond))
    return np.minimum.accumulate(idx[::-1])[::-1]


def signals(bars: pd.DataFrame, config: EmaVwapConfig) -> pd.DataFrame:
    """Entry events with stop level, exit deadline and filter features (filters NOT applied)."""
    c, o, h, l = (bars[k].to_numpy(dtype=float) for k in ("close", "open", "high", "low"))
    fast, slow, vwap = (bars[k].to_numpy(dtype=float) for k in ("ema_fast", "ema_slow", "vwap"))
    atr = bars["atr"].to_numpy(dtype=float)
    seg = bars["seg"].to_numpy()
    n = len(bars)
    trend = np.sign(fast - slow)
    side_vwap = np.sign(c - vwap)
    aligned = np.where((trend == side_vwap) & (trend != 0), trend, 0)
    prev = lambda a: np.concatenate(([np.nan], a[:-1]))
    same_seg = np.concatenate(([False], seg[1:] == seg[:-1]))
    if config.trigger == "cross":
        fire = (trend != prev(trend)) & (aligned == trend)
    elif config.trigger == "vwap_reclaim":
        fire = (side_vwap != prev(side_vwap)) & (aligned == side_vwap)
    elif config.trigger == "align":
        fire = (aligned != 0) & (aligned != prev(aligned))
    elif config.trigger == "pullback":
        touched = np.where(aligned == 1, l <= fast, h >= fast)
        fire = (aligned != 0) & touched & ((c - fast) * aligned > 0)
    else:
        raise ValueError(f"Unknown trigger {config.trigger}")
    fire &= same_seg & np.isfinite(slow) & np.isfinite(atr) & np.isfinite(vwap)
    fire[-1] = False
    fire &= np.concatenate((seg[1:] == seg[:-1], [False]))  # next bar exists for the fill
    side = aligned

    # signal exits: first later bar whose close breaks the rule, per side
    if config.exit_on == "opposite":
        exit_long, exit_short = trend < 0, trend > 0
    elif config.exit_on == "vwap":
        exit_long, exit_short = c < vwap, c > vwap
    else:
        exit_long = exit_short = np.zeros(n, dtype=bool)
    next_exit_long, next_exit_short = _next_true(exit_long), _next_true(exit_short)
    session_start = bars["session"].to_numpy()

    swing_low = pd.Series(l).rolling(config.swing_lookback, min_periods=1).min().to_numpy()
    swing_high = pd.Series(h).rolling(config.swing_lookback, min_periods=1).max().to_numpy()
    k = config.stop_atr
    times = bars.index
    step = pd.Timedelta(minutes=config.timeframe_minutes)
    rows = []
    for t in np.flatnonzero(fire):
        s = int(side[t])
        if config.stop == "atr":
            stop = c[t] - s * k * atr[t]
        elif config.stop == "swing":
            stop = (swing_low[t] - k * atr[t]) if s == 1 else (swing_high[t] + k * atr[t])
        elif config.stop == "vwap":
            stop = vwap[t] - s * k * atr[t]
        elif config.stop == "slow_ema":
            stop = slow[t] - s * k * atr[t]
        else:
            raise ValueError(f"Unknown stop {config.stop}")
        j = (next_exit_long if s == 1 else next_exit_short)[t + 1] if t + 1 < n else n
        signal_exit = times[j] if j < n else None  # exit at that bar's close
        session_end = pd.Timestamp(session_start[t]) + pd.Timedelta(days=1)
        rows.append({
            "signal_time": times[t],
            "entry_time": times[t + 1] - step,
            "side": s,
            "stop": stop,
            "signal_exit": signal_exit,
            "session_end": session_end,
            "atr": atr[t],
            "adx": bars["adx"].iat[t],
            "minutes_in_session": bars["minutes_in_session"].iat[t],
            "h1_ema50_dir": bars["h1_ema50_dir"].iat[t],
            "h4_ema50_dir": bars["h4_ema50_dir"].iat[t],
            "ema_gap_atr": abs(fast[t] - slow[t]) / atr[t] if atr[t] > 0 else 0.0,
        })
    return pd.DataFrame(rows)


def filter_mask(events: pd.DataFrame, config: EmaVwapConfig) -> np.ndarray:
    """The config's session, chop, trend and side filters as a boolean mask over events."""
    if events.empty:
        return np.zeros(0, dtype=bool)
    keep = events["minutes_in_session"] >= config.skip_open_minutes
    if config.min_adx > 0:
        keep &= events["adx"] >= config.min_adx
    if config.htf_filter != "none":
        keep &= events["side"] == events[f"{config.htf_filter}_dir"]
    if config.min_ema_gap_atr > 0:
        keep &= events["ema_gap_atr"] >= config.min_ema_gap_atr
    if config.sides != "both":
        keep &= events["side"] == (1 if config.sides == "long" else -1)
    return keep.to_numpy()


def _deadline_minutes(row: dict, start_time: pd.Timestamp, config: EmaVwapConfig) -> int:
    limit = start_time + pd.Timedelta(hours=config.max_hours)
    if config.flat_at_session_end:
        limit = min(limit, row["session_end"])
    if row["signal_exit"] is not None and not pd.isna(row["signal_exit"]):
        limit = min(limit, row["signal_exit"])
    return max(1, int((limit - start_time).total_seconds() // 60))


def exit_outcomes(events: pd.DataFrame, path: MinutePath, config: EmaVwapConfig):
    """Per-event (entry minute, exit minute, net return, R, reason), ignoring overlap."""
    n = len(events)
    starts, ends = np.zeros(n, dtype=int), np.zeros(n, dtype=int)
    rets, r_mult = np.full(n, np.nan), np.full(n, np.nan)
    reasons = np.empty(n, dtype=object)
    for k, row in enumerate(events.to_dict("records")):
        start = min(path.start(row["entry_time"]), len(path.ns) - 1)
        starts[k] = ends[k] = start
        side, entry = int(row["side"]), float(path.open[start])
        risk = (entry - row["stop"]) * side
        if risk <= 0 or risk / entry < config.min_stop_pct:
            continue
        target = entry + side * config.target_r * risk if config.target_r else entry + side * entry * 10
        span = _deadline_minutes(row, path.index[start], config)
        ends[k], fill, reason = walk_exit(path, start, side, entry, row["stop"], target, span)
        if reason == "time":
            reason = "signal/session"
        reasons[k] = reason
        rets[k] = (1 - config.fee_per_side) ** 2 * (1 + side * (fill - entry) / entry) - 1
        r_mult[k] = rets[k] / (risk / entry)
    return starts, ends, rets, r_mult, reasons


def simulate(events: pd.DataFrame, path: MinutePath, config: EmaVwapConfig) -> pd.DataFrame:
    """Trades taken one at a time after the config's filters."""
    from strategy.ob_rejection import take_sequential

    if events.empty:
        return pd.DataFrame()
    starts, ends, rets, r_mult, reasons = exit_outcomes(events, path, config)
    taken = take_sequential(starts, ends, rets, filter_mask(events, config))
    trades = events.iloc[taken][["signal_time", "side", "stop"]].reset_index(drop=True)
    trades["side"] = np.where(trades["side"] == 1, "long", "short")
    trades["entry_time"] = path.index[starts[taken]]
    trades["exit_time"] = path.index[ends[taken]]
    trades["entry"] = path.open[starts[taken]]
    trades["exit_reason"] = reasons[taken]
    trades["risk_%"] = np.abs(trades["entry"] - trades["stop"]) / trades["entry"] * 100
    trades["ret_net"] = rets[taken]
    trades["r_net"] = r_mult[taken]
    return trades


def risk_sized_equity(trades: pd.DataFrame, config: EmaVwapConfig) -> pd.Series:
    """Equity when each trade risks ``risk_per_trade_pct`` of equity, capped by max leverage."""
    if trades.empty:
        return pd.Series(dtype=float)
    risk = config.risk_per_trade_pct / 100
    leverage = np.minimum(risk / (trades["risk_%"] / 100), config.max_leverage)
    growth = 1 + leverage * trades["ret_net"]
    return pd.Series(np.cumprod(growth.to_numpy()), index=trades["exit_time"])
