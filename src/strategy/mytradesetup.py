"""Signals from the user's "MYTradeSetup" TradingView indicator (order_block_new.txt), ported to Python.

The Pine file is an indicator, not a strategy: it defines no entries, stops or targets, and its
order blocks are display-only. What it does define as tradeable markers are (a) the Hull/Kalman
"Buy"/"Sell" crosses and (b) the pivot-gated reversal signals (wick / extreme / outside / doji).
Both are ported as written, evaluated on bar close with no lookahead, and entered at the open of
the first minute after the signal bar closes. Exits are not part of the indicator, so
``simulate_signals`` reuses the ATR stop + ATR trailing walk from ``ob_touch_15m``.

Known quirk kept on purpose (``reversal_fixed=False``): in the Pine source ``shortsignal`` uses
``Wlongsignal`` (a bullish hammer) where ``Wshortsignal`` was clearly meant. The corrected
variant is available for comparison.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from strategy.luxalgo_internal_ob import OrderBlock, wilder_rma
from strategy.ob_rejection import FEE_PER_SIDE, MinutePath, true_range
from strategy.ob_touch_15m import TrailConfig, walk_trailing_exit


def wma(values: np.ndarray, length: int) -> np.ndarray:
    """Pine ta.wma: linearly weighted, newest bar weighted most; NaN until ``length`` bars exist."""
    out = np.full(len(values), np.nan)
    if length < 1 or len(values) < length:
        return out
    weights = np.arange(1, length + 1, dtype=float)
    windows = np.lib.stride_tricks.sliding_window_view(values, length)
    out[length - 1:] = windows @ weights / weights.sum()
    return out


def sma(values: np.ndarray, length: int) -> np.ndarray:
    return pd.Series(values).rolling(length).mean().to_numpy()


def kalman(x: np.ndarray, gain: float) -> np.ndarray:
    """The indicator's recursive 'Kalman' filter, call-for-call (state kept per call site)."""
    out = np.full(len(x), np.nan)
    prev_kf = prev_velo = np.nan
    root = np.sqrt(gain / 10000 * 2)
    for i, value in enumerate(x):
        base = prev_kf if np.isfinite(prev_kf) else value  # nz(kf[1], x)
        dk = value - base
        smooth = base + dk * root
        velo = (prev_velo if np.isfinite(prev_velo) else 0.0) + gain / 10000 * dk
        kf = smooth + velo
        out[i], prev_kf, prev_velo = kf, kf, velo
    return out


def hull_kalman_lines(bars: pd.DataFrame, length: int = 24, gain: float = 10000.0) -> tuple[np.ndarray, np.ndarray]:
    """Lines ``a`` (HMA of hl2) and ``b`` (the file's hma3, which uses close, not the source)."""
    hl2 = ((bars["high"] + bars["low"]) / 2).to_numpy(dtype=float)
    close = bars["close"].to_numpy(dtype=float)
    half, root = length // 2, int(round(np.sqrt(length)))
    a_raw = wma(2 * wma(hl2, half) - wma(hl2, length), root)
    p = length // 2
    b_raw = wma(wma(close, p // 3) * 3 - wma(close, p // 2) - wma(close, p), p)
    return kalman(a_raw, gain), kalman(b_raw, gain)


def hull_cross_signals(bars: pd.DataFrame, length: int = 24, gain: float = 10000.0) -> pd.DataFrame:
    """Buy = b crosses above a; Sell = a crosses above b. Known at the signal bar's close."""
    a, b = hull_kalman_lines(bars, length, gain)
    a1, b1 = np.roll(a, 1), np.roll(b, 1)
    a1[0] = b1[0] = np.nan
    crossup = (b > a) & (b1 < a1)
    crossdn = (a > b) & (a1 < b1)
    return pd.DataFrame({"long": crossup, "short": crossdn}, index=bars.index)


def reversal_signals(bars: pd.DataFrame, reversal_fixed: bool = False, wick_multiplier: float = 2.5,
                     body_percentage: float = 0.25, bodysize: float = 0.525, body_mult: float = 2.0,
                     bar_mult: float = 1.25, doji_pct: float = 0.10, lookback: int = 50,
                     pivot_left: int = 5) -> pd.DataFrame:
    """Wick / extreme / outside / doji reversals, gated by ta.pivotlow/pivothigh(5, 0)."""
    O, H, L, C = (bars[c].to_numpy(dtype=float) for c in ("open", "high", "low", "close"))
    rng, body = H - L, np.abs(C - O)

    def prev(arr: np.ndarray, k: int = 1) -> np.ndarray:
        out = np.roll(arr, k).astype(float)
        out[:k] = np.nan
        return out

    avg_range = sma(rng, lookback)
    avg_body = sma(body, lookback)
    sma10 = sma(C, 10)
    with np.errstate(invalid="ignore", divide="ignore"):
        w_long = (((C > O) & (O - L >= (C - O) * wick_multiplier) & (H - C <= rng * body_percentage))
                  | ((C < O) & (C - L >= (O - C) * wick_multiplier) & (H - C <= rng * body_percentage))
                  | ((C == O) & (C != H) & (rng >= (H - C) * wick_multiplier) & (H - C <= rng * body_percentage))
                  | ((O == H) & (C == H) & (rng >= sma(rng, 50))))
        w_short = (((C < O) & (H - O >= (O - C) * wick_multiplier) & (C - L <= rng * body_percentage))
                   | ((C > O) & (H - C >= (C - O) * wick_multiplier) & (C - L <= rng * body_percentage))
                   | ((C == O) & (C != L) & (rng >= (C - L) * wick_multiplier) & (C - L <= rng * body_percentage))
                   | ((O == L) & (C == L) & (rng >= sma(rng, 50))))
        O1, C1, H1, L1 = prev(O), prev(C), prev(H), prev(L)
        O2, C2, H2, L2 = prev(O, 2), prev(C, 2), prev(H, 2), prev(L, 2)
        e_long = ((O1 - C1 >= bodysize * (H1 - L1)) & (H1 - L1 > avg_range * body_mult)
                  & (O1 - C1 > avg_body) & (C > O))
        e_short = ((C1 - O1 >= bodysize * (H1 - L1)) & (H1 - L1 > avg_range * body_mult)
                   & (C1 - O1 > avg_body) & (O > C))
        o_long = (L < L1) & (C > H1) & (rng >= avg_range * bar_mult)
        o_short = (H > H1) & (C < L1) & (rng >= avg_range * bar_mult)
        frange_hl, frange_co = H1 - L1, np.abs(C1 - O1)
        d_short = (((frange_co <= frange_hl * doji_pct) & (C < L1) & (L1 > sma10) & (C < O))
                   | ((C < L2) & (C1 >= L2) & (frange_co <= frange_co * doji_pct) & (C < O) & (L2 > sma10)))
        d_long = (((frange_co <= frange_hl * doji_pct) & (C > H1) & (H1 < sma10) & (C > O))
                  | ((C > H2) & (C1 <= H2) & (frange_co <= frange_co * doji_pct) & (C > O) & (H2 < sma10)))
    low_pivot = L <= pd.Series(L).shift(1).rolling(pivot_left).min().to_numpy()   # ta.pivotlow(5, 0)
    high_pivot = H >= pd.Series(H).shift(1).rolling(pivot_left).max().to_numpy()  # ta.pivothigh(5, 0)
    long_sig = low_pivot & (w_long | e_long | o_long | d_long)
    short_sig = high_pivot & ((w_short if reversal_fixed else w_long) | e_short | o_short | d_short)
    return pd.DataFrame({"long": long_sig, "short": short_sig}, index=bars.index)


def order_block_confluence(bars: pd.DataFrame, blocks: list[OrderBlock], near_pct: float = 0.0025) -> pd.DataFrame:
    """Per bar: is a live same-bias 15m order block touched (within ``near_pct``) by that bar?"""
    times = bars.index
    H, L, C = (bars[c].to_numpy(dtype=float) for c in ("high", "low", "close"))
    long_ok = np.zeros(len(bars), dtype=bool)
    short_ok = np.zeros(len(bars), dtype=bool)
    for block in blocks:
        start = int(times.searchsorted(block.created_at, side="left"))
        end = len(times) if block.expires_at is None else int(times.searchsorted(block.expires_at, side="left"))
        if end <= start:
            continue
        if block.bias == 1:
            long_ok[start:end] |= (L[start:end] <= block.top * (1 + near_pct)) & (C[start:end] >= block.bottom)
        else:
            short_ok[start:end] |= (H[start:end] >= block.bottom * (1 - near_pct)) & (C[start:end] <= block.top)
    return pd.DataFrame({"long": long_ok, "short": short_ok}, index=times)


def signal_entries(bars: pd.DataFrame, signals: pd.DataFrame, path: MinutePath, stop_atr: float = 1.5,
                   mask: pd.DataFrame | None = None) -> pd.DataFrame:
    """One entry per signal bar, filled at the open of the first minute after that bar closes."""
    atr = wilder_rma(true_range(bars).fillna(bars["high"] - bars["low"]), 14).to_numpy()
    rows: list[dict[str, object]] = []
    for side_name, side in (("long", 1), ("short", -1)):
        flags = signals[side_name].to_numpy(dtype=bool)
        if mask is not None:
            flags = flags & mask[side_name].to_numpy(dtype=bool)
        for k in np.flatnonzero(flags):
            if not np.isfinite(atr[k]):
                continue
            i = path.start(bars.index[k])  # bars are labelled by close time -> next minute is the first unseen one
            if i >= len(path.ns) or path.ns[i] != bars.index[k].as_unit("ns").value:
                continue
            entry = float(path.open[i])
            rows.append({
                "signal_time": bars.index[k], "side": side, "entry_i": i, "entry_time": path.index[i],
                "entry": entry, "atr": float(atr[k]),
                "stop0": entry - side * stop_atr * float(atr[k]),
            })
    out = pd.DataFrame(rows)
    return out.sort_values("entry_time").reset_index(drop=True) if not out.empty else out


def simulate_signals(entries: pd.DataFrame, path: MinutePath, trail: TrailConfig,
                     fee_per_side: float = FEE_PER_SIDE) -> pd.DataFrame:
    """One position at a time; signals that arrive while a trade is open are skipped."""
    if entries.empty:
        return entries
    trades: list[dict[str, object]] = []
    busy_until = -1
    for row in entries.to_dict("records"):
        if row["entry_i"] <= busy_until:
            continue
        side, entry, stop0 = int(row["side"]), float(row["entry"]), float(row["stop0"])
        risk = (entry - stop0) * side
        if risk <= 0 or risk / entry < trail.min_stop_pct:
            continue
        exit_i, fill, reason, final_stop = walk_trailing_exit(path, int(row["entry_i"]), side, entry, stop0,
                                                              float(row["atr"]), trail)
        busy_until = exit_i
        gross = side * (fill - entry) / entry
        net = (1 - fee_per_side) * (1 + gross) * (1 - fee_per_side) - 1
        trades.append({
            "signal_time": row["signal_time"], "side": "long" if side == 1 else "short",
            "entry_time": path.index[int(row["entry_i"])], "exit_time": path.index[exit_i],
            "entry": entry, "stop0": stop0, "final_stop": final_stop, "exit": fill, "exit_reason": reason,
            "risk_%": risk / entry * 100, "ret_net": net, "r_net": net / (risk / entry),
        })
    return pd.DataFrame(trades)
