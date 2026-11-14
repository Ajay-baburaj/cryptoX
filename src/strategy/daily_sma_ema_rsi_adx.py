"""Daily long-only SMA/EMA/RSI/ADX strategy and indicator calculations."""
from __future__ import annotations

import pandas as pd


def rsi(close: pd.Series, length: int = 2) -> pd.Series:
    """Calculate Wilder-smoothed RSI using an EWM approximation."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()
    avg_loss = loss.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()
    relative_strength = avg_gain / avg_loss.replace(0, float("nan"))
    return (100 - 100 / (1 + relative_strength)).fillna(100)


def adx(bars: pd.DataFrame, length: int = 2) -> pd.Series:
    """Calculate Wilder ADX from high, low and close columns."""
    up_move = bars["high"].diff()
    down_move = -bars["low"].diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)

    previous_close = bars["close"].shift(1)
    true_range = pd.concat(
        [
            bars["high"] - bars["low"],
            (bars["high"] - previous_close).abs(),
            (bars["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    smooth = lambda series: series.ewm(  # noqa: E731 - shared Wilder smoother
        alpha=1 / length, adjust=False, min_periods=length
    ).mean()
    atr = smooth(true_range)
    plus_di = 100 * smooth(plus_dm) / atr
    minus_di = 100 * smooth(minus_dm) / atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, float("nan"))
    return smooth(dx)


def add_indicators(bars: pd.DataFrame) -> pd.DataFrame:
    """Add SMA(50), EMA(7), RSI(2), ADX(2) and the stated entry/exit flags."""
    result = bars.copy()
    result["sma50"] = result["close"].rolling(50, min_periods=50).mean()
    result["ema7"] = result["close"].ewm(span=7, adjust=False, min_periods=7).mean()
    result["rsi2"] = rsi(result["close"], 2)
    result["adx2"] = adx(result, 2)
    result["entry_signal"] = (
        (result["close"] > result["sma50"])
        & (result["close"] > result["ema7"])
        & (result["rsi2"] > result["adx2"])
    )
    result["exit_signal"] = result["rsi2"] < result["adx2"]
    return result
