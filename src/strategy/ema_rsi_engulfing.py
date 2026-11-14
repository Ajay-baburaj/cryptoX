"""
EMA200 + RSI50 + Engulfing strategy (from TradingLab's "Best Scalping Strategy for Beginners").

Rules (long):
  1. Trend:    close > EMA(200)
  2. Momentum: RSI(14) > 50
  3. Trigger:  bullish engulfing on a CLOSED candle
  Entry: next candle open
  Stop:  entry - 2 x engulfing candle range (high - low)   [stop_mode="entry"]
         or engulfing low - 2 x range                       [stop_mode="candle_low"]
  Target: entry + rr x stop distance (default rr = 2)

Bonus (optional): bullish RSI divergence -> sets `divergence=True` on the signal.
Shorts: mirror rules, disabled by default (not shown in the video).

Place at: src/strategy/ema_rsi_engulfing.py
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

import numpy as np
import pandas as pd


# ----------------------------------------------------------------------------- indicators

def ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False, min_periods=length).mean()


def rsi(close: pd.Series, length: int = 14) -> pd.Series:
    """Wilder's RSI (matches TradingView)."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()
    avg_loss = loss.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(100)


def bullish_engulfing(df: pd.DataFrame) -> pd.Series:
    po, pc = df["open"].shift(1), df["close"].shift(1)
    o, c = df["open"], df["close"]
    return (pc < po) & (c > o) & (o <= pc) & (c >= po)


def bearish_engulfing(df: pd.DataFrame) -> pd.Series:
    po, pc = df["open"].shift(1), df["close"].shift(1)
    o, c = df["open"], df["close"]
    return (pc > po) & (c < o) & (o >= pc) & (c <= po)


def _pivots(s: pd.Series, left: int, right: int, kind: Literal["low", "high"]) -> pd.Series:
    """True where s has a pivot low/high. Confirmed `right` bars later (no lookahead when shifted)."""
    win = left + right + 1
    roll = s.rolling(win, center=True)
    ext = roll.min() if kind == "low" else roll.max()
    return s.eq(ext)


def bullish_divergence(df: pd.DataFrame, r: pd.Series, left: int = 5, right: int = 5,
                       max_gap: int = 60) -> pd.Series:
    """Price lower low + RSI higher low between the last two RSI pivot lows.
    Flag is placed on the bar where the second pivot becomes confirmed (pivot + right)."""
    piv = _pivots(r, left, right, "low")
    out = pd.Series(False, index=df.index)
    idx = np.flatnonzero(piv.to_numpy())
    lows, rv = df["low"].to_numpy(), r.to_numpy()
    for a, b in zip(idx[:-1], idx[1:]):
        if b - a > max_gap:
            continue
        if lows[b] < lows[a] and rv[b] > rv[a]:
            confirm = b + right
            if confirm < len(out):
                out.iloc[confirm] = True
    # keep the flag "fresh" for a few bars so it can coincide with an engulfing
    return out.rolling(right + 3, min_periods=1).max().astype(bool)


def bearish_divergence(df: pd.DataFrame, r: pd.Series, left: int = 5, right: int = 5,
                       max_gap: int = 60) -> pd.Series:
    piv = _pivots(r, left, right, "high")
    out = pd.Series(False, index=df.index)
    idx = np.flatnonzero(piv.to_numpy())
    highs, rv = df["high"].to_numpy(), r.to_numpy()
    for a, b in zip(idx[:-1], idx[1:]):
        if b - a > max_gap:
            continue
        if highs[b] > highs[a] and rv[b] < rv[a]:
            confirm = b + right
            if confirm < len(out):
                out.iloc[confirm] = True
    return out.rolling(right + 3, min_periods=1).max().astype(bool)


# ----------------------------------------------------------------------------- config / signal

@dataclass
class Params:
    ema_len: int = 200
    rsi_len: int = 14
    rsi_mid: float = 50.0
    stop_mult: float = 2.0                 # stop = stop_mult x engulfing candle range
    rr: float = 2.0                        # take profit = rr x stop distance
    stop_mode: Literal["entry", "candle_low"] = "entry"
    min_stop_pct: float = 0.0025           # skip trades whose stop < 0.25% (fees would dominate)
    require_divergence: bool = False       # video: bonus only, not required
    allow_shorts: bool = False             # video shows longs only


@dataclass
class Signal:
    side: Literal["long", "short"]
    entry_ref: float          # reference price (signal close); fill at next open in backtest
    stop: float
    target: float
    divergence: bool
    ts: pd.Timestamp


# ----------------------------------------------------------------------------- vectorized (backtest)

def compute(
    df: pd.DataFrame,
    p: Params = Params(),
    *,
    include_divergence: bool = True,
) -> pd.DataFrame:
    """df: columns open, high, low, close (DatetimeIndex, closed candles only).
    Returns df with indicator + signal columns. Signal on bar t => enter at open of t+1."""
    out = df.copy()
    out["ema"] = ema(out["close"], p.ema_len)
    out["rsi"] = rsi(out["close"], p.rsi_len)
    rng = out["high"] - out["low"]

    if include_divergence or p.require_divergence:
        out["bull_div"] = bullish_divergence(out, out["rsi"])
        out["bear_div"] = bearish_divergence(out, out["rsi"])
    else:
        # Divergence is metadata when not required; omit its expensive pivot scan during parameter search.
        out["bull_div"] = False
        out["bear_div"] = False

    long_ok = (out["close"] > out["ema"]) & (out["rsi"] > p.rsi_mid) & bullish_engulfing(out)
    short_ok = (out["close"] < out["ema"]) & (out["rsi"] < p.rsi_mid) & bearish_engulfing(out)
    if p.require_divergence:
        long_ok &= out["bull_div"]
        short_ok &= out["bear_div"]
    if not p.allow_shorts:
        short_ok &= False

    # Entry assumed at next bar's open
    entry = out["open"].shift(-1)
    stop_dist = p.stop_mult * rng

    long_stop = np.where(p.stop_mode == "entry", entry - stop_dist, out["low"] - stop_dist)
    short_stop = np.where(p.stop_mode == "entry", entry + stop_dist, out["high"] + stop_dist)
    risk_long = entry - long_stop
    risk_short = short_stop - entry

    long_ok &= (risk_long / entry) >= p.min_stop_pct
    short_ok &= (risk_short / entry) >= p.min_stop_pct

    out["signal"] = np.select([long_ok, short_ok], [1, -1], 0)
    out["entry"] = np.where(out["signal"] != 0, entry, np.nan)
    out["stop"] = np.select([long_ok, short_ok], [long_stop, short_stop], np.nan)
    out["target"] = np.select(
        [long_ok, short_ok],
        [entry + p.rr * risk_long, entry - p.rr * risk_short],
        np.nan,
    )
    return out


def simulate(sig: pd.DataFrame, fee_per_side: float = 0.00059) -> pd.DataFrame:
    """Simple bar-by-bar SL/TP simulator, one position at a time.
    If SL and TP are both inside one bar, assume SL first (conservative).
    fee_per_side default ~ Delta taker 0.05% + 18% GST."""
    trades = []
    o, h, l, c = (sig[k].to_numpy() for k in ("open", "high", "low", "close"))
    s, st, tg = sig["signal"].to_numpy(), sig["stop"].to_numpy(), sig["target"].to_numpy()
    idx = sig.index
    i, n = 0, len(sig)
    while i < n - 1:
        if s[i] == 0:
            i += 1
            continue
        side, entry, stop, target = s[i], o[i + 1], st[i], tg[i]
        j = i + 1
        exit_px, reason = None, None
        while j < n:
            if side == 1:
                if l[j] <= stop:
                    exit_px, reason = stop, "SL"
                elif h[j] >= target:
                    exit_px, reason = target, "TP"
            else:
                if h[j] >= stop:
                    exit_px, reason = stop, "SL"
                elif l[j] <= target:
                    exit_px, reason = target, "TP"
            if exit_px is not None:
                break
            j += 1
        if exit_px is None:
            exit_px, reason, j = c[-1], "EOD", n - 1
        gross = side * (exit_px - entry) / entry
        trades.append({
            "entry_time": idx[i + 1], "exit_time": idx[j], "side": "long" if side == 1 else "short",
            "entry": entry, "exit": exit_px, "reason": reason,
            "ret_gross": gross, "ret_net": gross - 2 * fee_per_side,
            "divergence": bool(sig["bull_div"].iloc[i] if side == 1 else sig["bear_div"].iloc[i]),
        })
        i = j + 1
    return pd.DataFrame(trades)


def summary(trades: pd.DataFrame) -> dict:
    if trades.empty:
        return {"trades": 0}
    eq = (1 + trades["ret_net"]).cumprod()
    dd = (eq / eq.cummax() - 1).min()
    return {
        "trades": len(trades),
        "win_rate": round((trades["ret_net"] > 0).mean(), 3),
        "avg_net_%": round(trades["ret_net"].mean() * 100, 3),
        "total_net_%": round((eq.iloc[-1] - 1) * 100, 2),
        "max_dd_%": round(dd * 100, 2),
        "win_rate_with_div": round((trades.loc[trades["divergence"], "ret_net"] > 0).mean(), 3)
        if trades["divergence"].any() else None,
    }


# ----------------------------------------------------------------------------- live (on_bar)

class EmaRsiEngulfing:
    """Live usage: call on_bar() with the rolling DataFrame of CLOSED candles
    (at least ~ema_len + 50 rows). Returns a Signal or None."""

    def __init__(self, params: Params = Params()):
        self.p = params

    def on_bar(self, bars: pd.DataFrame) -> Optional[Signal]:
        if len(bars) < self.p.ema_len + 20:
            return None
        df = bars.copy()
        df["ema"] = ema(df["close"], self.p.ema_len)
        df["rsi"] = rsi(df["close"], self.p.rsi_len)
        last = df.iloc[-1]
        rng = last["high"] - last["low"]
        ref = last["close"]  # live entry ~ next open ≈ this close
        stop_dist = self.p.stop_mult * rng

        if (last["close"] > last["ema"] and last["rsi"] > self.p.rsi_mid
                and bool(bullish_engulfing(df.iloc[-2:]).iloc[-1])):
            stop = ref - stop_dist if self.p.stop_mode == "entry" else last["low"] - stop_dist
            risk = ref - stop
            div = bool(bullish_divergence(df, df["rsi"]).iloc[-1])
            if risk / ref >= self.p.min_stop_pct and (div or not self.p.require_divergence):
                return Signal("long", ref, stop, ref + self.p.rr * risk, div, df.index[-1])

        if (self.p.allow_shorts and last["close"] < last["ema"] and last["rsi"] < self.p.rsi_mid
                and bool(bearish_engulfing(df.iloc[-2:]).iloc[-1])):
            stop = ref + stop_dist if self.p.stop_mode == "entry" else last["high"] + stop_dist
            risk = stop - ref
            div = bool(bearish_divergence(df, df["rsi"]).iloc[-1])
            if risk / ref >= self.p.min_stop_pct and (div or not self.p.require_divergence):
                return Signal("short", ref, stop, ref - self.p.rr * risk, div, df.index[-1])
        return None


