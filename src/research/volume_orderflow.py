"""Causal volume-profile and order-flow rules on 1m klines. See research/volume_orderflow/PROTOCOL.md."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

COST = 0.0014
STRESS_COST = 0.0020
BIN_FRACTION = 0.0005
VALUE_AREA = 0.70
BAR = 30
DAY = 1440


@dataclass(frozen=True)
class Market:
    """Contiguous 1m arrays; `funding[i]` is the rate settled at minute i, `tb` taker-buy volume."""
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    v: np.ndarray
    tb: np.ndarray
    funding: np.ndarray

    def __post_init__(self):
        object.__setattr__(self, 'cum_funding', np.cumsum(self.funding))


def profile(low, high, volume, bin_size):
    """Volume per bin, each bar's volume spread uniformly across the bins it spans. Returns (origin, hist)."""
    origin = np.floor(low.min() / bin_size) * bin_size
    lo = np.clip(((low - origin) / bin_size).astype(int), 0, None)
    hi = np.maximum(((high - origin) / bin_size).astype(int), lo)
    diff = np.zeros(hi.max() + 2)
    each = volume / (hi - lo + 1)
    np.add.at(diff, lo, each)
    np.add.at(diff, hi + 1, -each)
    return origin, np.cumsum(diff)[:-1]


def value_area(origin, hist, bin_size, share=VALUE_AREA):
    """(poc, val, vah) from a histogram, expanding from the POC toward the heavier neighbouring bin."""
    poc = int(np.argmax(hist))
    left = right = poc
    total, target = hist[poc], hist.sum() * share
    while total < target and (left > 0 or right < len(hist) - 1):
        down = hist[left - 1] if left > 0 else -1.
        up = hist[right + 1] if right < len(hist) - 1 else -1.
        if up > down:
            right += 1
            total += up
        else:
            left -= 1
            total += down
    return origin + (poc + .5) * bin_size, origin + left * bin_size, origin + (right + 1) * bin_size


def window_levels(m: Market, anchor: int):
    """Per-window array [poc, val, vah]; row k is built only from minutes of window k."""
    count = (len(m.o) - anchor) // DAY
    out = np.zeros((count, 3))
    for k in range(count):
        s = anchor + k * DAY
        size = m.o[s] * BIN_FRACTION
        out[k] = value_area(*profile(m.l[s:s + DAY], m.h[s:s + DAY], m.v[s:s + DAY], size), size)
    return out


def trade(m: Market, entry_i, side, stop, target, last_i):
    """Gross return after funding, or None when the entry is already beyond stop or target."""
    entry = m.o[entry_i]
    last_i = min(last_i, len(m.o) - 1)
    if stop is not None and side * (entry - stop) <= 0:
        return None
    if target is not None and side * (target - entry) <= 0:
        return None
    exit_i, price = last_i, m.c[last_i]
    lows, highs = m.l[entry_i:last_i + 1], m.h[entry_i:last_i + 1]
    adverse, favourable = (lows, highs) if side == 1 else (highs, lows)
    n = len(lows)
    stop_at = n
    if stop is not None:
        hit = adverse <= stop if side == 1 else adverse >= stop
        stop_at = int(np.argmax(hit)) if hit.any() else n
    target_at = n
    if target is not None:
        hit = favourable >= target if side == 1 else favourable <= target
        target_at = int(np.argmax(hit)) if hit.any() else n
    if stop_at < n and stop_at <= target_at:
        exit_i = entry_i + stop_at
        price = min(stop, m.o[exit_i]) if side == 1 else max(stop, m.o[exit_i])
    elif target_at < n:
        exit_i, price = entry_i + target_at, target
    # Funding settled strictly after entry and up to exit; longs pay a positive rate.
    funding = m.cum_funding[exit_i] - m.cum_funding[entry_i]
    return exit_i, side * (price / entry - 1) - side * funding


def bars30(m: Market):
    n = len(m.o) // BAR
    o, c = m.o[::BAR][:n], m.c[BAR - 1::BAR][:n]
    h = m.h[:n * BAR].reshape(n, BAR).max(axis=1)
    l = m.l[:n * BAR].reshape(n, BAR).min(axis=1)
    tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
    tr = np.r_[h[0] - l[0], tr]
    atr = np.full(n, np.nan)
    atr[13] = tr[:14].mean()
    for i in range(14, n):
        atr[i] = (atr[i - 1] * 13 + tr[i]) / 14
    return o, h, l, c, atr


def level_trades(m: Market, bars, levels, anchor, rule, params=None, shifts=None):
    """Sequential trades for a level rule. `shifts` (per window) moves all levels, for placebos."""
    params = params or {}
    o, h, l, c, atr = bars
    if shifts is not None:
        levels = levels + shifts[:, None]
    out, free_at = [], 0
    first, per_window = anchor // BAR, DAY // BAR
    if rule == 'naked_poc':
        return _naked_poc(m, bars, levels, first, per_window, params)
    for k in range(3, len(levels) - 1):  # levels[k] trades window k + 1
        b0 = first + (k + 1) * per_window
        if b0 + per_window > len(c):
            break
        poc, val, vah = levels[k]
        signal = globals()['_' + rule](bars, b0, per_window, poc, val, vah, levels[:k + 1], params)
        if signal is None:
            continue
        bar, side, stop, target, horizon = signal
        entry_i = (bar + 1) * BAR
        if entry_i < free_at:
            continue
        last_i = (b0 + per_window) * BAR - 1 if horizon is None else entry_i + horizon - 1
        result = trade(m, entry_i, side, stop, target, last_i)
        if result:
            free_at = result[0] + 1
            out.append((entry_i, result[1]))
    return out


def _eighty(bars, b0, n, poc, val, vah, _levels, params):
    o, h, l, c, atr = bars
    width = vah - val
    if width / o[b0] < params.get('min_width', 0) or val <= o[b0] <= vah:
        return None
    side = 1 if o[b0] < val else -1
    for b in range(b0 + 1, b0 + n - 1):
        if val <= c[b - 1] <= vah and val <= c[b] <= vah and not np.isnan(atr[b]):
            return (b, 1, val - .25 * atr[b], vah, None) if side == 1 else (b, -1, vah + .25 * atr[b], val, None)
    return None


def _va_rejection(bars, b0, n, poc, val, vah, _levels, _params):
    o, h, l, c, atr = bars
    if not val <= o[b0] <= vah:
        return None
    for b in range(b0, b0 + n - 1):
        if np.isnan(atr[b]):
            return None
        if l[b] < val and val - l[b] < .25 * atr[b] and c[b] >= val:
            return b, 1, l[b] - .25 * atr[b], poc, None
        if h[b] > vah and h[b] - vah < .25 * atr[b] and c[b] <= vah:
            return b, -1, h[b] + .25 * atr[b], poc, None
    return None


def _poc_reversion(bars, b0, n, poc, val, vah, _levels, _params):
    o, h, l, c, atr = bars
    limit = 1.5 * (vah - val) / 2
    for b in range(b0, b0 + n - 1):
        if np.isnan(atr[b]):
            return None
        if c[b] < poc - limit and c[b] > o[b]:
            return b, 1, l[b0:b + 1].min() - atr[b], poc, None
        if c[b] > poc + limit and c[b] < o[b]:
            return b, -1, h[b0:b + 1].max() + atr[b], poc, None
    return None


def _balance_breakout(bars, b0, n, poc, val, vah, levels, _params):
    o, h, l, c, atr = bars
    recent = levels[-3:]
    if recent[:, 1].max() >= recent[:, 2].min():  # some pair of value areas does not overlap
        return None
    low, high = recent[:, 1].min(), recent[:, 2].max()
    for b in range(b0 + 1, b0 + n - 1):
        if np.isnan(atr[b]):
            return None
        width = high - low
        if c[b - 1] > high and c[b] > high:
            return b, 1, high - .25 * atr[b], c[b] + width, DAY
        if c[b - 1] < low and c[b] < low:
            return b, -1, low + .25 * atr[b], c[b] - width, DAY
    return None


def _naked_poc(m, bars, levels, first, per_window, params):
    o, h, l, c, atr = bars
    reward = params['reward']
    out, free_at, live = [], 0, {}
    for k in range(len(levels) - 1):
        start = first + (k + 1) * per_window
        live[k] = levels[k, 0]
        for b in range(start, min(start + per_window, len(c) - 1)):
            for born, level in list(live.items()):
                if k - born >= 20:
                    del live[born]
                    continue
                if not l[b] <= level <= h[b]:
                    continue
                del live[born]  # first touch only
                entry_i = (b + 1) * BAR
                if np.isnan(atr[b]) or entry_i < free_at:
                    continue
                side = 1 if c[b - 1] > level and c[b] > level else -1 if c[b - 1] < level and c[b] < level else 0
                if not side:
                    continue
                stop = level - side * .5 * atr[b]
                entry = m.o[entry_i]
                target = entry + side * reward * abs(entry - stop)
                result = trade(m, entry_i, side, stop, target, entry_i + DAY - 1)
                if result:
                    free_at = result[0] + 1
                    out.append((entry_i, result[1]))
    return out


def sequential_holds(m: Market, signals, hold):
    """`signals` = iterable of (signal minute, side); enter the next minute, skip while in a trade."""
    out, free_at = [], 0
    for i, side in signals:
        entry_i = i + 1
        if entry_i < free_at or entry_i + hold >= len(m.o):
            continue
        result = trade(m, entry_i, side, None, None, entry_i + hold - 1)
        free_at = result[0] + 1
        out.append((entry_i, result[1]))
    return out


def _rolling(values, window, fn):
    out = np.full(len(values), np.nan)
    for i in range(window, len(values)):
        out[i] = fn(values[i - window:i])
    return out


def quarter_signals(m: Market, kind):
    """Causal (minute, side) quarter-hour flow signals; the current value is excluded from its baseline."""
    idx = np.arange(0, len(m.o), 15)
    window = 30 * 96
    if kind == 'first_minute':
        flow = (2 * m.tb[idx] - m.v[idx]) / np.maximum(m.v[idx], 1e-12)
        mean = _rolling(flow, window, np.mean)
        std = _rolling(flow, window, np.std)
        z = (flow - mean) / std
        return [(int(i), 1 if s >= 2 else -1) for i, s in zip(idx, z) if abs(s) >= 2]
    cum_v, cum_tb = np.r_[0, np.cumsum(m.v)], np.r_[0, np.cumsum(m.tb)]
    idx = idx[idx >= 60]
    v = cum_v[idx] - cum_v[idx - 60]
    flow = (2 * (cum_tb[idx] - cum_tb[idx - 60]) - v) / np.maximum(v, 1e-12)
    low = _rolling(flow, window, lambda x: np.quantile(x, .1))
    high = _rolling(flow, window, lambda x: np.quantile(x, .9))
    # Decided from the 60 minutes ending at the boundary, so step back one minute for the entry convention.
    return [(int(i) - 1, 1 if f > hi else -1) for i, f, lo, hi in zip(idx, flow, low, high)
            if not np.isnan(lo) and (f > hi or f < lo)]


def funding_signals(m: Market, kind):
    idx = np.flatnonzero(m.funding)
    rates = m.funding[idx]
    if kind == 'abs':
        return [(int(i), -1 if r > 0 else 1) for i, r in zip(idx, rates) if abs(r) >= .0005]
    z = (rates - _rolling(rates, 180, np.mean)) / _rolling(rates, 180, np.std)
    return [(int(i), -1 if s > 0 else 1) for i, s in zip(idx, z) if abs(s) > 2.5]


def cvd_signals(m: Market, vpin_filter=False, step=15, width=3):
    n = len(m.o) // step
    h = m.h[:n * step].reshape(n, step).max(axis=1)
    l = m.l[:n * step].reshape(n, step).min(axis=1)
    delta = (2 * m.tb[:n * step] - m.v[:n * step]).reshape(n, step).sum(axis=1)
    cvd = np.cumsum(delta)
    blocked = None
    if vpin_filter:
        imbalance = np.abs(2 * m.tb - m.v)
        cum_i, cum_v = np.r_[0, np.cumsum(imbalance)], np.r_[0, np.cumsum(m.v)]
        vpin = np.full(len(m.o), np.nan)
        vpin[50:] = (cum_i[50:-1] - cum_i[:-51]) / np.maximum(cum_v[50:-1] - cum_v[:-51], 1e-12)
        sampled = vpin[step - 1::step][:n]
        p90 = _rolling(sampled, 30 * 96, lambda x: np.nanquantile(x, .9))
        blocked = sampled > p90
    signals, highs, lows = [], [], []
    for p in range(width, n - width):
        confirm = p + width
        window = range(p - width, p + width + 1)
        if h[p] == max(h[j] for j in window):
            highs = [q for q in highs if p - q <= 60]
            if any(4 <= p - q and h[p] > h[q] and cvd[p] < cvd[q] for q in highs):
                if blocked is None or not blocked[confirm]:
                    signals.append(((confirm + 1) * step - 1, -1))
            highs.append(p)
        if l[p] == min(l[j] for j in window):
            lows = [q for q in lows if p - q <= 60]
            if any(4 <= p - q and l[p] < l[q] and cvd[p] > cvd[q] for q in lows):
                if blocked is None or not blocked[confirm]:
                    signals.append(((confirm + 1) * step - 1, 1))
            lows.append(p)
    return sorted(signals)
